// 作品查询，供 /v1 API、页面 loader、sitemap 与面向 LLM 的 Markdown 共用
import { bangumi, point } from "@schema";
import { asc, db, desc, eq, gt, sql } from "void/db";
import { type Card, type Group, groupOf, missingDetails } from "../series";

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
        source: point.source,
        sourceUrl: point.sourceUrl,
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

/**
 * 页面用的系列数据：all 为 true（系列页）时加载系列里所有有地标的作品；否则（作品页）只带这一部，其余在浏览器里按需加载。
 */
export async function getGroup(id: number, all: boolean): Promise<Group | null> {
  const d = await getBangumi(id);
  if (!d) return null;
  const group = groupOf(d);
  if (all) {
    const rest = await Promise.all(missingDetails(group).map(getBangumi));
    group.details.push(...rest.filter((x) => x != null));
  }
  return group;
}

/** 首页的热门：按系列合并（系列名取代表作，封面取地标最多的那部），按系列地标总数排序 */
export async function listCards(limit: number): Promise<Card[]> {
  const rows = await db.all<Omit<Card, "i18n" | "series"> & { i18n: string | null; series: number }>(sql`
    SELECT coalesce(b.series_id, b.id) AS id, b.series_works > 1 AS series, r.cn, r.title, r.en, r.i18n,
           b.cover, b.series_points AS pointCount, b.series_works AS works, max(b.point_count) AS top
    FROM bangumi b JOIN bangumi r ON r.id = coalesce(b.series_id, b.id)
    WHERE b.point_count > 0
    GROUP BY coalesce(b.series_id, b.id)
    ORDER BY b.series_points DESC
    LIMIT ${limit}`);
  return rows.map(({ top: _top, ...r }: typeof rows[number] & { top?: number }) => ({ ...r, series: !!r.series, i18n: r.i18n ? JSON.parse(r.i18n) : null }));
}

/** 有地标、不止一部作品的系列（sitemap 列出系列页用） */
export async function listSeriesKeys(): Promise<number[]> {
  const rows = await db
    .selectDistinct({ id: bangumi.seriesId })
    .from(bangumi)
    .where(sql`${bangumi.pointCount} > 0 AND ${bangumi.seriesWorks} > 1`);
  return rows.map((r) => r.id!).filter(Boolean);
}

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
