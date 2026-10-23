"""整理 / 补全流水线的公共部分。

所有派生数据写进 data/enrich.sqlite，原始同步库 data/anitabi.sqlite 只读挂载为 src，绝不修改。
外部请求和 LLM 结果缓存在 data/cache.sqlite：enrich.sqlite 可以随时删掉重建，缓存不受影响。

数据目录默认是 <项目根>/data，可用环境变量 JUNREI_DATA 或各脚本的 --data 覆盖。
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from sync.sync import DEFAULT_OUT

DATA_DIR = Path(os.environ.get("JUNREI_DATA") or DEFAULT_OUT)
UA = "junrei-enrich/0.1 (+https://junrei.jannchie.com; non-commercial)"

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
  url TEXT PRIMARY KEY, status INTEGER, body BLOB, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
  task TEXT NOT NULL, prompt_version TEXT NOT NULL, model TEXT NOT NULL,
  input_sha TEXT NOT NULL, input TEXT, output TEXT,  -- output 是该条目的 JSON 结果
  served_model TEXT,                                 -- 实际响应的模型（可能与请求的不同）
  created_at TEXT,
  PRIMARY KEY (task, prompt_version, model, input_sha)
);
CREATE TABLE IF NOT EXISTS llm_batch (
  id TEXT PRIMARY KEY, task TEXT, prompt_version TEXT, model TEXT,
  chunks TEXT,          -- {custom_id: [input_sha, ...]}，结果按 custom_id 对回条目
  status TEXT, created_at TEXT, collected_at TEXT
);
"""

ENRICH_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrich_run (
  step TEXT, started_at TEXT, finished_at TEXT, params TEXT, stats TEXT
);
"""


def _ssl_context():
    """有 certifi 就用它的根证书：部分 Windows 环境的系统证书库会让 api.bgm.tv 这类新签发链校验失败。
    也可以用环境变量 SSL_CERT_FILE 指定证书文件。"""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


SSL_CONTEXT = _ssl_context()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def open_db(data_dir: Path = DATA_DIR) -> sqlite3.Connection:
    """打开 enrich.sqlite，并挂载 src（原始库，只读）与 cache。"""
    src = data_dir / "anitabi.sqlite"
    if not src.exists():
        sys.exit(f"找不到 {src}，先跑 pnpm data:sync（或用 JUNREI_DATA / --data 指定数据目录）")
    db = sqlite3.connect((data_dir / "enrich.sqlite").resolve().as_uri(), uri=True, timeout=60)  # uri=True 才能只读 ATTACH
    db.execute("ATTACH DATABASE ? AS src", (f"{src.resolve().as_uri()}?mode=ro",))
    db.execute("ATTACH DATABASE ? AS cache", (str(data_dir / "cache.sqlite"),))
    db.execute("PRAGMA cache.journal_mode=WAL")  # 允许多个补全脚本同时读写缓存
    db.executescript(ENRICH_SCHEMA + CACHE_SCHEMA.replace("IF NOT EXISTS ", "IF NOT EXISTS cache."))
    return db


def log_run(db, step: str, started: str, params: dict, stats: dict) -> None:
    db.execute("INSERT INTO enrich_run VALUES (?,?,?,?,?)", (
        step, started, now_iso(), json.dumps(params, ensure_ascii=False), json.dumps(stats, ensure_ascii=False)))
    db.commit()


class Http:
    """限速 + 缓存的 GET。命中缓存不发请求、也不计入限速。"""

    def __init__(self, db, interval: float, ua: str = UA, max_age_days: float | None = None):
        self.db = db
        self.interval = interval
        self.ua = ua
        self.max_age = max_age_days
        self._last = 0.0
        self.requests = 0
        self.hits = 0

    def get(self, url: str, params: dict | None = None) -> tuple[int, bytes]:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        row = self.db.execute("SELECT status, body, fetched_at FROM cache.http_cache WHERE url=?", (url,)).fetchone()
        if row and (self.max_age is None or
                    dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(row[2]) < dt.timedelta(days=self.max_age)):
            self.hits += 1
            return row[0], row[1]
        status, body = self._fetch(url)
        if status == 200 or 400 <= status < 500:  # 4xx 也缓存（如条目不存在），5xx / 网络错误不缓存
            # 多个补全脚本同时写缓存时可能等锁超时：缓存写不进去只是下次再请求，不值得让整个任务退出
            for attempt in range(5):
                try:
                    self.db.execute("INSERT OR REPLACE INTO cache.http_cache VALUES (?,?,?,?)", (url, status, body, now_iso()))
                    self.db.commit()
                    break
                except sqlite3.OperationalError as e:
                    if "locked" not in str(e):
                        raise
                    self.db.rollback()
                    time.sleep(2 ** attempt)
        return status, body

    def get_json(self, url: str, params: dict | None = None):
        status, body = self.get(url, params)
        return status, (json.loads(body) if status == 200 and body else None)

    def _fetch(self, url: str) -> tuple[int, bytes]:
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "gzip",
                                                   "Accept": "application/json"})
        for attempt in range(4):
            wait = self.interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as r:
                    body = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return r.status, body
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    retry = float(e.headers.get("Retry-After") or 2 ** (attempt + 1))
                    print(f"  ! {url} → {e.code}，{retry:.0f}s 后重试", file=sys.stderr)
                    time.sleep(retry)
                    continue
                return e.code, e.read()
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"  ! {url} 失败（{e}），{2 ** attempt}s 后重试", file=sys.stderr)
                time.sleep(2**attempt)
        return 599, b""


def add_data_arg(ap) -> None:
    ap.add_argument("--data", default=str(DATA_DIR), help="数据目录（默认 <项目根>/data，或环境变量 JUNREI_DATA）")


def setup_stdout() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]  # Windows 控制台默认不是 UTF-8
    sys.stderr.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
