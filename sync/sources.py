"""Anitabi 引用过的探访博客：全站遍历文章，按标题对上作品，生成补漏清单。

Anitabi 地标的来源链接（origin_link）指向约 150 个站点，其中的巡礼博客写过的作品远多于 Anitabi 引用的那几篇。流程：

  python -m sync.sources list               # 各博客的文章目录 → 文章标题 → Bangumi 作品 → data/review/legwork-sources.csv
  python -m sync.sources list --hosts riyot.hatenablog.com   # 只看指定站点（试跑用）
  python -m sync.gaps run --list sources --top 50 --mode batch --wait   # 之后与其他补漏清单相同：截图比对、提取、草稿

文章目录依次尝试：robots.txt 里的 Sitemap、/sitemap.xml、WordPress 的 REST API、FC2 的「?all」全記事一覧、
はてなブログ的 /archive 归档页。各站点并行抓取，同一站点每秒一个请求；页面缓存与补漏共用，run 时不必重抓。
标题对不上任何作品、但整个博客只为一部作品被 Anitabi 引用过的（单作品的巡礼博客），文章算作那部作品；
是不是真的写这部作品，run 时由截图比对把关。本地 trace.moe 帧库里没有的作品另存 legwork-sources-noframes.csv，
下次从 trace.moe 数据库导出帧时一并带上。
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import threading
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sync.enrich_common import Http, add_data_arg, open_db, setup_stdout
from sync.fold import fold
from sync.gaps import GAPS_UA, all_subjects, decode, work_names

NOT_BLOG = re.compile(r"(?i)(^|\.)(google\.\w+|goo\.gl|x\.com|twitter\.com|twimg\.com|bilibili\.com|b23\.tv|youtube\.com|youtu\.be|"
                      r"nicovideo\.jp|weibo\.com|reddit\.com|baidu\.com|zhihu\.com|instagram\.com|facebook\.com|gamer\.com\.tw|"
                      r"pixiv\.net|amazon\.\w+|wikipedia\.org)$")
# 一个用户一个子目录的博客平台：博客的根是「域名/第一级路径」
USER_DIR = {"blog.livedoor.jp", "ameblo.jp", "note.com", "plaza.rakuten.co.jp", "blog.goo.ne.jp", "blog.naver.com", "blog.sina.com.cn"}
NOT_ARTICLE = re.compile(r"(?i)/(category|categories|tag|tags|page|about|search|archive|archives/(19|20)\d\d-\d\d|author|feed)(/|$)|"
                         r"\.(jpe?g|png|gif|webp|xml|gz)$|[?&](tag|cat|page)=")
MAX_ARTICLES = 5000  # 每个博客最多看多少篇
MAX_SITEMAPS = 400
LINKS_PER_WORK = 30  # 每部作品最多送多少篇文章去比对
MIN_KEY = 4  # 作品名（归一后）至少这么长才在标题里按子串找；更短的只认「」『』【】里的整名
MIN_ASCII_KEY = 6  # 纯英文的作品名容易撞上普通单词（「Land」），要更长
# 写很多作品的博客（感想、开箱、巡礼混在一起）只看标题带这些词的文章
PILGRIM = re.compile(r"(?i)聖地|圣地|巡礼|巡禮|舞台|探訪|探访|ロケ地|ロケハン|モデル地|取材地|seichi|pilgrimage")
WORKERS = 8


def blog_root(url: str) -> str | None:
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if not host or NOT_BLOG.search(host):
        return None
    if host in USER_DIR:
        seg = u.path.strip("/").split("/")[0]
        return f"{u.scheme}://{host}/{seg}" if seg else None
    return f"{u.scheme}://{host}"


def sources(db) -> dict[str, Counter]:
    """Anitabi 引用过的博客：博客根地址 → 被引用的作品（Bangumi id → 地标数）"""
    out: dict[str, Counter] = {}
    for link, bid in db.execute("SELECT origin_link, bangumi_id FROM src.point WHERE origin_link IS NOT NULL"):
        if root := blog_root(link):
            out.setdefault(root, Counter())[bid] += 1
    return out


# ---- 文章目录 ----

def locs(body: bytes) -> list[str]:
    return [html.unescape(x.strip()) for x in re.findall(rb"<loc>\s*(.*?)\s*</loc>", body, re.S) for x in [x.decode("utf-8", "replace")]]


def from_sitemaps(http: Http, root: str) -> list[str]:
    status, body = http.get(root + "/robots.txt")
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", body.decode("utf-8", "replace")) if status == 200 else []
    queue = list(dict.fromkeys([*maps, root + "/sitemap.xml"]))
    urls, done = [], 0
    while queue and done < MAX_SITEMAPS and len(urls) < MAX_ARTICLES:
        sm = queue.pop(0)
        done += 1
        status, body = http.get(sm)
        if status != 200 or b"<loc>" not in body:
            continue
        found = locs(body)
        if b"<sitemapindex" in body[:2000]:
            # WordPress 等：只看文章的子 sitemap（分类、标签、用户页不要）
            queue += [x for x in found if not re.search(r"(?i)(categor|tag|user|author|taxonom|page-sitemap)", x)]
        else:
            urls += found
    return urls


def from_wordpress(http: Http, root: str) -> list[tuple[str, str]]:
    out = []
    for page in range(1, MAX_ARTICLES // 100 + 1):
        status, items = http.get_json(root + "/wp-json/wp/v2/posts", {"per_page": 100, "page": page, "_fields": "link,title"})
        if status != 200 or not isinstance(items, list) or not items:
            break
        out += [(i["link"], html.unescape(re.sub(r"<[^>]+>", "", i["title"]["rendered"]))) for i in items]
    return out


def from_fc2(http: Http, root: str) -> list[tuple[str, str]]:
    status, body = http.get(root + "/?all")
    if status != 200:
        return []
    page = decode(body)
    pat = r'<a [^>]*href="((?:%s)?/?blog-entry-\d+\.html)"[^>]*>(.*?)</a>' % re.escape(root)
    return [(urllib.parse.urljoin(root + "/", h), html.unescape(re.sub(r"<[^>]+>", "", t)).strip()) for h, t in re.findall(pat, page, re.S)]


def from_hatena(http: Http, root: str) -> list[tuple[str, str]]:
    out = []
    for page in range(1, MAX_ARTICLES // 30 + 1):
        status, body = http.get(root + "/archive", {"page": page} if page > 1 else None)
        if status != 200:
            break
        found = re.findall(r'<a [^>]*class="entry-title-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', decode(body), re.S)
        if not found:
            break
        out += [(h, html.unescape(re.sub(r"<[^>]+>", "", t)).strip()) for h, t in found]
    return out


def page_title(body: bytes) -> str:
    page = decode(body)
    m = re.search(r'(?is)<meta property="og:title" content="([^"]*)"', page) or re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return html.unescape(m.group(1)).strip() if m else ""


def articles(http: Http, root: str) -> list[tuple[str, str]]:
    """博客的全部文章：[(地址, 标题)]。目录里没有标题的，逐篇打开页面读标题"""
    titled: list[tuple[str, str]] = []
    if "hatena" in root or "hateblo" in root:
        titled = from_hatena(http, root)
    if not titled and ("fc2" in root):
        titled = from_fc2(http, root)
    if not titled:
        titled = from_wordpress(http, root)
    if titled:
        return list(dict(titled).items())[:MAX_ARTICLES]
    host = urllib.parse.urlsplit(root).hostname
    urls = [u for u in from_sitemaps(http, root)
            if urllib.parse.urlsplit(u).hostname == host and u.startswith(root) and u.rstrip("/") != root and not NOT_ARTICLE.search(u)]
    out = []
    for u in list(dict.fromkeys(urls))[:MAX_ARTICLES]:
        status, body = http.get(u)
        if status == 200:
            out.append((u, page_title(body)))
    return out


# ---- 标题 → 作品 ----

class Works:
    """动画作品名（原名、中文名、英文名、别名，归一后）→ Bangumi 条目，在文章标题里找作品名"""

    def __init__(self, subs: dict[int, dict], cmap: dict[str, str]):
        self.cmap = cmap
        self.index: dict[str, dict] = {}
        for s in subs.values():
            if s.get("cat") == "游戏":
                continue
            for n in [s.get("name"), s.get("cn"), s.get("en"), *s.get("aliases", [])]:
                k = fold(n, cmap)
                if len(k) >= 2 and (k not in self.index or s["popularity"] > self.index[k]["popularity"]):
                    self.index[k] = s
        self.longest = max(map(len, self.index))

    def find(self, title: str) -> list[dict]:
        """标题里提到的作品：取最长的匹配，被更长的名称包含的不算（「けいおん」在「けいおん！！」里）"""
        t = fold(title, self.cmap)
        hits: list[tuple[int, int]] = []
        for i in range(len(t)):
            for j in range(min(len(t), i + self.longest), i + MIN_KEY - 1, -1):
                if t[i:j] in self.index and (not t[i:j].isascii() or j - i >= MIN_ASCII_KEY):
                    hits.append((i, j))
                    break
        for inner in re.findall(r"[「『【《〈\[]([^」』】》〉\]]{2,40})[」』】》〉\]]", title):
            k = fold(inner, self.cmap)
            if k in self.index and (m := t.find(k)) >= 0:
                hits.append((m, m + len(k)))
        hits = [h for h in hits if not any(o != h and o[0] <= h[0] and h[1] <= o[1] for o in hits)]
        return list({(s := self.index[t[a:b]])["id"]: s for a, b in hits}.values())


def crawl(data: Path, root: str) -> tuple[str, list[tuple[str, str]]]:
    db = open_db(data)  # 每个线程自己的连接（sqlite 连接不能跨线程用）
    http = Http(db, interval=1.0, ua=GAPS_UA, max_age_days=30)
    try:
        return root, articles(http, root)
    except Exception as e:  # noqa: BLE001  一个站点出错不影响其他站点
        print(f"  ! {root}：{e}", flush=True)
        return root, []
    finally:
        db.close()


def cmd_list(data: Path, hosts: list[str] | None) -> None:
    from sync import tracemoe

    db = open_db(data)
    blogs = sources(db)
    if hosts:
        blogs = {r: c for r, c in blogs.items() if urllib.parse.urlsplit(r).hostname in hosts or r in hosts}
    subs = all_subjects(data)
    works = Works(subs, json.loads((data.parent / "src" / "fold-map.json").read_text(encoding="utf-8")))
    print(f"Anitabi 引用过的博客 {len(blogs)} 个，开始列文章（各站每秒一个请求）", flush=True)
    links: dict[int, list[str]] = {}
    lock = threading.Lock()
    report = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for root, arts in pool.map(lambda r: crawl(data, r), blogs):
            # 只为一部作品（一个系列）被引用过的博客，算单作品的巡礼博客：标题没提作品名的文章也算这部
            cited = {b: n for b, n in blogs[root].items() if b in subs and subs[b].get("cat") != "游戏"}
            series = {subs[b].get("series") or b for b in cited}
            only = max(cited, key=cited.__getitem__) if len(series) == 1 else None
            found_in = {url: works.find(title) for url, title in arts}
            # 但标题里常提到别的作品的（什么都写、只是 Anitabi 只引用过一部的），不算
            other = sum(1 for f in found_in.values() if any((s.get("series") or s["id"]) not in series for s in f))
            if only and other > 0.2 * len(arts):
                only = None
            matched = 0
            for url, title in arts:
                if only is None and not PILGRIM.search(title):
                    continue
                found = found_in[url] or ([subs[only]] if only else [])
                matched += bool(found)
                with lock:
                    for s in found:
                        links.setdefault(s["id"], []).append(url)
            report.append((root, len(arts), matched))
            print(f"  {root}：{len(arts)} 篇，{matched} 篇对上作品", flush=True)

    tm = tracemoe.open_db() if (tracemoe.DIR / "frames.sqlite").exists() else None
    framed = {r[0] for r in tm.execute("SELECT DISTINCT anilist_id FROM files")} if tm else set()  # anilist 表是全量，有帧的只是一部分
    have, missing = [], []
    for bid, urls in links.items():
        s = subs[bid]
        row = (s["popularity"], s.get("name"), s.get("cn") or "", bid, urls[0], " ".join(list(dict.fromkeys(urls))[:LINKS_PER_WORK]))
        (have if tm and framed & set(tracemoe.match_anilist(tm, work_names(None, None, s))) else missing).append(row)
    for name, rows in [("legwork-sources.csv", have), ("legwork-sources-noframes.csv", missing)]:
        rows.sort(reverse=True)
        with (data / "review" / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["bangumi_popularity", "title", "cn", "bangumi_id", "legwork_page", "links"])
            w.writerows(rows)
    empty = [r for r, n, _ in report if not n]
    print(f"完成：{len(report)} 个博客，{sum(n for _, n, _ in report)} 篇文章；对上 {len(links)} 部作品，"
          f"其中 {len(have)} 部在 trace.moe 帧库里 → legwork-sources.csv，{len(missing)} 部不在 → legwork-sources-noframes.csv")
    if empty:
        print(f"列不出文章的博客 {len(empty)} 个：" + " ".join(empty))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--hosts", help="只看这些站点（域名或博客根地址，逗号分隔）")
    args = ap.parse_args()
    cmd_list(Path(args.data), args.hosts.split(",") if args.hosts else None)


if __name__ == "__main__":
    setup_stdout()
    main()
