// 系列：同一系列的作品（TV 各季、剧场版、OVA…）作为一个整体浏览，默认显示全部地标，也可以筛选到某一部。
// 服务端渲染与浏览器共用这里的类型与组装逻辑。
import type { I18n } from "./i18n";
import type { BangumiDetail } from "./server/bangumi";

/** 系列里的一部作品（列表、切换条用） */
export type SeriesWork = BangumiDetail["series"][number];

/** 一个系列：key 是代表作 id（不在系列里的作品就是它自己）；details 是已加载的作品详情，按需补齐 */
export interface Group {
  key: number;
  works: SeriesWork[];
  details: BangumiDetail[];
}

/** 列表、地图上的地标，带上所属作品 */
export type ViewPoint = BangumiDetail["points"][number] & { bangumiId: number };

/** 面板显示的内容：筛选到某部作品时就是那部作品；「全部」时名称取系列代表作，地标合并 */
export type View = Omit<BangumiDetail, "points"> & {
  points: ViewPoint[];
  /** 系列 key */
  key: number;
  /** 当前筛选的作品；null 表示全部 */
  filter: number | null;
  /** Bangumi、Anitabi、KML 链接指向的作品：筛选时是它，全部时是地标最多的那部 */
  linkId: number;
};

/** 系列卡片（搜索结果、首页）：系列显示系列名与地标总数，单独的作品显示自己 */
export interface Card {
  id: number;
  series: boolean;
  cn: string | null;
  title: string | null;
  en: string | null;
  i18n: I18n | null;
  cover: string | null;
  pointCount: number;
  works: number;
}

/**
 * 不显示成人向时，系列里只留一般向作品（筛选中的那部除外）。整个系列都是成人向时原样返回，由页面决定是否先确认。
 */
export function visibleGroup(g: Group, adult: boolean, filter: number | null): Group {
  if (adult) return g;
  const works = g.works.filter((w) => !w.nsfw || w.id === filter);
  if (!works.some((w) => w.pointCount > 0 || w.id === filter) || works.length === g.works.length) return g;
  return { ...g, works, details: g.details.filter((d) => works.some((w) => w.id === d.id)) };
}

/** 打开这一屏需要先确认：筛选的作品是成人向，或系列里有地标的作品（单独一部时就是它自己）全是成人向 */
export function needsAdultGate(g: Group, filter: number | null): boolean {
  if (filter != null) return !!g.works.find((w) => w.id === filter)?.nsfw;
  const withPoints = g.works.filter((w) => w.pointCount > 0);
  return (withPoints.length ? withPoints : g.works).every((w) => w.nsfw);
}

export const groupKey = (d: Pick<BangumiDetail, "id" | "seriesId">) => d.seriesId ?? d.id;

/** 由一部作品的详情建立系列（只含它自己的详情，其余按需加载） */
export function groupOf(d: BangumiDetail): Group {
  const self: SeriesWork = { id: d.id, cn: d.cn, title: d.title, en: d.en, cat: d.cat, pointCount: d.pointCount, airDate: d.airDate, i18n: d.i18n, nsfw: d.nsfw, cover: d.cover };
  return { key: groupKey(d), works: d.series.length ? d.series : [self], details: [d] };
}

/** 「全部」需要加载的作品：有地标、还没加载的 */
export const missingDetails = (g: Group) => g.works.filter((w) => w.pointCount > 0 && !g.details.some((d) => d.id === w.id)).map((w) => w.id);

const tag = (d: BangumiDetail): ViewPoint[] => d.points.map((p) => ({ ...p, bangumiId: d.id }));

/** 视图的路径：系列「全部」是 /s/:系列，筛选到某部作品（或不在系列里的作品）是 /b/:作品 */
export const viewPath = (v: Pick<View, "filter" | "series" | "key" | "id">) =>
  v.filter == null && v.series.length > 1 ? `/s/${v.key}` : `/b/${v.id}`;

export function buildView(g: Group, filter: number | null): View | null {
  const single = g.works.length <= 1 ? g.details[0] : undefined;
  const pick = filter ?? single?.id;
  if (pick != null) {
    const d = g.details.find((x) => x.id === pick);
    return d ? { ...d, points: tag(d), key: g.key, filter: g.works.length > 1 ? pick : null, linkId: d.id } : null;
  }
  // 全部：作品按系列顺序，各自的地标按原顺序接起来
  const order = new Map(g.works.map((w, i) => [w.id, i]));
  const loaded = [...g.details].sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  const top = loaded.reduce((a, b) => (b.pointCount > a.pointCount ? b : a));
  const head = g.works.find((w) => w.id === g.key) ?? g.works[0];
  // 城市按系列第一部算：地标最多的那部可能是外地篇（如修学旅行去了京都）
  const home = loaded.find((d) => d.id === g.key && d.city) ?? top;
  return {
    ...top,
    id: g.key,
    cn: head.cn,
    title: head.title,
    en: head.en,
    city: home.city,
    i18n: { ...head.i18n, city: home.i18n?.city },
    cat: null,
    pointCount: loaded.reduce((n, d) => n + d.pointCount, 0),
    points: loaded.flatMap(tag),
    series: g.works,
    key: g.key,
    filter: null,
    linkId: top.id,
  };
}
