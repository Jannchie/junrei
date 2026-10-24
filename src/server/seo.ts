import type { CreditName, Credits } from "@schema";
import type { HeadDescriptor } from "void";
import { cityFor, type Locale, LOCALES, localNameFor, localePath, markFor, pickNameFor, spotNames, subNameFor, translate, workNames } from "../i18n";
import { formatEpisode, formatTime, imageUrl } from "../format";
import { type BangumiDetail, SITE } from "./bangumi";
import { buildView, type Group, needsAdultGate, viewPath, visibleGroup } from "../series";

/** 各语言的 Open Graph locale 与分享图 */
const OG_LOCALE: Record<Locale, string> = { "zh-Hans": "zh_CN", "zh-Hant": "zh_TW", ja: "ja_JP", en: "en_US" };
/** 加到主屏幕后图标下的名字（iOS），与清单的 short_name 一致 */
const APP_NAME: Record<Locale, string> = { "zh-Hans": "圣地巡礼", "zh-Hant": "聖地巡禮", ja: "聖地巡礼", en: "Pilgrimage" };
const ogImage = (locale: Locale) => `${SITE}/icons/og-${locale.toLowerCase()}.png`;

const HOME: Record<Locale, { title: string; description: string }> = {
  "zh-Hans": {
    title: "圣地巡礼地图 · 动画与游戏取景地",
    description: "在地图上浏览和搜索动画、游戏的取景地（圣地巡礼）：数千部作品、数万个地标，附截图、集数与时间点。",
  },
  "zh-Hant": {
    title: "聖地巡禮地圖 · 動畫與遊戲取景地",
    description: "在地圖上瀏覽和搜尋動畫、遊戲的取景地（聖地巡禮）：數千部作品、數萬個地標，附截圖、集數與時間點。",
  },
  ja: {
    title: "聖地巡礼マップ · アニメ・ゲームの舞台を地図で",
    description: "アニメやゲームの舞台（聖地）を地図で探せます。数千作品・数万か所のスポットを、場面写真・話数・時間とともに掲載。",
  },
  en: {
    title: "Anime Pilgrimage Map · Real places from anime and games",
    description: "Browse and search the real-world locations behind anime and games on a map: thousands of titles and tens of thousands of spots with screenshots, episodes and timestamps.",
  },
};

function bangumiDescription(locale: Locale, b: BangumiDetail, name: string, original: string | null, spots: string) {
  const n = b.pointCount;
  const d = { city: cityFor(locale, b) };
  switch (locale) {
    case "zh-Hans":
      return `${name}${original ? `（${original}）` : ""}的圣地巡礼地图${d.city ? `，主要位于${d.city}` : ""}，共 ${n} 个取景地${spots ? `，包括${spots}等` : ""}。`;
    case "zh-Hant":
      return `${name}${original ? `（${original}）` : ""}的聖地巡禮地圖${d.city ? `，主要位於${d.city}` : ""}，共 ${n} 個取景地${spots ? `，包括${spots}等` : ""}。`;
    case "ja":
      return `${name}の聖地巡礼マップ。${d.city ? `主に${d.city}、` : ""}全${n}か所の舞台${spots ? `（${spots}など）` : ""}を地図と場面写真で紹介。`;
    case "en":
      return `Anime pilgrimage map for ${name}${original ? ` (${original})` : ""}: ${n} real-world locations${d.city ? ` around ${d.city}` : ""}${spots ? `, including ${spots}` : ""}.`;
  }
}

/** 页面通用的 SEO head：语言、description、canonical、各语言互链、Open Graph、Twitter 卡片与 JSON-LD */
function siteHead(locale: Locale, path: string, o: { title: string; description: string; image?: string; jsonLd?: object; noindex?: boolean; markdown?: string }): HeadDescriptor {
  const url = SITE + localePath(locale, path);
  return {
    title: o.title,
    htmlAttrs: { lang: locale },
    meta: [
      { name: "description", content: o.description },
      { property: "og:type", content: "website" },
      { property: "og:site_name", content: translate(locale, "brand") },
      { property: "og:locale", content: OG_LOCALE[locale] },
      { property: "og:title", content: o.title },
      { property: "og:description", content: o.description },
      { property: "og:url", content: url },
      { property: "og:image", content: o.image ?? ogImage(locale) },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "apple-mobile-web-app-title", content: APP_NAME[locale] },
      ...(o.noindex ? [{ name: "robots", content: "noindex" }] : []),
    ],
    link: [
      { rel: "canonical", href: url },
      // 各语言各自的 PWA 清单（应用名、启动页）与地址栏搜索（scripts/gen-pwa.mts 生成）
      { rel: "manifest", href: `/manifest-${locale.toLowerCase()}.webmanifest` },
      { rel: "search", type: "application/opensearchdescription+xml", href: `/opensearch-${locale.toLowerCase()}.xml`, title: translate(locale, "brand") },
      // 同一页面的各语言版本互相指向，搜索引擎据此按用户语言展示
      ...LOCALES.map((l) => ({ rel: "alternate", hreflang: l, href: SITE + localePath(l, path) })),
      { rel: "alternate", hreflang: "x-default", href: SITE + localePath("zh-Hans", path) },
      // 给 LLM 读的 Markdown 版本（routes/md）
      ...(o.markdown ? [{ rel: "alternate", type: "text/markdown", href: SITE + o.markdown }] : []),
    ],
    // JSON 里的 "</" 要转义，避免提前结束 script 标签
    script: o.jsonLd ? [{ type: "application/ld+json", innerHTML: JSON.stringify(o.jsonLd).replace(/</g, "\\u003c") }] : [],
  };
}

export function homeHead(locale: Locale): HeadDescriptor {
  const { title, description } = HOME[locale];
  return siteHead(locale, "/", {
    title,
    description,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: translate(locale, "brand"),
      alternateName: ["圣地巡礼地图", "聖地巡禮地圖", "聖地巡礼マップ", "Anime Pilgrimage Map", "junrei"],
      url: SITE + localePath(locale, "/"),
      inLanguage: locale,
      potentialAction: {
        "@type": "SearchAction",
        target: { "@type": "EntryPoint", urlTemplate: `${SITE}${localePath(locale, "/")}?q={search_term_string}` },
        "query-input": "required name=search_term_string",
      },
    },
  });
}

const RECENT: Record<Locale, { title: string; description: string }> = {
  "zh-Hans": { title: "最近更新的取景地 · 圣地巡礼地图", description: "圣地巡礼地图最近新增和更新的动画、游戏取景地，按更新日期排列。" },
  "zh-Hant": { title: "最近更新的取景地 · 聖地巡禮地圖", description: "聖地巡禮地圖最近新增和更新的動畫、遊戲取景地，按更新日期排列。" },
  ja: { title: "最近更新されたスポット · 聖地巡礼マップ", description: "聖地巡礼マップに最近追加・更新されたアニメ・ゲームの舞台を、更新日順に掲載。" },
  en: { title: "Recently updated spots · Anime Pilgrimage Map", description: "Anime and game locations recently added or updated on the Anime Pilgrimage Map, sorted by date." },
};

export const recentHead = (locale: Locale): HeadDescriptor => siteHead(locale, "/recent", RECENT[locale]);

/** 截到 max 字以内：优先在句末断开，其次在空格处，都没有就硬截并加省略号 */
function clip(text: string, max: number) {
  if (text.length <= max) return text;
  const head = text.slice(0, max);
  const end = Math.max(...["。", ". ", "！", "？", "! ", "? "].map((p) => head.lastIndexOf(p)));
  if (end > max / 3) return head.slice(0, end + 1).trim();
  const space = head.lastIndexOf(" ");
  return `${(space > max / 2 ? head.slice(0, space) : head).trim()}…`;
}

/** schema.org 的人员：原作（author）、监督（director）、动画制作（productionCompany）、角色（character） */
function creditsLd(locale: Locale, c: Credits | null | undefined) {
  if (!c) return {};
  const name = (e: CreditName) => (locale === "zh-Hans" ? e.cn : locale === "zh-Hant" ? (e.tw ?? e.cn) : locale === "en" ? e.en : null) ?? e.n;
  const people = (r: Credits["staff"][number]["r"], type: string) =>
    c.staff.find((s) => s.r === r)?.p.map((e) => ({ "@type": type, name: name(e), alternateName: e.n !== name(e) ? e.n : undefined }));
  return {
    author: people("original", "Person"),
    director: people("director", "Person"),
    productionCompany: people("studio", "Organization"),
    character: c.cast.length ? c.cast.map((e) => ({ "@type": "Person", name: name(e), alternateName: e.n !== name(e) ? e.n : undefined })) : undefined,
  };
}

/** 地标页的标题：地名在前（搜地名的人先看到），再是作品名，各语言按习惯写「圣地巡礼」 */
function spotTitle(locale: Locale, spot: string, work: string) {
  switch (locale) {
    case "zh-Hans":
      return `${spot} · ${work} 圣地巡礼取景地`;
    case "zh-Hant":
      return `${spot} · ${work} 聖地巡禮取景地`;
    case "ja":
      return `${spot}｜${work} 聖地巡礼スポット`;
    case "en":
      return `${spot} – ${work} anime pilgrimage spot`;
  }
}

function spotDescription(locale: Locale, spot: string, local: string | null, work: string, scene: string, mark: string | null, city: string | null) {
  const m = mark ? clip(mark.replace(/\s+/g, " "), 120) : "";
  switch (locale) {
    case "zh-Hans":
      return `${spot}${local ? `（${local}）` : ""}是${work}${scene ? ` ${scene}` : ""}中出现的取景地${city ? `，位于${city}` : ""}。${m}附截图、地图位置与导航。`;
    case "zh-Hant":
      return `${spot}${local ? `（${local}）` : ""}是${work}${scene ? ` ${scene}` : ""}中出現的取景地${city ? `，位於${city}` : ""}。${m}附截圖、地圖位置與導航。`;
    case "ja":
      return `${spot}${local ? `（${local}）` : ""}は${work}${scene ? ` ${scene}` : ""}に登場する聖地${city ? `（${city}）` : ""}。${m}場面写真と地図・ルート案内つき。`;
    case "en":
      return `${spot}${local ? ` (${local})` : ""} appears in ${work}${scene ? ` ${scene}` : ""}${city ? `, in ${city}` : ""}. ${m}${m ? " " : ""}With the anime screenshot, map location and directions.`;
  }
}

/**
 * 地标页 /b/:作品?p=:地标：每个地标单独收录，canonical 指向自己。标题和描述以地名开头，正文由服务端渲染展开的地标（名称、当地原名、备注）。
 * 地标不在这部作品里时退回作品页的 head
 */
export function spotHead(locale: Locale, g: Group, filter: number, pointId: string): HeadDescriptor {
  const d = buildView(visibleGroup(g, false, filter), filter)!;
  const p = d.points.find((x) => x.id === pointId);
  if (!p || needsAdultGate(g, filter)) return bangumiHead(locale, g, filter);
  const work = pickNameFor(locale, workNames(d));
  const spot = pickNameFor(locale, spotNames(p)) || work;
  const local = localNameFor(locale, p);
  const scene = [p.ep ? formatEpisode(p.ep) : "", p.s ? formatTime(p.s) : ""].filter(Boolean).join(" ");
  const mark = markFor(locale, p).text;
  const path = `/b/${d.id}?p=${encodeURIComponent(p.id)}`;
  const url = SITE + localePath(locale, path);
  return siteHead(locale, path, {
    // 同一地点常有多个镜头（各集都出现的编辑部、教室…）：标题带上集数与时间，各页标题不重复
    title: spotTitle(locale, scene ? `${spot} (${scene})` : spot, work),
    description: spotDescription(locale, spot, local, work, scene, mark, cityFor(locale, d)),
    image: p.image ? imageUrl(p.image, "h360") : d.cover ? imageUrl(d.cover, "h360") : undefined,
    markdown: `/md/b/${d.id}`,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "TouristAttraction",
      name: spot,
      alternateName: local ?? undefined,
      description: mark ?? undefined,
      url,
      inLanguage: locale,
      geo: { "@type": "GeoCoordinates", latitude: p.lat, longitude: p.lng },
      hasMap: `https://www.google.com/maps/search/?api=1&query=${p.lat}%2C${p.lng}`,
      image: p.image ? imageUrl(p.image, "h360") : undefined,
      touristType: "Anime pilgrimage",
      subjectOf: { "@type": "CreativeWork", name: d.title ?? work, alternateName: [d.cn, d.en].filter(Boolean), url: SITE + localePath(locale, `/b/${d.id}`), sameAs: `https://bgm.tv/subject/${d.id}` },
    },
  });
}

/**
 * 作品页与系列页：筛选到某部作品时路径是 /b/:id，系列「全部」时是 /s/:key。
 * 按默认（不显示成人向）的样子组装；成人向作品页不让搜索引擎收录，也不带封面和地标。
 */
export function bangumiHead(locale: Locale, g: Group, filter: number | null): HeadDescriptor {
  const adult = needsAdultGate(g, filter);
  const d = buildView(visibleGroup(g, false, filter), filter)!;
  const names = workNames(d);
  const name = pickNameFor(locale, names);
  const path = viewPath(d);
  const spots = (adult ? [] : d.points)
    .slice(0, 6)
    .map((p) => pickNameFor(locale, spotNames(p)))
    .filter(Boolean)
    .join(locale === "en" ? ", " : "、");
  const url = SITE + localePath(locale, path);
  return siteHead(locale, path, {
    title: `${name} · ${translate(locale, "brand")}`,
    description: bangumiDescription(locale, d, name, subNameFor(locale, names), spots),
    image: adult || !d.cover ? undefined : imageUrl(d.cover, "h360"),
    // 还没有地标的作品页内容很少、成人向作品页，都不让搜索引擎收录（也不在 sitemap 里）
    noindex: d.points.length === 0 || adult,
    markdown: adult || d.filter == null ? undefined : `/md/b/${d.id}`,
    jsonLd: adult ? undefined : {
      "@context": "https://schema.org",
      "@type": "ItemList",
      name: `${name} · ${translate(locale, "brand")}`,
      url,
      inLanguage: locale,
      about: { "@type": "CreativeWork", name: d.title ?? name, alternateName: [d.cn, d.en].filter(Boolean), sameAs: `https://bgm.tv/subject/${d.id}`, ...creditsLd(locale, d.credits) },
      numberOfItems: d.points.length,
      itemListElement: d.points.slice(0, 200).map((p, i) => ({
        "@type": "ListItem",
        position: i + 1,
        item: {
          "@type": "TouristAttraction",
          name: pickNameFor(locale, spotNames(p)),
          alternateName: p.cn && p.name ? p.name : undefined,
          url: `${url}?p=${p.id}`,
          geo: { "@type": "GeoCoordinates", latitude: p.lat, longitude: p.lng },
          image: p.image ? imageUrl(p.image, "h360") : undefined,
        },
      })),
    },
  });
}
