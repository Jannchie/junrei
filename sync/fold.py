"""搜索用的文本「折叠」：把同一个词的不同写法归一，让中日英、简繁、平片假名之间能互相搜到。

规则必须和前端 src/fold.ts 一致：
  NFKC（全角→半角等）→ 小写 → 汉字按映射表归一到简体 → 片假名→平假名 → 去掉空白、标点与符号
汉字映射表由 OpenCC 生成，只收录数据里出现的字及其繁体写法，导出为 data/fold.json 供前后端共用。
"""

from __future__ import annotations

import unicodedata

from opencc import OpenCC

_t2s = OpenCC("t2s")
_s2t = OpenCC("s2t")


def build_char_map(texts) -> dict[str, str]:
    """数据里出现的每个汉字，连同它的繁体写法，映射到简体（只保留有变化的）"""
    chars = {c for t in texts if t for c in unicodedata.normalize("NFKC", t)}
    variants = chars | {v for c in chars for v in _s2t.convert(c)}
    out = {}
    for c in sorted(variants):  # 排序：集合遍历顺序每次运行都不同，输出要稳定，避免无意义的提交
        s = _t2s.convert(c)
        if len(s) == 1 and s != c:
            out[c] = s
    return out


def fold(text: str | None, char_map: dict[str, str]) -> str:
    if not text:
        return ""
    out = []
    for c in unicodedata.normalize("NFKC", text).lower():
        c = char_map.get(c, c)
        o = ord(c)
        if 0x30A1 <= o <= 0x30F6:  # 片假名 → 平假名
            c = chr(o - 0x60)
        cat = unicodedata.category(c)
        if cat[0] in "PSZC":  # 标点、符号、空白、控制字符
            continue
        out.append(c)
    return "".join(out)


_kakasi = None


def romaji(text: str | None) -> str:
    """日文标题的罗马音（赫本式），没有假名或汉字时返回空串"""
    global _kakasi
    if not text or not any(ord(c) > 0x3000 for c in text):
        return ""
    if _kakasi is None:
        import pykakasi

        _kakasi = pykakasi.kakasi()
    return "".join(item["hepburn"] for item in _kakasi.convert(text))
