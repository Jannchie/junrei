"""junrei 数据同步：从 Anitabi 全量 + 增量拉取巡礼数据，规范化后落到本地 SQLite。

数据源是主站前端自己用的静态数据包（非公开接口，格式可能随时变化）：
  /d/g.json      全站索引：作品基本信息 + 每个地标的坐标/优先级 + 全局 modified
  /d/g{n}.json   详情分页：每页 pageSize 部作品，按作品 modified 倒序，顺序与索引一致

增量策略（与主站前端一致）：顺序拉详情页，遇到 modified 与本地相同的作品即停止；
另外若索引里某作品的地标 id 集合与本地不同，也补拉它所在的页。

仅用标准库。用法：
  python -m sync.sync              # 增量（首次运行即全量）
  python -m sync.sync --full       # 强制全量
  python -m sync.sync --report     # 只根据本地数据库重新生成质量报告
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from sync.net import request

BASE = "https://www.anitabi.cn"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data"
UA = "junrei-sync/0.1 (+https://junrei.jannchie.com; non-commercial)"
PAGE_DELAY = 1.0  # 每次请求之间的间隔（秒），别给对方服务器添麻烦

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS bangumi (
  id INTEGER PRIMARY KEY,
  cn TEXT, en TEXT, title TEXT, city TEXT, color TEXT, cover TEXT,
  fade REAL,            -- 前端字段名为 fade，取值形似 Bangumi 评分
  cat TEXT, lat REAL, lng REAL, zoom REAL,
  abbr TEXT, tags TEXT, priority INTEGER, icon TEXT, t_abbr TEXT,
  modified INTEGER,     -- 来自详情页；NULL 表示还没拉过详情
  theme TEXT,
  index_point_ids TEXT, -- 索引中的地标 id 列表（JSON），用于发现需要补拉的作品
  deleted INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS point (
  bangumi_id INTEGER NOT NULL,
  id TEXT NOT NULL,
  name TEXT, cn TEXT, lat REAL, lng REAL, priority INTEGER,
  is_folder INTEGER, folder TEXT, mid TEXT, uid INTEGER, image TEXT, fid TEXT,
  ep TEXT, s REAL, mark TEXT, origin TEXT, origin_link TEXT, density INTEGER,
  in_index INTEGER, in_detail INTEGER,
  raw TEXT,
  PRIMARY KEY (bangumi_id, id)
);
CREATE INDEX IF NOT EXISTS point_geo ON point (lat, lng);
CREATE TABLE IF NOT EXISTS sync_log (
  started_at TEXT, finished_at TEXT, mode TEXT, index_modified INTEGER,
  pages_fetched TEXT, bangumi_updated INTEGER, bytes INTEGER, note TEXT
);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def nz(v):
    """前端用 0 表示空值。"""
    return None if v in (0, "", None) else v


class Fetcher:
    def __init__(self, cache_key: str, raw_dir: Path | None):
        self.cache_key = cache_key
        self.raw_dir = raw_dir
        self.bytes = 0
        self._last = 0.0

    def get_json(self, path: str):
        wait = PAGE_DELAY - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = f"{BASE}{path}?d={self.cache_key}"
        status, body = request(url, ua=UA, timeout=60)
        if status != 200:
            raise RuntimeError(f"{path} → {status}")
        self._last = time.monotonic()
        self.bytes += len(body)
        if self.raw_dir:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            (self.raw_dir / Path(path).name).write_bytes(body)
        print(f"  ↓ {path}  {len(body) / 1e6:.2f} MB")
        return json.loads(body)


# ---------- 解析（字段顺序对照前端 FD / DD / PD 函数） ----------

def parse_index(data):
    rows, page_size, modified = data
    out = []
    for r in rows:
        (bid, cn, en, title, city, color, cover, fade, cat, lat, lng, zoom,
         flat, abbr, tags, priority, icon, t_abbr) = r
        points = [
            {"id": flat[i], "lat": flat[i + 1], "lng": flat[i + 2], "priority": flat[i + 3] or 999}
            for i in range(0, len(flat), 4)
        ]
        out.append({
            "id": bid, "cn": nz(cn), "en": nz(en), "title": nz(title), "city": nz(city),
            "color": nz(color), "cover": image_url(nz(cover)), "fade": nz(fade),
            "cat": None if not cat or "<" in cat else cat,  # 源数据里混进过 HTML
            "lat": lat or None, "lng": lng or None, "zoom": nz(zoom), "abbr": nz(abbr),
            "tags": json.dumps(tags or [], ensure_ascii=False), "priority": int(priority or 999),
            "icon": nz(icon), "t_abbr": nz(t_abbr), "points": points,
        })
    return out, page_size, modified


def parse_detail_point(p):
    (pid, name, cn, is_folder, mid, uid, image, fid, ep, s, mark, origin,
     origin_link, folder, density) = p
    return {
        "id": pid, "name": nz(name), "cn": nz(cn), "is_folder": int(bool(is_folder)),
        "mid": nz(mid), "uid": nz(uid), "image": image_url(nz(image)), "fid": nz(fid),
        "ep": None if ep in ("", None) else str(ep), "s": s if s not in ("", None) else None,
        "mark": nz(mark), "origin": nz(origin), "origin_link": nz(origin_link),
        "folder": nz(folder), "density": nz(density), "raw": json.dumps(p, ensure_ascii=False),
    }


def parse_page(data):
    for bid, theme, points, modified in data:
        yield bid, theme, [parse_detail_point(p) for p in points], modified


# ---------- 同步 ----------

def sync(db: sqlite3.Connection, fetcher: Fetcher, full: bool) -> None:
    started = now_iso()
    meta = dict(db.execute("SELECT key, value FROM meta"))
    print("拉取索引 …")
    index, page_size, index_modified = parse_index(fetcher.get_json("/d/g.json"))
    print(f"  索引：{len(index)} 部作品，{sum(len(b['points']) for b in index)} 个地标，pageSize={page_size}")

    if not full and meta.get("index_modified") == str(index_modified):
        print("索引 modified 未变化，无需同步。")
        db.execute("INSERT INTO sync_log VALUES (?,?,?,?,?,?,?,?)",
                   (started, now_iso(), "noop", index_modified, "[]", 0, fetcher.bytes, None))
        db.commit()
        return

    local = {r[0]: (r[1], r[2]) for r in db.execute(
        "SELECT id, modified, index_point_ids FROM bangumi WHERE deleted = 0")}
    is_first = not local
    mode = "full" if full or is_first else "incremental"

    # 1) 索引是全量的：作品基本信息、地标坐标每次都整体更新
    ts = now_iso()
    must_pages = set()
    index_ids = {}  # 作品 id → 索引中的地标 id 列表（JSON），与本地比对发现需要补拉的作品
    for pos, b in enumerate(index):
        ids = index_ids[b["id"]] = json.dumps(sorted(p["id"] for p in b["points"]))
        old = local.get(b["id"])
        if old is None or old[1] != ids:
            must_pages.add(pos // page_size)
        db.execute(
            """INSERT INTO bangumi (id, cn, en, title, city, color, cover, fade, cat, lat, lng, zoom,
                 abbr, tags, priority, icon, t_abbr, index_point_ids, deleted, first_seen, updated_at)
               VALUES (:id,:cn,:en,:title,:city,:color,:cover,:fade,:cat,:lat,:lng,:zoom,
                 :abbr,:tags,:priority,:icon,:t_abbr,:ids,0,:ts,:ts)
               ON CONFLICT(id) DO UPDATE SET cn=excluded.cn, en=excluded.en, title=excluded.title,
                 city=excluded.city, color=excluded.color, cover=excluded.cover, fade=excluded.fade,
                 cat=excluded.cat, lat=excluded.lat, lng=excluded.lng, zoom=excluded.zoom,
                 abbr=excluded.abbr, tags=excluded.tags, priority=excluded.priority, icon=excluded.icon,
                 t_abbr=excluded.t_abbr, index_point_ids=excluded.index_point_ids, deleted=0,
                 updated_at=excluded.updated_at""",
            {**b, "ids": ids, "ts": ts},
        )
        db.executemany(
            "UPDATE point SET lat=?, lng=?, priority=? WHERE bangumi_id=? AND id=?",
            [(p["lat"], p["lng"], p["priority"], b["id"], p["id"]) for p in b["points"]],
        )
    gone = set(local) - set(index_ids)
    if gone:
        db.executemany("UPDATE bangumi SET deleted=1, updated_at=? WHERE id=?", [(ts, i) for i in gone])
        print(f"  索引中消失（标记删除）：{len(gone)} 部")
    index_by_id = {b["id"]: b for b in index}

    # 2) 详情分页
    n_pages = math.ceil(len(index) / page_size)
    fetched, updated = [], 0
    stop = False
    for page in range(n_pages):
        if stop and page not in must_pages:
            continue
        data = fetcher.get_json(f"/d/g{page}.json")
        fetched.append(page)
        prev_mod = math.inf
        for bid, theme, points, modified in parse_page(data):
            if modified > prev_mod:
                print(f"  ! 第 {page} 页未按 modified 倒序，增量提前停止可能不可靠", file=sys.stderr)
            prev_mod = modified
            old = local.get(bid)
            if old is not None and old[0] == modified and not full:
                stop = True  # 之后的作品都更旧，只需补拉 must_pages
                if old[1] == index_ids.get(bid):
                    continue
            write_points(db, bid, points, index_by_id.get(bid, {}).get("points", []))
            db.execute("UPDATE bangumi SET modified=?, theme=?, updated_at=? WHERE id=?",
                       (modified, json.dumps(theme, ensure_ascii=False) if theme else None, ts, bid))
            updated += 1
        db.commit()
        print(f"    第 {page} 页处理完，累计更新 {updated} 部")

    db.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [
        ("index_modified", str(index_modified)), ("page_size", str(page_size)), ("last_sync", now_iso()),
    ])
    db.execute("INSERT INTO sync_log VALUES (?,?,?,?,?,?,?,?)",
               (started, now_iso(), mode, index_modified, json.dumps(fetched), updated, fetcher.bytes, None))
    db.commit()
    print(f"完成（{mode}）：拉取 {len(fetched)} 个详情页，更新 {updated} 部作品，共下载 {fetcher.bytes / 1e6:.1f} MB")


def write_points(db, bid, detail_points, index_points):
    geo = {p["id"]: p for p in index_points}
    detail_ids = {p["id"] for p in detail_points}
    db.execute("DELETE FROM point WHERE bangumi_id=?", (bid,))
    rows = []
    for p in detail_points:
        g = geo.get(p["id"], {})
        rows.append({**p, "bangumi_id": bid, "lat": g.get("lat"), "lng": g.get("lng"),
                     "priority": g.get("priority"), "in_index": int(p["id"] in geo), "in_detail": 1})
    for pid, g in geo.items():  # 索引里有、详情里没有的地标也保留，便于质量统计
        if pid not in detail_ids:
            rows.append({"id": pid, "bangumi_id": bid, "lat": g["lat"], "lng": g["lng"],
                         "priority": g["priority"], "in_index": 1, "in_detail": 0})
    cols = ["bangumi_id", "id", "name", "cn", "lat", "lng", "priority", "is_folder", "folder", "mid",
            "uid", "image", "fid", "ep", "s", "mark", "origin", "origin_link", "density",
            "in_index", "in_detail", "raw"]
    db.executemany(
        f"INSERT INTO point ({','.join(cols)}) VALUES ({','.join(':' + c for c in cols)})",
        [{c: r.get(c) for c in cols} for r in rows],
    )


# ---------- 规范化 ----------

def image_url(image):
    """/images/xxx → https://image.anitabi.cn/xxx（与官方 API 一致）。尺寸参数 plan 由前端按需追加。"""
    if not image:
        return None
    if image.startswith("/images/"):
        return "https://image.anitabi.cn/" + image[len("/images/"):]
    return image.replace("http://", "https://", 1)


def attribution(bid, pid, origin, link):
    """截图署名（CC BY-NC-SA）。无外部来源时按官方 API 的做法，回退为指向 Anitabi 地标页。"""
    return origin or "Anitabi", link or f"https://www.anitabi.cn/map?bangumiId={bid}&pid={pid}"


def valid_geo(lat, lng):
    return lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0, 0)


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ---------- 数据质量 ----------

JAPAN_BBOX = (24.0, 46.0, 122.0, 154.0)


def haversine_km(a_lat, a_lng, b_lat, b_lng):
    r = math.radians
    h = math.sin(r(b_lat - a_lat) / 2) ** 2 + math.cos(r(a_lat)) * math.cos(r(b_lat)) * math.sin(r(b_lng - a_lng) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def pct(n, total):
    return f"{n} ({n / total:.1%})" if total else "0"


def quality_report(db, out: Path):
    B = db.execute("SELECT id, cn, title, city, cover, cat, lat, lng, modified FROM bangumi WHERE deleted=0").fetchall()
    P = db.execute(
        """SELECT p.bangumi_id, p.id, p.name, p.cn, p.lat, p.lng, p.image, p.ep, p.s, p.origin,
                  p.origin_link, p.is_folder, p.in_index, p.in_detail, p.uid, p.mark
           FROM point p JOIN bangumi b ON b.id=p.bangumi_id WHERE b.deleted=0""").fetchall()
    nb, np_ = len(B), len(P)
    by_b = Counter(p[0] for p in P)
    counts = sorted(by_b.get(b[0], 0) for b in B)
    now_ms = time.time() * 1000

    # 作品中心点离自己所有地标都很远 → 中心点可能填错
    pts_of = {}
    for p in P:
        if valid_geo(p[4], p[5]):
            pts_of.setdefault(p[0], []).append((p[4], p[5]))
    far_center = []
    for b in B:
        pts = pts_of.get(b[0])
        if pts and valid_geo(b[6], b[7]):
            d = min(haversine_km(b[6], b[7], la, ln) for la, ln in pts)
            if d > 100:
                far_center.append((b[0], b[1] or b[2], round(d)))

    dup_coord = Counter()
    for p in P:
        if valid_geo(p[4], p[5]):
            dup_coord[(p[0], round(p[4], 6), round(p[5], 6))] += 1
    dup_points = sum(c - 1 for c in dup_coord.values() if c > 1)

    def age_bucket(m):
        if not m:
            return "未知"
        d = (now_ms - m) / 86_400_000
        for lim, name in ((7, "≤7 天"), (30, "≤30 天"), (180, "≤180 天"), (365, "≤1 年")):
            if d <= lim:
                return name
        return ">1 年"

    with_img = [p for p in P if p[6]]
    in_japan = sum(1 for p in P if valid_geo(p[4], p[5])
                   and JAPAN_BBOX[0] <= p[4] <= JAPAN_BBOX[1] and JAPAN_BBOX[2] <= p[5] <= JAPAN_BBOX[3])
    stats = {
        "generated_at": now_iso(),
        "bangumi": {
            "total": nb,
            "deleted": db.execute("SELECT COUNT(*) FROM bangumi WHERE deleted=1").fetchone()[0],
            "no_points": sum(1 for c in counts if c == 0),
            "no_center_geo": sum(1 for b in B if not valid_geo(b[6], b[7])),
            "no_city": sum(1 for b in B if not b[3]),
            "no_cover": sum(1 for b in B if not b[4]),
            "no_cn_title": sum(1 for b in B if not b[1]),
            "no_cat": sum(1 for b in B if not b[5]),
            "detail_never_fetched": sum(1 for b in B if b[8] is None),
            "center_far_from_points_gt100km": len(far_center),
            "points_per_bangumi": {
                "median": statistics.median(counts) if counts else 0,
                "p90": counts[int(len(counts) * 0.9)] if counts else 0,
                "max": counts[-1] if counts else 0,
            },
            "category": dict(Counter(b[5] or "（空）" for b in B).most_common()),
            "modified_age": dict(Counter(age_bucket(b[8]) for b in B)),
        },
        "points": {
            "total": np_,
            "invalid_geo": sum(1 for p in P if not valid_geo(p[4], p[5])),
            "outside_japan_bbox": sum(1 for p in P if valid_geo(p[4], p[5])) - in_japan,
            "no_image": sum(1 for p in P if not p[6]),
            "no_cn_name": sum(1 for p in P if not p[3]),
            "no_name": sum(1 for p in P if not p[2] and not p[3]),
            "no_episode": sum(1 for p in P if p[7] is None),
            "no_timestamp": sum(1 for p in P if not p[8]),
            "image_without_attribution": sum(1 for p in with_img if not p[9] and not p[10]),
            "has_note": sum(1 for p in P if p[15]),
            "folder": sum(1 for p in P if p[11]),
            "only_in_index": sum(1 for p in P if p[12] and not p[13]),
            "only_in_detail": sum(1 for p in P if p[13] and not p[12]),
            "duplicate_coords_in_same_bangumi": dup_points,
            "contributors": len({p[14] for p in P if p[14]}),
            "top_contributor_uids": Counter(p[14] for p in P if p[14]).most_common(10),
        },
        "top_bangumi_by_points": [
            (bid, next((b[1] or b[2] for b in B if b[0] == bid), None), n) for bid, n in by_b.most_common(10)
        ],
        "center_far_samples": sorted(far_center, key=lambda x: -x[2])[:15],
    }
    write_json(out / "report.json", stats)

    bs, ps = stats["bangumi"], stats["points"]
    L = [f"# Anitabi 数据质量报告", "", f"生成时间：{stats['generated_at']}", "",
         "## 作品", "", "| 指标 | 数量 |", "|---|---|"]
    rows_b = [("作品总数", nb), ("已从索引消失（软删除）", bs["deleted"]),
              ("没有地标", pct(bs["no_points"], nb)), ("缺中心坐标", pct(bs["no_center_geo"], nb)),
              ("缺城市", pct(bs["no_city"], nb)), ("缺封面", pct(bs["no_cover"], nb)),
              ("缺中文名", pct(bs["no_cn_title"], nb)), ("缺分类", pct(bs["no_cat"], nb)),
              ("中心点离所有地标 >100km", pct(bs["center_far_from_points_gt100km"], nb)),
              ("每部地标数 中位数 / P90 / 最大", "{median} / {p90} / {max}".format(**bs["points_per_bangumi"]))]
    L += [f"| {k} | {v} |" for k, v in rows_b]
    L += ["", "分类：" + "、".join(f"{k} {v}" for k, v in bs["category"].items()), "",
          "最近更新：" + "、".join(f"{k} {v}" for k, v in sorted(bs["modified_age"].items())), "",
          "## 地标", "", "| 指标 | 数量 |", "|---|---|"]
    rows_p = [("地标总数", np_), ("坐标无效", pct(ps["invalid_geo"], np_)),
              ("在日本范围外", pct(ps["outside_japan_bbox"], np_)), ("无截图", pct(ps["no_image"], np_)),
              ("无中文名", pct(ps["no_cn_name"], np_)), ("完全无名称", pct(ps["no_name"], np_)),
              ("无集数", pct(ps["no_episode"], np_)), ("无时间点", pct(ps["no_timestamp"], np_)),
              ("有截图但无外部来源（导出时回退署名为 Anitabi）", pct(ps["image_without_attribution"], len(with_img))),
              ("带备注", pct(ps["has_note"], np_)), ("文件夹型地标", pct(ps["folder"], np_)),
              ("只在索引、不在详情", ps["only_in_index"]), ("只在详情、不在索引", ps["only_in_detail"]),
              ("同作品内坐标完全重复", ps["duplicate_coords_in_same_bangumi"]),
              ("贡献者（uid）数", ps["contributors"])]
    L += [f"| {k} | {v} |" for k, v in rows_p]
    L += ["", "## 地标最多的作品", ""] + [f"- {n} 个：{name}（{bid}）" for bid, name, n in stats["top_bangumi_by_points"]]
    if far_center:
        L += ["", "## 中心点可疑的作品（离最近地标的距离）", ""] + [
            f"- {name}（{bid}）：{d} km" for bid, name, d in stats["center_far_samples"]]
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"质量报告：{out / 'report.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（默认 <项目根>/data）")
    ap.add_argument("--full", action="store_true", help="强制全量同步")
    ap.add_argument("--report", action="store_true", help="不联网，只重新生成质量报告")
    ap.add_argument("--cache-key", default=dt.date.today().isoformat(),
                    help="请求参数 d 的值。默认与主站一致按天，命中同一份 CDN 缓存，对源站最友好")
    ap.add_argument("--keep-raw", action="store_true", help="保存原始响应到 out/raw/<cache-key>/")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out / "anitabi.sqlite")
    db.executescript(SCHEMA)
    if not args.report:
        raw = out / "raw" / args.cache_key if args.keep_raw else None
        sync(db, Fetcher(args.cache_key, raw), args.full)
    quality_report(db, out)
    db.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]  # Windows 控制台默认不是 UTF-8
    main()
