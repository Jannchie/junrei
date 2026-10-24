// 面向 LLM 的 Markdown 版本（llms.txt 约定）：纯文本、无脚本，链接都是绝对地址
import type { CreditName, Credits } from "@schema";
import { formatDate, formatEpisode, formatTime } from "../format";
import { type BangumiDetail, displayName, SITE } from "./bangumi";

export const markdownResponse = (body: string) =>
  new Response(body, { headers: { "Content-Type": "text/markdown; charset=utf-8" } });

const ROLE: Record<Credits["staff"][number]["r"], string> = {
  original: "原作", director: "监督", composition: "系列构成", studio: "动画制作", originalDesign: "人物原案", characterDesign: "人物设定", music: "音乐",
};
/** 人名：中文名（原名），没有中文名就只写原名 */
const nameOf = (e: CreditName) => (e.cn && e.n && e.cn !== e.n ? `${e.cn}（${e.n}）` : (e.cn ?? e.n ?? ""));

const esc = (s: string) => s.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");

function scene(ep: string | null, s: number | null) {
  return [ep && formatEpisode(ep), s && formatTime(s)].filter(Boolean).join(" ");
}

export function bangumiMarkdown(d: BangumiDetail) {
  const name = displayName(d);
  const lines = [
    `# ${name} 圣地巡礼取景地`,
    "",
    [
      d.title && d.title !== name ? `- 原名：${d.title}` : null,
      d.en ? `- 英文名：${d.en}` : null,
      d.cat ? `- 类型：${d.cat}` : null,
      d.city ? `- 主要城市：${d.city}` : null,
      ...(d.credits?.staff ?? []).map((s) => `- ${ROLE[s.r]}：${s.p.map(nameOf).join("、")}`),
      d.credits?.cast.length ? `- 主要角色：${d.credits.cast.map((c) => `${nameOf(c)}${c.cv?.length ? `（CV ${c.cv.map(nameOf).join("、")}）` : ""}`).join("、")}` : null,
      `- 取景地数量：${d.pointCount}`,
      `- 地图：${SITE}/b/${d.id}`,
      `- Bangumi：https://bgm.tv/subject/${d.id}`,
    ]
      .filter(Boolean)
      .join("\n"),
    "",
    "## 取景地",
    "",
    "名称链接到该取景地的单独页面（含截图与地图），引用某个地点时请用这个链接。",
    "",
    "| 名称 | 原名 | English | 场景 | 坐标（纬度, 经度） | 备注 | 来源 | 更新 |",
    "|---|---|---|---|---|---|---|---|",
    ...d.points.map((p) =>
      `| [${esc(p.cn ?? p.name ?? p.id)}](${SITE}/b/${d.id}?p=${encodeURIComponent(p.id)}) | ${esc(p.cn && p.name ? p.name : "")} | ${esc(p.i18n?.name?.en ?? "")} | ${scene(p.ep, p.s)} | ${p.lat.toFixed(5)}, ${p.lng.toFixed(5)} | ${esc(p.mark ?? "")} | ${p.sourceUrl ? `[${esc(p.source ?? "link")}](${p.sourceUrl})` : ""} | ${p.updated ? formatDate(p.updated) : ""} |`,
    ),
    "",
    "数据主要来自 Anitabi（https://www.anitabi.cn/）社区投稿，另有探访博客、Anime Pilgrimage、Anime Tourism 等来源，每个地标的出处见「来源」列；截图采用 CC BY-NC-SA 4.0，引用时请署名来源。",
    "",
  ];
  return lines.join("\n");
}
