import { defineHandler } from "void";
import { getBangumi } from "../../../src/server/bangumi";
import { bangumiMarkdown, markdownResponse } from "../../../src/server/markdown";
import { idParam } from "../../../src/server/pages";

// /md/b/:id：作品页的 Markdown 版本，给 LLM 读
export const GET = defineHandler(async (c) => {
  const id = idParam(c);
  const detail = id ? await getBangumi(id) : null;
  if (!detail) return c.notFound();
  return markdownResponse(bangumiMarkdown(detail));
});
