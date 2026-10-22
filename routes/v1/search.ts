import { bangumi, type I18n, point } from "@schema";
import { defineHandler } from "void";
import { db, desc, eq, like, sql } from "void/db";
import { z } from "zod";
import { fold } from "../../src/fold";

interface PointHit {
  bangumiId: number;
  id: string;
  name: string | null;
  cn: string | null;
  image: string | null;
  bangumiCn: string | null;
  bangumiTitle: string | null;
  bangumiEn: string | null;
  i18n: I18n | null;
  bangumiI18n: I18n | null;
}

// 全语种：查询词与 search 列都经过同一套折叠（简繁、平片假名、全半角、大小写、标点都归一）。
// 路径不在 /api 下，才能被 Void 的 ISR 按 q 缓存（见 void.config.ts）。
export const GET = defineHandler.withValidator({
  query: z.object({ q: z.string().trim().min(1).max(50) }),
})(async (_c, { query }) => {
  const q = fold(query.q);
  if (!q) return { bangumis: [], points: [] };
  const pattern = `%${q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;
  const has = (col: Parameters<typeof like>[0]) => sql`${col} LIKE ${pattern} ESCAPE '\\'`;

  const [bangumis, points] = await Promise.all([
    // 作品只有一千多行，直接扫（网页端在浏览器里做模糊搜索，这里给 API 与 LLM 用）
    db
      .select({ id: bangumi.id, cn: bangumi.cn, title: bangumi.title, en: bangumi.en, cover: bangumi.cover, pointCount: bangumi.pointCount, i18n: bangumi.i18n })
      .from(bangumi)
      .where(has(bangumi.search))
      .orderBy(desc(bangumi.pointCount))
      .limit(20),
    searchPoints(q, has),
  ]);
  return { bangumis, points };
});

/** 地标 5 万多行：≥3 个字符走 FTS5 trigram 索引，只读命中的行；更短的查询只能 LIKE 扫描 */
async function searchPoints(q: string, has: (col: Parameters<typeof like>[0]) => ReturnType<typeof sql>): Promise<PointHit[]> {
  if ([...q].length >= 3) {
    // 原生 SQL 不经过 Drizzle 的 json 列解析，i18n 要自己 parse
    const rows = await db.all<Omit<PointHit, "i18n" | "bangumiI18n"> & { i18n: string | null; bangumiI18n: string | null }>(sql`
      SELECT p.bangumi_id AS bangumiId, p.id, p.name, p.cn, p.image, p.i18n,
             b.cn AS bangumiCn, b.title AS bangumiTitle, b.en AS bangumiEn, b.i18n AS bangumiI18n
      FROM point_fts JOIN point p ON p.rowid = point_fts.rowid JOIN bangumi b ON b.id = p.bangumi_id
      WHERE point_fts MATCH ${`"${q}"`}
      LIMIT 30`);
    const parse = (s: string | null): I18n | null => (s ? JSON.parse(s) : null);
    return rows.map((r) => ({ ...r, i18n: parse(r.i18n), bangumiI18n: parse(r.bangumiI18n) }));
  }
  return db
    .select({
      bangumiId: point.bangumiId,
      id: point.id,
      name: point.name,
      cn: point.cn,
      image: point.image,
      bangumiCn: bangumi.cn,
      bangumiTitle: bangumi.title,
      bangumiEn: bangumi.en,
      i18n: point.i18n,
      bangumiI18n: bangumi.i18n,
    })
    .from(point)
    .innerJoin(bangumi, eq(bangumi.id, point.bangumiId))
    .where(has(point.search))
    .limit(30);
}
