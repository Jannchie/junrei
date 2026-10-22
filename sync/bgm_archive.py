"""全部动画条目：从 Bangumi 官方每周发布的数据包（github.com/bangumi/Archive）读出动画条目的元数据，
写到 data/bgm-anime.json，由 sync.export 并进作品表。没有巡礼地标的作品也因此能被搜到。

只取动画（type=2）、排除 nsfw；每条只留名称、别名、首播日期、类型与热度。数据包约 450 MB，
已下载过同一版本就不再下载。

  python -m sync.bgm_archive
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from sync.enrich_common import SSL_CONTEXT
from sync.sync import DEFAULT_OUT

LATEST = "https://raw.githubusercontent.com/bangumi/Archive/master/aux/latest.json"
UA = "junrei-sync/0.1 (+https://junrei.jannchie.com)"
ARCHIVE_DIR = DEFAULT_OUT / "bgm-archive"
OUT = DEFAULT_OUT / "bgm-anime.json"
# Bangumi 动画条目的 platform → 与 Anitabi 一致的类别名（前端再按语言翻译）
PLATFORM = {1: "TV", 2: "OVA", 3: "剧场版", 5: "WEB"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as r:
        return r.read()


def download() -> Path:
    latest = json.loads(fetch(LATEST))
    path = ARCHIVE_DIR / latest["name"]
    if path.exists() and path.stat().st_size == latest["size"]:
        print(f"数据包已是最新：{path.name}")
        return path
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for old in ARCHIVE_DIR.glob("*.zip"):
        old.unlink()
    print(f"下载 {latest['name']}（{latest['size'] / 1e6:.0f} MB）…")
    req = urllib.request.Request(latest["browser_download_url"], headers={"User-Agent": UA})
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=600, context=SSL_CONTEXT) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(path)
    return path


def aliases(infobox: str) -> list[str]:
    """infobox 里的「别名」「英文名」等（维基模板文本）"""
    out = []
    for key, body in re.findall(r"^\|(别名|英文名|罗马字|日文名)\s*=\s*(\{.*?^\}|[^\n]*)", infobox or "", re.M | re.S):
        values = re.findall(r"\[(?:[^|\]]*\|)?([^\]]+)\]", body) if body.startswith("{") else [body]
        out += [v.strip() for v in values if v.strip()]
    return list(dict.fromkeys(out))


def english(names: list[str]) -> str | None:
    """别名里第一个以拉丁字母为主的名称当英文名"""
    for n in names:
        letters = re.findall(r"[^\W\d_]", n)
        if letters and sum(c.isascii() for c in letters) / len(letters) > 0.9:
            return n
    return None


def main():
    path = download()
    rows = []
    with zipfile.ZipFile(path) as z, z.open("subject.jsonlines") as f:
        for line in f:
            s = json.loads(line)
            if s["type"] != 2 or s.get("nsfw"):
                continue
            alias = aliases(s.get("infobox", ""))
            fav = s.get("favorite") or {}
            rows.append({
                "id": s["id"],
                "name": s.get("name") or None,
                "cn": s.get("name_cn") or None,
                "en": english(alias),
                "aliases": [a for a in alias if a not in (s.get("name"), s.get("name_cn"))][:8],
                "date": s.get("date") or None,
                "cat": PLATFORM.get(s.get("platform"), "其他"),
                # 热度：看过 + 在看 + 想看，用于没有地标的作品之间排序
                "popularity": fav.get("done", 0) + fav.get("doing", 0) + fav.get("wish", 0),
            })
    rows.sort(key=lambda r: r["id"])
    OUT.write_text(json.dumps({"archive": path.name, "subjects": rows}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"{OUT}：{len(rows)} 部动画（{OUT.stat().st_size / 1e6:.1f} MB）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    main()
