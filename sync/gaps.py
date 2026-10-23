"""补漏：Anitabi 没有收录、但有人实地探访过舞台的作品，从探访文章里提取地标草稿，人工审核后并入 sync/manual.json。

线索来自「舞台探訪アーカイブ」(https://wikiwiki.jp/legwork/)：按作品收录实地探访文章的目录。流程：

  python -m sync.gaps list                  # 目录 × Bangumi 动画 − 已有地标的作品 → data/review/legwork-gaps.csv（按热度）
  python -m sync.gaps run --top 5           # 取前 5 部：抓作品页与探访文章 → LLM 提取地点与集数 → 地理编码 → 草稿
  python -m sync.gaps run --ids 181354      # 指定作品（Bangumi id）
  python -m sync.gaps run --list nishikibuna --top 20   # 錦鮒出版「聖地巡礼特集」探访过的美少女游戏（成人向标 nsfw，网站默认隐藏）
  python -m sync.gaps trace --budget 50     # 用来源文章里的截图查 trace.moe：对上作品的提高把握度，补集数与时间
  python -m sync.gaps apply                 # 草稿里 approved 为 true 的地标（或审核页导出的 approved.json）并入 manual.json

草稿在 data/review/gaps/<作品 id>.json，审核页 data/review/gaps/review.html（地图上逐个确认，勾选后导出）。
文章正文只用于提取，不写进任何数据；地标只记地点、集数、一句自己写的场景说明，并保留来源链接。
LLM 步骤需要 Claude API（pip install anthropic，ANTHROPIC_API_KEY），结果按文章缓存，同一篇不会重复请求。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import unicodedata
import urllib.parse
from pathlib import Path

from sync import llm
from sync.enrich_common import Http, add_data_arg, now_iso, open_db, setup_stdout

LEGWORK = "https://wikiwiki.jp/legwork/"
NISHIKIBUNA = "https://nishikibuna.web.fc2.com/EXTRA/"  # 美少女游戏（多为成人向）的取景探访，按都道府县整理
ROWS = "あかさたなはまやらわ"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch"
MANUAL = Path(__file__).resolve().parent / "manual.json"
ARTICLE_CHARS = 8000  # 每篇文章最多送给模型的字数
ARTICLES_PER_WORK = 8
THIN = 15  # 地标少于这个数的已收录作品算「偏少」，也值得补
DUP_METERS = 150  # 和已有地标相距不到这个距离（或同名）的候选视为重复，不进草稿

SYSTEM = """你在帮动画圣地巡礼地图整理「舞台探访」文章：粉丝实地走访动画里出现的真实地点后写的博客。
每条输入是 JSON：work 为作品名，area 为目录给出的地区提示，text 为文章正文（可能夹着导航、广告等杂讯）。

找出文章里明确对应到作品画面的真实地点，每个地点一条：
- name_ja：地点的正式名称（日文），尽量具体到设施、车站、桥、路口；只知道大概区域时写区域名。
- name_zh_hans / name_en：简体中文名、英文名（车站写「××站 / ×× Station」）。
- query：拿去地理编码的查询串，名称加上所在市区町村，例如「田無駅 西東京市」。
- area：所在都道府县与市区町村，如「東京都西東京市」。
- episode：集数，只写数字（如 "3"），剧场版、不确定写 ""。
- scene_zh / scene_ja / scene_en：一句话（各 30 字以内）说明这个地点对应作品里的什么场景，用你自己的话，不要照抄原文。
- confidence：0 到 1，这个地点确实是作品舞台、且名称足以定位的把握。
文章没有可定位的地点就返回空数组。不要编造文章里没有的地点；同一地点在同一篇里只写一次。"""

SPOT = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in
                   ["name_ja", "name_zh_hans", "name_en", "query", "area", "episode", "scene_zh", "scene_ja", "scene_en"]}
    | {"confidence": {"type": "number"}},
    "required": ["name_ja", "name_zh_hans", "name_en", "query", "area", "episode", "scene_zh", "scene_ja", "scene_en",
                 "confidence"],
    "additionalProperties": False,
}
TASK = llm.Task(
    name="gap_spots",
    version="v1",
    system=SYSTEM,
    item_properties={"spots": {"type": "array", "items": SPOT}},
    chunk_size=4,
    chunk_chars=30000,
    effort="medium",
)
MODEL = "claude-sonnet-5-5"  # 长文阅读 + 判断，Haiku 容易漏或编


# ---- 抓取 ----

def decode(body: bytes) -> str:
    """博客的编码五花八门（老的 FC2 是 EUC-JP / Shift_JIS）：先看 meta charset，再依次试"""
    m = re.search(rb'charset=["\']?([\w-]+)', body[:4000], re.I)
    for enc in ([m.group(1).decode()] if m else []) + ["utf-8", "cp932", "euc_jp"]:
        try:
            return body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", "replace")


def text_of(page: str) -> str:
    """粗略的正文提取：优先常见博客正文容器；容器里几乎没字（结构没认对）时退回全文"""
    page = re.sub(r"(?is)<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", " ", page)
    # 类名要整词匹配（"preventry-text" 这种上一篇导航不能算）
    m = re.search(r'class="(?:[^"]*\s)?(?:entry[-_]?(?:content|body|text)|article[-_]?(?:body|text)|post[-_]?(?:content|body)|'
                  r'main[-_]?text|blog[-_]?body|articleText|skin-entryBody)(?:\s[^"]*)?"', page, re.I)
    body = strip_tags(page[m.start():m.start() + 200000]) if m else ""
    return body if len(body) >= 300 else strip_tags(page)


def strip_tags(page: str) -> str:
    """去掉标签，图片换成 [图: alt]，合并空白"""
    page = re.sub(r'(?is)<img[^>]*alt="([^"]+)"[^>]*>', r" [图: \1] ", page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return re.sub(r"[ \t　]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def images_near(page: str, base: str, names: list[str], n: int = 4) -> list[str]:
    """文章里某个地点附近的图片（名称第一次出现之后的 n 张，通常是「动画截图 + 实拍」对照），
    只给本地审核页对照用，不保存、不发布。找不到名称时返回空"""
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    plain = re.sub(r"<[^>]+>", lambda m: " " * len(m.group(0)), page)  # 标签换成占位，位置与原文对齐
    at = -1
    for name in names:
        for part in [name, *name.split(" ")]:
            if len(part) >= 2 and (at := plain.find(part)) >= 0:
                break
        if at >= 0:
            break
    if at < 0:
        return []
    out = []
    for m in re.finditer(r'(?is)<img[^>]*?(?:data-src|data-original|src)="([^"]+)"', page[at:]):
        src = urllib.parse.urljoin(base, html.unescape(m.group(1)))
        if src.startswith("http") and not re.search(r"(?i)icon|avatar|logo|emoji|button|banner|\.gif", src) and src not in out:
            out.append(src)
        if len(out) >= n:
            break
    return out


def work_links(http: Http, title: str) -> list[tuple[str, str]]:
    """目录里一部作品的探访文章：[(链接, 地区提示)]"""
    status, body = http.get(LEGWORK + urllib.parse.quote(title))
    if status != 200:
        return []
    page = decode(body)
    page = page[page.find('id="content"'):page.find('id="footer"')] if 'id="content"' in page else page
    out = []
    for line in re.split(r"(?i)<br\s*/?>|</li>|</p>|\n", page):
        for url in re.findall(r'href="(https?://[^"]+)"', line):
            if "wikiwiki.jp" in url:
                continue
            hint = html.unescape(re.sub(r"<[^>]+>", " ", line)).replace(url, " ")
            hint = re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", hint)).strip(" 「」")
            out.append((url, hint[:60]))
    return list(dict.fromkeys(out))


def nishikibuna_works(http: Http) -> dict[str, list[str]]:
    """錦鮒出版「聖地巡礼特集」首页的都道府县别作品一览：作品名 → 各县页面（带锚点）"""
    status, body = http.get(NISHIKIBUNA + "seichi.html")
    if status != 200:
        return {}
    page = decode(body)
    page = page[page.find("</map>"):]
    page = page[:page.find("ブランド")] if "ブランド" in page else page
    out: dict[str, list[str]] = {}
    for href, name in re.findall(r'<a [^>]*href="([^"#]+\.html(?:#[^"]*)?)"[^>]*>([^<]+)</a>', page):
        name = html.unescape(name).strip()
        if href != "seichi.html" and not name.endswith(("県", "都", "府", "道", "海外")):
            out.setdefault(name, []).append(urllib.parse.urljoin(NISHIKIBUNA, href))
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def nishikibuna_text(page: str, work: str) -> str:
    """县页面里属于这部作品的探访条目：「・地点 / 作品：… / 訪問日：…」，连同所在地区（◆）与开头的地点一览"""
    fold = lambda t: norm(unicodedata.normalize("NFKC", t))  # noqa: E731
    lines = [ln.strip() for ln in strip_tags(page).split("\n") if ln.strip()]
    key = fold(work)
    out, region, place, summary = [], "", "", False
    for i, ln in enumerate(lines):
        if ln.startswith("○"):
            summary = key in fold(ln)  # 开头一览：「○ 作品」下面几行是「・ 市区町村 ( 地点 ， … )」
            if summary:
                out.append(ln)
            continue
        if summary and ln.startswith("・") and "(" in ln.replace("（", "("):
            out.append(ln)
            continue
        summary = False
        if ln.startswith("◆"):
            region = ln
        elif ln.startswith("・"):
            place = ln
        elif ln.startswith("作品：") and key in fold(ln):
            out += [f"{place}（{region.lstrip('◆')}）", ln, *[x for x in lines[i + 1:i + 4] if x.startswith(("訪問日", "[图"))]]
    return "\n".join(out)


def game_subjects(data: Path) -> list[dict]:
    """Bangumi 的游戏条目（含成人向）：data/bgm-games.json，从 Bangumi Archive 数据包读出，数据包更新后重建"""
    import zipfile

    from sync.bgm_archive import ARCHIVE_DIR, aliases

    archive = max(ARCHIVE_DIR.glob("*.zip"), default=None)
    out = data / "bgm-games.json"
    if out.exists():
        cached = json.loads(out.read_text(encoding="utf-8"))
        if archive is None or cached["archive"] == archive.name:
            return cached["subjects"]
    if archive is None:
        return []
    rows = []
    with zipfile.ZipFile(archive) as z, z.open("subject.jsonlines") as f:
        for line in f:
            s = json.loads(line)
            if s["type"] != 4:
                continue
            fav = s.get("favorite") or {}
            alias = aliases(s.get("infobox", ""))
            rows.append({"id": s["id"], "name": s.get("name") or None, "cn": s.get("name_cn") or None, "en": None,
                         "aliases": [a for a in alias if a not in (s.get("name"), s.get("name_cn"))][:8], "cat": "游戏",
                         "popularity": fav.get("done", 0) + fav.get("doing", 0) + fav.get("wish", 0),
                         **({"nsfw": True} if s.get("nsfw") else {})})
    out.write_text(json.dumps({"archive": archive.name, "subjects": rows}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    return rows


def all_subjects(data: Path) -> dict[int, dict]:
    subs = json.loads((data / "bgm-anime.json").read_text(encoding="utf-8"))["subjects"]
    return {s["id"]: s for s in [*game_subjects(data), *subs]}


# ---- 待补清单 ----

def cmd_list(db, http: Http, data: Path) -> None:
    from sync.fold import fold

    names = []
    for r in ROWS:
        status, body = http.get(LEGWORK + urllib.parse.quote(f"作品名50音順一覧（{r}行）"))
        if status == 200:
            names += [html.unescape(m).strip() for m in re.findall(r'<li><a [^>]*class="rel-wiki-page"[^>]*>([^<]+)</a>', decode(body))]
    names = [n for n in dict.fromkeys(names) if not re.search("50音|一覧|地域別|FrontPage", n)]
    cmap = json.loads((data.parent / "src" / "fold-map.json").read_text(encoding="utf-8"))
    subs = json.loads((data / "bgm-anime.json").read_text(encoding="utf-8"))["subjects"]
    have = {r[0] for r in db.execute("SELECT DISTINCT bangumi_id FROM src.point")}
    have |= {p["bangumi"] for p in json.loads(MANUAL.read_text(encoding="utf-8"))["points"]}
    series_has = {s.get("series") for s in subs if s["id"] in have and s.get("series")}
    index: dict[str, list[dict]] = {}
    for s in subs:
        for n in [s["name"], s["cn"], s["en"], *s.get("aliases", [])]:
            if k := fold(n, cmap):
                index.setdefault(k, []).append(s)
    counts: dict[int, int] = {}
    for (bid,) in db.execute("SELECT bangumi_id FROM src.point"):
        counts[bid] = counts.get(bid, 0) + 1
    gaps, thin = [], []
    for n in names:
        cands = index.get(fold(n, cmap))
        if not cands:
            continue
        page = LEGWORK + urllib.parse.quote(n)
        covered = [s for s in cands if s["id"] in have]
        if not covered and not any(s.get("series") in series_has for s in cands):
            # 待补：作品（连同所在系列）一个地标都没有
            top = max(cands, key=lambda s: s["popularity"])
            gaps.append((top["popularity"], n, top["cn"] or "", top["id"], page))
        elif covered:
            # 偏少：有地标但不多，探访文章里可能还有没收录的地点
            top = max(covered, key=lambda s: s["popularity"])
            if counts.get(top["id"], 0) < THIN:
                thin.append((top["popularity"], n, top["cn"] or "", top["id"], page))
    for name, rows in [("legwork-gaps.csv", gaps), ("legwork-thin.csv", thin)]:
        rows.sort(reverse=True)
        out = data / "review" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["bangumi_popularity", "title", "cn", "bangumi_id", "legwork_page"])
            w.writerows(rows)
    print(f"目录 {len(names)} 部，待补 {len(gaps)} 部、偏少（不到 {THIN} 个地标）{len(thin)} 部 → {data / 'review'}")

    # 錦鮒出版：美少女游戏为主，作品对到 Bangumi 的游戏条目（其次动画）；地标不到 THIN 个的都值得补
    for s in game_subjects(data):
        for n in [s["name"], s["cn"], *s.get("aliases", [])]:
            if k := fold(n, cmap):
                index.setdefault(k, []).insert(0, s)
    found: dict[int, tuple] = {}
    for n, links in nishikibuna_works(http).items():
        k = fold(n, cmap)
        # 对不上全名时退一步：Bangumi 的名称常带副标题（「星空のメモリア」→「星空のメモリア-Wish upon a shooting star-」）
        cands = index.get(k) or [s for key, ss in index.items() if len(k) >= 4 and key.startswith(k) for s in ss]
        if not cands:
            print(f"  ? 錦鮒出版「{n}」在 Bangumi 里没对上")
            continue
        top = max(cands, key=lambda s: (s.get("cat") == "游戏", s["popularity"]))
        if counts.get(top["id"], 0) < THIN:
            # 同一部作品在一览里可能写法不同（「鬼ごっこ！」「鬼ごっこ!」），链接合并
            old = found.get(top["id"])
            links = [*(old[5].split() if old else []), *links]
            found[top["id"]] = (top["popularity"], old[1] if old else n, top["cn"] or "", top["id"],
                                NISHIKIBUNA + "seichi.html", " ".join(dict.fromkeys(links)))
    rows = sorted(found.values(), reverse=True)
    with (data / "review" / "legwork-nishikibuna.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bangumi_popularity", "title", "cn", "bangumi_id", "legwork_page", "links"])
        w.writerows(rows)
    print(f"錦鮒出版：{len(rows)} 部待补")


# ---- 地理编码 ----

def city_of(area: str) -> str:
    """「北海道札幌市中央区」→「札幌」：用来核对地理编码结果是不是落在文章说的地方（政令市取市名，区名太常见）"""
    area = re.sub(r"^(東京都|北海道|(?:京都|大阪)府|\S{2,3}県)", "", area or "")
    m = re.match(r"(.+?)市", area) or re.match(r"(?:.+?郡)?(.+?)[区町村]", area)
    return m.group(1) if m else ""


def geocode(http: Http, spot: dict) -> dict | None:
    """先用 OSM Nominatim 查名称（设施、车站查得到），再用国土地理院按地址 / 地名查。
    结果必须落在文章给出的市区町村里（标签含市名），否则换下一种查法；最后只能退到行政区中心（gsi-area）。"""
    name = re.sub(r"[（(][^）)]*[）)]", "", spot["name_ja"]).strip()  # 去掉「（国道2号線付近）」这类补充说明
    city = city_of(spot["area"])
    m = re.match(r"(東京|北海道|京都|大阪|\S{2,3}?)[都府県]?", spot["area"] or "")
    pref = m.group(1) if m else ""
    near = lambda label: (not city or city in label) and (not pref or pref in label)  # noqa: E731
    # 名称在 OSM 里常常没有空格，或只登记了最后一段（「国立国会図書館 国際子ども図書館」→「国際子ども図書館」）
    variants = [name, name.replace(" ", ""), name.split(" ")[-1], name.split(" ")[0]]  # 最后才退到第一段（「京都駅 大階段」→「京都駅」）
    queries = list(dict.fromkeys(q for q in [spot["query"], *(f"{v} {city}" for v in variants), *variants] if q.strip()))
    for q in queries:
        status, hits = http.get_json(NOMINATIM, {"q": q, "format": "json", "limit": 5, "accept-language": "ja"})
        for h in hits or [] if status == 200 else []:
            if near(h["display_name"]):
                return {"lat": float(h["lat"]), "lng": float(h["lon"]), "by": "osm", "query": q, "label": h["display_name"][:120]}
    for q in queries:
        status, hits = http.get_json(GSI, {"q": q})
        for h in hits or [] if status == 200 else []:
            title = h["properties"].get("title", "")
            # 只匹配到市区町村名（标题就是行政区）的不算具体地点
            if near(title) and not re.fullmatch(r"\S+?[都道府県]\S*?[市区町村]", title):
                lng, lat = h["geometry"]["coordinates"]
                return {"lat": lat, "lng": lng, "by": "gsi", "query": q, "label": title}
    status, hits = http.get_json(GSI, {"q": spot["area"]}) if spot["area"] else (0, None)
    if status == 200 and hits:
        # 只查到市区町村，坐标在行政区中心，审核时要手动挪到准确位置
        lng, lat = hits[0]["geometry"]["coordinates"]
        return {"lat": lat, "lng": lng, "by": "gsi-area", "query": spot["area"], "label": hits[0]["properties"].get("title", "")}
    return None


# ---- 生成草稿 ----

def cmd_run(db, http: Http, geo: Http, data: Path, args) -> None:
    gaps = list(csv.DictReader((data / "review" / f"legwork-{args.list}.csv").open(encoding="utf-8-sig")))
    if args.ids:
        want = {int(i) for i in args.ids.split(",")}
        gaps = [g for g in gaps if int(g["bangumi_id"]) in want]
    else:
        done = {int(p.stem) for p in (data / "review" / "gaps").glob("*.json") if p.stem.isdigit()}
        gaps = [g for g in gaps if int(g["bangumi_id"]) not in done][: args.top]
    subs = all_subjects(data)

    # 1. 每部作品的探访文章 → 送给模型的输入
    works = []
    for g in gaps:
        if g.get("links"):
            # 錦鮒出版：县页面里一部作品只占几条，按作品摘出来；锚点只是定位，同一页只取一次
            links = list({u.split("#")[0]: (u, "") for u in reversed(g["links"].split())}.values())[::-1]
        else:
            links = work_links(http, g["title"])[:ARTICLES_PER_WORK]
        inputs = []
        for url, hint in links:
            status, body = http.get(url.split("#")[0])
            if status != 200:
                print(f"  ! {url} → {status}")
                continue
            text = (nishikibuna_text(decode(body), g["title"]) if g.get("links") else text_of(decode(body)))[:ARTICLE_CHARS]
            if not text:
                continue
            inputs.append((url, llm.clean_text(json.dumps({"work": g["title"], "area": hint, "text": text}, ensure_ascii=False))))
        works.append((g, links, inputs))
        print(f"{g['title']}：{len(links)} 篇文章")

    # 2. LLM 提取（按文章缓存）。--manual：没有 API 时，把待提取的文章导出给任意模型或人工，答案导回缓存
    if args.manual:
        texts = [t for _, _, ins in works for _, t in ins]
        if not exchange(db, Path(args.manual), texts, args.model):
            return
    # 任何模型已经提取过的文章都直接用（例如会话里人工 / 其他模型给出的答案），只把剩下的送去请求
    texts = [t for _, _, ins in works for _, t in ins]
    other = {}
    for model in {r[0] for r in db.execute("SELECT DISTINCT model FROM cache.llm_cache WHERE task = ?", (TASK.name,))} - {args.model}:
        other |= {k: v for k, v in llm.cached(db, TASK, model).items() if k not in other}
    results = llm.run(db, TASK, [t for t in texts if llm.sha(t) not in other], model=args.model, mode=args.mode,
                      dry_run=args.dry_run, limit=args.limit, wait=args.wait)
    results = {**other, **results}
    if args.dry_run:
        return

    # 3. 地理编码，写草稿
    out_dir = data / "review" / "gaps"
    out_dir.mkdir(parents=True, exist_ok=True)
    for g, _, inputs in works:
        bid = int(g["bangumi_id"])
        spots, seen = [], set()
        existing = existing_points(db, bid)
        dropped = 0
        for url, text in inputs:
            r = results.get(llm.sha(text))
            if not r:
                continue
            _, body = http.get(url.split("#")[0])  # 已缓存，给审核页找对照图
            page = decode(body) if body else ""
            for s in r[0]["spots"]:
                key = s["name_ja"]
                if key in seen or s["confidence"] < args.min_confidence:
                    continue
                seen.add(key)
                if norm(key) in existing["names"]:
                    dropped += 1
                    continue
                loc = geocode(geo, s)
                if loc and loc["by"] != "gsi-area" and any(dist(loc["lat"], loc["lng"], la, ln) < DUP_METERS for la, ln in existing["coords"]):
                    dropped += 1
                    continue
                spots.append({
                    "id": f"m-{bid}-{hashlib.sha1(key.encode()).hexdigest()[:8]}",
                    "approved": False,
                    "name": s["name_ja"],
                    "names": {"zh-Hans": s["name_zh_hans"], "ja": s["name_ja"], "en": s["name_en"]},
                    "ep": s["episode"],
                    "marks": {"zh-Hans": s["scene_zh"], "ja": s["scene_ja"], "en": s["scene_en"]},
                    "confidence": s["confidence"],
                    "area": s["area"],
                    "lat": loc and loc["lat"],
                    "lng": loc and loc["lng"],
                    "geocode": loc,
                    "reference": url,
                    "images": images_near(page, url, [s["name_ja"], s["query"].split(" ")[0]]) if page else [],
                    "model": r[1],
                })
        sub = subs.get(bid, {})
        draft = {"bangumi": bid, "title": g["title"], "cn": sub.get("cn"), "legwork": g["legwork_page"], "spots": spots,
                 **({"nsfw": True} if sub.get("nsfw") else {})}
        (out_dir / f"{bid}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {g['title']}：{len(spots)} 个候选地标，{sum(1 for s in spots if s['lat'])} 个定位成功"
              + (f"，{dropped} 个与已有地标重复已去掉" if dropped else ""))
    write_review(out_dir)


def exchange(db, folder: Path, texts: list[str], model: str) -> bool:
    """folder/answers.jsonl（{"sha", "spots"}）导入缓存；还没有答案的写到 folder/pending.jsonl。全部有答案返回 True"""
    folder.mkdir(parents=True, exist_ok=True)
    answers = folder / "answers.jsonl"
    if answers.exists():
        by_sha = {llm.sha(t): t for t in texts}
        for line in answers.read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = json.loads(line)
                if a["sha"] in by_sha:
                    db.execute("INSERT OR REPLACE INTO cache.llm_cache VALUES (?,?,?,?,?,?,?,?)", (
                        TASK.name, TASK.prompt_version, model, a["sha"], by_sha[a["sha"]],
                        json.dumps({"spots": a["spots"]}, ensure_ascii=False), a.get("served_model", "manual"), now_iso()))
        db.commit()
    done = llm.cached(db, TASK, model)
    pending = [t for t in texts if llm.sha(t) not in done]
    with (folder / "pending.jsonl").open("w", encoding="utf-8") as f:
        for t in pending:
            f.write(json.dumps({"sha": llm.sha(t), "input": json.loads(t)}, ensure_ascii=False) + "\n")
    if pending:
        (folder / "prompt.md").write_text(SYSTEM + '\n\n输出：每篇一行 JSON {"sha": …, "spots": [...]}，写到 answers.jsonl。字段见 sync/gaps.py 的 SPOT。\n',
                                          encoding="utf-8")
        print(f"还有 {len(pending)} 篇文章没有答案：{folder / 'pending.jsonl'}（说明见 prompt.md）")
    return not pending


def norm(name: str) -> str:
    return re.sub(r"[\s\W_]+", "", name or "").casefold()


def dist(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点距离（米），近距离用等距矩形近似就够了"""
    import math
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(x, math.radians(lat2 - lat1)) * 6371000


def existing_points(db, bid: int) -> dict:
    """作品已有的地标（Anitabi + manual.json）：名称（规范化）与坐标，用来给候选去重"""
    rows = db.execute("SELECT name, cn, lat, lng FROM src.point WHERE bangumi_id = ?", (bid,)).fetchall()
    rows += [(p.get("name"), p.get("cn"), p["lat"], p["lng"])
             for p in json.loads(MANUAL.read_text(encoding="utf-8"))["points"] if p["bangumi"] == bid]
    return {"names": {norm(n) for r in rows for n in r[:2] if n}, "coords": [(r[2], r[3]) for r in rows if r[2] is not None]}


def write_review(out_dir: Path) -> None:
    """审核页：读所有草稿，地图上逐个看位置，勾选后导出 approved.json"""
    drafts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.json")) if p.stem.isdigit()]
    template = (Path(__file__).resolve().parent / "gaps_review.html").read_text(encoding="utf-8")
    page = template.replace("/*DRAFTS*/[]", json.dumps(drafts, ensure_ascii=False).replace("</", "<\\/"))
    (out_dir / "review.html").write_text(page, encoding="utf-8")
    print(f"审核页：{out_dir / 'review.html'}")


# ---- trace.moe：用来源文章里的动画截图核对作品、补集数与时间 ----

TRACE = "https://api.trace.moe/search?anilistInfo&cutBorders"
TRACE_SIMILARITY = 0.9  # trace.moe 自己建议低于 0.9 的结果多半不对
LOCAL_SIMILARITY = 0.9  # 本地只在这部作品里比对，阈值用在线结果校准（见 sync.tracemoe）
TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_moe (
  image TEXT PRIMARY KEY,  -- 来源文章里的图片地址
  result TEXT,             -- trace.moe 的第一条结果（JSON）；图片下载失败为 NULL
  checked_at TEXT
);
"""


def looks_like_frame(body: bytes) -> bool:
    """粗筛动画截图，省 trace.moe 额度：16:9、够大、平涂多（相邻像素几乎同色的比例高）；实拍照片多半过不了"""
    import io

    from PIL import Image

    try:
        im = Image.open(io.BytesIO(body)).convert("L")
    except Exception:  # noqa: BLE001 - 图片格式五花八门（svg、坏图）
        return False
    w, h = im.size
    if w < 300 or not 1.7 <= w / h <= 1.9:
        return False
    sm = im.resize((160, 90))
    px = sm.tobytes()
    flat = sum(1 for i in range(len(px) - 1) if (i + 1) % 160 and abs(px[i] - px[i + 1]) <= 1) / len(px)
    return flat >= 0.3


def download_image(url: str) -> bytes | None:
    import urllib.request

    from sync.enrich_common import SSL_CONTEXT

    try:
        full = re.sub(r"-s(\.\w+)$", r"\1", url) if "blogimg.jp" in url else url  # livedoor 的 -s 是缩略图
        req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0 (junrei-gaps; +https://junrei.jannchie.com)"})
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as r:
            body = r.read()
    except Exception:  # noqa: BLE001 - 文章里的图片地址什么样都有（模板残片、坏链接）
        return None
    return body if len(body) >= 2000 else None


def trace_image(url: str) -> tuple[int, dict | None]:
    """先自己下载图片再上传（博客多有防盗链，让 trace.moe 去抓常常失败还白占额度）。
    返回 (状态, 第一条结果)；状态 0 表示图片没下载到，或看着不像动画截图、没有去查"""
    import urllib.error
    import urllib.request

    from sync.enrich_common import SSL_CONTEXT

    body = download_image(url)
    if not body or not looks_like_frame(body):
        return 0, None
    req = urllib.request.Request(TRACE, data=body, method="POST", headers={"Content-Type": "image/jpeg", "User-Agent": "junrei-gaps/0.1 (+https://junrei.jannchie.com)"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as r:
            hits = json.loads(r.read()).get("result") or []
            return 200, hits[0] if hits else {}
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return 0, None


def trace_match(hit: dict, names: list[str]) -> str | None:
    """trace.moe 给的是 AniList 条目。标题与作品名（含别名）一致为 "exact"；
    互为前缀为 "series"（多是续作：「ヨルムンガンド PERFECT ORDER」，舞台同属一个系列，但集数是续作那一季的）"""
    fold = lambda t: norm(unicodedata.normalize("NFKC", t or ""))  # noqa: E731
    info = hit.get("anilist") or {}
    titles = [fold(t) for t in [*(info.get("title") or {}).values(), *(info.get("synonyms") or [])] if t]
    ours = [fold(n) for n in names if n and len(fold(n)) >= 2]
    if set(titles) & set(ours):
        return "exact"
    return "series" if any(a.startswith(b) or b.startswith(a) for a in titles if a for b in ours) else None


def local_lookup(tm, vectors: dict, img: str, ids: dict[int, str]) -> tuple[dict, str] | None:
    """本地 trace.moe（sync.tracemoe）：先在标题一致的条目里找，找不到再看同系列的续作"""
    from sync import tracemoe

    if img not in vectors:
        body = download_image(img)
        vectors[img] = tracemoe.image_vector(body) if body else None
    vec = vectors[img]
    # 几乎没有细节的图（纯黑、纯色）在任何作品里都能找到「很像」的帧，不算数
    if not vec or sum(abs(x - 16) for x in vec[1:21] + vec[22:27] + vec[28:33]) < 20:
        return None
    for kind in ("exact", "series"):
        best = tracemoe.search(tm, vec, [a for a, k in ids.items() if k == kind])
        if best and best["similarity"] >= LOCAL_SIMILARITY:
            return {"anilist": {"id": best["anilist"]}, "episode": best["episode"], "from": best["from"],
                    "similarity": best["similarity"]}, kind
    return None


def cmd_trace(db, data: Path, budget: int) -> None:
    db.executescript(TRACE_SCHEMA)
    from sync import tracemoe

    # 有本地帧库（python -m sync.tracemoe extract）就在本地比对，不占在线额度；图片向量缓存在 image_vector 表
    tm = tracemoe.open_db() if (tracemoe.DIR / "frames.sqlite").exists() else None
    if tm and not tm.execute("SELECT 1 FROM files LIMIT 1").fetchone():
        tm = None
    db.execute("CREATE TABLE IF NOT EXISTS image_vector (image TEXT PRIMARY KEY, vector TEXT)")
    vectors = {i: json.loads(v) if v else None for i, v in db.execute("SELECT image, vector FROM image_vector")}
    known_vectors = set(vectors)
    cache = {img: json.loads(r) if r else None for img, r in db.execute("SELECT image, result FROM trace_moe")}
    subs = all_subjects(data)
    out_dir = data / "review" / "gaps"
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    applied = {p["id"]: p for p in manual["points"]}
    drafts = {p: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.json")) if p.stem.isdigit()}
    # 先查没有集数的；游戏、成人向作品 trace.moe 里没有
    todo = [(p, d, s) for p, d in drafts.items() if not d.get("nsfw") for s in d["spots"]
            if s.get("images") and ("trace" not in s if not tm else not s.get("trace") and not s.get("trace_local"))]
    todo.sort(key=lambda x: (bool(x[2]["ep"]), -x[2]["confidence"]))
    used = found = 0
    for p, d, s in todo:
        sub = subs.get(d["bangumi"], {})
        names = [d["title"], d.get("cn"), sub.get("name"), sub.get("cn"), sub.get("en"), *sub.get("aliases", [])]
        hit, queries = None, 0
        if tm:
            ids = tracemoe.match_anilist(tm, [n for n in names if n])
            for img in s["images"]:
                if ids and (r := local_lookup(tm, vectors, img, ids)):
                    hit = (img, *r)
                    break
            if not hit:
                s["trace_local"] = "none"  # 本地比对过、没有对上
                continue
        for img in s["images"] if not hit else []:
            if img not in cache:
                if used >= budget or queries >= 2:
                    break
                status, res = trace_image(img)
                if status in (402, 429):
                    print("trace.moe 额度用完了（匿名每月 100 次），下个月再继续，或配置赞助后的 API key")
                    budget = used
                    break
                if status == 200:
                    used += 1
                    queries += 1
                elif status:
                    print(f"  ! trace.moe → {status}：{img}")
                if status in (0, 200):
                    cache[img] = res
                    db.execute("INSERT OR REPLACE INTO trace_moe VALUES (?,?,?)",
                               (img, json.dumps(res, ensure_ascii=False) if res is not None else None, now_iso()))
                    db.commit()
            res = cache.get(img)
            if res and res.get("similarity", 0) >= TRACE_SIMILARITY and (match := trace_match(res, names)):
                hit = (img, res, match)
                break
        if not hit:
            if all(i in cache for i in s["images"]):
                s["trace"] = None  # 查过、没有对上（多半是实拍照片）
            continue
        img, res, match = hit
        found += 1
        s["trace"] = {"image": img, "anilist": (res.get("anilist") or {}).get("id"), "episode": res.get("episode"),
                      "from": round(res["from"], 1), "similarity": round(res["similarity"], 3), "match": match}
        s["confidence"] = max(s["confidence"], 0.95)  # 截图对上了作品，地点是这部作品（系列）的舞台基本可以确定

    # 集数与时间：只在标题完全一致（不是续作）、且这张截图只对应这一个地点时采用（文章里同一张图挨着好几个地名的，说明不了是哪个）
    for d in drafts.values():
        traced = [s for s in d["spots"] if s.get("trace")]
        shared = {t for t in (s["trace"]["image"] for s in traced) if sum(x["trace"]["image"] == t for x in traced) > 1}
        for s in traced:
            t = s["trace"]
            ep = str(t["episode"]) if t["episode"] else ""
            if t.get("match") == "exact" and t["image"] not in shared:
                if not s["ep"] and ep:
                    s["ep"], s["ep_by"] = ep, "trace.moe"
                if s["ep"] == ep:
                    s["s"] = int(t["from"])
            else:
                s.pop("s", None)
                if s.pop("ep_by", None):
                    s["ep"] = ""
            if (m := applied.get(s["id"])) is not None and s.get("s") is not None and (m.get("ep") or s["ep"]) == s["ep"]:
                m["ep"], m["s"] = s["ep"] or None, s["s"]
    db.executemany("INSERT OR REPLACE INTO image_vector VALUES (?,?)",
                   [(i, json.dumps(v) if v else None) for i, v in vectors.items() if i not in known_vectors])
    db.commit()
    for p, d in drafts.items():
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    MANUAL.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"trace.moe：查询 {used} 次，对上 {found} 个地标；还有 {sum(1 for _, _, s in todo if 'trace' not in s)} 个待查")
    write_review(out_dir)


# ---- 并入 manual.json ----

def cmd_apply(data: Path, approved_file: str | None, auto_min: float | None = None) -> None:
    import opencc

    to_hant = opencc.OpenCC("s2twp").convert
    out_dir = data / "review" / "gaps"
    # 审核页导出的是 {地标 id: {lat, lng}}：有记录即通过，坐标可能在审核页里拖动修正过
    ok: dict | None = json.loads(Path(approved_file).read_text(encoding="utf-8")) if approved_file else None
    subs = all_subjects(data)
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    known_points = {p["id"] for p in manual["points"]}
    known_works = {b["id"] for b in manual["bangumi"]}
    added = 0
    for p in sorted(out_dir.glob("*.json")):
        if not p.stem.isdigit():
            continue
        draft = json.loads(p.read_text(encoding="utf-8"))
        bid = draft["bangumi"]
        for s in draft["spots"]:
            # 自动通过：把握度够高、又精确定位到具体地点（不是只落在行政区中心）的，不必人工审核
            auto = auto_min is not None and s["confidence"] >= auto_min and (s.get("geocode") or {}).get("by") in ("osm", "gsi")
            if not (auto or (s["approved"] if ok is None else s["id"] in ok)) or s["id"] in known_points:
                continue
            if ok and ok.get(s["id"]):
                s.update(ok[s["id"]])
            if s["lat"] is None:
                continue
            names = {**s["names"], "zh-Hant": to_hant(s["names"]["zh-Hans"])}
            marks = {k: v for k, v in {**s["marks"], "zh-Hant": to_hant(s["marks"]["zh-Hans"])}.items() if v}
            manual["points"].append({
                "bangumi": bid, "id": s["id"], "name": s["name"], "cn": s["names"]["zh-Hans"],
                "lat": round(s["lat"], 6), "lng": round(s["lng"], 6), "ep": s["ep"] or None, "src": "ja",
                "names": names, "marks": marks, "reference": s["reference"], "source": s.get("source"), "s": s.get("s"),
            })
            known_points.add(s["id"])
            added += 1
            if bid not in known_works:
                # 作品信息取 Bangumi；有没有地标由 export 统计，这里只登记作品本身
                sub = subs.get(bid, {})
                title = {k: v for k, v in {"zh-Hans": sub.get("cn"), "zh-Hant": sub.get("cn") and to_hant(sub["cn"]),
                                           "ja": sub.get("name"), "en": sub.get("en")}.items() if v}
                manual["bangumi"].append({"id": bid, "title": sub.get("name"), "cn": sub.get("cn"), "en": sub.get("en"),
                                          "names": title, "cat": sub.get("cat"), **({"nsfw": True} if sub.get("nsfw") else {}),
                                          "cover": f"https://api.bgm.tv/v0/subjects/{bid}/image?type=common"})
                known_works.add(bid)
    MANUAL.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"并入 {added} 个地标 → {MANUAL}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("--top", type=int, default=5, help="取清单里还没有草稿的前 N 部")
    run.add_argument("--list", choices=["gaps", "thin", "nishikibuna"], default="gaps",
                     help="gaps：没有地标的作品；thin：地标偏少的作品；nishikibuna：錦鮒出版探访过的美少女游戏")
    run.add_argument("--ids", help="指定作品的 Bangumi id，逗号分隔")
    run.add_argument("--model", default=MODEL)
    run.add_argument("--mode", choices=["batch", "sync"], default="sync")
    run.add_argument("--limit", type=int, help="最多请求多少篇文章（试跑用）")
    run.add_argument("--wait", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--min-confidence", type=float, default=0.7, help="低于这个把握度的候选不进草稿（默认 0.7）")
    run.add_argument("--manual", metavar="DIR", help="不调用 API：待提取的文章导出到 DIR/pending.jsonl，读 DIR/answers.jsonl 的答案")
    sub.add_parser("review", help="只根据现有草稿重建审核页")
    tr = sub.add_parser("trace", help="用来源文章里的截图查 trace.moe：核对作品、补集数与时间")
    tr.add_argument("--budget", type=int, default=50, help="这次最多查询多少次（匿名额度每月 100 次）")
    apply = sub.add_parser("apply")
    apply.add_argument("approved", nargs="?", help="审核页导出的 approved.json；省略则用草稿里的 approved 字段")
    apply.add_argument("--auto", type=float, metavar="CONF", help="把握度不低于 CONF 且精确定位的候选自动通过，例如 --auto 0.85")
    args = ap.parse_args()

    data = Path(args.data)
    db = open_db(data)
    # 探访目录与博客：每秒一个请求，缓存 30 天；地理编码按 Nominatim 的使用规范每秒一个
    http = Http(db, interval=1.0, ua="junrei-gaps/0.1 (+https://junrei.jannchie.com)", max_age_days=30)
    geo = Http(db, interval=1.1, ua="junrei-gaps/0.1 (+https://junrei.jannchie.com)")
    if args.cmd == "list":
        cmd_list(db, http, data)
    elif args.cmd == "run":
        cmd_run(db, http, geo, data, args)
    elif args.cmd == "trace":
        cmd_trace(db, data, args.budget)
    elif args.cmd == "review":
        write_review(data / "review" / "gaps")
    else:
        cmd_apply(data, args.approved, args.auto)


if __name__ == "__main__":
    setup_stdout()
    main()
