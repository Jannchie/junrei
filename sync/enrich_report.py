"""把 enrich.sqlite 里各步骤的结果汇总进 data/report.md 的「整理与补全」一节。

sync.sync 每次会整体重写 report.md，所以这一节放在标记之间、由各补全脚本跑完后重新生成；
也可以单独跑：python -m sync.enrich_report
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sync.enrich_common import add_data_arg, now_iso, open_db, setup_stdout
from sync.sync import pct, write_json

START, END = "<!-- enrich:start -->", "<!-- enrich:end -->"


def has(db, table: str) -> bool:
    return db.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def one(db, sql: str, *args):
    return db.execute(sql, args).fetchone()[0]


def last_run(db, step: str):
    r = db.execute("SELECT finished_at, params, stats FROM enrich_run WHERE step=? ORDER BY finished_at DESC LIMIT 1",
                   (step,)).fetchone()
    return (r[0], json.loads(r[1]), json.loads(r[2])) if r else (None, {}, {})


def section_places(db, L, out):
    if not has(db, "place"):
        return
    when, params, s = last_run(db, "places")
    out["places"] = s
    L += ["", "### 地点合并（place / place_point）", "",
          f"规则：≤{params.get('same_m')} m 视为同一坐标；≤{params.get('near_m')} m 且名称相似度 ≥{params.get('name_sim')} 合并；"
          f"簇跨度上限 {params.get('max_span_m')} m。生成于 {when}。", "",
          "| 指标 | 数量 |", "|---|---|",
          f"| 参与合并的地标 | {s['points']} |", f"| 地点（place）总数 | {s['places']} |",
          f"| 被合并掉的地标（地标数 − 地点数） | {s['points_merged_away']} |",
          f"| 含多个地标的地点 | {s['multi_point_places']} |", f"| 挂多部作品的地点 | {s['multi_bangumi_places']} |",
          f"| 合并边：同坐标 / 近距同名 / 因跨度上限拒绝 | {s['merges'].get('same_coord', 0)} / "
          f"{s['merges'].get('near_name', 0)} / {s['merges'].get('rejected_span', 0)} |"]
    top = db.execute("""SELECT p.id, coalesce(p.cn, p.name), p.bangumi_count, p.point_count FROM place p
                        ORDER BY p.bangumi_count DESC, p.point_count DESC LIMIT 10""").fetchall()
    L += ["", "挂作品最多的地点：", ""] + [f"- {name}（{pid}）：{nb} 部作品、{npt} 个地标" for pid, name, nb, npt in top]


def section_notes(db, L, out):
    if not has(db, "note_class"):
        return
    total = one(db, "SELECT count(*) FROM src.point WHERE mark IS NOT NULL")
    done = one(db, "SELECT count(*) FROM note_class")
    tags = db.execute("""SELECT tag, count(*), sum(confidence >= 0.7) FROM note_tag GROUP BY tag ORDER BY 2 DESC""").fetchall()
    models = db.execute("SELECT served_model, prompt_version, count(*) FROM note_class GROUP BY 1, 2").fetchall()
    out["notes"] = {"with_mark": total, "classified": done, "tags": {t: n for t, n, _ in tags}}
    L += ["", "### 备注标签（note_class / note_tag）", "",
          f"已分类 {pct(done, total)} 条带备注的地标。模型：" + "、".join(f"{m}（{v}）{n} 条" for m, v, n in models), "",
          "| 标签 | 地标数 | 其中置信度 ≥0.7 |", "|---|---|---|"] + [f"| {t} | {n} | {h} |" for t, n, h in tags]
    hint = one(db, "SELECT count(*) FROM note_class WHERE episode_hint IS NOT NULL")
    no_ep = one(db, """SELECT count(*) FROM note_class c JOIN src.point p ON p.bangumi_id=c.bangumi_id AND p.id=c.point_id
                       WHERE c.episode_hint IS NOT NULL AND p.ep IS NULL""")
    L += ["", f"备注里识别出集数 {hint} 条，其中原始数据无集数的 {no_ep} 条（可用于补全集数，需审核）。"]


def section_names(db, L, out):
    if not has(db, "translation"):
        return
    totals = {
        ("bangumi", "title"): one(db, "SELECT count(*) FROM src.bangumi WHERE deleted=0"),
        ("point", "name"): one(db, "SELECT count(*) FROM src.point p JOIN src.bangumi b ON b.id=p.bangumi_id "
                                   "WHERE b.deleted=0 AND p.name IS NOT NULL"),
        ("point", "mark"): one(db, "SELECT count(*) FROM src.point p JOIN src.bangumi b ON b.id=p.bangumi_id "
                                   "WHERE b.deleted=0 AND p.mark IS NOT NULL"),
    }
    cov = {(e, f, lang): (n, mt) for e, f, lang, n, mt in db.execute(
        """SELECT entity, field, lang, count(DISTINCT entity_id),
                  count(DISTINCT entity_id) - count(DISTINCT CASE WHEN machine_translated = 0 THEN entity_id END)
           FROM translation GROUP BY 1, 2, 3""")}
    src = db.execute("SELECT source, count(*) FROM translation GROUP BY 1 ORDER BY 2 DESC").fetchall()
    langs = ["zh-Hans", "zh-Hant", "ja", "en"]
    out["translation"] = {f"{e}.{f}": {lang: cov.get((e, f, lang), (0, 0))[0] for lang in langs} for e, f in totals}
    L += ["", "### 多语言翻译（translation）", "",
          "每格为「有该语言文本的条目数（其中仅有机器翻译 / 转换的条目数）」。来源：" + "、".join(f"{k} {v} 行" for k, v in src), "",
          "| 字段 | 条目数 | " + " | ".join(langs) + " |", "|---|---|" + "---|" * len(langs)]
    for (e, f), total in totals.items():
        cells = [f"{pct(cov.get((e, f, lang), (0, 0))[0], total)}（{cov.get((e, f, lang), (0, 0))[1]}）" for lang in langs]
        L.append(f"| {e}.{f} | {total} | " + " | ".join(cells) + " |")


def section_bgm(db, L, out):
    if not has(db, "bangumi_meta"):
        return
    total = one(db, "SELECT count(*) FROM src.bangumi WHERE deleted=0")
    ok = one(db, "SELECT count(*) FROM bangumi_meta WHERE status=200")
    missing = one(db, "SELECT count(*) FROM bangumi_meta WHERE status<>200")
    aliases = one(db, "SELECT count(*) FROM bangumi_alias")
    with_alias = one(db, "SELECT count(DISTINCT bangumi_id) FROM bangumi_alias")
    dated = one(db, "SELECT count(*) FROM bangumi_meta WHERE air_date IS NOT NULL")
    langs = db.execute("SELECT lang, count(*) FROM bangumi_alias GROUP BY lang ORDER BY 2 DESC").fetchall()
    filled_cn = one(db, """SELECT count(*) FROM bangumi_meta m JOIN src.bangumi b ON b.id=m.bangumi_id
                           WHERE b.cn IS NULL AND m.name_cn IS NOT NULL""")
    out["bangumi_meta"] = {"total": total, "fetched": ok, "missing": missing, "aliases": aliases}
    L += ["", "### Bangumi 作品元数据（bangumi_meta / bangumi_alias）", "",
          "| 指标 | 数量 |", "|---|---|",
          f"| 取到条目 | {pct(ok, total)} |", f"| 条目不可用（404 / 需登录等） | {missing} |",
          f"| 有放送 / 发售日期 | {dated} |", f"| 别名总数 / 有别名的作品 | {aliases} / {with_alias} |",
          f"| 原始数据缺中文名、Bangumi 可补 | {filled_cn} |",
          "", "别名语言：" + "、".join(f"{k} {v}" for k, v in langs)]


def section_geo(db, L, out):
    if not has(db, "review_city"):
        return
    rows = dict(db.execute("SELECT status, count(*) FROM review_city GROUP BY status").fetchall())
    pts = one(db, "SELECT count(*) FROM point_geo")
    nomuni = one(db, "SELECT count(*) FROM point_geo WHERE muni_cd IS NULL")
    out["geocheck"] = {"points_geocoded": pts, "status": rows}
    L += ["", "### 市町村比对（国土地理院反向地理编码，point_geo / review_city）", "",
          f"已反查 {pts} 个地标（坐标取 3 位小数，同格只查一次），其中 {nomuni} 个查不到市町村（海上 / 日本境外）。", "",
          "| 作品状态 | 数量 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(rows.items())] + [
          "", "说明：`mismatch` = 标注城市里的地标不到 30%；`suggest` = 原始数据缺城市、按地标多数给出建议；"
          "`ok` = 一致；`city_unrecognized` = 城市名不是日本行政区（如「日本」「海外」）或无法识别；`no_sample` = 没有日本境内地标或查到的太少；`pending` = 抽样点还没查完（用 --max-requests 分批跑时）。",
          "", "待复核清单：`data/review/city-mismatch.csv`、`data/review/city-suggest.csv`、`data/review/point-no-municipality.csv`。"]


def write_report(db, data: Path) -> None:
    L = [START, "", "## 整理与补全", "", f"派生数据在 `data/enrich.sqlite`，原始同步数据未修改。汇总时间：{now_iso()}"]
    out = {"generated_at": now_iso()}
    for fn in (section_places, section_notes, section_names, section_bgm, section_geo):
        fn(db, L, out)
    L += ["", END]
    block = "\n".join(L) + "\n"
    report = data / "report.md"
    text = report.read_text(encoding="utf-8") if report.exists() else ""
    if START in text and END in text:
        head, rest = text.split(START, 1)
        text = head + block + rest.split(END, 1)[1].lstrip("\n")
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + block
    report.write_text(text, encoding="utf-8")
    write_json(data / "enrich-report.json", out)
    print(f"报告已更新：{report}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    args = ap.parse_args()
    write_report(open_db(Path(args.data)), Path(args.data))


if __name__ == "__main__":
    setup_stdout()
    main()
