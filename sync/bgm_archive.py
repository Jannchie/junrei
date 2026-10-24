"""全部动画条目：从 Bangumi 官方每周发布的数据包（github.com/bangumi/Archive）读出动画条目的元数据，
写到 data/bgm-anime.json，由 sync.export 并进作品表。没有巡礼地标的作品也因此能被搜到。

只取动画（type=2）；每条只留名称、别名、首播日期、类型与热度。成人向（nsfw）的动画也收录并标上 nsfw，
网站默认隐藏；另把所有类型的 nsfw 条目 id（多为成人游戏）列进 nsfw，Anitabi、手动补充里的游戏取景据此标记。数据包约 450 MB，
已下载过同一版本就不再下载。

人员与角色：每部动画的原作、监督、系列构成、人物原案与设定、音乐、动画制作，以及主角、配角（带声优），
写到 data/bgm-credits.json（人物、角色各自的中文名、英文名、别名一并写出），作品页展示，也进搜索键。

系列：按条目关系（前传、续集、总集篇、全集、番外篇、主线故事）把动画连成系列，
每部作品记下所属系列的代表作（系列里最早播出的一部）的 id。「相同世界观」「衍生」太宽泛，不算。

  python -m sync.bgm_archive
"""

from __future__ import annotations

import json
import re
import urllib.request
import zipfile
from pathlib import Path

from sync.enrich_common import setup_stdout
from sync.net import SSL_CONTEXT, request
from sync.sync import DEFAULT_OUT

LATEST = "https://raw.githubusercontent.com/bangumi/Archive/master/aux/latest.json"
UA = "junrei-sync/0.1 (+https://junrei.jannchie.com)"
ARCHIVE_DIR = DEFAULT_OUT / "bgm-archive"
OUT = DEFAULT_OUT / "bgm-anime.json"
GAMES = DEFAULT_OUT / "bgm-games.json"
CREDITS = DEFAULT_OUT / "bgm-credits.json"
# 作品页列出的职位（subject-persons 的 position）：原作、监督、系列构成、人物原案、人物设定、音乐、动画制作
STAFF = {1: "original", 2: "director", 10: "composition", 7: "originalDesign", 8: "characterDesign", 6: "music", 67: "studio"}
CAST_TYPES = {1: 0, 2: 1}  # 主角、配角（客串不列），值为排序先后
CAST_MAX = 12  # 每部作品最多列出的角色
CV_MAX = 2  # 每个角色最多列出的声优
# Bangumi 动画条目的 platform → 与 Anitabi 一致的类别名（前端再按语言翻译）
PLATFORM = {1: "TV", 2: "OVA", 3: "剧场版", 5: "WEB"}
SERIES_RELATIONS = {2, 3, 4, 5, 6, 12}  # 前传、续集、总集篇、全集、番外篇、主线故事


def fetch(url: str) -> bytes:
    status, body = request(url, ua=UA, timeout=60)
    if status != 200:
        raise RuntimeError(f"{url} → {status}")
    return body


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


def entity_names(d: dict) -> dict:
    """人物、角色 → {n 原名, cn 中文名, en 英文名或罗马字, a 其余别名}，空的不写"""
    box = d.get("infobox") or ""
    m = re.search(r"^\|简体中文名[ \t]*=[ \t]*([^\r\n{]*)", box, re.M)
    cn = m.group(1).strip() if m else None
    tagged = dict(re.findall(r"\[([^|\]]+)\|([^\]]+)\]", box))
    en = (tagged.get("英文名") or tagged.get("罗马字") or "").strip() or None
    out = {"n": d.get("name") or None, "cn": cn if cn != d.get("name") else None, "en": en,
           # 别名：去掉空着的模板项（「第二中文名|」）和太长的说明文字
           "a": [a for a in aliases(box) if a not in (d.get("name"), cn, en) and not a.endswith("|") and len(a) <= 24][:6]}
    return {k: v for k, v in out.items() if v}


def write_credits(z: zipfile.ZipFile, anime: set[int]) -> None:
    """动画的主要人员与角色（见模块说明）→ CREDITS"""
    staff: dict[int, list] = {}
    with z.open("subject-persons.jsonlines") as f:
        for line in f:
            r = json.loads(line)
            if r["subject_id"] in anime and r["position"] in STAFF:
                staff.setdefault(r["subject_id"], []).append([STAFF[r["position"]], r["person_id"]])
    cast: dict[int, list] = {}
    with z.open("subject-characters.jsonlines") as f:
        for line in f:
            r = json.loads(line)
            if r["subject_id"] in anime and r["type"] in CAST_TYPES:
                cast.setdefault(r["subject_id"], []).append((CAST_TYPES[r["type"]], r.get("order", 0), r["character_id"]))
    cast = {sid: [c for *_, c in sorted(cs)[:CAST_MAX]] for sid, cs in cast.items()}
    wanted = {(sid, c) for sid, cs in cast.items() for c in cs}
    cv: dict[tuple[int, int], list[int]] = {}
    with z.open("person-characters.jsonlines") as f:
        for line in f:
            r = json.loads(line)
            key = (r["subject_id"], r["character_id"])
            if key in wanted and len(cv.setdefault(key, [])) < CV_MAX:
                cv[key].append(r["person_id"])
    pids = {p for ss in staff.values() for _, p in ss} | {p for ps in cv.values() for p in ps}
    cids = {c for cs in cast.values() for c in cs}
    persons, characters = {}, {}
    with z.open("person.jsonlines") as f:
        for line in f:
            d = json.loads(line)
            if int(d["id"]) in pids:
                persons[int(d["id"])] = entity_names(d)
    with z.open("character.jsonlines") as f:
        for line in f:
            d = json.loads(line)
            if int(d["id"]) in cids:
                characters[int(d["id"])] = entity_names(d)
    subjects = {sid: {"staff": staff.get(sid, []), "cast": [[c, cv.get((sid, c), [])] for c in cast.get(sid, [])]}
                for sid in anime if sid in staff or sid in cast}
    CREDITS.write_text(json.dumps({"subjects": subjects, "persons": persons, "characters": characters},
                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{CREDITS}：{len(subjects)} 部作品，{len(persons)} 位人物，{len(characters)} 个角色（{CREDITS.stat().st_size / 1e6:.1f} MB）")


def add_series(z: zipfile.ZipFile, rows: list[dict]) -> None:
    """按条目关系做连通分量（并查集），每部作品写上 series：代表作 id。只有一部的不写。"""
    by_id = {r["id"]: r for r in rows}
    parent = {i: i for i in by_id}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    with z.open("subject-relations.jsonlines") as f:
        for line in f:
            r = json.loads(line)
            a, b = r["subject_id"], r["related_subject_id"]
            if r["relation_type"] in SERIES_RELATIONS and a in by_id and b in by_id:
                parent[find(a)] = find(b)
    groups: dict[int, list[dict]] = {}
    for i, r in by_id.items():
        groups.setdefault(find(i), []).append(r)
    for members in groups.values():
        if len(members) < 2:
            continue
        head = min(members, key=lambda r: (r["date"] or "9999", r["id"]))
        for r in members:
            r["series"] = head["id"]
    sizes = sorted((len(m) for m in groups.values() if len(m) > 1), reverse=True)
    print(f"系列：{len(sizes)} 个（最大 {sizes[:5]} 部）")


def subject_row(s: dict, cat: str) -> dict:
    """数据包里的一个条目 → 只留名称、别名、首播日期、类型与热度"""
    alias = aliases(s.get("infobox", ""))
    fav = s.get("favorite") or {}
    return {
        "id": s["id"],
        "name": s.get("name") or None,
        "cn": s.get("name_cn") or None,
        "en": english(alias),
        "aliases": [a for a in alias if a not in (s.get("name"), s.get("name_cn"))][:8],
        "date": s.get("date") or None,
        "cat": cat,
        # 热度：看过 + 在看 + 想看，用于没有地标的作品之间排序
        "popularity": fav.get("done", 0) + fav.get("doing", 0) + fav.get("wish", 0),
        **({"nsfw": True} if s.get("nsfw") else {}),
    }


def main():
    path = download()
    rows, games, nsfw = [], [], []
    with zipfile.ZipFile(path) as z, z.open("subject.jsonlines") as f:
        for line in f:
            s = json.loads(line)
            if s.get("nsfw"):
                nsfw.append(s["id"])
            if s["type"] == 2:
                rows.append(subject_row(s, PLATFORM.get(s.get("platform"), "其他")))
            elif s["type"] == 4:
                games.append(subject_row(s, "游戏"))  # 补漏（sync.gaps）对美少女游戏的取景用
    rows.sort(key=lambda r: r["id"])
    with zipfile.ZipFile(path) as z:
        add_series(z, rows)
        write_credits(z, {r["id"] for r in rows})
    OUT.write_text(json.dumps({"archive": path.name, "subjects": rows, "nsfw": sorted(nsfw)}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    GAMES.write_text(json.dumps({"archive": path.name, "subjects": games}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT}：{len(rows)} 部动画，成人向条目 {len(nsfw)} 个（{OUT.stat().st_size / 1e6:.1f} MB）；游戏 {len(games)} 部")


if __name__ == "__main__":
    setup_stdout()
    main()
