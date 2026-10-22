// 作品查询，供 /v1 API、页面 loader、sitemap 与面向 LLM 的 Markdown 共用
import { bangumi, point } from "@schema";
import { asc, db, desc, eq, gt, sql } from "void/db";

export const SITE = "https://junrei.jannchie.com";

export async function getBangumi(id: number) {
  const [[info], points] = await Promise.all([
    db.select().from(bangumi).where(eq(bangumi.id, id)),
    db
      .select({
        id: point.id,
        name: point.name,
        cn: point.cn,
        lat: point.lat,
        lng: point.lng,
        ep: point.ep,
        s: point.s,
        image: point.image,
        origin: point.origin,
        originLink: point.originLink,
        mark: point.mark,
        i18n: point.i18n,
      })
      .from(point)
      .where(eq(point.bangumiId, id))
      .orderBy(asc(point.priority), asc(point.id)),
  ]);
  if (!info) return null;
  const series = info.seriesId
    ? await db
        .select({ id: bangumi.id, cn: bangumi.cn, title: bangumi.title, en: bangumi.en, cat: bangumi.cat, pointCount: bangumi.pointCount, airDate: bangumi.airDate, i18n: bangumi.i18n })
        .from(bangumi)
        .where(eq(bangumi.seriesId, info.seriesId))
        .orderBy(sql`${bangumi.airDate} IS NULL`, asc(bangumi.airDate), asc(bangumi.id))
    : [];
  return { ...info, points, series };
}

export type BangumiDetail = NonNullable<Awaited<ReturnType<typeof getBangumi>>>;

/** 有地标的作品，按地标数排序；limit 省略即全部（sitemap、Markdown 索引用）。没有地标的作品只能搜到 */
export function listBangumi(limit?: number) {
  const q = db
    .select({ id: bangumi.id, cn: bangumi.cn, title: bangumi.title, en: bangumi.en, city: bangumi.city, cover: bangumi.cover, pointCount: bangumi.pointCount, i18n: bangumi.i18n })
    .from(bangumi)
    .where(gt(bangumi.pointCount, 0))
    .orderBy(desc(bangumi.pointCount), asc(bangumi.id));
  return limit ? q.limit(limit) : q;
}

export const displayName = (b: { cn: string | null; title: string | null }) => b.cn ?? b.title ?? "";
