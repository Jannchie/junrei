"""把 sync.sync 同步下来的 data/anitabi.sqlite 转成应用使用的数据（只做格式转换，规范化在 sync.sync 里）：

  data/d1-import.sql          全量覆盖 D1 的 bangumi / point 表并重建全文索引（pnpm data:import）
  src/fold-map.json           搜索折叠用的汉字映射表（繁/日→简），前后端共用，见 sync/fold.py
  public/data/points.geojson  地图点位，maplibre 在 worker 里直接加载并聚合；前端也用它按视口筛选作品
  public/data/bangumi.json    全部作品的轻量索引（名称、封面、地标数、搜索键），前端本地模糊搜索用

多语言：data/enrich.sqlite 的 translation 表（sync.translate 生成）存在时，每个作品标题、地标名、备注
按语言挑最可信的一条写进 i18n 列，并把各语言名称都加进搜索键；city_label 表（sync.cities）给出城市的各语言名称。

全部动画：data/bgm-anime.json（sync.bgm_archive 生成）存在时，Bangumi 上所有动画条目都进作品表，
没有地标的作品地标数为 0：能被搜到、有作品页，但不进前端的本地索引与 sitemap。

  python -m sync.export
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import sys

from sync.fold import build_char_map, fold, romaji
from sync.llm import clean_text
from sync.sync import DEFAULT_OUT, attribution, valid_geo, write_json

PUBLIC_DATA = DEFAULT_OUT.parent / "public" / "data"
MANUAL = Path(__file__).resolve().parent / "manual.json"
FOLD_MAP = DEFAULT_OUT.parent / "src" / "fold-map.json"
BGM_ANIME = DEFAULT_OUT / "bgm-anime.json"
BGM_COVER = "https://api.bgm.tv/v0/subjects/{}/image?type=common"  # 数据包里没有封面地址，用官方接口的跳转
ROWS_PER_INSERT = 200  # 分批插入
MAX_STATEMENT_BYTES = 90_000  # D1 单条语句上限 100 KB
LANGS = ("zh-Hans", "zh-Hant", "ja", "en")
# 同一语言有多条时：原文混了别的语言时的纯净版本（llm_fix）最优先，其次人工数据、复核过的机翻、机翻、繁简转换；
# 置信度太低的机翻排到最后，只在这种语言没有别的文本时兜底，保证每条都有四种语言
SOURCE_RANK = {"llm_fix": -1, "anitabi": 0, "bangumi": 1, "llm_review": 2, "llm": 3, "opencc": 4}
MIN_CONFIDENCE = 0.5
LOW_CONFIDENCE_RANK = 10
FIELD_KEY = {"title": "name", "name": "name", "mark": "mark"}


def load_i18n() -> dict[tuple[str, str], dict]:
    """(entity, entity_id) → {"name": {lang: text}, "mark": {...}, "mt": ["name.en", ...], "_orig": {lang: 原文}}

    _orig 是 Anitabi 原始名称按语言的分布，导出地标时据此判断原文语言（写成 src），用完删掉。"""
    path = DEFAULT_OUT / "enrich.sqlite"
    if not path.exists():
        print("没有 data/enrich.sqlite，跳过多语言（先跑 pnpm enrich:translate）")
        return {}
    best: dict[tuple, tuple] = {}
    orig: dict[tuple, dict[str, str]] = {}
    with sqlite3.connect(path) as db:
        for entity, eid, field, lang, text, source, mt, conf in db.execute(
            "SELECT entity, entity_id, field, lang, text, source, machine_translated, confidence FROM translation"):
            if lang not in LANGS or field not in FIELD_KEY or not text or source not in SOURCE_RANK:
                continue
            key = (entity, eid, FIELD_KEY[field], lang)
            rank = SOURCE_RANK[source] + (LOW_CONFIDENCE_RANK if mt and conf is not None and conf < MIN_CONFIDENCE else 0)
            if key not in best or rank < best[key][0]:
                best[key] = (rank, text.strip(), bool(mt))
            if source == "anitabi" and field == "name" and entity == "point":
                orig.setdefault((entity, eid), {})[lang] = text.strip()
    out: dict[tuple[str, str], dict] = {(e, i): {"_orig": o} for (e, i), o in orig.items()}
    with sqlite3.connect(path) as db:
        has_cities = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'city_label'").fetchone()
        for city, labels in db.execute("SELECT city, labels FROM city_label WHERE labels IS NOT NULL") if has_cities else []:
            out[("city", city)] = json.loads(labels)
    for (entity, eid, field, lang), (_, text, mt) in best.items():
        item = out.setdefault((entity, eid), {})
        item.setdefault(field, {})[lang] = text
        if mt:
            item.setdefault("mt", []).append(f"{field}.{lang}")
    return out


def i18n_json(item: dict | None) -> str | None:
    if not item:
        return None
    if "mt" in item:
        item["mt"].sort()
    return json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def merge_manual(rows: list, points: list, counts: dict[int, int], i18n: dict) -> None:
    """合并 sync/manual.json：Anitabi 没有收录的作品与地标。多语言名称直接写在文件里。"""
    data = json.loads(MANUAL.read_text(encoding="utf-8"))
    known = {r[0] for r in rows}
    for b in data.get("bangumi", []):
        if b["id"] not in known:
            rows.append((b["id"], b.get("cn"), b.get("title"), b.get("en"), b.get("city"), b.get("cat"), b.get("color"), b.get("cover")))
        if b.get("names"):
            i18n[("bangumi", str(b["id"]))] = {"name": b["names"]}
    for p in data.get("points", []):
        points.append((p["bangumi"], p["id"], p.get("name"), p.get("cn"), p["lat"], p["lng"], p.get("priority", 0),
                       p.get("ep"), p.get("s"), p.get("image"), p.get("origin"), p.get("origin_link"), p.get("mark")))
        counts[p["bangumi"]] = counts.get(p["bangumi"], 0) + 1
        item = {k: v for k, v in (("name", p.get("names")), ("mark", p.get("marks")), ("src", p.get("src"))) if v}
        if item:
            i18n[("point", f"{p['bangumi']}:{p['id']}")] = item
    rows.sort(key=lambda r: r[0])
    print(f"手动补充：{len(data.get('bangumi', []))} 部作品，{len(data.get('points', []))} 个地标")


def merge_bgm(rows: list, i18n: dict) -> dict[int, dict]:
    """并入 Bangumi 全部动画条目：已有的作品补上热度、首播日期和别名，没有的新增一行（地标数 0）"""
    if not BGM_ANIME.exists():
        print("没有 data/bgm-anime.json，只导出有地标的作品（先跑 python -m sync.bgm_archive）")
        return {}
    import opencc  # 繁体名由简体中文名转换（台湾用字）

    to_hant = opencc.OpenCC("s2twp").convert
    subjects = json.loads(BGM_ANIME.read_text(encoding="utf-8"))["subjects"]
    known = {r[0] for r in rows}
    extra = {}
    for s in subjects:
        extra[s["id"]] = s
        if s["id"] in known:
            continue
        rows.append((s["id"], s["cn"], s["name"], s["en"], None, s["cat"], None, BGM_COVER.format(s["id"])))
        name = {k: v for k, v in (("zh-Hans", s["cn"]), ("zh-Hant", s["cn"] and to_hant(s["cn"])), ("ja", s["name"]),
                                  ("en", s["en"])) if v}
        if name:
            i18n[("bangumi", str(s["id"]))] = {"name": name}
    rows.sort(key=lambda r: r[0])
    print(f"Bangumi 动画：{len(subjects)} 部，其中 {len(subjects) - len(known & extra.keys())} 部没有地标")
    return extra


def sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert_statements(table: str, cols: list[str], rows: list[tuple]):
    """按字节数分批：D1 单条语句上限 100 KB，个别地标备注很长，按行数分批不够稳"""
    head = f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n"
    chunk: list[str] = []
    size = 0
    for r in rows:
        values = "(" + ", ".join(sql_value(v) for v in r) + ")"
        n = len(values.encode()) + 2
        if chunk and (size + n > MAX_STATEMENT_BYTES or len(chunk) >= ROWS_PER_INSERT):
            yield head + ",\n".join(chunk) + ";\n"
            chunk, size = [], 0
        chunk.append(values)
        size += n
    if chunk:
        yield head + ",\n".join(chunk) + ";\n"


def main():
    src = sqlite3.connect(DEFAULT_OUT / "anitabi.sqlite")

    points = []
    for (bid, pid, name, cn, lat, lng, prio, ep, s, image, origin, link, mark) in src.execute(
        """SELECT p.bangumi_id, p.id, p.name, p.cn, p.lat, p.lng, p.priority, p.ep, p.s, p.image,
                  p.origin, p.origin_link, p.mark
           FROM point p JOIN bangumi b ON b.id = p.bangumi_id
           WHERE b.deleted = 0 ORDER BY p.bangumi_id, p.priority, p.id"""):
        if not valid_geo(lat, lng):
            continue
        if image:
            origin, link = attribution(bid, pid, origin, link)
        points.append((bid, pid, name, cn, lat, lng, prio, ep, s, image, origin, link, mark))

    i18n = load_i18n()

    counts: dict[int, int] = {}
    for p in points:
        counts[p[0]] = counts.get(p[0], 0) + 1
    rows = src.execute(
        "SELECT id, cn, title, en, city, cat, color, cover FROM bangumi WHERE deleted = 0 ORDER BY id").fetchall()
    merge_manual(rows, points, counts, i18n)
    extra = merge_bgm(rows, i18n)

    # 搜索键：各语言名称折叠后用 | 连起来，日文标题再加一份罗马音
    titles = {r[0]: i18n.get(("bangumi", str(r[0]))) for r in rows}
    for r in rows:  # 城市名按作品写进同一个 i18n
        if r[4] and ("city", r[4]) in i18n:
            titles[r[0]] = {**(titles[r[0]] or {}), "city": i18n[("city", r[4])]}
    spots = {(p[0], p[1]): i18n.get(("point", f"{p[0]}:{p[1]}")) for p in points}
    # 原文语言：原名（没有原名时是中文名）是哪种语言。列表里展开地标时，用这种语言的版本作为「当地原名」对照
    for p in points:
        item = spots[(p[0], p[1])]
        if not item or "_orig" not in item:  # 手动补充的地标自带 src
            continue
        source = clean_text(p[2] or p[3] or "")
        item["src"] = next((lang for lang, text in item.pop("_orig", {}).items() if text == source), None)
        if not item["src"]:
            del item["src"]
    for item in i18n.values():
        item.pop("_orig", None)
    names = lambda item: list((item or {}).get("name", {}).values())  # noqa: E731
    char_map = build_char_map(
        [t for r in rows for t in [*r[1:5], *names(titles[r[0]]), *extra.get(r[0], {}).get("aliases", [])]]
        + [t for p in points for t in [*p[2:4], *names(spots[(p[0], p[1])])]])
    def keys(*texts):
        return "|".join(dict.fromkeys(k for k in (fold(t, char_map) for t in texts) if k))
    bangumi = [
        (*r, counts.get(r[0], 0), extra.get(r[0], {}).get("popularity", 0), extra.get(r[0], {}).get("date"),
         i18n_json(titles[r[0]]),
         keys(r[1], r[2], r[3], r[4], romaji(r[2]), *names(titles[r[0]]), *extra.get(r[0], {}).get("aliases", [])))
        for r in rows
    ]
    points = [(*p, i18n_json(spots[(p[0], p[1])]), keys(p[2], p[3], *names(spots[(p[0], p[1])]))) for p in points]

    out_sql = DEFAULT_OUT / "d1-import.sql"
    with out_sql.open("w", encoding="utf-8") as f:
        f.write("DELETE FROM point;\nDELETE FROM bangumi;\n")
        cols = ["id", "cn", "title", "en", "city", "cat", "color", "cover", "point_count", "popularity", "air_date",
                "i18n", "search"]
        f.writelines(insert_statements("bangumi", cols, bangumi))
        cols = ["bangumi_id", "id", "name", "cn", "lat", "lng", "priority", "ep", "s", "image", "origin",
                "origin_link", "mark", "i18n", "search"]
        f.writelines(insert_statements("point", cols, points))
        f.write("INSERT INTO point_fts(point_fts) VALUES('rebuild');\n")
        f.write("INSERT INTO bangumi_fts(bangumi_fts) VALUES('rebuild');\n")

    # 坐标保留 5 位小数（约 1 m）；属性只留点击时需要的作品 id 和地标 id
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    out_geo = PUBLIC_DATA / "points.geojson"
    write_json(out_geo, {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(p[5], 5), round(p[4], 5)]},
             "properties": {"b": p[0], "p": p[1]}}
            for p in points
        ],
    })

    write_json(FOLD_MAP, char_map)
    # [id, 中文名, 原名, 英文名, 封面, 地标数, 搜索键, 各语言标题]；只收有地标的作品，其余由服务端搜索
    write_json(PUBLIC_DATA / "bangumi.json",
               [[b[0], b[1], b[2], b[3], b[7], b[8], b[12], (titles[b[0]] or {}).get("name")] for b in bangumi if b[8]])

    print(f"{out_sql}：{len(bangumi)} 部作品，{len(points)} 个地标，{out_sql.stat().st_size / 1e6:.1f} MB")
    print(f"{out_geo}：{out_geo.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]  # Windows 控制台默认不是 UTF-8
    main()
