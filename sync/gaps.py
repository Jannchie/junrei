"""补漏：Anitabi 没有收录、但有人实地探访过舞台的作品，从探访文章里提取地标草稿，人工审核后并入 sync/manual.json。

线索来自「舞台探訪アーカイブ」(https://wikiwiki.jp/legwork/)：按作品收录实地探访文章的目录。流程：

  python -m sync.gaps list                  # 目录 × Bangumi 动画 − 已有地标的作品 → data/review/legwork-gaps.csv（按热度）
  python -m sync.gaps run --top 5           # 取前 5 部：抓作品页与探访文章 → LLM 提取地点与集数 → 地理编码 → 草稿
  python -m sync.gaps run --ids 181354      # 指定作品（Bangumi id）
  python -m sync.gaps run --list nishikibuna --top 20   # 錦鮒出版「聖地巡礼特集」探访过的美少女游戏（成人向标 nsfw，网站默认隐藏）
  python -m sync.gaps trace                 # 老草稿的来源截图在本地 trace.moe 帧库里比对：对上作品的提高把握度，补集数与时间
  python -m sync.gaps apply                 # 草稿里 approved 为 true 的地标（或审核页导出的 approved.json）并入 manual.json

并入的地标都带截图：文章里与 trace.moe 帧对上的那张动画截图，缩到 640px 宽转存到 R2（junrei/shots/），
不引用博客的图片地址（会防盗链、会随博客消失）。没有对上截图、或截图转存失败的候选不并入，留在草稿里下次再试。

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
import urllib.parse
from pathlib import Path

from sync import llm
from sync.enrich_common import Http, add_data_arg, now_iso, open_db, setup_stdout
from sync.fold import loose
from sync.net import request
from sync.sync import haversine_km

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
GAPS_UA = "junrei-gaps/0.1 (+https://junrei.jannchie.com)"
IMG_JUNK = re.compile(r"(?i)icon|avatar|logo|emoji|button|banner|\.gif|\.svg")  # 不是正文图片的地址

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


def spot_task(name: str, system: str, extra: dict | None = None) -> llm.Task:
    item = {**SPOT, "properties": {**SPOT["properties"], **(extra or {})}, "required": [*SPOT["required"], *(extra or {})]}
    return llm.Task(name=name, version="v1", system=system, item_properties={"spots": {"type": "array", "items": item}},
                    chunk_size=4, chunk_chars=30000, effort="medium")


TASK = spot_task("gap_spots", SYSTEM)

# 截图证据模式：文章里的图片先用本地 trace.moe 比对，确认是这部作品画面的截图换成 [截图#k：…] 标记，
# 模型只能输出能指认截图的地点（evidence 填 k），没有截图依据的地点一律不收
EVIDENCE_SYSTEM = SYSTEM + """

文中形如 [截图#3：第5集 12:05] 的标记，是经画面比对确认来自这部作品的动画截图（附集数与时间；同系列续作的截图不带集数）。
博客通常把动画截图和实拍照片放在一起，地点名写在附近。
- 每个地点必须对应一个截图标记：evidence 写该地点所依据的截图编号 k（就近、且文字说明这张截图拍的就是这个地点）。
- 找不到对应截图的地点不要输出；一张截图只对应一个地点。
- episode 以截图标记里的集数为准。"""
EVIDENCE_TASK = spot_task("gap_spots_evidence", EVIDENCE_SYSTEM, {"evidence": {"type": "integer"}})
EVIDENCE_IMAGES = 60  # 每篇文章最多比对多少张图
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


def strip_scripts(page: str) -> str:
    return re.sub(r"(?is)<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", " ", page)


def content_html(page: str) -> str:
    """粗略的正文区域：优先常见博客正文容器；容器里几乎没字（结构没认对）时退回全文"""
    page = strip_scripts(page)
    # 类名要整词匹配（"preventry-text" 这种上一篇导航不能算）
    m = re.search(r'class="(?:[^"]*\s)?(?:entry[-_]?(?:content|body|text)|article[-_]?(?:body|text)|post[-_]?(?:content|body)|'
                  r'main[-_]?text|blog[-_]?body|articleText|skin-entryBody)(?:\s[^"]*)?"', page, re.I)
    body = page[m.start():m.start() + 200000] if m else ""
    return body if len(strip_tags(body)) >= 300 else page


def text_of(page: str) -> str:
    return strip_tags(content_html(page))


def strip_tags(page: str) -> str:
    """去掉标签，图片换成 [图: alt]，合并空白"""
    page = re.sub(r'(?is)<img[^>]*alt="([^"]+)"[^>]*>', r" [图: \1] ", page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return re.sub(r"[ \t　]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def img_tags(page: str, base: str) -> list[tuple[tuple[int, int], str]]:
    """正文图片：[(标签在 page 里的位置, 绝对地址)]，图标、头像、按钮之类不算"""
    out = []
    for m in re.finditer(r"(?is)<img\b[^>]*>", page):
        src = re.search(r'(?:data-src|data-original|src)="([^"]+)"', m.group(0))
        url = urllib.parse.urljoin(base, html.unescape(src.group(1))) if src else ""
        if url.startswith("http") and not IMG_JUNK.search(url):
            out.append((m.span(), url))
    return out


def images_near(page: str, base: str, names: list[str], n: int = 4) -> list[str]:
    """文章里某个地点附近的图片（名称第一次出现之后的 n 张，通常是「动画截图 + 实拍」对照），
    只给本地审核页对照用，不保存、不发布。找不到名称时返回空"""
    page = strip_scripts(page)
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
    return list(dict.fromkeys(url for _, url in img_tags(page[at:], base)))[:n]


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


def with_evidence(page: str, base: str, tm, ids: dict[int, str], vectors: "Vectors") -> tuple[str, dict[int, dict]]:
    """文章正文，其中对上这部作品画面的图片换成 [截图#k：第N集 mm:ss]，其余图片去掉。返回 (正文, {k: 比对结果})"""
    region = content_html(page)
    tags = img_tags(region, base)[:EVIDENCE_IMAGES]
    vectors.prefetch([u for _, u in tags])
    evidence: dict[int, dict] = {}
    out, last = [], 0
    for (start, end), url in tags:
        out.append(region[last:start])
        last = end
        proof = lookup(tm, vectors, url, ids)
        if not proof:
            continue
        k = len(evidence) + 1
        evidence[k] = proof
        when = f"{int(proof['from']) // 60}:{int(proof['from']) % 60:02d}"
        label = f"第{proof['episode']}集 {when}" if proof["match"] == "exact" and proof["episode"] else (
            "同系列续作" if proof["match"] == "series" else when)
        out.append(f"<br>[截图#{k}：{label}]<br>")
    out.append(region[last:])
    return strip_tags("".join(out)), evidence


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
    lines = [ln.strip() for ln in strip_tags(page).split("\n") if ln.strip()]
    key = loose(work)
    out, region, place, summary = [], "", "", False
    for i, ln in enumerate(lines):
        if ln.startswith("○"):
            summary = key in loose(ln)  # 开头一览：「○ 作品」下面几行是「・ 市区町村 ( 地点 ， … )」
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
        elif ln.startswith("作品：") and key in loose(ln):
            out += [f"{place}（{region.lstrip('◆')}）", ln, *[x for x in lines[i + 1:i + 4] if x.startswith(("訪問日", "[图"))]]
    return "\n".join(out)


def game_subjects(data: Path) -> list[dict]:
    """Bangumi 的游戏条目（含成人向）：python -m sync.bgm_archive 顺带导出的 data/bgm-games.json"""
    path = data / "bgm-games.json"
    if not path.exists():
        print("没有 data/bgm-games.json（先跑 python -m sync.bgm_archive），游戏条目对不上")
        return []
    return json.loads(path.read_text(encoding="utf-8"))["subjects"]


def all_subjects(data: Path) -> dict[int, dict]:
    subs = json.loads((data / "bgm-anime.json").read_text(encoding="utf-8"))["subjects"]
    return {s["id"]: s for s in [*game_subjects(data), *subs]}


def work_names(title: str | None, cn: str | None, sub: dict) -> list[str]:
    """一部作品的各种叫法（目录里的写法 + Bangumi 的原名、中文名、英文名、别名），对 trace.moe 的 AniList 条目用"""
    return [n for n in [title, cn, sub.get("name"), sub.get("cn"), sub.get("en"), *sub.get("aliases", [])] if n]


def drafts(out_dir: Path) -> list[tuple[Path, dict]]:
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(out_dir.glob("*.json")) if p.stem.isdigit()]


def load_manual() -> dict:
    return json.loads(MANUAL.read_text(encoding="utf-8"))


def save_manual(manual: dict) -> None:
    MANUAL.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        done = {d["bangumi"] for _, d in drafts(data / "review" / "gaps")}
        gaps = [g for g in gaps if int(g["bangumi_id"]) not in done][: args.top]
    subs = all_subjects(data)
    from sync import tracemoe

    evidence_mode = args.list != "nishikibuna"  # 游戏不在 trace.moe 里，只能照旧
    task = EVIDENCE_TASK if evidence_mode else TASK
    if evidence_mode:
        if not (tracemoe.DIR / "frames.sqlite").exists():
            raise SystemExit("截图证据需要本地 trace.moe 帧库：python -m sync.tracemoe extract <dump>")
        tm = tracemoe.open_db()
        vectors = Vectors(db)

    # 1. 每部作品的探访文章 → 送给模型的输入
    works = []
    for g in gaps:
        if evidence_mode:
            ids = tracemoe.match_anilist(tm, work_names(g["title"], g.get("cn"), subs.get(int(g["bangumi_id"]), {})))
            tracemoe.clear_cache()  # 帧数据按作品载入，换作品就释放
            if not ids:
                print(f"{g['title']}：trace.moe 里没有这部作品，跳过")
                continue
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
            ev: dict[int, dict] = {}
            if evidence_mode:
                text, ev = with_evidence(decode(body), url, tm, ids, vectors)
                if not ev:
                    continue  # 没有一张截图对上，这篇不送去提取
            elif g.get("links"):
                text = nishikibuna_text(decode(body), g["title"])
            else:
                text = text_of(decode(body))
            text = text[:ARTICLE_CHARS]
            if not text:
                continue
            payload = llm.clean_text(json.dumps({"work": g["title"], "area": hint, "text": text}, ensure_ascii=False))
            inputs.append((url, payload, ev))
        works.append((g, inputs))
        if evidence_mode:
            vectors.save()  # 每部作品存一次：中途停下，下次不必重新下载图片
        shots = sum(len(ev) for *_, ev in inputs)
        print(f"{g['title']}：{len(links)} 篇文章" + (f"，{len(inputs)} 篇有对上的截图（共 {shots} 张）" if evidence_mode else ""), flush=True)

    # 2. LLM 提取（按文章缓存）。--manual：没有 API 时，把待提取的文章导出给任意模型或人工，答案导回缓存
    texts = [t for _, ins in works for _, t, _ in ins]
    if args.manual and not exchange(db, Path(args.manual), texts, args.model, task):
        return
    # 任何模型已经提取过的文章都直接用（例如会话里人工 / 其他模型给出的答案），只把剩下的送去请求
    other = {}
    for model in {r[0] for r in db.execute("SELECT DISTINCT model FROM cache.llm_cache WHERE task = ?", (task.name,))} - {args.model}:
        other |= {k: v for k, v in llm.cached(db, task, model).items() if k not in other}
    results = llm.run(db, task, [t for t in texts if llm.sha(t) not in other], model=args.model, mode=args.mode,
                      dry_run=args.dry_run, limit=args.limit, wait=args.wait)
    results = {**other, **results}
    if args.dry_run:
        return

    # 3. 地理编码，写草稿
    out_dir = data / "review" / "gaps"
    out_dir.mkdir(parents=True, exist_ok=True)
    manual_points: dict[int, list] = {}
    for mp in load_manual()["points"]:
        manual_points.setdefault(mp["bangumi"], []).append(mp)
    for g, inputs in works:
        bid = int(g["bangumi_id"])
        spots, seen = [], set()
        existing = existing_points(db, bid, manual_points.get(bid, []))
        dropped = 0
        for url, text, ev in inputs:
            r = results.get(llm.sha(text))
            if not r:
                continue
            page = ""
            if not evidence_mode:  # 没有截图证据时，审核页按地名在原文里找附近的图（页面已缓存）
                _, body = http.get(url.split("#")[0])
                page = decode(body) if body else ""
            for s in r[0]["spots"]:
                key = s["name_ja"]
                proof = ev.get(s.get("evidence", -1)) if evidence_mode else None
                if key in seen or s["confidence"] < args.min_confidence or (evidence_mode and not proof):
                    continue
                seen.add(key)
                if loose(key) in existing["names"]:
                    dropped += 1
                    continue
                loc = geocode(geo, s)
                if loc and loc["by"] != "gsi-area" and any(haversine_km(loc["lat"], loc["lng"], la, ln) * 1000 < DUP_METERS for la, ln in existing["coords"]):
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
                    "images": [proof["image"]] if proof else images_near(page, url, [s["name_ja"], s["query"].split(" ")[0]]) if page else [],
                    "model": r[1],
                    **({"trace": proof} if proof else {}),
                })
        apply_trace(spots, retarget=anilist_bangumi(tm, subs, {s["trace"]["anilist"] for s in spots if s.get("trace")})
                    if evidence_mode else None)
        sub = subs.get(bid, {})
        draft = {"bangumi": bid, "title": g["title"], "cn": sub.get("cn"), "legwork": g["legwork_page"], "spots": spots,
                 **({"nsfw": True} if sub.get("nsfw") else {})}
        (out_dir / f"{bid}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {g['title']}：{len(spots)} 个候选地标，{sum(1 for s in spots if s['lat'])} 个定位成功"
              + (f"，{dropped} 个与已有地标重复已去掉" if dropped else ""))
    write_review(out_dir)


def exchange(db, folder: Path, texts: list[str], model: str, task: llm.Task = TASK) -> bool:
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
                        task.name, task.prompt_version, model, a["sha"], by_sha[a["sha"]],
                        json.dumps({"spots": a["spots"]}, ensure_ascii=False), a.get("served_model", "manual"), now_iso()))
        db.commit()
    done = llm.cached(db, task, model)
    pending = [t for t in texts if llm.sha(t) not in done]
    with (folder / "pending.jsonl").open("w", encoding="utf-8") as f:
        for t in pending:
            f.write(json.dumps({"sha": llm.sha(t), "input": json.loads(t)}, ensure_ascii=False) + "\n")
    if pending:
        (folder / "prompt.md").write_text(task.system + '\n\n输出：每篇一行 JSON {"sha": …, "spots": [...]}，写到 answers.jsonl。字段见 sync/gaps.py 的 SPOT。\n',
                                          encoding="utf-8")
        print(f"还有 {len(pending)} 篇文章没有答案：{folder / 'pending.jsonl'}（说明见 prompt.md）")
    return not pending


def existing_points(db, bid: int, manual_points: list[dict]) -> dict:
    """作品已有的地标（Anitabi + manual.json）：名称（宽松归一）与坐标，用来给候选去重"""
    rows = db.execute("SELECT name, cn, lat, lng FROM src.point WHERE bangumi_id = ?", (bid,)).fetchall()
    rows += [(p.get("name"), p.get("cn"), p["lat"], p["lng"]) for p in manual_points]
    return {"names": {loose(n) for r in rows for n in r[:2] if n}, "coords": [(r[2], r[3]) for r in rows if r[2] is not None]}


def write_review(out_dir: Path) -> None:
    """审核页：读所有草稿，地图上逐个看位置，勾选后导出 approved.json"""
    items = [d for _, d in drafts(out_dir)]
    template = (Path(__file__).resolve().parent / "gaps_review.html").read_text(encoding="utf-8")
    page = template.replace("/*DRAFTS*/[]", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
    (out_dir / "review.html").write_text(page, encoding="utf-8")
    print(f"审核页：{out_dir / 'review.html'}")


# ---- 截图证据：在本地 trace.moe 帧库（sync.tracemoe）里比对来源文章的图片 ----

SIMILARITY = 0.9  # 与 trace.moe 的建议一致：低于 0.9 的结果多半不对
MARGIN = 0.05  # 比别的集里最像的一帧高出这么多，才认定是这一集（片头片尾、总集篇各集都有）
SHOT_UA = "Mozilla/5.0 (junrei-gaps; +https://junrei.jannchie.com)"  # 部分图床拒绝非浏览器的 UA


def download_image(url: str) -> bytes | None:
    """文章里的图片。只看 8×8 的色块分布，缩略图就够了，不换原图"""
    status, body = request(url, ua=SHOT_UA, retries=2)
    return body if status == 200 and len(body) >= 2000 else None


class Vectors:
    """图片地址 → Color Layout 向量（下载不到为 None），缓存在 enrich.sqlite 的 image_vector 表"""

    def __init__(self, db):
        db.execute("CREATE TABLE IF NOT EXISTS image_vector (image TEXT PRIMARY KEY, vector TEXT)")
        self.db = db
        self.known = {i: json.loads(v) if v else None for i, v in db.execute("SELECT image, vector FROM image_vector")}
        self.new: dict[str, list[int] | None] = {}

    def _compute(self, url: str) -> list[int] | None:
        from sync import tracemoe

        body = download_image(url)
        return tracemoe.image_vector(body) if body else None

    def prefetch(self, urls: list[str]) -> None:
        from concurrent.futures import ThreadPoolExecutor

        todo = [u for u in dict.fromkeys(urls) if u not in self.known and u not in self.new]
        with ThreadPoolExecutor(6) as pool:
            self.new.update(zip(todo, pool.map(self._compute, todo)))

    def get(self, url: str) -> list[int] | None:
        if url not in self.known and url not in self.new:
            self.new[url] = self._compute(url)
        return self.known[url] if url in self.known else self.new[url]

    def save(self) -> None:
        self.db.executemany("INSERT OR REPLACE INTO image_vector VALUES (?,?)",
                            [(i, json.dumps(v) if v else None) for i, v in self.new.items()])
        self.db.commit()
        self.known.update(self.new)
        self.new.clear()


def lookup(tm, vectors: Vectors, img: str, ids: dict[int, str]) -> dict | None:
    """一张图在这部作品（ids：AniList 条目 → exact / series）里的比对结果：先找标题一致的条目，再看同系列的续作"""
    from sync import tracemoe

    vec = vectors.get(img)
    # 几乎没有细节的图（纯黑、纯色）在任何作品里都能找到「很像」的帧，不算数
    if not vec or sum(abs(x - 16) for x in vec[1:21] + vec[22:27] + vec[28:33]) < 20:
        return None
    for kind in ("exact", "series"):
        best = tracemoe.search(tm, vec, [a for a, k in ids.items() if k == kind])
        if best and best["similarity"] >= SIMILARITY:
            return {"image": img, "anilist": best["anilist"], "episode": best["episode"], "from": round(best["from"], 1),
                    "similarity": round(best["similarity"], 3), "runner_up": round(best["runner_up"], 3), "match": kind}
    return None


def anilist_bangumi(tm, subs: dict[int, dict], aids: set[int]) -> dict[int, int]:
    """AniList 条目 → 标题一致的唯一一部 Bangumi 作品（对上续作的截图，地标改记到续作上）"""
    from sync import tracemoe

    if not aids:
        return {}
    index: dict[str, set[int]] = {}
    for bid, s in subs.items():
        for n in work_names(None, None, s):
            index.setdefault(loose(n), set()).add(bid)
    titles = tracemoe.anilist_titles(tm)
    out = {}
    for aid in aids:
        found = set().union(*(index.get(n, set()) for n in titles.get(aid, set())))
        if len(found) == 1:
            out[aid] = found.pop()
    return out


def apply_trace(spots: list[dict], applied: dict | None = None, retarget: dict[int, int] | None = None) -> None:
    """有截图为证的地点：提高把握度，集数与时间取截图对上的那一帧（地标显示的就是这张截图）。
    - 帧的集数与文章写的一致：采用；不一致或文章没写：只有这一帧明显比别的集都像（MARGIN）时，以帧为准
    - 对上的是续作（retarget：AniList 条目 → Bangumi 作品）：地标改记到续作上，再按上面的规则取集数与时间
    applied 是已并入 manual.json 的地标，同步更新"""
    for s in [s for s in spots if s.get("trace")]:
        t = s["trace"]
        s["confidence"] = max(s["confidence"], 0.9)
        if s.pop("ep_by", None):
            s["ep"] = ""
        s.pop("s", None)
        moved = (retarget or {}).get(t["anilist"]) if t.get("match") == "series" else None
        if moved:
            t["bangumi"] = moved
        if t.get("match") == "exact" or t.get("bangumi"):
            ep = str(t["episode"]) if t["episode"] else ""
            clear = t.get("similarity", 0) - t.get("runner_up", 1) >= MARGIN
            if ep and s["ep"] != ep and clear:
                s["ep"], s["ep_by"] = ep, "trace.moe"
            if s["ep"] == ep and (clear or ep):
                s["s"] = int(t["from"])
        if applied and (m := applied.get(s["id"])) is not None:
            if t.get("bangumi"):
                m["bangumi"] = t["bangumi"]
            m["ep"], m["s"] = s["ep"] or None, s.get("s")


def cmd_trace(db, data: Path, refresh: bool = False) -> None:
    """老草稿（没有截图证据时生成的）里的图片补做比对；refresh 时已对上的也重新比对（规则或帧库更新后）"""
    from sync import tracemoe

    if not (tracemoe.DIR / "frames.sqlite").exists():
        raise SystemExit("需要本地 trace.moe 帧库：python -m sync.tracemoe extract <dump>")
    tm = tracemoe.open_db()
    vectors = Vectors(db)
    subs = all_subjects(data)
    out_dir = data / "review" / "gaps"
    manual = load_manual()
    applied = {p["id"]: p for p in manual["points"]}
    found = 0
    for path, d in drafts(out_dir):
        todo = [s for s in d["spots"] if s.get("images") and not s.get("trace_local") and (refresh or not s.get("trace"))]
        ids = tracemoe.match_anilist(tm, work_names(d["title"], d.get("cn"), subs.get(d["bangumi"], {}))) if todo else {}
        tracemoe.clear_cache()  # 帧数据按作品载入，换作品就释放
        for s in todo if ids else []:
            images = [s["trace"]["image"]] if s.get("trace") else s["images"]
            proof = next((p for img in images if (p := lookup(tm, vectors, img, ids))), None)
            if proof:
                found += not s.get("trace")
                s["trace"] = proof
            elif not s.get("trace"):
                s["trace_local"] = "none"  # 比对过、没有对上（多半是实拍照片）
        apply_trace(d["spots"], applied, anilist_bangumi(tm, subs, {s["trace"]["anilist"] for s in d["spots"] if s.get("trace")}))
        vectors.save()
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    register_works(manual, subs)  # 改记到续作上的地标
    save_manual(manual)
    print(f"本地 trace.moe：新对上 {found} 个地标")
    write_review(out_dir)


# ---- 并入 manual.json ----

SHOTS = "junrei/shots/"
SHOT_WIDTH = 640


def shot_candidates(url: str) -> list[str]:
    """博客常在正文里放缩略图：先试原图（livedoor 去掉 -s，FC2 去掉末尾的 s），不行再用缩略图本身"""
    full = re.sub(r"-s(\.\w+)$", r"\1", url) if "blogimg.jp" in url else re.sub(r"(\d{6,})s(\.\w+)$", r"\1\2", url)
    return [full, url] if full != url else [url]


def shot_jpeg(body: bytes, aspect: float | None = None) -> bytes | None:
    """缩到 SHOT_WIDTH 宽、去掉元数据的 JPEG；aspect 给了时比例要一致（防止「原图」其实是另一张图）"""
    import io

    from PIL import Image

    try:
        im = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception:  # noqa: BLE001 - 图片格式五花八门
        return None
    if aspect and abs(im.width / im.height - aspect) > 0.03 * aspect:
        return None
    if im.width > SHOT_WIDTH:
        im = im.resize((SHOT_WIDTH, round(im.height * SHOT_WIDTH / im.width)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    return out.getvalue()


def mirror_shot(up, pid: str, url: str) -> str | None:
    """来源截图转存到 R2，返回公开地址；下载或上传失败返回 None"""
    import io

    from PIL import Image

    from sync.covers import PUBLIC

    thumb = download_image(url)
    if not thumb:
        return None
    try:
        aspect = (lambda im: im.width / im.height)(Image.open(io.BytesIO(thumb)))
    except Exception:  # noqa: BLE001
        return None
    for cand in shot_candidates(url):
        body = thumb if cand == url else download_image(cand)
        jpeg = body and shot_jpeg(body, aspect)
        if jpeg:
            key = f"{SHOTS}{pid}-{hashlib.sha1(cand.encode()).hexdigest()[:8]}.jpg"
            return PUBLIC + key if up.put(key, jpeg) else None
    return None


def attach_shots(points: list[tuple[dict, dict]]) -> int:
    """(manual 地标, 草稿候选) → 并行转存截图，写进地标的 image / origin / origin_link；返回成功数"""
    from concurrent.futures import ThreadPoolExecutor

    from sync.covers import Uploader

    if not points:
        return 0
    up = Uploader()
    with ThreadPoolExecutor(up.workers) as pool:
        urls = list(pool.map(lambda ps: mirror_shot(up, ps[0]["id"], ps[1]["trace"]["image"]), points))
    for (p, s), url in zip(points, urls):
        if url:
            ref = s["reference"]
            p.update(image=url, origin=s.get("source") or urllib.parse.urlparse(ref).hostname, origin_link=ref)
    return sum(1 for u in urls if u)


def register_works(manual: dict, subs: dict[int, dict]) -> None:
    """manual.json 里有地标、还没登记的作品，按 Bangumi 的信息登记（有没有地标由 export 统计，这里只登记作品本身）"""
    from sync.export import BGM_COVER, subject_names
    from sync.translate import opencc_converter

    to_hant = opencc_converter("s2twp")
    known = {b["id"] for b in manual["bangumi"]}
    for bid in dict.fromkeys(p["bangumi"] for p in manual["points"]):
        if bid not in known:
            sub = subs.get(bid, {})
            manual["bangumi"].append({"id": bid, "title": sub.get("name"), "cn": sub.get("cn"), "en": sub.get("en"),
                                      "names": subject_names(sub, to_hant), "cat": sub.get("cat"),
                                      **({"nsfw": True} if sub.get("nsfw") else {}), "cover": BGM_COVER.format(bid)})
            known.add(bid)


def cmd_apply(data: Path, approved_file: str | None, auto_min: float | None = None) -> None:
    from sync.translate import opencc_converter

    to_hant = opencc_converter("s2twp")
    out_dir = data / "review" / "gaps"
    # 审核页导出的是 {地标 id: {lat, lng}}：有记录即通过，坐标可能在审核页里拖动修正过
    ok: dict | None = json.loads(Path(approved_file).read_text(encoding="utf-8")) if approved_file else None
    subs = all_subjects(data)
    manual = load_manual()
    by_id = {p["id"]: p for p in manual["points"]}
    candidates: list[tuple[dict, dict]] = []  # (将要并入的地标, 草稿候选)
    backfill: list[tuple[dict, dict]] = []  # 早先并入、还没有截图的地标
    for _, draft in drafts(out_dir):
        bid = draft["bangumi"]
        for s in draft["spots"]:
            if (m := by_id.get(s["id"])) is not None:
                if not m.get("image") and s.get("trace"):
                    backfill.append((m, s))
                continue
            if not s.get("trace"):
                continue  # 没有对上动画截图的不并入
            # 自动通过：把握度够高、又精确定位到具体地点（不是只落在行政区中心）的，不必人工审核
            auto = auto_min is not None and s["confidence"] >= auto_min and (s.get("geocode") or {}).get("by") in ("osm", "gsi")
            if not (auto or (s["approved"] if ok is None else s["id"] in ok)):
                continue
            if ok and ok.get(s["id"]):
                s.update(ok[s["id"]])
            if s["lat"] is None:
                continue
            names = {**s["names"], "zh-Hant": to_hant(s["names"]["zh-Hans"])}
            marks = {k: v for k, v in {**s["marks"], "zh-Hant": to_hant(s["marks"]["zh-Hans"])}.items() if v}
            point = {
                "bangumi": s["trace"].get("bangumi", bid), "id": s["id"], "name": s["name"], "cn": s["names"]["zh-Hans"],
                "lat": round(s["lat"], 6), "lng": round(s["lng"], 6), "ep": s["ep"] or None, "src": "ja",
                "names": names, "marks": marks, "reference": s["reference"], "source": s.get("source"), "s": s.get("s"),
            }
            by_id[s["id"]] = point
            candidates.append((point, s))
    filled = attach_shots(backfill)
    attach_shots(candidates)
    added = [p for p, _ in candidates if p.get("image")]
    manual["points"].extend(added)
    register_works(manual, subs)
    save_manual(manual)
    print(f"并入 {len(added)} 个地标（另有 {len(candidates) - len(added)} 个截图转存失败，下次再试），"
          f"给已有地标补上 {filled}/{len(backfill)} 张截图 → {MANUAL}")


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
    trace = sub.add_parser("trace", help="老草稿的来源截图在本地 trace.moe 帧库里比对：核对作品、补集数与时间")
    trace.add_argument("--refresh", action="store_true", help="已对上的也重新比对")
    apply = sub.add_parser("apply")
    apply.add_argument("approved", nargs="?", help="审核页导出的 approved.json；省略则用草稿里的 approved 字段")
    apply.add_argument("--auto", type=float, metavar="CONF", help="把握度不低于 CONF 且精确定位的候选自动通过，例如 --auto 0.85")
    args = ap.parse_args()

    data = Path(args.data)
    db = open_db(data)
    # 探访目录与博客：每秒一个请求，缓存 30 天；地理编码按 Nominatim 的使用规范每秒一个
    http = Http(db, interval=1.0, ua=GAPS_UA, max_age_days=30)
    geo = Http(db, interval=1.1, ua=GAPS_UA)
    if args.cmd == "list":
        cmd_list(db, http, data)
    elif args.cmd == "run":
        cmd_run(db, http, geo, data, args)
    elif args.cmd == "trace":
        cmd_trace(db, data, args.refresh)
    elif args.cmd == "review":
        write_review(data / "review" / "gaps")
    else:
        cmd_apply(data, args.approved, args.auto)


if __name__ == "__main__":
    setup_stdout()
    main()
