// 搜索用的文本「折叠」，规则与 sync/fold.py 一致：
// NFKC → 小写 → 汉字按映射表归一到简体 → 片假名转平假名 → 去掉空白、标点与符号
// 这样「聖地巡禮」「圣地巡礼」「ｾｲﾁ」「せいち」之类不同写法能互相搜到。
import charMap from "../data/fold.json";

const MAP = charMap as Record<string, string>;
const DROP = /[\p{P}\p{S}\p{Z}\p{C}]/u;

export function fold(text: string): string {
  let out = "";
  for (let c of text.normalize("NFKC").toLowerCase()) {
    c = MAP[c] ?? c;
    const o = c.codePointAt(0)!;
    if (o >= 0x30a1 && o <= 0x30f6) c = String.fromCodePoint(o - 0x60); // 片假名 → 平假名
    if (!DROP.test(c)) out += c;
  }
  return out;
}
