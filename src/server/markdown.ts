// 面向 LLM 的 Markdown 版本（llms.txt 约定）：纯文本、无脚本，链接都是绝对地址
import { type BangumiDetail, displayName, SITE } from "./bangumi";

export const markdownResponse = (body: string) =>
  new Response(body, { headers: { "Content-Type": "text/markdown; charset=utf-8" } });

const esc = (s: string) => s.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");

function scene(ep: string | null, s: number | null) {
  const parts = [];
  if (ep) parts.push(/^\d+$/.test(ep) ? `EP${ep}` : ep);
  if (s) parts.push(`${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);
  return parts.join(" ");
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
      `- 取景地数量：${d.pointCount}`,
      `- 地图：${SITE}/b/${d.id}`,
      `- Bangumi：https://bgm.tv/subject/${d.id}`,
    ]
      .filter(Boolean)
      .join("\n"),
    "",
    "## 取景地",
    "",
    "| 名称 | 原名 | 场景 | 坐标（纬度, 经度） | 备注 |",
    "|---|---|---|---|---|",
    ...d.points.map((p) =>
      `| ${esc(p.cn ?? p.name ?? "")} | ${esc(p.cn && p.name ? p.name : "")} | ${scene(p.ep, p.s)} | ${p.lat.toFixed(5)}, ${p.lng.toFixed(5)} | ${esc(p.mark ?? "")} |`,
    ),
    "",
    "数据来自 Anitabi（https://www.anitabi.cn/）社区投稿；截图采用 CC BY-NC-SA 4.0，引用时请署名来源。",
    "",
  ];
  return lines.join("\n");
}
