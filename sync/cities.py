"""城市名多语言：作品的 city（多为简体中文，如「宇治市」「东京都」）到 Wikidata 查对应地区的官方名称，
补齐 zh-Hans / zh-Hant / ja / en，写进 data/enrich.sqlite 的 city_label 表（sync.export 读取）。

只用 Wikidata 的搜索与实体接口（人工维护的名称，不调用 LLM）；按描述判断是不是行政区，找不到的留空，前端显示原文。
「海外」这类不是地名的值用下面的固定译名。

  python -m sync.cities
  python -m sync.cities --refresh   # 已查过的也重新查
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from pathlib import Path

from sync.enrich_common import add_data_arg, open_db, setup_stdout
from sync.net import request

API = "https://www.wikidata.org/w/api.php"
UA = "junrei-data/0.1 (https://junrei.jannchie.com)"
# Wikidata 的语言代码 → 前端语言；繁体优先台湾用法
LABEL_LANGS = {"zh-hans": "zh-Hans", "zh-cn": "zh-Hans", "zh-tw": "zh-Hant", "zh-hant": "zh-Hant", "ja": "ja", "en": "en"}
# 描述里出现这些词才算行政区或地区，避免「宇治市」搜到同名的车站、学校
PLACE = re.compile(r"\b(city|town|village|ward|prefecture|province|county|district|municipality|region|state|"
                   r"country|continent|island|capital|special ward|metropolis|area)\b", re.I)
FIXED = {
    "海外": {"zh-Hans": "海外", "zh-Hant": "海外", "ja": "海外", "en": "Overseas"},
    "其他": {"zh-Hans": "其他", "zh-Hant": "其他", "ja": "その他", "en": "Other"},
    # Wikidata 里没有这种写法的同名地区
    "东京府中市": {"zh-Hans": "府中市（东京都）", "zh-Hant": "府中市（東京都）", "ja": "府中市（東京都）", "en": "Fuchū, Tokyo"},
    "北海道伊达市": {"zh-Hans": "伊达市（北海道）", "zh-Hant": "伊達市（北海道）", "ja": "伊達市（北海道）", "en": "Date, Hokkaido"},
    "关岛": {"zh-Hans": "关岛", "zh-Hant": "關島", "ja": "グアム", "en": "Guam"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS city_label (
  city TEXT PRIMARY KEY,   -- 作品数据里的原文
  qid TEXT,                -- Wikidata 实体；找不到为 NULL
  labels TEXT,             -- {"zh-Hans": ..., "zh-Hant": ..., "ja": ..., "en": ...}
  fetched_at TEXT
);
"""


def get(params: dict) -> dict:
    status, body = request(f"{API}?{urllib.parse.urlencode({**params, 'format': 'json'})}", ua=UA)
    if status != 200:
        raise RuntimeError(f"Wikidata → {status}")
    return json.loads(body)


def find(city: str) -> str | None:
    """名称完全匹配（标签或别名）且描述像行政区的第一个实体"""
    for lang in ("zh", "ja"):
        res = get({"action": "wbsearchentities", "search": city, "language": lang, "uselang": "en", "type": "item", "limit": 7})
        for hit in res.get("search", []):
            if hit.get("match", {}).get("text") == city and PLACE.search(hit.get("description", "")):
                return hit["id"]
    return None


def labels(qids: list[str]) -> dict[str, dict[str, str]]:
    out = {}
    for i in range(0, len(qids), 50):
        res = get({"action": "wbgetentities", "ids": "|".join(qids[i : i + 50]), "props": "labels",
                   "languages": "|".join(LABEL_LANGS)})
        for qid, ent in res.get("entities", {}).items():
            names: dict[str, str] = {}
            for code, lang in LABEL_LANGS.items():  # 前面的代码优先（zh-hans 先于 zh-cn）
                if code in ent.get("labels", {}) and lang not in names:
                    # 英文名有的带罗马字后缀（Sōka-shi），去掉与其他城市统一
                    names[lang] = re.sub(r"-(shi|ku|machi|cho|chō|mura)$", "", ent["labels"][code]["value"])
            out[qid] = names
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    db = open_db(Path(args.data))
    db.executescript(SCHEMA)
    cities = [c for (c,) in db.execute(
        "SELECT DISTINCT city FROM src.bangumi WHERE deleted = 0 AND city IS NOT NULL AND city != '' ORDER BY city")]
    done = set() if args.refresh else {c for (c,) in db.execute("SELECT city FROM city_label")}
    todo = [c for c in cities if c not in done]
    print(f"{len(cities)} 个城市，要查 {len(todo)} 个")

    found: dict[str, str | None] = {}
    for n, city in enumerate(todo, 1):
        found[city] = None if city in FIXED else find(city)
        if n % 25 == 0:
            print(f"  {n}/{len(todo)}")
    names = labels(sorted({q for q in found.values() if q}))
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    rows = []
    for city, qid in found.items():
        label = FIXED.get(city) or (names.get(qid) if qid else None)
        rows.append((city, qid, json.dumps(label, ensure_ascii=False) if label else None, now))
    db.executemany("INSERT OR REPLACE INTO city_label VALUES (?, ?, ?, ?)", rows)
    db.commit()
    total = db.execute("SELECT count(*), count(labels) FROM city_label").fetchone()
    print(f"已有 {total[0]} 个城市，其中 {total[1]} 个找到了多语言名称")
    missing = [c for (c,) in db.execute("SELECT city FROM city_label WHERE labels IS NULL ORDER BY city")]
    if missing:
        print("没找到：" + "、".join(missing))


if __name__ == "__main__":
    setup_stdout()
    main()
