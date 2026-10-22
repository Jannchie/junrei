"""中文名补全：给只有日文 / 外文名、没有中文名的地标机翻一个简体中文名。

结果写入 enrich.sqlite 的 point_cn_mt，machine_translated 恒为 1，原始 cn 字段不变；
前端展示时应标明「机翻」，人工录入的 cn 永远优先。相同名称只请求一次（见 sync.llm）。

  python -m sync.translate --dry-run
  python -m sync.translate --wait
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sync import llm
from sync.enrich_common import add_data_arg, log_run, now_iso, open_db, setup_stdout
from sync.enrich_report import write_report

# 取自 Anitabi 现有的人工中文名，只挑了译法规范的
EXAMPLES = [
    ("東京タワー", "东京塔"), ("仙台駅", "仙台站"), ("西鏡島バス停", "西镜岛公交站"), ("宇治橋", "宇治桥"),
    ("伊予農業高等学校", "伊予农业高中"), ("大須スケートリンク", "大须滑冰场"), ("許波多神社", "许波多神社"),
    ("梅林公園 すべり台", "梅林公园 滑梯"), ("お台場海浜公園", "台场海滨公园"), ("大観覧車", "大摩天轮"),
    ("葛西臨海水族園", "葛西临海水族园"), ("豊橋市視聴覚教育センター", "丰桥市视听教育中心"),
    ("江ノ電鎌倉駅JR連絡口改札", "江之电镰仓站JR联络口检票口"), ("七里ヶ浜海岸駐車場", "七里滨海岸停车场"),
    ("文京区立目白台一丁目遊び場", "文京区立目白台一丁目游乐场"), ("タイムズ下北沢第８", "Times下北泽第8停车场"),
    ("デニーズ 藤沢北口店", "Denny's 藤泽北口店"), ("St. Michael's Tower", "圣米迦勒塔"),
    ("Heathrow Airport", "伦敦希思罗机场"),
]

SYSTEM = f"""你在为动画圣地巡礼地图把地标名称译成简体中文，给中文巡礼者看。输入多为日文，也有英文等外文。

译法约定（与中文巡礼社区习惯一致）：
- 汉字地名、设施名按字转成简体中文汉字（鎌倉→镰仓，沢→泽，浜→滨，駅→站，バス停→公交站，高等学校→高中/高等学校），不要意译专有名词。
- 假名专有名词：有通行中文译名的用译名（東京タワー→东京塔）；连锁店、品牌保留常见写法（デニーズ→Denny's、セブンイレブン→7-Eleven）；否则用通俗音译或保留原文。
- 「〇丁目」「〇番線」「〇号」等编号保留；交叉口（交差点）→路口，踏切→道口，歩道橋→人行天桥。
- 名称里的集数、编号前缀（如「6話」「#03」「①」）原样保留。
- 只做翻译，不添加说明。输入若已经是中文，只做简体化后原样返回。
- confidence：0 到 1，表示译名可靠程度；纯汉字逐字转写通常较高，生僻音译、无法确定所指时给低分。

示例：
{chr(10).join(f"{a} → {b}" for a, b in EXAMPLES)}"""

TASK = llm.Task(
    name="point_name_cn",
    version="v1",
    system=SYSTEM,
    item_properties={"cn": {"type": "string"}, "confidence": {"type": "number"}},
    chunk_size=80,
)

SCHEMA = """
DROP TABLE IF EXISTS point_cn_mt;
CREATE TABLE point_cn_mt (
  bangumi_id INTEGER NOT NULL, point_id TEXT NOT NULL,
  name TEXT,                  -- 翻译时的原名（clean_text 后）
  cn TEXT, confidence REAL,
  machine_translated INTEGER NOT NULL DEFAULT 1,
  model TEXT, served_model TEXT, prompt_version TEXT, created_at TEXT,
  PRIMARY KEY (bangumi_id, point_id)
);
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--mode", choices=["batch", "sync"], default="batch")
    ap.add_argument("--limit", type=int, help="最多请求多少个不同名称（试跑用）")
    ap.add_argument("--wait", action="store_true", help="提交批次后轮询直到结束")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    started = now_iso()

    points = [(b, p, llm.clean_text(n)) for b, p, n in db.execute(
        """SELECT p.bangumi_id, p.id, p.name FROM src.point p JOIN src.bangumi b ON b.id = p.bangumi_id
           WHERE b.deleted = 0 AND p.cn IS NULL AND p.name IS NOT NULL""")]
    results = llm.run(db, TASK, [n for _, _, n in points], model=args.model, mode=args.mode,
                      dry_run=args.dry_run, limit=args.limit, wait=args.wait)
    if args.dry_run:
        return

    db.executescript(SCHEMA)
    ts = now_iso()
    rows = []
    for b, p, n in points:
        r = results.get(llm.sha(n))
        if r is None or not r[0].get("cn"):
            continue
        out, served = r
        conf = min(max(float(out.get("confidence", 0)), 0), 1)
        rows.append((b, p, n, out["cn"].strip(), conf, 1, args.model, served, TASK.prompt_version, ts))
    db.executemany("INSERT INTO point_cn_mt VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    stats = {"points_without_cn": len(points), "translated": len(rows)}
    log_run(db, "translate", started, {"model": args.model, "prompt_version": TASK.prompt_version}, stats)
    print(stats)
    write_report(db, data)


if __name__ == "__main__":
    setup_stdout()
    main()
