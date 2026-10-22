"""备注结构化：用 Claude 把地标的自由文本备注（point.mark）分类成标签，顺带识别其中的集数。

结果写入 enrich.sqlite：
  note_class  每个已分类地标一行：标签 JSON、集数线索、模型、提示词版本
  note_tag    展开后的 (地标, 标签, 置信度)，便于查询
原始 mark 字段不变。相同备注文本只请求一次（见 sync.llm）。

  python -m sync.notes --dry-run          # 只看要发多少请求、请求长什么样
  python -m sync.notes --wait             # 提交 Message Batch 并等待结果
  python -m sync.notes --mode sync --limit 200   # 同步小规模试跑
  python -m sync.notes --wait --review   # 再用 Opus 复核低置信度的分类
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sync import llm
from sync.enrich_common import add_data_arg, log_run, now_iso, open_db, setup_stdout
from sync.enrich_report import write_report

TAGS = {
    "restricted": "禁止进入、私有地、学校/住宅等未经许可不可入内、仅能在外部观看",
    "gone": "已消失：拆除、闭店、停业、搬迁、不复存在",
    "changed": "仍存在但与作品相比已改建、改装、外观变化",
    "ticket_or_reservation": "需购票、收费入场、需预约或登记",
    "hours_or_season": "开放时间、定休日、季节/时段/活动期间限定",
    "photo_etiquette": "拍摄礼仪：禁止或限制拍摄、注意居民/学生隐私、保持安静、勿妨碍通行或营业",
    "safety": "安全风险：车流危险、悬崖、涉水、野生动物、需登山装备、天气影响",
    "access": "交通、停车、路线或步行指引",
    "shot_direction": "取景复现提示：站位、拍摄朝向、角度、参照物",
    "episode_ref": "说明在作品哪一集/哪个场景出现",
    "background": "原型说明、历史或背景介绍",
}

SYSTEM = f"""你在为动画圣地巡礼地图整理地标备注。每条备注是巡礼者写的自由文本（中文、日文或英文），
请判断它包含哪些对巡礼者有用的信息，给出标签。可用标签：
{chr(10).join(f"- {k}：{v}" for k, v in TAGS.items())}

规则：
- 只标备注里明确写到的信息，不要根据常识推测（例如提到"学校"但没说禁止入内，不标 restricted）。
- gone 只用于现实中曾经存在、后来消失的地点；作品虚构、现实里本来就没有的建筑不算 gone，可标 background。
- 一条备注可以有多个标签，也可以一个都没有（如只是一句台词或无意义文本）。
- confidence 是 0 到 1 的数，表示备注确实表达了该信息的把握；含糊的说法给 0.5 左右。
- episode：备注里提到的集数/话数，规范成"第N话"或原样的短标记（如"OP""ED""S2第3话""网络版23话"），多个用逗号分隔；没有就给空字符串。"""

TASK = llm.Task(
    name="note_tags",
    version="v1",
    system=SYSTEM,
    item_properties={
        "tags": {"type": "array", "items": {
            "type": "object",
            "properties": {"tag": {"type": "string", "enum": list(TAGS)}, "confidence": {"type": "number"}},
            "required": ["tag", "confidence"], "additionalProperties": False}},
        "episode": {"type": "string"},
    },
    chunk_size=40,
)

REVIEW_TASK = llm.Task(
    name="note_tags_review",
    version="v1",
    system=SYSTEM + """

你现在是复核者：每条输入是 JSON，text 为备注原文，draft 为另一个模型给出的初步标签和集数（可能有误）。
请按上述规则独立判断，给出最终的 tags 和 episode；draft 正确就照抄。""",
    item_properties=TASK.item_properties,
    chunk_size=30,
)
REVIEW_MODEL = "claude-opus-5-5"
REVIEW_BAND = (0.4, 0.7)  # 初分类里有标签的置信度落在这个区间才复核

SCHEMA = """
DROP TABLE IF EXISTS note_class;
DROP TABLE IF EXISTS note_tag;
CREATE TABLE note_class (
  bangumi_id INTEGER NOT NULL, point_id TEXT NOT NULL,
  mark_sha TEXT,              -- 分类时备注文本（clean_text 后）的 sha256，原文变了即失效
  tags TEXT,                  -- [{"tag":…, "confidence":…}]
  episode_hint TEXT,          -- 备注中识别出的集数，空则 NULL
  model TEXT, served_model TEXT, prompt_version TEXT, created_at TEXT,
  reviewed INTEGER NOT NULL DEFAULT 0,  -- 1：tags / episode 来自复核模型（model、prompt_version 也是复核的）
  PRIMARY KEY (bangumi_id, point_id)
);
CREATE TABLE note_tag (
  bangumi_id INTEGER NOT NULL, point_id TEXT NOT NULL, tag TEXT NOT NULL, confidence REAL,
  model TEXT, prompt_version TEXT,
  PRIMARY KEY (bangumi_id, point_id, tag)
);
CREATE INDEX note_tag_tag ON note_tag (tag, confidence);
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--mode", choices=["batch", "sync"], default="batch")
    ap.add_argument("--limit", type=int, help="最多请求多少条不同文本（试跑用）")
    ap.add_argument("--wait", action="store_true", help="提交批次后轮询直到结束")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--review", action="store_true",
                    help=f"用更强的模型复核初分类里置信度在 {REVIEW_BAND[0]}–{REVIEW_BAND[1]} 之间的备注")
    ap.add_argument("--review-model", default=REVIEW_MODEL)
    args = ap.parse_args()
    data = Path(args.data)
    db = open_db(data)
    started = now_iso()

    points = [(b, p, llm.clean_text(m)) for b, p, m in db.execute(
        """SELECT p.bangumi_id, p.id, p.mark FROM src.point p JOIN src.bangumi b ON b.id = p.bangumi_id
           WHERE b.deleted = 0 AND p.mark IS NOT NULL""")]
    opts = dict(mode=args.mode, dry_run=args.dry_run, limit=args.limit, wait=args.wait)
    results = llm.run(db, TASK, [m for _, _, m in points], model=args.model, **opts)
    final = {s: (out, served, args.model, TASK.prompt_version, 0) for s, (out, served) in results.items()}
    if args.review:
        payloads = {}
        for s, (out, _) in results.items():
            if any(REVIEW_BAND[0] <= float(t.get("confidence", 0)) < REVIEW_BAND[1] for t in out.get("tags", [])):
                mark = db.execute("SELECT input FROM cache.llm_cache WHERE input_sha=? LIMIT 1", (s,)).fetchone()[0]
                payloads[s] = json.dumps({"text": mark, "draft": out}, ensure_ascii=False)
        reviewed = llm.run(db, REVIEW_TASK, list(payloads.values()), model=args.review_model, **opts)
        for s, payload in payloads.items():
            if (r := reviewed.get(llm.sha(payload))) is not None:
                final[s] = (r[0], r[1], args.review_model, REVIEW_TASK.prompt_version, 1)
        print(f"复核 {len(payloads)} 条不同备注，已完成 {sum(1 for v in final.values() if v[4])} 条")
    if args.dry_run:
        return

    db.executescript(SCHEMA)
    ts = now_iso()
    classes, tags = [], []
    for b, p, m in points:
        r = final.get(llm.sha(m))
        if r is None:
            continue
        out, served, model, pv, rev = r
        seen = {}
        for t in out.get("tags", []):
            if t.get("tag") in TAGS:
                seen[t["tag"]] = max(seen.get(t["tag"], 0), min(max(float(t.get("confidence", 0)), 0), 1))
        tag_json = json.dumps([{"tag": k, "confidence": v} for k, v in seen.items()], ensure_ascii=False)
        classes.append((b, p, llm.sha(m), tag_json, out.get("episode") or None, model, served, pv, ts, rev))
        tags += [(b, p, k, v, served, pv) for k, v in seen.items()]
    db.executemany("INSERT INTO note_class VALUES (?,?,?,?,?,?,?,?,?,?)", classes)
    db.executemany("INSERT INTO note_tag VALUES (?,?,?,?,?,?)", tags)
    db.commit()
    stats = {"points_with_mark": len(points), "classified": len(classes), "tags": len(tags),
             "reviewed": sum(1 for c in classes if c[-1])}
    log_run(db, "notes", started, {"model": args.model, "prompt_version": TASK.prompt_version,
                                   "review": args.review and {"model": args.review_model, "band": REVIEW_BAND,
                                                              "prompt_version": REVIEW_TASK.prompt_version}}, stats)
    print(stats)
    write_report(db, data)


if __name__ == "__main__":
    setup_stdout()
    main()
