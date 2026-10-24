"""铁路线路图层：从 OpenStreetMap 取铁路线路（route 关系），按线路配色切成矢量瓦片（PMTiles），放到 R2。

  python -m sync.rail fetch     # 拉取各地区的线路关系与轨道几何（缓存在 data/rail/，已有的不再请求）
  python -m sync.rail build     # 合并成线路、切瓦片，写出 data/rail/rail.pmtiles
  python -m sync.rail upload    # 上传到 R2（cdn.jannchie.com/junrei/rail/…）

底图（OpenMapTiles）里的铁路丢掉了线路名、颜色与是否高铁，所以另做一层。
高铁直接取标了 highspeed=yes 的轨道，按轨道的线路名合并（新干线在 OSM 里多半只有「のぞみ」这类车次关系，靠关系认不全）。
其余轨道每段只归给一条线路（普通铁路优先，其次地铁…；有 route_master、有颜色、名称不像车次的优先），同一线路相连的轨道合成一条线。
颜色取 OSM 的 colour（线路关系或其 route_master），没有颜色的由前端按类型给一个默认色。
Overpass 一次取不动带几何的关系，所以分两步：先取关系（只有成员 id），再按 id 分批取轨道几何。
数据 © OpenStreetMap contributors（ODbL）。
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import mapbox_vector_tile
import numpy as np
import shapely
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import MultiLineString

from sync.covers import Uploader
from sync.enrich_common import setup_stdout
from sync.net import request

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "junrei-rail/1.0 (https://junrei.jannchie.com)"
ROOT = Path("data/rail")
OUT = ROOT / "rail.pmtiles"
KEY = "junrei/rail/rail-v4.pmtiles"  # 内容变了就换版本号：对象按 immutable 缓存

# 地区按 bbox（南, 西, 北, 东）取；相邻地区重复的关系按 id 去重
REGIONS = {
    "jp-kr": (24.0, 122.0, 46.0, 146.0),
    "tw": (21.8, 119.3, 25.4, 122.1),
}
BUILD_REGIONS = ["jp-kr"]  # 目前只画日本（取数仍可取各地区，切瓦片时只留 in_japan 的轨道）


def in_japan(lng: float, lat: float) -> bool:
    """粗略的日本范围：冲绳；九州西端（平户、佐世保约 129.5°E）以东、北纬 37.5° 以南；东经 138.5° 以东的本州北部与北海道。
    朝鲜半岛的铁路都在 129.4°E 以西，俄罗斯远东在 138.5°E 以西或北纬 46° 以北"""
    return (lat < 27 and lng >= 125) or (lat < 37.5 and lng >= 129.5) or (lng >= 138.5 and lat <= 46)
ROUTES = "train|subway|light_rail|monorail|tram"
# 线路类型的优先级（同一段轨道属于多条线路时归给谁），也是瓦片里的 k 属性
KINDS = ["hs", "train", "subway", "light_rail", "monorail", "tram"]
# 各类型从哪一级开始出现：缩小时只留高铁与干线
MINZOOM = {"hs": 4, "train": 6, "subway": 9, "light_rail": 9, "monorail": 9, "tram": 11}
MAXZOOM = 13
EXTENT = 4096
BUFFER = 64  # 瓦片四周多切出的边距（瓦片单位），线在瓦片边上不断
NOT_TRACK = re.compile(r"platform|stop")


def overpass(query: str) -> dict:
    for attempt in range(4):
        status, body = request(OVERPASS, data=f"data={_quote(query)}".encode(), method="POST", ua=UA, timeout=600,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        if status == 200:
            return json.loads(body)
        print(f"  ! Overpass {status}，{30 * (attempt + 1)} 秒后重试", file=sys.stderr)
        time.sleep(30 * (attempt + 1))
    sys.exit("Overpass 一直失败")


def _quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s, safe="")


def fetch(regions: list[str]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in regions:
        s, w, n, e = REGIONS[name]
        rel_file = ROOT / f"{name}-relations.json"
        if not rel_file.exists():
            print(f"{name}：线路关系")
            data = overpass(f'[out:json][timeout:300];(relation[type=route][route~"^({ROUTES})$"]({s},{w},{n},{e});'
                            f'relation[type=route_master][route_master~"^({ROUTES})$"]({s},{w},{n},{e}););out body qt;')
            rel_file.write_text(json.dumps(data["elements"], ensure_ascii=False), encoding="utf-8")
            time.sleep(1)
        hs_file = ROOT / f"{name}-highspeed.json"
        if not hs_file.exists():
            print(f"{name}：高铁轨道")
            data = overpass(f"[out:json][timeout:300];way[railway=rail][highspeed=yes]({s},{w},{n},{e});out tags geom qt;")
            hs = {e["id"]: {"g": [(p["lon"], p["lat"]) for p in e["geometry"]],
                            **{k: v for k, v in e.get("tags", {}).items() if k in ("name", "name:en", "name:ja", "name:zh", "colour")}}
                  for e in data["elements"] if e.get("geometry")}
            hs_file.write_text(json.dumps(hs, ensure_ascii=False), encoding="utf-8")
            time.sleep(1)
        rels = json.loads(rel_file.read_text(encoding="utf-8"))
        ways = sorted({m["ref"] for r in rels if r["tags"].get("type") == "route" for m in r["members"]
                       if m["type"] == "way" and not NOT_TRACK.search(m.get("role", ""))})
        way_dir = ROOT / f"{name}-ways"
        way_dir.mkdir(exist_ok=True)
        size = 5000
        for i in range(0, len(ways), size):
            f = way_dir / f"{i // size:04d}.json"
            if f.exists():
                continue
            print(f"{name}：轨道几何 {i}–{min(i + size, len(ways))} / {len(ways)}")
            ids = ",".join(map(str, ways[i:i + size]))
            data = overpass(f"[out:json][timeout:300];way(id:{ids});out geom qt;")
            geoms = {e["id"]: [(p["lon"], p["lat"]) for p in e["geometry"]] for e in data["elements"] if e.get("geometry")}
            f.write_text(json.dumps(geoms), encoding="utf-8")
            time.sleep(1)


COLOUR = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
NAMED = {"red": "#e60012", "green": "#009944", "blue": "#0068b7", "orange": "#f39800", "yellow": "#ffd400",
         "purple": "#8f4b9f", "brown": "#8f5e3a", "pink": "#e85298", "gray": "#8e8e8e", "grey": "#8e8e8e"}
# 名称里的方向、区间说明：「（上り）」「 (外回り)」「: 東京 => 新大阪」
NAME_NOISE = re.compile(r"\s*[（(][^）)]*[）)]|\s*[:：].*$")


def colour(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip().lower()
    if v in NAMED:
        return NAMED[v]
    m = COLOUR.match(v)
    if not m:
        return None
    h = m.group(1)
    return "#" + (h if len(h) == 6 else "".join(c * 2 for c in h))


def clean(name: str | None) -> str | None:
    if not name:
        return None
    name = name.split(";")[0]  # 「山陽新幹線;石原トンネル」：多值取第一个
    return NAME_NOISE.sub("", name).strip() or name


# 车次、运行区间一类的名称（「台灣高鐵 603 南港->左營」「のぞみ」）：不适合当线路名
SERVICE_NAME = re.compile(r"\d{2,}|->|=>|→|列車|直通|service", re.I)
LINE_NAME = re.compile(r"線|ライン|[Ll]ine|선|线")
EXPRESS = {"express", "long_distance", "night", "tourism", "high_speed", "car_shuttle"}


def names(tags: dict) -> dict:
    return {dst: v for src, dst in (("name", "n"), ("name:en", "en"), ("name:ja", "ja"), ("name:zh", "zh")) if (v := clean(tags.get(src)))}


def lines(regions: list[str]) -> list[dict]:
    """线路关系 → 线路（每段轨道只归给一条线路，同一线路的相连轨道合并）"""
    rels: dict[int, dict] = {}
    geoms: dict[int, list] = {}
    hs: dict[int, dict] = {}
    for name in regions:
        hs.update({int(k): v for k, v in json.loads((ROOT / f"{name}-highspeed.json").read_text(encoding="utf-8")).items() if in_japan(*v["g"][0])})
        for r in json.loads((ROOT / f"{name}-relations.json").read_text(encoding="utf-8")):
            rels[r["id"]] = r
        for f in sorted((ROOT / f"{name}-ways").glob("*.json")):
            geoms.update({int(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if v and in_japan(*v[0])})
    # route → route_master（名称与颜色以 route_master 为准，上下行两条关系合成一条线路）
    master_of = {m["ref"]: r for r in rels.values() if r["tags"].get("type") == "route_master" for m in r["members"] if m["type"] == "relation"}
    routes = [r for r in rels.values() if r["tags"].get("type") == "route" and r["tags"].get("route") in KINDS]

    info: dict[int, dict] = {}  # 线路 id（route_master 或 route 自己）→ 属性
    owner: dict[int, tuple] = {}  # 轨道 → (优先级, 线路 id)
    for r in routes:
        m = master_of.get(r["id"])
        key = m["id"] if m else r["id"]
        t = {**r["tags"], **(m["tags"] if m else {})}
        if key not in info:
            # 名称不像线路名的（特急「あずさ」、运行系统「Stopping service」）只画线、不标名称
            props = {"k": r["tags"]["route"], **(names(t) if LINE_NAME.search(t.get("name", "")) else {})}
            c = colour(t.get("colour")) or colour(r["tags"].get("colour"))
            if c:
                props["c"] = c
            info[key] = props
        props = info[key]
        # 同一段轨道上有多条线路时：像线路名的（「…線」）、普通列车的、有 route_master 的、有颜色的优先；
        # 特急（「あずさ」「はこね」）、直通运转这类运行系统排在后面
        rank = (KINDS.index(props["k"]), not LINE_NAME.search(props.get("n", "")), r["tags"].get("service") in EXPRESS,
                bool(SERVICE_NAME.search(props.get("n", ""))), m is None, "c" not in props, key)
        for mem in r["members"]:
            if mem["type"] == "way" and not NOT_TRACK.search(mem.get("role", "")) and mem["ref"] in geoms and mem["ref"] not in hs:
                if mem["ref"] not in owner or rank < owner[mem["ref"]]:
                    owner[mem["ref"]] = rank

    parts: dict = defaultdict(list)
    for way, rank in owner.items():
        if len(geoms[way]) >= 2:
            parts[rank[-1]].append(geoms[way])
    # 高铁按轨道上的线路名分组（东海道新幹線、경부고속선…），没有名称的归在一起
    for way in hs.values():
        if len(way["g"]) >= 2:
            key = ("hs", way.get("name", "").split(";")[0])
            parts[key].append(way["g"])
            if key not in info:
                info[key] = {"k": "hs", **names(way), **({"c": c} if (c := colour(way.get("colour"))) else {})}
    return [{"geom": shapely.line_merge(MultiLineString(segs)), "props": info[key]} for key, segs in parts.items()]


def build(regions: list[str]) -> None:
    feats = lines(regions)
    print(f"{len(feats)} 条线路")
    for f in feats:
        f["geom"] = shapely.transform(f["geom"], _merc_array)

    tiles: dict[int, bytes] = {}
    # 自上而下逐级切：子瓦片只从父瓦片切出的部分里再切，长线路不必和每个瓦片求交
    level: dict[tuple[int, int], list] = {}
    z0 = min(MINZOOM.values())
    n0 = 2 ** z0
    for i, f in enumerate(feats):
        x0, y0, x1, y1 = f["geom"].bounds
        for tx in range(int(x0 * n0), int(x1 * n0) + 1):
            for ty in range(int(y0 * n0), int(y1 * n0) + 1):
                level.setdefault((tx, ty), []).append((i, f["geom"]))
    for z in range(z0, MAXZOOM + 1):
        n = 2 ** z
        unit = 1 / (n * EXTENT)
        nxt: dict[tuple[int, int], list] = {}
        for (tx, ty), items in level.items():
            b = BUFFER * unit
            box = (tx / n - b, ty / n - b, (tx + 1) / n + b, (ty + 1) / n + b)
            kept = []
            for i, g in items:
                g = shapely.clip_by_rect(g, *box)
                if g.is_empty:
                    continue
                kept.append((i, g))
                if z < MAXZOOM:
                    for cx in (2 * tx, 2 * tx + 1):
                        for cy in (2 * ty, 2 * ty + 1):
                            nxt.setdefault((cx, cy), []).append((i, g))
            layer = []
            for i, g in kept:
                p = feats[i]["props"]
                if MINZOOM[p["k"]] > z:
                    continue
                g = shapely.simplify(g, unit * 1.5, preserve_topology=False)
                g = shapely.transform(g, lambda a, tx=tx, ty=ty, n=n: (a * n - [tx, ty]) * EXTENT)
                if g.is_empty or g.length < 2:
                    continue
                layer.append({"geometry": g, "properties": p})
            if layer:
                mvt = mapbox_vector_tile.encode([{"name": "rail", "features": layer}],
                                                default_options={"y_coord_down": True, "extents": EXTENT, "quantize_bounds": None})
                tiles[zxy_to_tileid(z, tx, ty)] = gzip.compress(mvt, mtime=0)
        print(f"z{z}：累计 {len(tiles)} 个瓦片")
        level = nxt

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("wb") as fh:
        w = Writer(fh)
        for tid in sorted(tiles):
            w.write_tile(tid, tiles[tid])
        lons = [c for f in feats for c in f["geom"].bounds]
        xs, ys = lons[0::2], lons[1::2]
        to_lon = lambda x: x * 360 - 180
        to_lat = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))
        w.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_lon_e7": int(to_lon(min(xs)) * 1e7), "min_lat_e7": int(to_lat(max(ys)) * 1e7),
                "max_lon_e7": int(to_lon(max(xs)) * 1e7), "max_lat_e7": int(to_lat(min(ys)) * 1e7),
                "center_zoom": 6, "center_lon_e7": int(139.7 * 1e7), "center_lat_e7": int(35.7 * 1e7),
            },
            {
                "name": "junrei rail",
                "attribution": "© OpenStreetMap contributors",
                "vector_layers": [{"id": "rail", "fields": {"k": "String", "c": "String", "n": "String", "en": "String", "ja": "String", "zh": "String"},
                                   "minzoom": z0, "maxzoom": MAXZOOM}],
            },
        )
    print(f"写出 {OUT}：{len(tiles)} 个瓦片，{OUT.stat().st_size / 1e6:.1f} MB")


def _merc_array(a):
    """经纬度 → 归一化的 Web 墨卡托坐标（0–1，y 向下）"""
    lon, lat = a[:, 0], np.clip(a[:, 1], -85.0511, 85.0511)
    s = np.sin(np.radians(lat))
    return np.column_stack(((lon + 180) / 360, 0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)))


def upload() -> None:
    ok = Uploader().put(KEY, OUT.read_bytes(), "application/vnd.pmtiles", "public, max-age=31536000, immutable")
    print(("已上传 " if ok else "上传失败 ") + KEY)


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "build", "upload"])
    ap.add_argument("--regions", nargs="*", default=None, help="默认：fetch 取全部地区，build 只用 BUILD_REGIONS")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.regions or list(REGIONS))
    elif a.cmd == "build":
        build(a.regions or BUILD_REGIONS)
    else:
        upload()


if __name__ == "__main__":
    main()
