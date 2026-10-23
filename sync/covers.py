"""封面镜像：从 Bangumi 拉作品封面，存到自己的 R2（public-assets 存储桶，cdn.jannchie.com），
网站不再直接引用别人的图床。

  python -m sync.covers                          # 镜像所有还没镜像的作品（本机一次跑完，适合首次补齐）
  python -m sync.covers --limit 2000 --max 8000  # 每日同步：最多调 2000 次 Bangumi API、镜像 8000 部

进度以 R2 上的清单 junrei/covers/index.json 为准（作品 id → 原图路径、对象名）：开始时读、结束时写，
所以本机和 CI 谁跑都行，不会重复下载。清单同时写进 data/enrich.sqlite 的 cover_mirror 表，sync.export 据此改用镜像地址。

封面地址：bgmd（github.com/AnimeGarden/bgmd，MIT）每天整理的数据里带着约 8400 部主流动画的封面地址，直接用；
其余的逐个调 Bangumi API，按每秒一个请求。下载 Bangumi CDN 上 400px 宽的版本；对象名带原图路径的哈希，
Bangumi 换了封面就是新文件，可以永久缓存。
上传：有 CLOUDFLARE_API_TOKEN（需要 R2 编辑权限）就走 Cloudflare API，否则用本机已登录的 wrangler。都并行上传。
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sync.bgm import API as BGM_API
from sync.bgm import BGM_UA as UA  # Bangumi 要求调用方在 UA 里标明身份
from sync.enrich_common import Http, add_data_arg, now_iso, open_db, setup_stdout
from sync.net import request

ACCOUNT = "ad02684d0205554549c21cd8bfc41d48"
BUCKET = "public-assets"
PREFIX = "junrei/covers/"
MANIFEST = PREFIX + "index.json"
PUBLIC = "https://cdn.jannchie.com/"
BGMD = "https://cdn.jsdelivr.net/npm/bgmd@0/dist/index.json"
IMMUTABLE = "public, max-age=31536000, immutable"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cover_mirror (
  bangumi_id INTEGER PRIMARY KEY,
  source TEXT,       -- Bangumi 原图路径；没有封面为 NULL，公开 API 看不到的条目（成人向、已删除）为 "hidden"
  key TEXT,          -- R2 里的对象名；没有封面为 NULL
  bytes INTEGER,
  mirrored_at TEXT
);
"""


def cover_key(bid: int, source: str) -> str:
    return f"{PREFIX}{bid}-{hashlib.sha1(source.encode()).hexdigest()[:8]}.jpg"


def mirrored(db) -> dict[int, str]:
    """已镜像的作品 → 公开地址（sync.export 用）"""
    db.executescript(SCHEMA)
    return {bid: PUBLIC + key for bid, key in db.execute("SELECT bangumi_id, key FROM cover_mirror WHERE key IS NOT NULL")}


def download(url: str) -> bytes | None:
    status, body = request(url, ua=UA, timeout=60, headers={"Cache-Control": "no-cache"})
    if status == 200:
        return body
    if status != 404:  # 404 是没有这张图；其他失败只算这一张，下次再试
        print(f"  ! 下载失败 {url}：{status}", file=sys.stderr)
    return None


class Uploader:
    def __init__(self):
        self.token = os.environ.get("CLOUDFLARE_API_TOKEN")
        self.pnpm = None if self.token else shutil.which("pnpm")
        if not self.token and not self.pnpm:
            sys.exit("需要 CLOUDFLARE_API_TOKEN（R2 编辑权限），或本机已登录的 wrangler")
        # 走 API 时并发高一些；wrangler 每次要起一个进程，并发低一点
        self.workers = 12 if self.token else 6

    def put(self, key: str, body: bytes, content_type: str = "image/jpeg", cache: str = IMMUTABLE) -> bool:
        if self.token:
            url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/r2/buckets/{BUCKET}/objects/{key}"
            status, _ = request(url, data=body, method="PUT", timeout=60, headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": content_type, "Cache-Control": cache})
            if status in (401, 403):
                sys.exit("令牌没有 R2 编辑权限（Account → Workers R2 Storage → Edit）")
            if not 200 <= status < 300:
                print(f"  ! 上传失败 {key}：{status}", file=sys.stderr)
            return 200 <= status < 300
        assert self.pnpm
        with tempfile.NamedTemporaryFile(suffix=Path(key).suffix, delete=False) as f:
            f.write(body)
        try:
            r = subprocess.run([self.pnpm, "exec", "wrangler", "r2", "object", "put", f"{BUCKET}/{key}", "--file", f.name,
                                "--content-type", content_type, "--cache-control", cache, "--remote"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "CLOUDFLARE_ACCOUNT_ID": ACCOUNT})
            if r.returncode != 0:
                print(f"  ! 上传失败 {key}：{r.stderr.strip()[-200:]}", file=sys.stderr)
            return r.returncode == 0
        finally:
            os.unlink(f.name)


def load_manifest(db) -> None:
    """R2 上的清单并入本地表（别处跑过的进度）"""
    body = download(PUBLIC + MANIFEST)
    if not body:
        return
    try:
        manifest = json.loads(body)
    except ValueError:
        return
    rows = [(int(bid), *v, None, now_iso()) for bid, v in manifest.items()]
    db.executemany("INSERT OR IGNORE INTO cover_mirror VALUES (?,?,?,?,?)", rows)
    db.commit()
    print(f"清单里已有 {len(rows)} 部")


def save_manifest(db, up: Uploader) -> None:
    rows = db.execute("SELECT bangumi_id, source, key FROM cover_mirror ORDER BY bangumi_id").fetchall()
    body = json.dumps({str(b): [s, k] for b, s, k in rows}, separators=(",", ":")).encode()
    if up.put(MANIFEST, body, "application/json", "no-cache"):
        print(f"清单已更新：{len(rows)} 部")


def queue(db, data: Path, token: str | None) -> list[int]:
    """还没镜像的作品：有地标的在前（按地标数），其余按 Bangumi 热度。有 Bangumi 令牌时，之前看不到的条目重新排队"""
    done = {r[0] for r in db.execute("SELECT bangumi_id FROM cover_mirror" + (" WHERE source IS NOT 'hidden'" if token else ""))}
    points: dict[int, int] = {}
    for (bid,) in db.execute("SELECT bangumi_id FROM src.point"):
        points[bid] = points.get(bid, 0) + 1
    subs = json.loads((data / "bgm-anime.json").read_text(encoding="utf-8"))["subjects"]
    pop = {s["id"]: s["popularity"] for s in subs}
    ids = set(points) | set(pop)
    ids |= {b["id"] for b in json.loads((Path(__file__).parent / "manual.json").read_text(encoding="utf-8"))["bangumi"]}
    return sorted(ids - done, key=lambda b: (-points.get(b, 0), -pop.get(b, 0)))


NSFW_AFTER_DAYS = 60  # Bangumi 只给注册满 60 天的账号看成人向条目（bangumi/server 的 auth.AllowNSFW）


def nsfw_token() -> str | None:
    """Bangumi 的公开 API 不登录时把成人向条目当作不存在（404）。有个人令牌（https://next.bgm.tv/demo/access-token）
    且账号注册满 60 天时返回令牌；否则返回 None，免得每次都把看不到的条目重新请求一遍、白白耗掉 API 额度"""
    import datetime as dt

    token = os.environ.get("BANGUMI_TOKEN")
    if not token:
        return None
    status, body = request("https://api.bgm.tv/v0/me", ua=UA, headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        print(f"BANGUMI_TOKEN 无效（/v0/me → {status}），成人向条目的封面先跳过")
        return None
    reg = json.loads(body).get("reg_time")
    ready = reg and dt.datetime.fromisoformat(reg) + dt.timedelta(days=NSFW_AFTER_DAYS)
    if not ready or ready > dt.datetime.now(dt.timezone.utc):
        print(f"Bangumi 账号注册未满 {NSFW_AFTER_DAYS} 天（{ready and ready.date()} 起可用），成人向条目的封面先跳过")
        return None
    return token


def bgmd_posters() -> dict[int, str]:
    """bgmd 数据里的封面：作品 id → 原图路径（pic/ 之后的部分）"""
    try:
        body = download(BGMD)
        subjects = json.loads(body)["subjects"] if body else []
    except (ValueError, KeyError):
        subjects = []
    return {s["id"]: s["poster"].split("/pic/", 1)[1] for s in subjects if "/pic/" in (s.get("poster") or "")}


def mirror_one(up: Uploader, bid: int, path: str) -> tuple[int, str, str, int] | None:
    body = download(f"https://lain.bgm.tv/r/400/pic/{path}")
    key = cover_key(bid, path)
    return (bid, path, key, len(body)) if body and up.put(key, body) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--limit", type=int, default=None, help="最多调用多少次 Bangumi API（bgmd 里已有封面地址的不算）；默认不限")
    ap.add_argument("--max", type=int, default=None, help="这次最多镜像多少部；默认不限")
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    db.executescript(SCHEMA)
    load_manifest(db)
    token = nsfw_token()
    todo = queue(db, data, token)[: args.max]
    print(f"待镜像 {len(todo)} 部")
    if not todo:
        return
    known = bgmd_posters()
    print(f"bgmd 提供了 {sum(1 for b in todo if b in known)} 部的封面地址")
    http = Http(db, interval=1.0, ua=UA, max_age_days=30)
    up = Uploader()
    stats = {"ok": 0, "none": 0, "hidden": 0, "fail": 0, "calls": 0}

    def collect(futures):
        rows = [r for r in (f.result() for f in futures) if r]
        db.executemany("INSERT OR REPLACE INTO cover_mirror VALUES (?,?,?,?,?)", [(*r, now_iso()) for r in rows])
        db.commit()
        stats["ok"] += len(rows)
        stats["fail"] += len(futures) - len(rows)

    # 调 API 拿地址（主线程，按每秒一个）与下载上传（线程池）同时进行；每攒够一批就落库，中途中断不丢进度
    try:
        with ThreadPoolExecutor(up.workers) as pool:
            futures = []
            for bid in todo:
                path = known.get(bid)
                if not path:
                    if args.limit is not None and stats["calls"] >= args.limit:
                        continue  # 这次的 API 额度用完了，下次接着来
                    stats["calls"] += 1
                    status, subject = http.get_json(BGM_API.format(bid))
                    if status == 404 and token:
                        status, body = request(BGM_API.format(bid), ua=UA, headers={"Authorization": f"Bearer {token}"})
                        subject = json.loads(body) if status == 200 else None
                    large = ((subject or {}).get("images") or {}).get("large") if status == 200 else None
                    if status in (200, 404) and not large:
                        # 200 没有封面；404 是公开 API 看不到（成人向或已删除），记下来不再每次重试
                        db.execute("INSERT OR REPLACE INTO cover_mirror VALUES (?,?,?,?,?)",
                                   (bid, "hidden" if status == 404 else None, None, None, now_iso()))
                        stats["none" if status == 200 else "hidden"] += 1
                        continue
                    if not large:
                        stats["fail"] += 1  # 其他错误（限流、服务端出错），下次再试
                        continue
                    path = large.split("/pic/", 1)[-1]
                futures.append(pool.submit(mirror_one, up, bid, path))
                if len(futures) >= 200:
                    collect(futures)
                    futures = []
                    print("  镜像 {ok}，无封面 {none}，看不到 {hidden}，失败 {fail}，API {calls} 次".format(**stats), flush=True)
            collect(futures)
    finally:
        db.commit()
        print("完成：镜像 {ok}，无封面 {none}，看不到 {hidden}（成人向或已删除，设 BANGUMI_TOKEN 可取），失败 {fail}，API {calls} 次".format(**stats))
        save_manifest(db, up)


if __name__ == "__main__":
    setup_stdout()
    main()
