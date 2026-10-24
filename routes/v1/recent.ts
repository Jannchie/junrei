import { defineHandler } from "void";
import { z } from "zod";
import { listRecent } from "../../src/server/bangumi";

// 全站最近更新的地标，一页 RECENT_PAGE 条；offset 翻页，adult=1 时包含成人向作品的地标（同 /v1/search）
export const GET = defineHandler.withValidator({
  query: z.object({ offset: z.coerce.number().int().min(0).max(100000).default(0), adult: z.literal("1").optional() }),
})(async (_c, { query }) => ({ points: await listRecent(query.offset, query.adult === "1") }));
