"""封面镜像：从 Bangumi 拉作品封面，存到自己的 R2（public-assets 存储桶，cdn.jannchie.com），
网站不再直接引用别人的图床。每次处理一批，状态记在 data/enrich.sqlite 的 cover_mirror 表，下次接着来。

  python -m sync.covers --limit 2000     # 处理 2000 部还没镜像的作品（有地标的优先，其余按热度）

封面地址 Bangumi 数据包里没有（带随机哈希），要逐个调 Bangumi API 拿，按每秒一个请求。
下载 Bangumi CDN 上 400px 宽的版本；文件名带原图路径的哈希，Bangumi 换了封面就是新文件，可以永久缓存。
上传：有 CLOUDFLARE_API_TOKEN（需要 R2 编辑权限）就走 Cloudflare API；否则用本机 wrangler 的登录（慢，只适合试跑）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from sync.enrich_common import SSL_CONTEXT, Http, add_data_arg, now_iso, open_db, setup_stdout

ACCOUNT = "ad02684d0205554549c21cd8bfc41d48"
BUCKET = "public-assets"
PREFIX = "junrei/covers/"
PUBLIC = "https://cdn.jannchie.com/"
BGM_API = "https://api.bgm.tv/v0/subjects/{}"
BGMD = "https://cdn.jsdelivr.net/npm/bgmd@0/dist/index.json"
UA = "Jannchie/junrei (https://junrei.jannchie.com)"  # Bangumi 要求调用方在 UA 里标明身份

SCHEMA = """
CREATE TABLE IF NOT EXISTS cover_mirror (
  bangumi_id INTEGER PRIMARY KEY,
  source TEXT,       -- Bangumi 原图路径；没有封面为 NULL
  key TEXT,          -- R2 里的对象名；没有封面为 NULL
  bytes INTEGER,
  mirrored_at TEXT
);
"""


def cover_key(bid: int, source: str) -> str:
    return f"{PREFIX}{bid}-{hashlib.sha1(source.encode()).hexdigest()[:8]}.jpg"


def public_url(key: str) -> str:
    return PUBLIC + key


def mirrored(db) -> dict[int, str]:
    """已镜像的作品 → 公开地址（sync.export 用）"""
    db.executescript(SCHEMA)
    return {bid: public_url(key) for bid, key in db.execute("SELECT bangumi_id, key FROM cover_mirror WHERE key IS NOT NULL")}


def download(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as r:
            return r.read()
    except urllib.error.URLError as e:
        print(f"  ! 下载失败 {url}：{e}", file=sys.stderr)
        return None


class Uploader:
    def __init__(self):
        self.token = os.environ.get("CLOUDFLARE_API_TOKEN")
        self.wrangler = None if self.token else shutil.which("pnpm")
        if not self.token and not self.wrangler:
            sys.exit("需要 CLOUDFLARE_API_TOKEN（R2 编辑权限），或本机已登录的 wrangler")

    def put(self, key: str, body: bytes) -> bool:
        if self.token:
            url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/r2/buckets/{BUCKET}/objects/{key}"
            req = urllib.request.Request(url, data=body, method="PUT", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "image/jpeg",
                "Cache-Control": "public, max-age=31536000, immutable",
            })
            try:
                with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as r:
                    return 200 <= r.status < 300
            except urllib.error.HTTPError as e:
                print(f"  ! 上传失败 {key}：{e.code} {e.read()[:200]!r}", file=sys.stderr)
                if e.code in (401, 403):
                    sys.exit("令牌没有 R2 编辑权限（Account → Workers R2 Storage → Edit）")
                return False
        assert self.wrangler
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(body)
        try:
            r = subprocess.run([self.wrangler, "exec", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}", "--file", f.name,
                                "--content-type", "image/jpeg", "--cache-control", "public, max-age=31536000, immutable",
                                "--remote"], capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "CLOUDFLARE_ACCOUNT_ID": ACCOUNT})
            return r.returncode == 0
        finally:
            os.unlink(f.name)


def queue(db, data: Path, limit: int) -> list[int]:
    """还没镜像的作品：有地标的在前（按地标数），其余按 Bangumi 热度"""
    done = {r[0] for r in db.execute("SELECT bangumi_id FROM cover_mirror")}
    points: dict[int, int] = {}
    for (bid,) in db.execute("SELECT bangumi_id FROM src.point"):
        points[bid] = points.get(bid, 0) + 1
    subs = json.loads((data / "bgm-anime.json").read_text(encoding="utf-8"))["subjects"]
    pop = {s["id"]: s["popularity"] for s in subs}
    ids = set(points) | set(pop)
    ids |= {b["id"] for b in json.loads((Path(__file__).parent / "manual.json").read_text(encoding="utf-8"))["bangumi"]}
    return sorted(ids - done, key=lambda b: (-points.get(b, 0), -pop.get(b, 0)))[:limit]


def bgmd_posters() -> dict[int, str]:
    """bgmd（github.com/AnimeGarden/bgmd，MIT）每天整理的 Bangumi 作品数据里带着封面地址，约 8400 部主流动画，
    这些不必再逐个调 Bangumi API。返回 作品 id → 原图路径（pic/ 之后的部分）"""
    try:
        body = download(BGMD)
        subjects = json.loads(body)["subjects"] if body else []
    except (ValueError, KeyError):
        subjects = []
    return {s["id"]: s["poster"].split("/pic/", 1)[1] for s in subjects if "/pic/" in (s.get("poster") or "")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--limit", type=int, default=2000, help="最多调用多少次 Bangumi API（bgmd 里已有封面地址的不算）")
    ap.add_argument("--max", type=int, default=8000, help="这次最多镜像多少部")
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    db.executescript(SCHEMA)
    todo = queue(db, data, args.max)
    print(f"待镜像 {len(todo)} 部")
    if not todo:
        return
    known = bgmd_posters()
    print(f"bgmd 提供了 {sum(1 for b in todo if b in known)} 部的封面地址")
    http = Http(db, interval=1.0, ua=UA, max_age_days=30)
    up = Uploader()
    ok = none = fail = calls = 0
    for n, bid in enumerate(todo, 1):
        path = known.get(bid)
        if not path:
            if calls >= args.limit:
                continue  # 今天的 API 额度用完了，明天接着来
            calls += 1
            status, subject = http.get_json(BGM_API.format(bid))
            large = ((subject or {}).get("images") or {}).get("large") if status == 200 else None
            if status == 200 and not large:
                db.execute("INSERT OR REPLACE INTO cover_mirror VALUES (?,?,?,?,?)", (bid, None, None, None, now_iso()))
                none += 1
                continue
            if not large:
                fail += 1  # API 出错（404 是条目被删或隐藏），下次再试
                continue
            path = large.split("/pic/", 1)[-1]
        body = download(f"https://lain.bgm.tv/r/400/pic/{path}")
        key = cover_key(bid, path)
        if body and up.put(key, body):
            db.execute("INSERT OR REPLACE INTO cover_mirror VALUES (?,?,?,?,?)", (bid, path, key, len(body), now_iso()))
            ok += 1
        else:
            fail += 1
        if n % 200 == 0:
            db.commit()
            print(f"  {n}/{len(todo)}：镜像 {ok}，无封面 {none}，失败 {fail}，API {calls} 次")
    db.commit()
    print(f"完成：镜像 {ok}，无封面 {none}，失败 {fail}，API {calls} 次")


if __name__ == "__main__":
    setup_stdout()
    main()
