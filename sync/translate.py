"""多语言翻译：给作品标题、地标名、地标备注补齐简体中文 zh-Hans、繁体中文 zh-Hant、日语 ja、英语 en。

来源优先级（都写进同一张 translation 表，按 source 区分，前端按语言挑选并回退）：
  anitabi  原始数据：point.name（语言由模型或文字判断）、point.cn、bangumi.title / cn / en
  bangumi  Bangumi API（先跑 sync.bgm）：name / name_cn / 英文名 / 罗马音（ja-Latn）
  llm      Claude 翻译：地标名、备注全部过一遍；作品标题只补前两者都缺的语言
  llm_review  --review 时用更强的模型复核 llm 行（作品标题全部、其余低置信度的），确认或改正，优先于 llm
  opencc   繁体由最优先的简体按 OpenCC 规则转换，不调用 LLM
同一语言已有 anitabi / bangumi 的人工数据时不再写 llm 行。原始字段不改。

  python -m sync.translate --dry-run
  python -m sync.translate --fields name --mode sync --limit 200
  python -m sync.translate --wait
  python -m sync.translate --wait --field-model title=claude-sonnet-5-5   # 作品标题用更强的模型
  python -m sync.translate --wait --field-model title=claude-sonnet-5-5 --review   # 再用 Opus 复核

LLM 步骤需要 `pip install anthropic`；繁体转换需要 `pip install opencc-python-reimplemented`（或 opencc），没装则跳过繁体。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from sync import llm
from sync.bgm import script_lang
from sync.enrich_common import add_data_arg, log_run, now_iso, open_db, setup_stdout
from sync.enrich_report import has, write_report

LANGS = ["zh-Hans", "zh-Hant", "ja", "en"]
LLM_LANGS = {"ja": "ja", "zh_hans": "zh-Hans", "en": "en"}  # 结构化输出字段 → 语言代码
SOURCE_RANK = {"anitabi": 0, "bangumi": 1, "llm_review": 2, "llm": 3}
MACHINE = {"llm", "llm_review", "opencc"}
REVIEW_MODEL = "claude-opus-5-5"
LANG_KEY = {v: k for k, v in LLM_LANGS.items()}
FIELDS = ["name", "mark", "title"]

# 取自 Anitabi 现有的人工中文名，只挑了译法规范的；英文按常见写法补
EXAMPLES = [
    ("東京タワー", "东京塔", "Tokyo Tower"), ("仙台駅", "仙台站", "Sendai Station"),
    ("西鏡島バス停", "西镜岛公交站", "Nishi-Kagashima Bus Stop"), ("宇治橋", "宇治桥", "Uji Bridge"),
    ("伊予農業高等学校", "伊予农业高中", "Iyo Agricultural High School"), ("許波多神社", "许波多神社", "Kohata Shrine"),
    ("梅林公園 すべり台", "梅林公园 滑梯", "Bairin Park Slide"), ("お台場海浜公園", "台场海滨公园", "Odaiba Seaside Park"),
    ("江ノ電鎌倉駅JR連絡口改札", "江之电镰仓站JR联络口检票口", "Enoden Kamakura Station JR Transfer Gate"),
    ("七里ヶ浜海岸駐車場", "七里滨海岸停车场", "Shichirigahama Beach Parking"),
    ("文京区立目白台一丁目遊び場", "文京区立目白台一丁目游乐场", "Mejirodai 1-chome Playground, Bunkyo"),
    ("デニーズ 藤沢北口店", "Denny's 藤泽北口店", "Denny's Fujisawa North Exit"),
]
EXAMPLE_TEXT = "\n".join(f"{a} → zh_hans: {b} / en: {c}" for a, b, c in EXAMPLES)

COMMON = """输出字段：
- source_lang：输入原文的语言（ja / zh-Hans / zh-Hant / en / ko / other）。只有汉字时按用字判断：日文用字（駅、沢、浜、気）或日文地名习惯判为 ja，简体字判为 zh-Hans。
- ja / zh_hans / en：译成日语、简体中文、英语的结果。原文本身就是该语言时原样返回原文。
- confidence：0 到 1，表示译文可靠程度；无法确定所指、生僻音译时给低分。"""

NAME_SYSTEM = f"""你在为动画圣地巡礼地图翻译地标名称。输入多为日文，也有中文、英文等。

译法约定：
- 简体中文：汉字地名、设施名按字转成简体（鎌倉→镰仓，沢→泽，浜→滨，駅→站，バス停→公交站，高等学校→高中/高等学校），不意译专有名词；
  假名专有名词有通行中文译名的用译名（東京タワー→东京塔），连锁店品牌保留常见写法（デニーズ→Denny's），否则通俗音译或保留原文。
- 英语：日本专有名词用赫本式罗马字，通用名词意译（駅→Station，神社→Shrine，公園→Park，交差点→Intersection，踏切→Railroad Crossing）。
- 日语：中文原名转成日本的写法（藤泽站南口→藤沢駅南口），外文名用日本通行的片假名或原文。
- 「〇丁目」「〇番線」等编号、名称里的集数前缀（「6話」「#03」「①」）原样保留。只做翻译，不添加说明。

{COMMON}

示例：
{EXAMPLE_TEXT}"""

MARK_SYSTEM = f"""你在为动画圣地巡礼地图翻译地标备注。备注是巡礼者写的自由文本（中文、日文或英文），
内容常是集数、场景说明、拍摄位置提示、交通与注意事项。

- 忠实翻译，保持原有的分行、集数标记（「11話」「#05」「OP」）、数字、价格、电话、时间；不增删内容，不加解释。
- 专有名词（地名、设施、角色名）用该语言的通行写法；拿不准的保留原文。
- 原文只有集数标记或符号（如「#06」「OP」）时三种语言都原样返回。

{COMMON}"""

TITLE_SYSTEM = """你在为动画圣地巡礼地图补全作品标题的多语言版本。输入是一部作品已知的标题（原名 title、中文 cn、英文 en 中的部分）和类别。

- 有官方或通行译名时用官方 / 通行译名（中文以中国大陆通行译名为准，英文用官方英文标题或英语圈通行名）；没有时再翻译。
- ja：日文原标题；原作不是日本作品时给日本通行的标题。
- 已知的字段原样返回，不要改写。
- confidence：0 到 1；不确定是不是官方译名、只是自己翻译时给 0.6 以下。"""

STRUCT = {"ja": {"type": "string"}, "zh_hans": {"type": "string"}, "en": {"type": "string"},
          "confidence": {"type": "number"}}
SOURCE_LANG = {"source_lang": {"type": "string", "enum": ["ja", "zh-Hans", "zh-Hant", "en", "ko", "other"]}}

REVIEW_SYSTEM = """你是动画圣地巡礼地图的多语言审校。每条输入是一个条目：field 是类型（title 作品标题、name 地标名、mark 地标备注），
original 是人工数据（按语言列出原文和已有的人工译名），machine 是待审校的机器翻译（键为 ja / zh_hans / en）。

逐条检查 machine 里的译文：误译、漏译或增添内容、专有名词和官方译名错误（作品标题优先用官方或通行的中文、英文名）、
译成了错误的语言或繁简混用、日文写法不自然。
- verdict：全部正确为 ok，有任何修改为 fixed。
- ja / zh_hans / en：最终译文。只填 machine 里出现的键，其余给空字符串；没有问题的原样返回。
- 不确定官方名称时不要编造：作品没有官方英文名时用通行的罗马字标题；地名用赫本式罗马字加英文通用名。
- 备注只改错误，不润色、不增删内容，保留集数标记、数字、分行。
- confidence：0 到 1，对最终译文的把握。"""

REVIEW_TASK = llm.Task("translation_review", "v1", REVIEW_SYSTEM,
                       {"verdict": {"type": "string", "enum": ["ok", "fixed"]}, **STRUCT}, chunk_size=25, chunk_chars=6000)

TASKS = {
    "name": llm.Task("point_name_i18n", "v1", NAME_SYSTEM, {**SOURCE_LANG, **STRUCT}, chunk_size=60),
    "mark": llm.Task("point_mark_i18n", "v1", MARK_SYSTEM, {**SOURCE_LANG, **STRUCT}, chunk_size=20, chunk_chars=2500),
    "title": llm.Task("bangumi_title_i18n", "v1", TITLE_SYSTEM, STRUCT, chunk_size=30),
}

SCHEMA = """
DROP TABLE IF EXISTS translation;
CREATE TABLE translation (
  entity TEXT NOT NULL,         -- bangumi / point
  entity_id TEXT NOT NULL,      -- bangumi: "<id>"；point: "<bangumi_id>:<point_id>"
  field TEXT NOT NULL,          -- title / name / mark
  lang TEXT NOT NULL,           -- zh-Hans / zh-Hant / ja / en；原文语言不在其中时如实记录（ko、und），罗马音为 ja-Latn
  text TEXT NOT NULL,
  source TEXT NOT NULL,         -- anitabi / bangumi / llm / llm_review / opencc
  machine_translated INTEGER NOT NULL,  -- llm、llm_review、opencc 为 1
  confidence REAL,              -- llm：译文可靠度；anitabi 原文：语言判断的把握
  model TEXT, prompt_version TEXT,
  derived_from TEXT,            -- opencc：转换自哪一行（如 "zh-Hans/llm"）；llm_review："llm:ok" 确认无误 / "llm:fixed" 已改正
  created_at TEXT,
  PRIMARY KEY (entity, entity_id, field, lang, source)
);
CREATE INDEX translation_entity ON translation (entity, entity_id, field);
"""


# 日文里不用的简体字（地名里常见的）；只有汉字的文本含这些字就判为简体中文
SIMPLIFIED = set(
    "东县泽滨镰岛冈广叶枥爱关长饭户涩马绳宫樱丰荣汤驿桥边龙泷须贺鸟绫织纪庆应乐兰门间阳乡发凤儿岁读访诹调圆尔乌鸭丽兴"
    "带齐斋济气时实盐仓贝钏网纹馆胜鹤库惠绘经结线练续终组细红纳纲缘总级绿统濑顺预领头风飞驹骏鱼鸣鹰陆达镇罗军车轮艺龟"
    "摄滩铫鹭栉灵莲苇觉阁营对涉鸠务业观赖伞吴杂凑历让浊训骑钟银铁锦阶际隐难韩页题颜冲热远霸势诸见灶穗浓宁闻场园楼过这"
    "们说话东车站厅馆")


def guess_lang(text: str) -> tuple[str, float]:
    """没有模型判断时按文字猜原文语言。只有汉字时：含简体字判为 zh-Hans，否则多半是日文地名，但把握不大。"""
    lang = script_lang(text)
    if lang == "ja" and SIMPLIFIED & set(text):  # 中文备注里夹着日文店名、台词：假名占比低就算中文
        kana = len(re.findall(r"[\u3040-\u30ff]", text))
        if kana < 0.3 * len(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", text)):
            return "zh-Hans", 0.7
    if lang == "cjk":
        return ("zh-Hans", 0.8) if SIMPLIFIED & set(text) else ("ja", 0.6)
    return {"ja": ("ja", 1.0), "ko": ("ko", 1.0)}.get(lang, ("und", 0.0))


class Rows:
    def __init__(self):
        self.rows: dict[tuple, tuple] = {}
        self.by_entity: dict[tuple, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))  # → {lang: {source}}
        self.ts = now_iso()

    def add(self, entity, eid, field, lang, text, source, conf=None, pv=None, derived=None, served=None):
        text = (text or "").strip()
        key = (entity, str(eid), field, lang, source)
        if not text or key in self.rows:
            return
        mt = int(source in MACHINE)
        self.rows[key] = (*key[:4], text, source, mt, conf, served, pv, derived, self.ts)
        self.by_entity[key[:3]][lang].add(source)

    def human_langs(self, entity, eid, field) -> set[str]:
        return {lang for lang, srcs in self.by_entity[(entity, str(eid), field)].items() if srcs & {"anitabi", "bangumi"}}

    def add_llm(self, entity, eid, field, result, pv, skip_lang=None):
        if result is None:
            return
        out, served = result
        have = self.human_langs(entity, eid, field)
        conf = min(max(float(out.get("confidence", 0)), 0), 1)
        for key, lang in LLM_LANGS.items():
            if lang != skip_lang and lang not in have:
                self.add(entity, eid, field, lang, out.get(key), "llm", conf, pv, served=served)

    def review_payloads(self, below: float) -> dict[str, list[tuple]]:
        """待复核的条目：作品标题全部复核，其余只复核 llm 置信度低于 below 的。返回 {输入 JSON: [条目, …]}（同内容去重）。"""
        out = defaultdict(list)
        for ent, langs in self.by_entity.items():
            mt = {lang: self.rows[(*ent, lang, "llm")] for lang, srcs in langs.items() if "llm" in srcs}
            if not mt or (ent[0] != "bangumi" and min(r[7] for r in mt.values()) >= below):
                continue
            human = {lang: self.rows[(*ent, lang, min(srcs & {"anitabi", "bangumi"}, key=SOURCE_RANK.__getitem__))][4]
                     for lang, srcs in langs.items() if srcs & {"anitabi", "bangumi"}}
            payload = {"field": ent[2], "original": human, "machine": {LANG_KEY[lang]: r[4] for lang, r in mt.items()}}
            out[json.dumps(payload, ensure_ascii=False, sort_keys=True)].append(ent)
        return out

    def add_review(self, ent, payload: str, result, pv) -> str | None:
        if result is None:
            return None
        out, served = result
        conf = min(max(float(out.get("confidence", 0)), 0), 1)
        verdict = "fixed" if out.get("verdict") == "fixed" else "ok"
        for key, old in json.loads(payload)["machine"].items():
            new = (out.get(key) or "").strip() or old
            self.add(*ent, LLM_LANGS[key], new, "llm_review", conf, REVIEW_TASK.prompt_version,
                     f"llm:{'fixed' if new != old else 'ok'}", served)
        return verdict

    def add_opencc(self, convert, config: str):
        for ent, langs in list(self.by_entity.items()):
            if "zh-Hant" in langs or "zh-Hans" not in langs:
                continue
            src = min(langs["zh-Hans"], key=SOURCE_RANK.__getitem__)
            r = self.rows[(*ent, "zh-Hans", src)]
            self.add(*ent, "zh-Hant", convert(r[4]), "opencc", r[7], config, f"zh-Hans/{src}")


def opencc_converter(config: str):
    try:
        import opencc
    except ImportError:
        print("没装 OpenCC（pip install opencc-python-reimplemented），跳过繁体转换")
        return None
    try:
        return opencc.OpenCC(config).convert
    except Exception:  # 官方 opencc 包的旧版本需要带 .json 的配置名
        return opencc.OpenCC(f"{config}.json").convert


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_data_arg(ap)
    ap.add_argument("--fields", default=",".join(FIELDS), help="要跑 LLM 的字段，逗号分隔：name,mark,title")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--field-model", action="append", default=[], metavar="FIELD=MODEL",
                    help="某个字段改用别的模型，可重复，如 --field-model title=claude-sonnet-5-5")
    ap.add_argument("--mode", choices=["batch", "sync"], default="batch")
    ap.add_argument("--limit", type=int, help="每个字段最多请求多少条不同文本（试跑用）")
    ap.add_argument("--wait", action="store_true", help="提交批次后轮询直到结束")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--review", action="store_true",
                    help=f"用更强的模型复核机器翻译：作品标题全部、其余置信度低于 --review-below 的（默认 {REVIEW_MODEL}）")
    ap.add_argument("--review-model", default=REVIEW_MODEL)
    ap.add_argument("--review-below", type=float, default=0.7)
    ap.add_argument("--opencc-config", default="s2twp", help="简→繁转换配置：s2twp（台湾用字与用词，默认）/ s2t / s2tw / s2hk")
    args = ap.parse_args()
    fields = [f for f in args.fields.split(",") if f]
    data = Path(args.data)
    db = open_db(data)
    started = now_iso()
    models = {f: args.model for f in FIELDS} | dict(fm.split("=", 1) for fm in args.field_model)
    opts = dict(mode=args.mode, dry_run=args.dry_run, limit=args.limit, wait=args.wait)
    run = lambda f, texts: llm.run(db, TASKS[f], texts, model=models[f], **opts) if f in fields else {}  # noqa: E731

    points = [(f"{b}:{p}", llm.clean_text(n or ""), cn, llm.clean_text(m or "")) for b, p, n, cn, m in db.execute(
        """SELECT p.bangumi_id, p.id, p.name, p.cn, p.mark FROM src.point p JOIN src.bangumi b ON b.id = p.bangumi_id
           WHERE b.deleted = 0""")]
    names = run("name", [n for _, n, _, _ in points])
    marks = run("mark", [m for _, _, _, m in points])

    R = Rows()
    for eid, name, cn, mark in points:
        r = names.get(llm.sha(name)) if name else None
        lang, conf = (r[0]["source_lang"], 1.0) if r and r[0].get("source_lang") else guess_lang(name)
        R.add("point", eid, "name", "zh-Hans", cn, "anitabi", 1.0)  # 人工中文名优先于按原名判断出的中文
        R.add("point", eid, "name", lang, name, "anitabi", conf)
        R.add_llm("point", eid, "name", r, TASKS["name"].prompt_version, skip_lang=lang)
        if mark:
            r = marks.get(llm.sha(mark))
            lang, conf = (r[0]["source_lang"], 1.0) if r and r[0].get("source_lang") else guess_lang(mark)
            R.add("point", eid, "mark", lang, mark, "anitabi", conf)
            R.add_llm("point", eid, "mark", r, TASKS["mark"].prompt_version, skip_lang=lang)

    bgm = {}
    if has(db, "bangumi_meta"):
        bgm = {r[0]: r[1:] for r in db.execute(
            "SELECT bangumi_id, name, name_cn, title_en, title_romaji FROM bangumi_meta WHERE status = 200")}
    else:
        print("没有 bangumi_meta，作品标题只用 Anitabi 数据（先跑 pnpm enrich:bgm）")
    works = db.execute("SELECT id, title, cn, en, cat FROM src.bangumi WHERE deleted = 0 ORDER BY id").fetchall()
    for bid, title, cn, en, _ in works:
        lang, conf = guess_lang(title or "")
        R.add("bangumi", bid, "title", "zh-Hans", cn, "anitabi", 1.0)
        R.add("bangumi", bid, "title", lang if lang != "und" else "en" if title == en else "und", title, "anitabi", conf)
        R.add("bangumi", bid, "title", "en", en, "anitabi", 1.0)
        if bid in bgm:
            name, name_cn, title_en, romaji = bgm[bid]
            if name and guess_lang(name)[0] == "ja":
                R.add("bangumi", bid, "title", "ja", name, "bangumi", guess_lang(name)[1])
            R.add("bangumi", bid, "title", "zh-Hans", name_cn, "bangumi", 1.0)
            R.add("bangumi", bid, "title", "en", title_en, "bangumi", 1.0)
            R.add("bangumi", bid, "title", "ja-Latn", romaji, "bangumi", 1.0)
    # 作品标题只对仍缺语言的作品调用 LLM；输入带上已知标题作为上下文
    missing = {bid: json.dumps({"title": t, "cn": c, "en": e, "category": cat}, ensure_ascii=False)
               for bid, t, c, e, cat in works
               if not {"ja", "zh-Hans", "en"} <= R.human_langs("bangumi", bid, "title")}
    titles = run("title", list(missing.values()))
    for bid, text in missing.items():
        R.add_llm("bangumi", bid, "title", titles.get(llm.sha(text)), TASKS["title"].prompt_version)
    reviews = {}
    if args.review:
        payloads = R.review_payloads(args.review_below)
        results = llm.run(db, REVIEW_TASK, list(payloads), model=args.review_model, **opts)
        for payload, ents in payloads.items():
            for ent in ents:
                v = R.add_review(ent, payload, results.get(llm.sha(payload)), REVIEW_TASK.prompt_version)
                if v:
                    reviews[v] = reviews.get(v, 0) + 1
        print(f"复核：{sum(len(e) for e in payloads.values())} 个条目（{len(payloads)} 条不同内容），结果 {reviews}")
    if args.dry_run:
        print(f"作品标题缺语言、需要 LLM 补的：{len(missing)} 部")
        return

    convert = opencc_converter(args.opencc_config)
    if convert:
        R.add_opencc(convert, args.opencc_config)
    db.executescript(SCHEMA)
    db.executemany(f"INSERT INTO translation VALUES ({','.join('?' * 12)})", list(R.rows.values()))
    db.commit()
    by = defaultdict(int)
    for k in R.rows:
        by[f"{k[0]}.{k[2]}/{k[3]}/{k[4]}"] += 1
    stats = {"rows": len(R.rows), "reviews": reviews, "by": dict(sorted(by.items()))}
    log_run(db, "translate", started, {"models": models, "fields": fields, "opencc": args.opencc_config,
                                       "prompt_versions": {f: TASKS[f].prompt_version for f in fields},
                                       "review": args.review and {"model": args.review_model, "below": args.review_below,
                                                                  "prompt_version": REVIEW_TASK.prompt_version}}, stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    write_report(db, data)


if __name__ == "__main__":
    setup_stdout()
    main()
