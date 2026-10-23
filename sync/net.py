"""同步脚本共用的 HTTP 请求：证书、gzip 与重试规则只在这里写一份。

网络层失败（超时、连接被重置、对方没响应就断开、读到一半断开）与 429 / 5xx 都会退避重试；
其他 4xx 直接返回状态码，由调用方决定怎么处理。重试等待最长 MAX_WAIT 秒：
有的站点 503 时给 Retry-After: 3600，照着等会把整批任务卡住几个小时。
"""

from __future__ import annotations

import gzip
import http.client
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "junrei-sync/0.1 (+https://junrei.jannchie.com)"
MAX_WAIT = 60.0


def _ssl_context():
    """有 certifi 就用它的根证书：部分 Windows 环境的系统证书库会让 api.bgm.tv 这类新签发链校验失败。
    也可以用环境变量 SSL_CERT_FILE 指定证书文件。"""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


SSL_CONTEXT = _ssl_context()


def _retry_after(e: urllib.error.HTTPError, attempt: int) -> float:
    try:
        wait = float(e.headers.get("Retry-After") or "")
    except ValueError:  # 没给，或给的是日期
        wait = 2.0 ** (attempt + 1)
    return min(wait, MAX_WAIT)


def request(url: str, *, data: bytes | None = None, method: str | None = None, headers: dict | None = None,
            ua: str = UA, timeout: float = 30, retries: int = 4) -> tuple[int, bytes]:
    """返回 (状态码, 响应体)；重试用尽仍是网络错误时返回 (599, b"")，地址本身不合法时返回 (400, b"")"""
    # 博客里的图片地址常带着没编码的日文、空格：先按百分号编码（已编码的部分保持不变）
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    try:
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"User-Agent": ua, "Accept-Encoding": "gzip", **(headers or {})})
    except ValueError:
        return 400, b""
    for attempt in range(retries):
        last = attempt == retries - 1
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return r.status, body
        except urllib.error.HTTPError as e:
            if (e.code == 429 or e.code >= 500) and not last:
                wait = _retry_after(e, attempt)
                print(f"  ! {url} → {e.code}，{wait:.0f}s 后重试", file=sys.stderr)
                time.sleep(wait)
                continue
            return e.code, e.read()
        except (http.client.InvalidURL, UnicodeError):  # 模板残片之类根本不是地址的
            return 400, b""
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            if last:
                print(f"  ! {url} 失败（{e!r}）", file=sys.stderr)
                break
            print(f"  ! {url} 失败（{e!r}），{2 ** attempt}s 后重试", file=sys.stderr)
            time.sleep(2**attempt)
    return 599, b""
