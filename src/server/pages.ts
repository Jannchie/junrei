// 页面 loader：简体中文页面没有语言前缀（/b/:id），其他语言带前缀（/ja/b/:id），同一套逻辑
import { defineHandler, defineHead, type InferProps } from "void";
import { type Locale, localeFromSegment } from "../i18n";
import { getGroup, listCards, listRecent } from "./bangumi";
import { bangumiHead, homeHead, recentHead } from "./seo";

type Params = { req: { param(name: string): string | undefined } };

/** 路由里没有 :lang 段就是简体中文；有但不认识的语言返回 null（404） */
function localeOf(c: Params): Locale | null {
  const seg = c.req.param("lang");
  return seg === undefined ? "zh-Hans" : localeFromSegment(seg);
}

/** 路径里的正整数 id，否则 null */
export function idParam(c: Params): number | null {
  const id = Number(c.req.param("id"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** 首页：服务端渲染概览与热门作品（真实链接，爬虫能走到每个作品页）；地图在浏览器里挂载 */
export const homeLoader = defineHandler(async (c) => {
  const lang = localeOf(c);
  if (!lang) return c.notFound();
  return { popular: await listCards(24), lang };
});
export const homePageHead = defineHead<InferProps<typeof homeLoader>>((_c, { lang }) => homeHead(lang));

/**
 * 作品页（series 为 false，所在系列筛选到这一部）与系列页（series 为 true，系列里所有作品的地标合在一起）。
 * 服务端渲染作品与地标，供搜索引擎与 LLM 读取
 */
export const groupLoader = (series: boolean) =>
  defineHandler(async (c) => {
    const lang = localeOf(c);
    const id = idParam(c);
    const group = lang && id ? await getGroup(id, series) : null;
    if (!lang || !group) return c.notFound();
    return { group, filter: (series ? null : id) as number | null, lang };
  });
export const groupPageHead = defineHead<InferProps<ReturnType<typeof groupLoader>>>((_c, { group, filter, lang }) =>
  bangumiHead(lang, group, filter),
);

/** 最近更新：服务端渲染第一页（全站最近新增或改动的地标），其余在浏览器里翻页 */
export const recentLoader = defineHandler(async (c) => {
  const lang = localeOf(c);
  if (!lang) return c.notFound();
  return { recent: await listRecent(0, false), lang };
});
export const recentPageHead = defineHead<InferProps<typeof recentLoader>>((_c, { lang }) => recentHead(lang));
