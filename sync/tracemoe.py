"""本地版 trace.moe：用截图找出是哪一集、第几秒，不受在线 API 的额度限制。

数据来自 trace.moe 官方公开的数据库 dump（https://huggingface.co/datasets/soruly/trace.moe-database-dump，CC0）：
每个视频每一帧的 MPEG-7 Color Layout（33 个整数），附 AniList 条目信息与集数。全量 25 GB、37 亿帧，
这里只留补漏用得到的作品（补漏清单与草稿里的作品，按标题对到 AniList），存进 data/tracemoe/frames.sqlite。

  python -m sync.tracemoe extract data/tracemoe/2026-10.sql.zst   # 流式解压、筛选；需要本机的 zstd 命令

依赖 numpy、pillow、zstandard（只在本机用，CI 不需要）。

检索时已经知道是哪部作品，只在它的各集里逐帧比对，比全库检索准，也不需要向量数据库。
向量算法移植自 trace.moe-id（github.com/soruly/trace.moe-id）的 ColorLayout，与 trace.moe 建库时一致。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import numpy as np

from sync.enrich_common import setup_stdout
from sync.fold import loose
from sync.sync import DEFAULT_OUT

DIR = DEFAULT_OUT / "tracemoe"
SCHEMA = """
CREATE TABLE IF NOT EXISTS anilist (id INTEGER PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, anilist_id INTEGER, episode_start INTEGER, episode_end INTEGER,
  path TEXT, duration REAL, color_layout BLOB  -- 原样保存：zstd 压缩的 JSON [{time, vector}]
);
CREATE INDEX IF NOT EXISTS files_anilist ON files(anilist_id);
"""

# ---- Color Layout（与 trace.moe-id 一致） ----

ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20,
          13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52,
          45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63]
# trace.moe-id 里写死的 DCT 系数表（照抄常数，保证和建库时一致）
_A, _B, _C, _D = 4.903926e-1, 4.157348e-1, 2.777851e-1, 9.754516e-2
_E, _F, _H = 3.535534e-1, 4.619398e-1, 1.913417e-1
COS = np.array([
    [_E, _E, _E, _E, _E, _E, _E, _E],
    [_A, _B, _C, _D, -_D, -_C, -_B, -_A],
    [_F, _H, -_H, -_F, -_F, -_H, _H, _F],
    [_B, -_D, -_A, -_C, _C, _A, _D, -_B],
    [_E, -_E, -_E, _E, _E, -_E, -_E, _E],
    [_C, -_A, _D, _B, -_B, -_D, _A, -_C],
    [_H, -_F, _F, -_H, -_H, _F, -_F, _H],
    [_D, -_C, _B, -_A, _A, -_B, _C, -_D],
])


def _quant_ydc(i: int) -> int:
    if i > 192:
        return 112 + ((i - 192) >> 2)
    if i > 160:
        return 96 + ((i - 160) >> 1)
    if i > 96:
        return 32 + (i - 96)
    if i > 64:
        return 16 + ((i - 64) >> 1)
    return i >> 2


def _quant_cdc(i: int) -> int:
    if i > 191:
        return 63
    if i > 160:
        return 56 + ((i - 160) >> 2)
    if i > 144:
        return 48 + ((i - 144) >> 1)
    if i > 112:
        return 16 + (i - 112)
    if i > 96:
        return 8 + ((i - 96) >> 1)
    if i > 64:
        return (i - 64) >> 2
    return 0


def _quant_ac(i: int) -> int:
    v = max(-256, min(255, i))
    a = abs(v)
    j = 64 + (a >> 2) if a > 127 else 32 + (a >> 1) if a > 63 else a
    return (-j if v < 0 else j) + 128


def _fdct(shape: np.ndarray) -> np.ndarray:
    block = shape.reshape(8, 8).astype(np.float64)
    rows = (block @ COS.T).astype(np.float32).astype(np.float64)  # 每行做一维 DCT；中间结果和原实现一样存成 float32
    return np.floor(COS @ rows + 0.499999).astype(np.int64).reshape(64)


def color_layout(rgb: np.ndarray) -> list[int]:
    """rgb：H×W×3 的 uint8 数组 → 33 个系数"""
    h, w, _ = rgb.shape
    xs = [-(-i * w // 8) for i in range(9)]
    ys = [-(-i * h // 8) for i in range(9)]
    shape = np.zeros((3, 64), dtype=np.int64)
    for by in range(8):
        for bx in range(8):
            block = rgb[ys[by]:ys[by + 1], xs[bx]:xs[bx + 1]].reshape(-1, 3).astype(np.float64)
            if not len(block):
                continue
            r, g, b = (block.sum(0) / (len(block) * 256)).astype(np.float32)
            yy = np.float32(0.299) * r + np.float32(0.587) * g + np.float32(0.114) * b
            k = by * 8 + bx
            shape[0, k] = int(np.floor(219 * yy + 16.5))
            shape[1, k] = int(np.floor(126.336 * (b - yy) + 128.5))
            shape[2, k] = int(np.floor(159.712 * (r - yy) + 128.5))
    y, cb, cr = (_fdct(s) for s in shape)
    out = [_quant_ydc(int(y[0]) >> 3) >> 1]
    out += [_quant_ac(int(y[ZIGZAG[i]]) >> 1) >> 3 for i in range(1, 21)]
    out += [_quant_cdc(int(cb[0]) >> 3)] + [_quant_ac(int(cb[ZIGZAG[i]])) >> 3 for i in range(1, 6)]
    out += [_quant_cdc(int(cr[0]) >> 3)] + [_quant_ac(int(cr[ZIGZAG[i]])) >> 3 for i in range(1, 6)]
    return out


def image_vector(body: bytes) -> list[int] | None:
    """和 trace.moe 处理上传图片一样：缩到 320×320 以内，透明处垫黑"""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(body))
        im.thumbnail((320, 320), Image.Resampling.LANCZOS)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
            im = Image.alpha_composite(bg, im)
        return color_layout(np.asarray(im.convert("RGB")))
    except Exception:  # noqa: BLE001 - 图片格式五花八门
        return None


# ---- 检索 ----

def titles_of(info: dict) -> list[str]:
    return [t for t in [*(info.get("title") or {}).values(), *(info.get("synonyms") or [])] if t]


def match_anilist(db, names: list[str]) -> dict[int, str]:
    """作品名（含别名）→ AniList 条目：标题一致为 exact，互为前缀为 series（多是续作、剧场版）"""
    ours = {loose(n) for n in names if n and len(loose(n)) >= 2}
    out: dict[int, str] = {}
    for aid, info in anilist_titles(db).items():
        if ours & info:
            out[aid] = "exact"
        elif any(a.startswith(b) or b.startswith(a) for a in info for b in ours):
            out[aid] = "series"
    return out


_titles: dict[int, set[str]] | None = None


def anilist_titles(db) -> dict[int, set[str]]:
    global _titles
    if _titles is None:
        _titles = {aid: {loose(t) for t in titles_of(json.loads(j))} - {""} for aid, j in db.execute("SELECT id, json FROM anilist")}
    return _titles


_frames: dict[int, list] = {}


def clear_cache() -> None:
    _frames.clear()


def frames(db, anilist_id: int) -> list[tuple[dict, np.ndarray, np.ndarray]]:
    """一部作品各集的帧：[(文件信息, 时间数组, 向量矩阵)]"""
    import zstandard

    if anilist_id not in _frames:
        out = []
        for fid, ep0, ep1, path, dur, blob in db.execute(
                "SELECT id, episode_start, episode_end, path, duration, color_layout FROM files WHERE anilist_id = ?",
                (anilist_id,)):
            data = json.loads(zstandard.ZstdDecompressor().decompress(blob, max_output_size=1 << 31))
            if not data:
                continue
            times = np.array([f["time"] for f in data], dtype=np.float32)
            vecs = np.array([f["vector"] for f in data], dtype=np.float32)
            out.append(({"id": fid, "episode_start": ep0, "episode_end": ep1, "path": path, "duration": dur}, times, vecs))
        _frames[anilist_id] = out
    return _frames[anilist_id]


def search(db, vector: list[int], anilist_ids: list[int]) -> dict | None:
    """在给定作品的所有帧里找最接近的一帧。相似度和 trace.moe 一致：(255 - 欧氏距离的平方) / 255（Milvus 的 L2 返回平方距离）。
    runner_up 是别的集里最接近的一帧的相似度：片头片尾、总集篇在各集都有，和第一名差不多时说明不了是哪一集"""
    q = np.array(vector, dtype=np.float32)
    hits = []
    for aid in anilist_ids:
        for info, times, vecs in frames(db, aid):
            d = ((vecs - q) ** 2).sum(1)
            i = int(d.argmin())
            hits.append({"anilist": aid, "file": info["path"], "episode": info["episode_start"],
                         "episode_end": info["episode_end"], "from": float(times[i]), "distance": float(d[i])})
    if not hits:
        return None
    best = min(hits, key=lambda h: h["distance"])
    sim = lambda h: max(0.0, (255 - h["distance"]) / 255)  # noqa: E731
    others = [h for h in hits if (h["anilist"], h["episode"]) != (best["anilist"], best["episode"])]
    best["similarity"] = sim(best)
    best["runner_up"] = max(map(sim, others), default=0.0)
    return best


def open_db() -> sqlite3.Connection:
    DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DIR / "frames.sqlite")
    db.executescript(SCHEMA)
    return db


# ---- 从 dump 抽取 ----

_ESC = {"\\\\": "\\", "\\n": "\n", "\\t": "\t", "\\r": "\r", "\\b": "\b", "\\f": "\f", "\\v": "\v"}


def unescape(field: str) -> str | None:
    """PostgreSQL COPY 文本格式的转义"""
    if field == "\\N":
        return None
    return re.sub(r"\\[\\ntrbfv]", lambda m: _ESC[m.group(0)], field) if "\\" in field else field


def wanted_names(data: Path) -> list[list[str | None]]:
    """补漏相关的作品：补漏清单（没有地标、地标偏少）与草稿里的作品，各自的名称与别名"""
    from sync.gaps import all_subjects

    subs = all_subjects(data)
    ids = set()
    for name in ["legwork-gaps.csv", "legwork-thin.csv", "legwork-sources.csv", "legwork-sources-noframes.csv"]:
        path = data / "review" / name
        if path.exists():
            ids |= {int(r["bangumi_id"]) for r in csv.DictReader(path.open(encoding="utf-8-sig"))}
    ids |= {int(p.stem.split(".")[0]) for p in (data / "review" / "gaps").glob("*.json") if p.stem.split(".")[0].isdigit()}
    return [[s.get("name"), s.get("cn"), s.get("en"), *s.get("aliases", [])]
            for i in ids if (s := subs.get(i)) and s.get("cat") != "游戏"]


def cmd_extract(dump: Path, data: Path) -> None:
    db = open_db()
    proc = subprocess.Popen(["zstd", "-dc", str(dump)], stdout=subprocess.PIPE)
    assert proc.stdout
    stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", newline="\n")
    table, cols, keep = None, [], set()
    kept = seen = 0
    for line in stream:
        if table is None:
            m = re.match(r"COPY public\.(\w+) \(([^)]*)\) FROM stdin;", line)
            if m:
                table, cols = m.group(1), [c.strip().strip('"') for c in m.group(2).split(",")]
            continue
        if line == "\\.\n":
            if table == "anilist":
                db.commit()
                works = wanted_names(data)
                keep = set()
                for names in works:
                    keep |= set(match_anilist(db, names))
                print(f"AniList {len(anilist_titles(db))} 部；补漏相关作品 {len(works)} 部，对到 {len(keep)} 个 AniList 条目", flush=True)
            table = None
            continue
        row = dict(zip(cols, line.rstrip("\n").split("\t")))
        if table == "anilist":
            db.execute("INSERT OR REPLACE INTO anilist VALUES (?,?)", (int(row["id"]), unescape(row["json"])))
        elif table == "files":
            seen += 1
            if row["anilist_id"] != "\\N" and int(row["anilist_id"]) in keep and row["color_layout"].startswith("\\\\x"):
                blob = bytes.fromhex(row["color_layout"][3:])
                num = lambda k: None if row.get(k, "\\N") == "\\N" else float(row[k])  # noqa: E731
                db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)", (
                    int(row["id"]), int(row["anilist_id"]), num("episode_start"), num("episode_end"),
                    unescape(row["path"]), num("duration"), blob))
                kept += 1
            if seen % 5000 == 0:
                db.commit()
                print(f"  视频 {seen}，保留 {kept}", flush=True)
    db.commit()
    proc.wait()
    print(f"完成：视频 {seen}，保留 {kept} → {DIR / 'frames.sqlite'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("dump", type=Path)
    args = ap.parse_args()
    if args.cmd == "extract":
        cmd_extract(args.dump, DEFAULT_OUT)


if __name__ == "__main__":
    setup_stdout()
    main()
