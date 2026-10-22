import { bangumi, point } from "@schema";
import { defineHandler } from "void";
import { db, desc, eq, like, or, sql } from "void/db";
import { z } from "zod";

interface PointHit {
  bangumiId: number;
  id: string;
  name: string | null;
  cn: string | null;
  image: string | null;
  bangumiCn: string | null;
  bangumiTitle: string | null;
  bangumiEn: string | null;
}

// 路径不在 /api 下，才能被 Void 的 ISR 按 q 缓存（见 void.config.ts）
export const GET = defineHandler.withValidator({
  query: z.object({ q: z.string().trim().min(1).max(50) }),
})(async (_c, { query }) => {
  const q = query.q;
  const pattern = `%${q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;
  const has = (col: Parameters<typeof like>[0]) => sql`${col} LIKE ${pattern} ESCAPE '\\'`;

  const [bangumis, points] = await Promise.all([
    // 作品只有一千多行，直接扫
    db
      .select({
        id: bangumi.id,
        cn: bangumi.cn,
        title: bangumi.title,
        en: bangumi.en,
        cover: bangumi.cover,
        pointCount: bangumi.pointCount,
      })
      .from(bangumi)
      .where(or(has(bangumi.cn), has(bangumi.title), has(bangumi.en), has(bangumi.city)))
      .orderBy(desc(bangumi.pointCount))
      .limit(20),
    searchPoints(q, has),
  ]);
  return { bangumis, points };
});

/** 地标 5 万多行：≥3 个字符走 FTS5 trigram 索引，只读命中的行；更短的查询只能 LIKE 扫描 */
function searchPoints(q: string, has: (col: Parameters<typeof like>[0]) => ReturnType<typeof sql>) {
  if ([...q].length >= 3) {
    const phrase = `"${q.replace(/"/g, '""')}"`;
    return db.all<PointHit>(sql`
      SELECT p.bangumi_id AS bangumiId, p.id, p.name, p.cn, p.image,
             b.cn AS bangumiCn, b.title AS bangumiTitle, b.en AS bangumiEn
      FROM point_fts JOIN point p ON p.rowid = point_fts.rowid JOIN bangumi b ON b.id = p.bangumi_id
      WHERE point_fts MATCH ${phrase}
      LIMIT 30`);
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
    })
    .from(point)
    .innerJoin(bangumi, eq(bangumi.id, point.bangumiId))
    .where(or(has(point.name), has(point.cn)))
    .limit(30);
}
