import { defineHandler } from "void";
import { displayName, listBangumi, SITE } from "../../src/server/bangumi";
import { markdownResponse } from "../../src/server/markdown";

// /md：全部作品的 Markdown 索引，按取景地数量排序
export const GET = defineHandler(async () => {
  const rows = await listBangumi();
  const body = [
    "# junrei 作品索引",
    "",
    `共 ${rows.length} 部作品。每行链接到该作品取景地的 Markdown 页面。`,
    "",
    ...rows.map((b) => `- [${displayName(b)}](${SITE}/md/b/${b.id})${b.city ? ` · ${b.city}` : ""} · ${b.pointCount} 处`),
    "",
  ].join("\n");
  return markdownResponse(body);
});
