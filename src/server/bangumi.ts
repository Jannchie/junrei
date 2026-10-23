// 作品查询，供 /v1 API、页面 loader、sitemap 与面向 LLM 的 Markdown 共用
import { bangumi, point } from "@schema";
import { and, asc, db, desc, eq, gt, inArray, sql } from "void/db";

type SQL = ReturnType<typeof sql>;
import { type Card, type Group, groupOf, missingDetails } from "../series";

export const SITE = "https://junrei.jannchie.com";

const POINT_FIELDS = {
  bangumiId: point.bangumiId,
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
};
const SERIES_FIELDS = { id: bangumi.id, cn: bangumi.cn, title: bangumi.title, en: bangumi.en, cat: bangumi.cat, pointCount: bangumi.pointCount, airDate: bangumi.airDate, i18n: bangumi.i18n, nsfw: bangumi.nsfw, cover: bangumi.cover };

/** 若干部作品的详情（作品、地标、所在系列的作品列表），所有查询一轮并行发出 */
async function getDetails(ids: number[]) {
  const [infos, points, series] = await Promise.all([
    db.select().from(bangumi).where(inArray(bangumi.id, ids)),
    db.select(POINT_FIELDS).from(point).where(inArray(point.bangumiId, ids)).orderBy(asc(point.priority), asc(point.id)),
    db
      .select({ ...SERIES_FIELDS, seriesId: bangumi.seriesId })
      .from(bangumi)
      .where(sql`${bangumi.seriesId} IN (SELECT series_id FROM bangumi WHERE id IN ${ids})`)
      .orderBy(sql`${bangumi.airDate} IS NULL`, asc(bangumi.airDate), asc(bangumi.id)),
  ]);
  return infos.map((info) => ({
    ...info,
    points: points.filter((p) => p.bangumiId === info.id).map(({ bangumiId: _b, ...p }) => p),
    series: info.seriesId ? series.filter((w) => w.seriesId === info.seriesId).map(({ seriesId: _s, ...w }) => w) : [],
  }));
}

export async function getBangumi(id: number) {
  const [d] = await getDetails([id]);
  return d ?? null;
}

export type BangumiDetail = NonNullable<Awaited<ReturnType<typeof getBangumi>>>;

/**
 * 页面用的系列数据：all 为 true（系列页）时加载系列里所有有地标的作品；否则（作品页）只带这一部，其余在浏览器里按需加载。
 */
export async function getGroup(id: number, all: boolean): Promise<Group | null> {
  const d = await getBangumi(id);
  if (!d) return null;
  const group = groupOf(d);
  const rest = all ? missingDetails(group) : [];
  if (rest.length) group.details.push(...(await getDetails(rest)));
  return group;
}

type CardRow = Omit<Card, "i18n" | "series"> & { i18n: string | null; series: number };

/**
 * 作品按系列合并成卡片（首页热门、搜索结果共用）：名称取系列代表作，封面取系列里地标最多的那部，地标数是系列总数。
 * where 作用在系列里的各部作品（别名 b）上
 */
export async function listCardsWhere(where: SQL, orderBy: SQL, limit: number): Promise<Card[]> {
  const rows = await db.all<CardRow>(sql`
    SELECT coalesce(b.series_id, b.id) AS id, b.series_works > 1 AS series, r.cn, r.title, r.en, r.i18n,
           b.cover, b.series_points AS pointCount, b.series_works AS works, max(b.point_count) AS top
    FROM bangumi b JOIN bangumi r ON r.id = coalesce(b.series_id, b.id)
    WHERE ${where}
    GROUP BY coalesce(b.series_id, b.id)
    ORDER BY ${orderBy}
    LIMIT ${limit}`);
  return rows.map(({ top: _top, ...r }: CardRow & { top?: number }) => ({ ...r, series: !!r.series, i18n: r.i18n ? JSON.parse(r.i18n) : null }));
}

/** 首页的热门：按系列地标总数排序；不含成人向作品 */
export const listCards = (limit: number) => listCardsWhere(sql`b.point_count > 0 AND b.nsfw = 0`, sql`b.series_points DESC`, limit);

/** 有地标、不止一部作品的系列（sitemap 列出系列页用）；代表作是成人向的不列 */
export async function listSeriesKeys(): Promise<number[]> {
  const rows = await db
    .selectDistinct({ id: bangumi.seriesId })
    .from(bangumi)
    .where(sql`${bangumi.pointCount} > 0 AND ${bangumi.seriesWorks} > 1 AND ${bangumi.nsfw} = 0`);
  return rows.map((r) => r.id!).filter(Boolean);
}

/** 有地标的一般向作品，按地标数排序；limit 省略即全部（sitemap、Markdown 索引用）。没有地标的作品只能搜到 */
export function listBangumi(limit?: number) {
  const q = db
    .select({ id: bangumi.id, cn: bangumi.cn, title: bangumi.title, en: bangumi.en, city: bangumi.city, cover: bangumi.cover, pointCount: bangumi.pointCount, i18n: bangumi.i18n })
    .from(bangumi)
    .where(and(gt(bangumi.pointCount, 0), eq(bangumi.nsfw, false)))
    .orderBy(desc(bangumi.pointCount), asc(bangumi.id));
  return limit ? q.limit(limit) : q;
}

export const displayName = (b: { cn: string | null; title: string | null }) => b.cn ?? b.title ?? "";
