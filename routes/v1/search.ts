import { bangumi, type I18n, point } from "@schema";
import { defineHandler } from "void";
import { and, db, desc, eq, like, sql } from "void/db";
import { z } from "zod";
import { fold } from "../../src/fold";
import type { Card } from "../../src/series";

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
// 路径不在 /api 下，才能被 Void 的 ISR 按 q、adult 缓存（见 void.config.ts）。
// 成人向作品与其地标默认不返回，adult=1 时才包含（前端开关见 src/adult.ts）。
export const GET = defineHandler.withValidator({
  query: z.object({ q: z.string().trim().min(1).max(50), adult: z.literal("1").optional() }),
})(async (_c, { query }) => {
  const adult = query.adult === "1";
  const q = fold(query.q);
  if (!q) return { bangumis: [], points: [] };
  const pattern = `%${q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;
  const has = (col: Parameters<typeof like>[0]) => sql`${col} LIKE ${pattern} ESCAPE '\\'`;

  const [bangumis, points] = await Promise.all([searchBangumi(q, adult), searchPoints(q, has, adult)]);
  return { bangumis, points };
});

/**
 * 作品约 3 万行（Bangumi 全部动画，多数没有地标）：≥3 个字符走 FTS5 trigram 索引；更短的查询只能 LIKE 扫描。
 * 命中的作品按系列合并成卡片：系列显示系列代表作的名称与系列的地标总数。有地标的排前面，其余按 Bangumi 热度。
 */
async function searchBangumi(q: string, adult: boolean): Promise<Card[]> {
  const pattern = `%${q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;
  const match = [...q].length >= 3
    ? sql`b.rowid IN (SELECT rowid FROM bangumi_fts WHERE bangumi_fts MATCH ${`"${q}"`})`
    : sql`b.search LIKE ${pattern} ESCAPE '\\'`;
  const rows = await db.all<Omit<Card, "i18n" | "series"> & { i18n: string | null; series: number }>(sql`
    SELECT coalesce(b.series_id, b.id) AS id, b.series_works > 1 AS series, r.cn, r.title, r.en, r.i18n,
           b.cover, b.series_points AS pointCount, b.series_works AS works
    FROM bangumi b JOIN bangumi r ON r.id = coalesce(b.series_id, b.id)
    WHERE ${match} ${adult ? sql`` : sql`AND b.nsfw = 0`}
    ORDER BY b.series_points DESC, b.popularity DESC
    LIMIT 40`);
  const seen = new Set<number>();
  return rows
    .filter((r) => !seen.has(r.id) && seen.add(r.id))
    .slice(0, 20)
    .map((r) => ({ ...r, series: !!r.series, i18n: r.i18n ? JSON.parse(r.i18n) : null }));
}

/** 地标 5 万多行：≥3 个字符走 FTS5 trigram 索引，只读命中的行；更短的查询只能 LIKE 扫描 */
async function searchPoints(q: string, has: (col: Parameters<typeof like>[0]) => ReturnType<typeof sql>, adult: boolean): Promise<PointHit[]> {
  if ([...q].length >= 3) {
    // 原生 SQL 不经过 Drizzle 的 json 列解析，i18n 要自己 parse
    const rows = await db.all<Omit<PointHit, "i18n" | "bangumiI18n"> & { i18n: string | null; bangumiI18n: string | null }>(sql`
      SELECT p.bangumi_id AS bangumiId, p.id, p.name, p.cn, p.image, p.i18n,
             b.cn AS bangumiCn, b.title AS bangumiTitle, b.en AS bangumiEn, b.i18n AS bangumiI18n
      FROM point_fts JOIN point p ON p.rowid = point_fts.rowid JOIN bangumi b ON b.id = p.bangumi_id
      WHERE point_fts MATCH ${`"${q}"`} ${adult ? sql`` : sql`AND b.nsfw = 0`}
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
    .where(adult ? has(point.search) : and(has(point.search), eq(bangumi.nsfw, false)))
    .limit(30);
}
