"""anime-tourism.jp（Anime Tourism 聖地巡礼DB）的地标作为线索并入 sync/manual.json。

  python -m sync.anime_tourism --dry-run    # 只抓取、比对，打印会并入多少
  python -m sync.anime_tourism --wait       # 并入（地标名的多语言翻译走 Claude Batch，等它完成）

各都道府县的地图页（/r/<地区>/）内嵌着该地区全部地标：坐标、地点名、所属作品，以及 1～2 张 200px 的场景截图。
流程：作品名对上唯一一部 Bangumi 作品 → 去掉和已有地标重复的（150 米内或同名）→ 截图在本地 trace.moe 帧库里比对，
对上的取集数与时间（规则同 sync.gaps.apply_trace），对不上的也照样收录 → 截图缩小后转存到 R2 → 并入 manual.json。
地标只记坐标、地点名、集数与时间，不搬运站点写的介绍；每个地标保留指向原页面的来源链接。
页面与截图按每秒一个请求抓取，缓存在 data/anime-tourism/（截图）与 cache.sqlite（页面）。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
from pathlib import Path

from sync import llm
from sync.enrich_common import Http, add_data_arg, open_db, setup_stdout
from sync.fold import loose
from sync.sync import haversine_km

BASE = "https://anime-tourism.jp/"
SOURCE = "Anime Tourism"
UA = "junrei-sync/0.1 (+https://junrei.jannchie.com)"
DUP_METERS = 150

MARKER = re.compile(r'lat\[(\d+)\]=([\d.\-]+);lng\[\1\]=([\d.\-]+);icon\[\1\]=\d+;popup\[\1\]="(.*?)";(?=lat\[|\s*\n|\s*<|\s*$)', re.S)


def parse_region(page: str) -> list[dict]:
    """地图页内嵌的地标：坐标、作品（站内 id 与标题）、地点名、地标页、截图"""
    out = []
    for m in MARKER.finditer(page):
        pop = m.group(4).replace('\\"', '"').replace("\\/", "/")
        work = re.search(r'<h5><a href="https://anime-tourism\.jp/t/(\d+)/"[^>]*>(.*?)</a>', pop)
        name = re.search(r"</h5><p>(.*?)</p>", pop)
        if not work or not name:
            continue
        tid = int(work.group(1))
        link = re.search(rf'href="(https://anime-tourism\.jp/t/{tid}/[^"/]+/)"', pop)
        out.append({
            "lat": float(m.group(2)), "lng": float(m.group(3)), "tid": tid, "work": html.unescape(work.group(2)),
            "name": html.unescape(re.sub(r"<[^>]+>", "", name.group(1))).strip(),
            "page": link.group(1) if link else f"{BASE}t/{tid}/",
            "images": re.findall(r'<img src="(https://anime-tourism\.jp/h\d/[^"]+)"', pop),
        })
    return out


def regions(http: Http) -> list[str]:
    _, body = http.get(BASE + "r/all/")
    return sorted(set(re.findall(r'href="\.\./([A-Za-z]+)/"', body.decode("utf-8", "replace"))) - {"all"})


def collect(http: Http) -> list[dict]:
    spots: dict[tuple, dict] = {}
    for r in regions(http):
        status, body = http.get(f"{BASE}r/{r}/")
        if status != 200:
            print(f"  ! {r}：{status}")
            continue
        for s in parse_region(body.decode("utf-8", "replace")):
            spots.setdefault((s["page"], s["name"], round(s["lat"], 5), round(s["lng"], 5)), s)
    return list(spots.values())


EP_PREFIX = re.compile(r"^(?:NEXT)?第?([0-9０-９]+)[話话集]\s*")
EP_PREFIX_EN = re.compile(r"^(?:NEXT)?(?:第?[0-9０-９]+[話话集]|Ep(?:isode)?\.?\s*\d+)[\s:：-]*", re.I)
# 站内的占位名（待考证、记号、编号）和漫画的扉页、封面：说明不了是什么地方，也不是动画画面
JUNK_NAME = re.compile(r"^(検討|目印|ポイント|候補|不明)\s*[0-9０-９①-⑳]*$|扉絵|表紙")


def clean_name(name: str) -> tuple[str, str] | None:
    """站内地点名 → (地点名, 名字里写着的集数)；占位名返回 None。「4話　踏切」→ (「踏切」, "4")"""
    import unicodedata

    name = re.sub(r"\s+", " ", name.replace("　", " ")).strip()
    if not name or JUNK_NAME.search(name):
        return None
    m = EP_PREFIX.match(name)
    if not m:
        return name, ""
    rest = name[m.end():].strip()
    return (rest or name), unicodedata.normalize("NFKC", m.group(1))


def spot_id(s: dict) -> str:
    key = s["page"] if s["page"].count("/") > 5 else f'{s["page"]}|{s["name"]}|{s["lat"]:.5f},{s["lng"]:.5f}'
    return f'at-{s["tid"]}-{hashlib.sha1(key.encode()).hexdigest()[:8]}'


class Images:
    """截图原件缓存在 data/anime-tourism/img/：比对与转存共用，同一张只下载一次"""

    def __init__(self, data: Path, http: Http):
        self.dir = data / "anime-tourism" / "img"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.http = http

    def get(self, url: str) -> bytes | None:
        path = self.dir / url.rsplit("/", 2)[-2] / url.rsplit("/", 1)[-1]
        if path.exists():
            return path.read_bytes() or None
        status, body = self.http.get(url)
        ok = status == 200 and len(body) >= 1000
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body if ok else b"")  # 下载不到的记成空文件，不再重试
        return body if ok else None


def is_color(body: bytes) -> bool:
    """站上少数「截图」其实是漫画分镜（黑白），不当作动画截图用"""
    import io

    from PIL import Image, ImageStat

    try:
        im = Image.open(io.BytesIO(body)).convert("HSV")
    except Exception:  # noqa: BLE001
        return False
    return ImageStat.Stat(im).mean[1] >= 20


def main():
    from sync import tracemoe
    from sync.gaps import (MANUAL, SHOTS, Vectors, all_subjects, anilist_bangumi, apply_trace, existing_points,
                           load_manual, lookup, register_works, save_manual, shot_jpeg, work_names)
    from sync.translate import TASKS, opencc_converter

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", action="store_true", help="等翻译的 Batch 完成")
    ap.add_argument("--mode", choices=["batch", "sync"], default="batch")
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    http = Http(db, interval=1.0, ua=UA, max_age_days=30)

    spots = collect(http)
    print(f"anime-tourism：{len(spots)} 个地标，{len({s['tid'] for s in spots})} 部作品")

    # 1. 作品：标题对上唯一一部 Bangumi 作品
    subs = all_subjects(data)
    index: dict[str, set[int]] = {}
    for bid, sub in subs.items():
        for n in work_names(None, None, sub):
            index.setdefault(loose(n), set()).add(bid)
    works = {}
    for tid, title in {s["tid"]: s["work"] for s in spots}.items():
        found = index.get(loose(title), set())
        if len(found) == 1:
            works[tid] = next(iter(found))
    print(f"对上 Bangumi 的作品 {len(works)} / {len({s['tid'] for s in spots})}")

    # 2. 去重：和已有地标（Anitabi + manual.json）相距不到 150 米或同名的不要
    manual = load_manual()
    known_ids = {p["id"] for p in manual["points"]}
    manual_points: dict[int, list] = {}
    for mp in manual["points"]:
        manual_points.setdefault(mp["bangumi"], []).append(mp)
    todo, have = [], {}
    for s in spots:
        bid = works.get(s["tid"])
        if not bid or (pid := spot_id(s)) in known_ids or not (cleaned := clean_name(s["name"])):
            continue
        s["bangumi"], s["id"] = bid, pid
        s["name"], s["ep"] = cleaned
        if bid not in have:
            have[bid] = existing_points(db, bid, manual_points.get(bid, []))
        ex = have[bid]
        if loose(s["name"]) in ex["names"] or any(
                haversine_km(s["lat"], s["lng"], la, ln) * 1000 < DUP_METERS for la, ln in ex["coords"]):
            continue
        ex["names"].add(loose(s["name"]))  # 站内同一地点在几个地区页重复出现
        ex["coords"].append((s["lat"], s["lng"]))
        todo.append(s)
    print(f"新地标 {len(todo)} 个（其中 {sum(1 for s in todo if s['images'])} 个带截图）")

    # 3. 截图：下载、在本地 trace.moe 帧库里比对
    images = Images(data, http)
    tm = tracemoe.open_db() if (tracemoe.DIR / "frames.sqlite").exists() else None
    vectors = Vectors(db)
    by_work: dict[int, list[dict]] = {}
    for s in todo:
        by_work.setdefault(s["bangumi"], []).append(s)
    traced = 0
    for bid, group in by_work.items():
        ids = tracemoe.match_anilist(tm, work_names(None, None, subs.get(bid, {}))) if tm else {}
        tracemoe.clear_cache()
        for s in group:
            s["confidence"] = 0.5
            for url in s["images"]:
                body = images.get(url)
                if not body or not is_color(body):
                    continue
                s.setdefault("shot", (url, body))
                if ids:
                    if url not in vectors.known:
                        vectors.new[url] = tracemoe.image_vector(body)
                    if proof := lookup(tm, vectors, url, ids):
                        s["trace"], s["shot"] = proof, (url, body)
                        traced += 1
                        break
        apply_trace(group, retarget=anilist_bangumi(tm, subs, {s["trace"]["anilist"] for s in group if s.get("trace")}) if tm else None)
        vectors.save()
    print(f"截图对上 trace.moe 的 {traced} 个，其中有集数与时间的 {sum(1 for s in todo if s.get('s') is not None)} 个")
    if args.dry_run:
        return

    # 4. 地标名的多语言版本（和 sync.translate 的地标名同一个任务、同一份缓存）
    names = {s["name"] for s in todo}
    results = llm.run(db, TASKS["name"], sorted(names), mode=args.mode, wait=args.wait)
    to_hant = opencc_converter("s2twp")

    # 5. 截图转存到 R2，并入
    from concurrent.futures import ThreadPoolExecutor

    from sync.covers import PUBLIC, Uploader

    up = Uploader()

    def mirror(s: dict) -> str | None:
        if "shot" not in s:
            return None
        url, body = s["shot"]
        jpeg = shot_jpeg(body)
        key = f"{SHOTS}{s['id']}-{hashlib.sha1(url.encode()).hexdigest()[:8]}.jpg"
        return PUBLIC + key if jpeg and up.put(key, jpeg) else None

    with ThreadPoolExecutor(up.workers) as pool:
        shots = list(pool.map(mirror, todo))
    added = 0
    for s, shot in zip(todo, shots):
        if "shot" in s and not shot:
            continue  # 转存失败，下次再试
        r = (results.get(llm.sha(s["name"])) or ({},))[0]
        cn = r.get("zh_hans") or None
        point = {
            "bangumi": (s.get("trace") or {}).get("bangumi", s["bangumi"]), "id": s["id"], "name": s["name"], "cn": cn,
            "lat": round(s["lat"], 6), "lng": round(s["lng"], 6), "ep": s["ep"] or None, "src": "ja",
            "names": {k: v for k, v in {"ja": s["name"], "zh-Hans": cn, "zh-Hant": cn and to_hant and to_hant(cn),
                                         "en": r.get("en") or None}.items() if v},
            "marks": {}, "reference": s["page"], "source": SOURCE, "s": s.get("s"),
        }
        if shot:
            point.update(image=shot, origin=SOURCE, origin_link=s["page"])
        manual["points"].append(point)
        added += 1
    register_works(manual, subs)
    save_manual(manual)
    print(f"并入 {added} 个地标（{sum(1 for x in shots if x)} 个带截图）→ {MANUAL}")


if __name__ == "__main__":
    setup_stdout()
    main()
