"""作品元数据：从 Bangumi 官方开放 API（https://bangumi.github.io/api/）补别名、原名、英文/罗马音标题、放送日期，用于搜索。

Anitabi 的作品 id 就是 Bangumi subject id。逐个请求 GET /v0/subjects/{id}，间隔 BGM_INTERVAL 秒，
响应缓存在 cache.http_cache（默认 30 天内不重复请求，--refresh 强制重拉）。

结果写入 enrich.sqlite：
  bangumi_meta   每部作品一行：原名、中文名、英文/罗马音标题、放送日期、平台、话数
  bangumi_alias  可用于搜索的所有名称，带语言和来源字段

  python -m sync.bgm
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sync.enrich_common import Http, add_data_arg, log_run, now_iso, open_db, setup_stdout
from sync.enrich_report import write_report

API = "https://api.bgm.tv/v0/subjects/{}"
BGM_UA = "jannchie/junrei (https://junrei.jannchie.com)"  # Bangumi 要求 UA 写明「用户/项目 (链接)」
BGM_INTERVAL = 1.0

SCHEMA = """
DROP TABLE IF EXISTS bangumi_meta;
DROP TABLE IF EXISTS bangumi_alias;
CREATE TABLE bangumi_meta (
  bangumi_id INTEGER PRIMARY KEY,
  status INTEGER,             -- API 响应码；非 200 时其余字段为空
  name TEXT, name_cn TEXT,    -- Bangumi 的原名（多为日文）与中文名
  title_en TEXT, title_romaji TEXT,
  air_date TEXT,              -- 放送 / 发售日期（YYYY-MM-DD）
  platform TEXT, eps INTEGER,
  source TEXT, fetched_at TEXT
);
CREATE TABLE bangumi_alias (
  bangumi_id INTEGER NOT NULL, alias TEXT NOT NULL,
  lang TEXT,                  -- ja / zh / en / romaji / ko / latin（拉丁字母但分不清英文还是罗马音）/ cjk（只有汉字）
  source_key TEXT,            -- 来自哪个字段：name / name_cn / infobox 的键名
  source TEXT,
  PRIMARY KEY (bangumi_id, alias)
);
CREATE INDEX bangumi_alias_alias ON bangumi_alias (alias);
"""

KEY_LANG = [
    (re.compile(r"罗马|羅馬|romaji", re.I), "romaji"),
    (re.compile(r"英文|英语|英語|english", re.I), "en"),
    (re.compile(r"日文|日语|日語|日本語"), "ja"),
    (re.compile(r"中文|译名|譯名|简体|繁体|港|台"), "zh"),
    (re.compile(r"韩|韓"), "ko"),
]
NAME_KEYS = re.compile(r"中文名|别名|別名|英文名|罗马|日文名|原名|译名|简体中文名|繁体中文名")


_ROMAJI = re.compile(r"(?:(?:ch|sh|ts|[kgnhbpmr]y|[kgsztdnhbpmrfjwy])?[aiueoāīūēō]|n|[kstpgdbcm](?=[kstpgdbcm]))+")


def is_romaji(s: str) -> bool:
    """每个词都能拆成罗马音音节才算（The / Garden 之类的英文词会失败）。"""
    words = re.findall(r"[a-zāīūēō]+", s.lower())
    return bool(words) and all(_ROMAJI.fullmatch(w) for w in words)


def script_lang(s: str) -> str:
    if re.search(r"[\u3040-\u30ff\u31f0-\u31ff]", s):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", s):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", s):
        return "cjk"
    if re.search(r"[A-Za-z]", s):
        return "romaji" if is_romaji(s) else "latin"
    return "other"


def key_lang(key: str | None) -> str | None:
    for pat, lang in KEY_LANG:
        if key and pat.search(key):
            return lang
    return None


def infobox_names(infobox) -> list[tuple[str, str]]:
    """从 infobox 取出名称类条目 → [(键名, 值)]。值可能是字符串，也可能是 [{"v": …} | {"k": …, "v": …}]。"""
    out = []
    for item in infobox or []:
        key, val = item.get("key"), item.get("value")
        if not key or not NAME_KEYS.search(key):
            continue
        for v in val if isinstance(val, list) else [{"v": val}]:
            text = (v.get("v") if isinstance(v, dict) else v) or ""
            sub = v.get("k") if isinstance(v, dict) else None
            for part in str(text).split("\n"):
                if part.strip():
                    out.append((f"{key}/{sub}" if sub else key, part.strip()))
    return out


def parse(bid: int, data: dict):
    aliases = {}

    def add(text, key, lang=None):
        text = (text or "").strip()
        if text and text not in aliases:
            aliases[text] = (lang or key_lang(key.split("/")[-1]) or key_lang(key) or script_lang(text), key)

    add(data.get("name"), "name", script_lang(data.get("name") or "") if script_lang(data.get("name") or "") != "cjk" else "ja")
    add(data.get("name_cn"), "name_cn", "zh")
    for key, text in infobox_names(data.get("infobox")):
        add(text, key)
    first = lambda lang: next((a for a, (lg, _) in aliases.items() if lg == lang), None)  # noqa: E731
    meta = (bid, 200, data.get("name") or None, data.get("name_cn") or None, first("en"), first("romaji"),
            data.get("date") or None, data.get("platform") or None, data.get("total_episodes") or data.get("eps") or None)
    return meta, [(bid, a, lg, k) for a, (lg, k) in aliases.items()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新请求")
    ap.add_argument("--max-age-days", type=float, default=30, help="缓存有效期（天）")
    ap.add_argument("--limit", type=int, help="最多处理多少部作品（试跑用）")
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    started = now_iso()
    http = Http(db, BGM_INTERVAL, ua=BGM_UA, max_age_days=0 if args.refresh else args.max_age_days)

    ids = [r[0] for r in db.execute("SELECT id FROM src.bangumi WHERE deleted = 0 ORDER BY id")][: args.limit]
    metas, aliases = [], []
    failed = 0
    ts = now_iso()
    for n, bid in enumerate(ids, 1):
        status, body = http.get_json(API.format(bid))
        if status == 200 and body:
            meta, al = parse(bid, body)
            metas.append((*meta, "bangumi_api", ts))
            aliases += [(*a, "bangumi_api") for a in al]
        elif status < 500:  # 404 等：条目不存在或需要登录；5xx / 网络错误不记录，下次重试
            metas.append((bid, status, *[None] * 7, "bangumi_api", ts))
        else:
            failed += 1
        if n % 100 == 0:
            print(f"  {n}/{len(ids)}（请求 {http.requests}，缓存命中 {http.hits}）")

    db.executescript(SCHEMA)
    db.executemany("INSERT INTO bangumi_meta VALUES (?,?,?,?,?,?,?,?,?,?,?)", metas)
    db.executemany("INSERT INTO bangumi_alias VALUES (?,?,?,?,?)", aliases)
    db.commit()
    stats = {"bangumi": len(ids), "ok": sum(1 for m in metas if m[1] == 200), "aliases": len(aliases), "failed": failed,
             "requests": http.requests, "cache_hits": http.hits}
    log_run(db, "bgm", started, {"interval": BGM_INTERVAL, "max_age_days": args.max_age_days}, stats)
    print(json.dumps(stats, ensure_ascii=False))
    write_report(db, data)


if __name__ == "__main__":
    setup_stdout()
    main()
