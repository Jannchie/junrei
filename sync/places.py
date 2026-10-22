"""地点实体：把坐标重复 / 相近且名称相似的地标合并成 place，一个地点可挂多部作品。

合并规则（只看坐标有效的地标）：
  - 两点相距 ≤ SAME_M：视为同一坐标，直接合并（多为同作品重复录入或跨作品复制）
  - 相距 ≤ NEAR_M 且名称相似度 ≥ NAME_SIM：合并
  - 防止链式合并：合并后簇的外包框对角线不能超过 MAX_SPAN_M
  - 候选边按距离从近到远处理

每个地标都属于且只属于一个 place（单点也是一个 place），place.id 取成员中最小的
"bangumi_id:point_id"，原始数据不变时保持稳定。

  python -m sync.places
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from sync.enrich_common import add_data_arg, log_run, now_iso, open_db, setup_stdout
from sync.enrich_report import write_report
from sync.sync import haversine_km, valid_geo

SAME_M = 2.0
NEAR_M = 30.0
NAME_SIM = 0.6
MAX_SPAN_M = 60.0
METHOD_VERSION = "places-v1"

SCHEMA = """
DROP TABLE IF EXISTS place;
DROP TABLE IF EXISTS place_point;
CREATE TABLE place (
  id TEXT PRIMARY KEY,          -- 成员中最小的 "bangumi_id:point_id"
  lat REAL, lng REAL,           -- 成员坐标的平均
  name TEXT, cn TEXT,           -- 成员中出现最多的名称
  point_count INTEGER, bangumi_count INTEGER,
  span_m REAL,                  -- 成员外包框对角线
  method_version TEXT, created_at TEXT
);
CREATE TABLE place_point (
  place_id TEXT NOT NULL, bangumi_id INTEGER NOT NULL, point_id TEXT NOT NULL,
  distance_m REAL,              -- 到 place 中心的距离
  method TEXT,                  -- seed | same_coord | near_name：并入该簇时依据的规则
  confidence REAL,              -- seed / same_coord 为 1，near_name 为名称相似度
  PRIMARY KEY (bangumi_id, point_id)
);
CREATE INDEX place_point_place ON place_point (place_id);
"""

_STRIP = re.compile(r"[\s\u3000\u200b-\u200d\ufeff·・,，、。.\-－‐—_/／|｜:：!！?？'\"“”‘’「」『』【】\[\]()（）〈〉<>《》~〜～]+")
_SUFFIX = re.compile(r"(付近|周辺|周边|附近|一帯|一带|辺り|あたり|前|旁|边|旁边)$")
_PAREN = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
_EPISODE = re.compile(r"^(第?\s*\d+\s*[話话集回]|#\s*\d+|ep\s*\d+|s\d+e\d+)\s*", re.I)  # 名称前缀的集数


def norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = _EPISODE.sub("", _PAREN.sub("", s) or s) or s
    s = _STRIP.sub("", s)
    return _SUFFIX.sub("", s) or s


def bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def name_sim(a: list[str], b: list[str]) -> float:
    """两组名称（name / cn 规范化后）之间的最大相似度：bigram Dice，包含关系视为 0.9。"""
    best = 0.0
    for x in a:
        for y in b:
            if not x or not y:
                continue
            if x == y:
                return 1.0
            if min(len(x), len(y)) >= 2 and (x in y or y in x):
                best = max(best, 0.9)
                continue
            bx, by = bigrams(x), bigrams(y)
            best = max(best, 2 * len(bx & by) / (len(bx) + len(by)))
    return best


def meters(a, b) -> float:
    return haversine_km(a[0], a[1], b[0], b[1]) * 1000


class Clusters:
    """带外包框约束的并查集。"""

    def __init__(self, coords):
        self.parent = list(range(len(coords)))
        self.box = [(la, ln, la, ln) for la, ln in coords]

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i, j, max_span) -> bool:
        ri, rj = self.find(i), self.find(j)
        if ri == rj:
            return False
        a, b = self.box[ri], self.box[rj]
        box = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
        if meters(box[:2], box[2:]) > max_span:
            return False
        self.parent[rj] = ri
        self.box[ri] = box
        return True


def candidate_pairs(coords, radius_m):
    """网格分桶找出所有相距 ≤ radius_m 的点对，返回 [(距离, i, j)]。"""
    dlat = radius_m / 111_320
    grid = defaultdict(list)

    def cell(la, ln):
        row = math.floor(la / dlat)
        dlng = dlat / max(math.cos(math.radians(row * dlat)), 0.01)
        return row, math.floor(ln / dlng), dlng

    for i, (la, ln) in enumerate(coords):
        r, c, _ = cell(la, ln)
        grid[(r, c)].append(i)
    pairs = []
    for i, (la, ln) in enumerate(coords):
        r0, _, _ = cell(la, ln)
        for r in (r0 - 1, r0, r0 + 1):
            rla = (r + 0.5) * dlat
            _, c0, _ = cell(rla, ln)
            for c in (c0 - 1, c0, c0 + 1):
                for j in grid.get((r, c), ()):
                    if j > i:
                        d = meters(coords[i], coords[j])
                        if d <= radius_m:
                            pairs.append((d, i, j))
    pairs.sort()
    return pairs


def build(db):
    rows = [r for r in db.execute(
        """SELECT p.bangumi_id, p.id, p.name, p.cn, p.lat, p.lng, p.priority
           FROM src.point p JOIN src.bangumi b ON b.id = p.bangumi_id
           WHERE b.deleted = 0 ORDER BY p.bangumi_id, p.id""") if valid_geo(r[4], r[5])]
    coords = [(r[4], r[5]) for r in rows]
    names = [[n for n in {norm_name(r[2]), norm_name(r[3])} if n] for r in rows]
    uf = Clusters(coords)
    how = {}  # 点 index → (method, confidence)
    edges = Counter()
    for d, i, j in candidate_pairs(coords, NEAR_M):
        if d <= SAME_M:
            method, conf = "same_coord", 1.0
        else:
            sim = name_sim(names[i], names[j])
            if sim < NAME_SIM:
                continue
            method, conf = "near_name", round(sim, 3)
        if uf.find(i) == uf.find(j):
            continue
        if uf.union(i, j, MAX_SPAN_M):
            edges[method] += 1
            # 记录较后加入的那个点的依据；同一点多次并入时保留置信度更高的
            for k in (i, j):
                if k not in how or how[k][1] < conf:
                    how[k] = (method, conf)
        else:
            edges["rejected_span"] += 1

    members = defaultdict(list)
    for i in range(len(rows)):
        members[uf.find(i)].append(i)

    ts = now_iso()
    places, links = [], []
    for idx in members.values():
        idx.sort(key=lambda k: (rows[k][0], rows[k][1]))
        seed = idx[0]
        pid = f"{rows[seed][0]}:{rows[seed][1]}"
        la = sum(coords[k][0] for k in idx) / len(idx)
        ln = sum(coords[k][1] for k in idx) / len(idx)
        lat_min, lng_min = min(coords[k][0] for k in idx), min(coords[k][1] for k in idx)
        lat_max, lng_max = max(coords[k][0] for k in idx), max(coords[k][1] for k in idx)
        name = Counter(rows[k][2] for k in idx if rows[k][2]).most_common(1)
        cn = Counter(rows[k][3] for k in idx if rows[k][3]).most_common(1)
        places.append((pid, la, ln, name[0][0] if name else None, cn[0][0] if cn else None, len(idx),
                       len({rows[k][0] for k in idx}), round(meters((lat_min, lng_min), (lat_max, lng_max)), 1),
                       METHOD_VERSION, ts))
        for k in idx:
            method, conf = ("seed", 1.0) if k == seed and len(idx) == 1 else how.get(k, ("seed", 1.0))
            links.append((pid, rows[k][0], rows[k][1], round(meters((la, ln), coords[k]), 1), method, conf))

    db.executescript(SCHEMA)
    db.executemany("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?,?)", places)
    db.executemany("INSERT INTO place_point VALUES (?,?,?,?,?,?)", links)
    db.commit()
    multi = [p for p in places if p[5] > 1]
    stats = {
        "points": len(rows), "places": len(places), "points_merged_away": len(rows) - len(places),
        "multi_point_places": len(multi), "multi_bangumi_places": sum(1 for p in places if p[6] > 1),
        "merges": dict(edges),
    }
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    started = now_iso()
    stats = build(db)
    log_run(db, "places", started, {"same_m": SAME_M, "near_m": NEAR_M, "name_sim": NAME_SIM,
                                    "max_span_m": MAX_SPAN_M, "version": METHOD_VERSION}, stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    write_report(db, data)


if __name__ == "__main__":
    setup_stdout()
    main()
