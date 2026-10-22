"""可疑数据：用国土地理院（GSI）反向地理编码查地标所属市町村，与作品标注的 city 比对，输出待复核清单。

  - 每部作品按优先级均匀抽最多 --per-bangumi 个日本境内地标；坐标取 3 位小数（约 100 m）去重后请求，
    结果缓存在 cache.http_cache，重跑只请求新坐标。--max-requests 限制本次新发请求数，可分多次跑完。
  - 市町村代码 → 名称用 GSI 的 muni.js。作品 city 多为简体中文（"镰仓市"），先转成日文字形再匹配。

结果写入 enrich.sqlite 的 point_geo / review_city，并导出 data/review/ 下的 CSV：
  city-mismatch.csv          标注城市里的地标不到 30%：city 可能填错
  city-suggest.csv           原始数据缺 city：按地标多数给出建议
  point-no-municipality.csv  日本范围内但查不到市町村（海上 / 坐标偏）

  python -m sync.geocheck --max-requests 2000
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from sync.enrich_common import Http, add_data_arg, log_run, now_iso, open_db, setup_stdout
from sync.enrich_report import write_report
from sync.sync import JAPAN_BBOX

GSI_REVERSE = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
GSI_MUNI = "https://maps.gsi.go.jp/js/muni.js"
GSI_INTERVAL = 1.0
MISMATCH_SHARE = 0.3
SUGGEST_SHARE = 0.5
MIN_CHECKED = 3
MIN_COVERAGE = 0.8

SCHEMA = """
CREATE TABLE IF NOT EXISTS point_geo (
  bangumi_id INTEGER NOT NULL, point_id TEXT NOT NULL,
  q_lat REAL, q_lng REAL,       -- 实际查询的坐标（3 位小数）
  muni_cd INTEGER, pref TEXT, muni TEXT, lv01 TEXT,  -- muni_cd 为空表示 GSI 没返回市町村
  source TEXT, fetched_at TEXT,
  PRIMARY KEY (bangumi_id, point_id)
);
DROP TABLE IF EXISTS review_city;
CREATE TABLE review_city (
  bangumi_id INTEGER PRIMARY KEY, title TEXT, city TEXT,
  status TEXT,                  -- ok / mismatch / suggest / city_unrecognized / no_sample / pending
  level TEXT,                   -- city 匹配到的层级：pref / muni
  checked INTEGER, in_city INTEGER, share REAL,
  top_munis TEXT,               -- [[市町村, 地标数], …]
  suggested_city TEXT, suggested_share REAL, confidence REAL,
  source TEXT, created_at TEXT
);
"""

# 简体 / 繁体 → 日本新字体，只收地名里常见的字（每对：源字 + 目标字）
FOLD = str.maketrans({p[0]: p[1] for p in (
    "并並 东東 县県 泽沢 滨浜 镰鎌 岛島 冈岡 广広 叶葉 枥栃 爱愛 关関 长長 饭飯 户戸 涩渋 马馬 黑黒 绳縄 宫宮 "
    "樱桜 丰豊 荣栄 汤湯 驿駅 桥橋 边辺 龙竜 泷滝 须須 贺賀 鸟鳥 绫綾 织織 纪紀 庆慶 应応 乐楽 兰蘭 门門 "
    "间間 阳陽 乡郷 发発 湾湾 凤鳳 儿児 岁歳 读読 访訪 诹諏 调調 圆円 尔爾 乌烏 鸭鴨 丽麗 兴興 带帯 齐斉 "
    "斋斎 济済 气気 时時 实実 盐塩 仓倉 贝貝 钏釧 网網 纹紋 馆館 胜勝 鹤鶴 库庫 惠恵 绘絵 经経 结結 线線 "
    "练練 续続 终終 组組 细細 红紅 纳納 纲綱 缘縁 总総 级級 绿緑 统統 濑瀬 顺順 预預 领領 头頭 风風 飞飛 "
    "驹駒 骏駿 鱼魚 鸣鳴 鹰鷹 陆陸 达達 镇鎮 罗羅 军軍 车車 轮輪 艺芸 龟亀 摄摂 滩灘 条条 铫銚 狭狭 鹭鷺 "
    "栉櫛 楼楼 双双 灵霊 浅浅 寿寿 莲蓮 苇葦 觉覚 阁閣 营営 对対 涉渉 桧桧 云雲 鸠鳩 鹿鹿 务務 业業 别別 "
    "观観 赖頼 伞傘 吴呉 杂雑 凑湊 历歴 礼礼 让譲 浊濁 训訓 讃讃 骑騎 稻稲 钟鐘 银銀 铁鉄 锦錦 阶階 际際 "
    "隐隠 难難 韩韓 页頁 题題 颜顔 澤沢 濱浜 廣広 縣県 鐮鎌 櫻桜 豐豊 榮栄 驛駅 龍竜 瀧滝 灣湾 兒児 歲歳 "
    "圓円 齋斎 濟済 氣気 實実 鹽塩 勝勝 繪絵 經経 續続 綠緑 瀨瀬 頭頭 陸陸 鎮鎮 龜亀 攝摂 灘灘 籠篭 條条 "
    "狹狭 樓楼 雙双 巖岩 靈霊 淺浅 壽寿 覺覚 營営 對対 涉渉 檜桧 國国 會会 學学 區区 澀渋 戶戸 黑黒 德徳 "
    "聲声 廳庁 爭争 藏蔵 邊辺 關関 寫写 舊旧 歸帰 萬万 與与 號号 處処 鐵鉄 冲沖 热熱 远遠 霸覇 势勢 诸諸 "
    "饰飾 见見 后後 灶竈 穗穂 浓濃 宁寧 闻聞 "
).split()})
# 日文名带假名、无法按字转换的市
KANA_CITY = {"埼玉市": "さいたま市", "筑波市": "つくば市", "磐城市": "いわき市", "宇流麻市": "うるま市",
             "仁賀保市": "にかほ市", "夷隅市": "いすみ市", "南阿爾卑斯市": "南アルプス市", "日之出町": "日の出町"}
PREF_SUFFIX = re.compile(r"(都|道|府|県|省)$")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).strip().translate(FOLD)
    return KANA_CITY.get(s, s)


class Muni:
    def __init__(self, js: str):
        self.by_code = {}
        for code, pref_cd, pref, name in re.findall(r"\"(\d+)\"\]\s*=\s*'(\d+),([^,]+),\d+,([^']+)'", js):
            base, _, ward = name.replace("\u3000", " ").partition(" ")
            self.by_code[int(code)] = {"pref_cd": int(pref_cd), "pref": pref, "name": name.replace("\u3000", ""),
                                       "base": base, "ward": ward or None}
        self.prefs = {}
        self.names = defaultdict(set)
        for code, m in self.by_code.items():
            self.prefs[m["pref"]] = m["pref_cd"]
            self.prefs[PREF_SUFFIX.sub("", m["pref"])] = m["pref_cd"]
            for key in {m["name"], m["base"], m["ward"]} - {None}:
                self.names[key].add(code)

    def label(self, code: int | None) -> str | None:
        """展示用：政令市的区归到市（横浜市），东京 23 区保留区名。"""
        m = self.by_code.get(code) if code else None
        return m["base"] if m else None

    def match_city(self, city: str):
        """作品 city → ("pref", {都道府県代码}) / ("muni", {市町村代码}) / None。多个城市用分隔符隔开时取并集。"""
        level, codes = None, set()
        for part in re.split(r"[、,，/／・\s]+", city):
            part = fold(part)
            if not part:
                continue
            if part in self.prefs:
                level = level or "pref"
                codes |= {c for c, m in self.by_code.items() if m["pref_cd"] == self.prefs[part]}
                continue
            hit = self.names.get(part) or self.names.get(part + "市")
            if not hit:  # "北海道伊達市" / "東京府中市"：去掉开头的都道府県名
                for pref, pcd in self.prefs.items():
                    rest = part[len(pref):]
                    if part.startswith(pref) and rest in self.names:
                        hit = {c for c in self.names[rest] if self.by_code[c]["pref_cd"] == pcd}
                        break
            if not hit:
                return None
            level = "muni"
            # 市名命中时把它下面的区也算进去（GSI 对政令市返回区的代码）
            codes |= {c for c, m in self.by_code.items() if c in hit or (m["base"] in {self.by_code[h]["name"] for h in hit})}
        return (level, codes) if codes else None


def sample(points: list, n: int) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--per-bangumi", type=int, default=30, help="每部作品最多抽查多少个地标")
    ap.add_argument("--max-requests", type=int, help="本次最多新发多少个 GSI 请求（缓存命中不算）")
    ap.add_argument("--interval", type=float, default=GSI_INTERVAL, help="请求间隔（秒）")
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    db.executescript(SCHEMA)
    started = now_iso()
    http = Http(db, args.interval)

    status, js = http.get(GSI_MUNI)
    if status != 200:
        raise SystemExit(f"取不到 {GSI_MUNI}（{status}）")
    muni = Muni(js.decode("utf-8"))

    la0, la1, ln0, ln1 = JAPAN_BBOX
    by_b = defaultdict(list)
    for b, p, name, lat, lng in db.execute(
            """SELECT p.bangumi_id, p.id, p.name, p.lat, p.lng FROM src.point p JOIN src.bangumi b ON b.id = p.bangumi_id
               WHERE b.deleted = 0 AND p.lat BETWEEN ? AND ? AND p.lng BETWEEN ? AND ?
               ORDER BY p.bangumi_id, p.priority, p.id""", (la0, la1, ln0, ln1)):
        by_b[b].append((p, name, lat, lng))
    # 按「每部作品的第 k 个抽样点」轮转排序：额度有限、分多次跑时各作品进度均匀
    picked = {b: sample(pts, args.per_bangumi) for b, pts in by_b.items()}
    todo = sorted(((k, b, *pt) for b, pts in picked.items() for k, pt in enumerate(pts)), key=lambda t: (t[0], t[1]))
    todo = [t[1:] for t in todo]
    print(f"抽查 {len(todo)} 个地标，{len({(round(t[3], 3), round(t[4], 3)) for t in todo})} 个不同坐标格")

    ts = now_iso()
    new_requests = 0
    rows = []

    def flush():  # 攒一批再写：不要在开着写事务时去写缓存（另一个进程也在写缓存时会死锁）
        db.executemany("INSERT OR REPLACE INTO point_geo VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        db.commit()
        rows.clear()

    for k, (b, p, name, lat, lng) in enumerate(todo, 1):
        q = {"lat": f"{lat:.3f}", "lon": f"{lng:.3f}"}  # 与 Http.get 拼出的缓存键一致
        if args.max_requests is not None and new_requests >= args.max_requests:
            # 额度用完后只读缓存
            row = db.execute("SELECT status, body FROM cache.http_cache WHERE url=?",
                             (f"{GSI_REVERSE}?lat={q['lat']}&lon={q['lon']}",)).fetchone()
            if not row:
                continue
            st, body = row
        else:
            before = http.requests
            st, body = http.get(GSI_REVERSE, q)
            new_requests += http.requests - before
        if st != 200:
            continue
        res = (json.loads(body) or {}).get("results") or {}
        cd = int(res["muniCd"]) if res.get("muniCd") else None
        m = muni.by_code.get(cd) if cd else None
        rows.append((b, p, float(q["lat"]), float(q["lon"]), cd, m and m["pref"], m and m["name"],
                     res.get("lv01Nm") or None, "gsi_reverse_geocoder", ts))
        if len(rows) >= 500:
            flush()
            print(f"  {k}/{len(todo)}（新请求 {new_requests}，缓存命中 {http.hits}）")
    flush()

    stats = evaluate(db, muni, data, {b: {pt[0] for pt in pts} for b, pts in picked.items()})
    stats.update({"sampled": len(todo), "new_requests": new_requests, "cache_hits": http.hits})
    log_run(db, "geocheck", started, {"per_bangumi": args.per_bangumi, "interval": args.interval}, stats)
    print(json.dumps(stats, ensure_ascii=False))
    write_report(db, data)


def evaluate(db, muni: Muni, data: Path, picked: dict[int, set[str]]) -> dict:
    """picked：本次每部作品抽中的地标 id。抽样点查完 MIN_COVERAGE 以上才下结论，否则记为 pending。"""
    geo = defaultdict(list)
    for b, p, cd in db.execute("SELECT bangumi_id, point_id, muni_cd FROM point_geo"):
        if p in picked.get(b, ()):
            geo[b].append((p, cd))
    ts = now_iso()
    rows = []
    for b, title, city in db.execute("SELECT id, coalesce(cn, title), city FROM src.bangumi WHERE deleted = 0 ORDER BY id"):
        pts = [cd for _, cd in geo.get(b, []) if cd]
        top = Counter(muni.label(cd) for cd in pts).most_common(3)
        sug, sug_share = (top[0][0], round(top[0][1] / len(pts), 3)) if top else (None, 0.0)
        base = dict(bangumi_id=b, title=title, city=city, level=None, checked=len(pts), in_city=None, share=None,
                    top_munis=json.dumps(top, ensure_ascii=False), suggested_city=sug, suggested_share=sug_share,
                    confidence=None)
        if not picked.get(b):
            rows.append({**base, "status": "no_sample"})
            continue
        if len(geo.get(b, [])) < MIN_COVERAGE * len(picked[b]):
            rows.append({**base, "status": "pending"})
            continue
        if len(pts) < min(MIN_CHECKED, len(picked[b])):
            rows.append({**base, "status": "no_sample"})
            continue
        if not city:
            ok = sug_share >= SUGGEST_SHARE
            conf = round(sug_share * min(len(pts), 10) / 10, 3)
            rows.append({**base, "status": "suggest" if ok else "no_sample", "confidence": conf})
            continue
        target = muni.match_city(city)
        if not target:
            rows.append({**base, "status": "city_unrecognized"})
            continue
        level, codes = target
        n_in = sum(1 for cd in pts if cd in codes)
        share = round(n_in / len(pts), 3)
        rows.append({**base, "status": "mismatch" if share < MISMATCH_SHARE else "ok", "level": level,
                     "in_city": n_in, "share": share, "confidence": round(1 - share, 3) if share < MISMATCH_SHARE else None})

    cols = ["bangumi_id", "title", "city", "status", "level", "checked", "in_city", "share", "top_munis",
            "suggested_city", "suggested_share", "confidence"]
    db.executemany(f"INSERT INTO review_city VALUES ({','.join('?' * (len(cols) + 2))})",
                   [tuple(r[c] for c in cols) + ("gsi_reverse_geocoder", ts) for r in rows])
    db.commit()

    out = data / "review"
    out.mkdir(exist_ok=True)
    link = lambda b: f"https://www.anitabi.cn/map?bangumiId={b}"  # noqa: E731

    def dump(name, header, items):
        with (out / name).open("w", encoding="utf-8-sig", newline="") as f:  # 带 BOM，Excel 直接打开不乱码
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(items)

    dump("city-mismatch.csv", ["bangumi_id", "title", "city", "checked", "in_city", "share", "top_munis", "suggested_city",
                               "suggested_share", "link"],
         [(r["bangumi_id"], r["title"], r["city"], r["checked"], r["in_city"], r["share"], r["top_munis"],
           r["suggested_city"], r["suggested_share"], link(r["bangumi_id"]))
          for r in sorted(rows, key=lambda r: (r["share"] or 0)) if r["status"] == "mismatch"])
    dump("city-suggest.csv", ["bangumi_id", "title", "checked", "suggested_city", "suggested_share", "confidence", "top_munis",
                              "link"],
         [(r["bangumi_id"], r["title"], r["checked"], r["suggested_city"], r["suggested_share"], r["confidence"],
           r["top_munis"], link(r["bangumi_id"]))
          for r in sorted(rows, key=lambda r: -(r["confidence"] or 0)) if r["status"] == "suggest"])
    dump("point-no-municipality.csv", ["bangumi_id", "point_id", "name", "lat", "lng", "link"],
         [(b, p, n, la, ln, f"{link(b)}&pid={p}") for b, p, n, la, ln in db.execute(
             """SELECT g.bangumi_id, g.point_id, p.name, p.lat, p.lng FROM point_geo g
                JOIN src.point p ON p.bangumi_id = g.bangumi_id AND p.id = g.point_id
                WHERE g.muni_cd IS NULL ORDER BY g.bangumi_id, g.point_id""")])
    unrecognized = Counter(r["city"] for r in rows if r["status"] == "city_unrecognized")
    return {"status": dict(Counter(r["status"] for r in rows)), "unrecognized_cities": dict(unrecognized.most_common(20))}


if __name__ == "__main__":
    setup_stdout()
    main()
