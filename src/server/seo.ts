import type { HeadDescriptor } from "void";
import { cityFor, type Locale, LOCALES, localePath, pickNameFor, subNameFor, translate } from "../i18n";
import { type BangumiDetail, SITE } from "./bangumi";
import { buildView, type Group, needsAdultGate, visibleGroup } from "../series";

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
function siteHead(locale: Locale, path: string, o: { title: string; description: string; image?: string; jsonLd?: object; noindex?: boolean }): HeadDescriptor {
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

/**
 * 作品页与系列页：筛选到某部作品时路径是 /b/:id，系列「全部」时是 /s/:key。
 * 按默认（不显示成人向）的样子组装；成人向作品页不让搜索引擎收录，也不带封面和地标。
 */
export function bangumiHead(locale: Locale, g: Group, filter: number | null): HeadDescriptor {
  const adult = needsAdultGate(g, filter);
  const d = buildView(visibleGroup(g, false, filter), filter)!;
  const names = { cn: d.cn, original: d.title, en: d.en, i18n: d.i18n };
  const name = pickNameFor(locale, names);
  const path = d.filter == null && d.series.length > 1 ? `/s/${d.key}` : `/b/${d.id}`;
  const spots = (adult ? [] : d.points)
    .slice(0, 6)
    .map((p) => pickNameFor(locale, { cn: p.cn, original: p.name, i18n: p.i18n }))
    .filter(Boolean)
    .join(locale === "en" ? ", " : "、");
  const url = SITE + localePath(locale, path);
  return siteHead(locale, path, {
    title: `${name} · ${translate(locale, "brand")}`,
    description: bangumiDescription(locale, d, name, subNameFor(locale, names), spots),
    image: adult ? undefined : d.cover?.startsWith("https://image.anitabi.cn/") ? `${d.cover}?plan=h360` : (d.cover ?? undefined),
    // 还没有地标的作品页内容很少、成人向作品页，都不让搜索引擎收录（也不在 sitemap 里）
    noindex: d.points.length === 0 || adult,
    jsonLd: adult ? undefined : {
      "@context": "https://schema.org",
      "@type": "ItemList",
      name: `${name} · ${translate(locale, "brand")}`,
      url,
      inLanguage: locale,
      about: { "@type": "CreativeWork", name: d.title ?? name, alternateName: [d.cn, d.en].filter(Boolean), sameAs: `https://bgm.tv/subject/${d.id}` },
      numberOfItems: d.points.length,
      itemListElement: d.points.slice(0, 200).map((p, i) => ({
        "@type": "ListItem",
        position: i + 1,
        item: {
          "@type": "TouristAttraction",
          name: pickNameFor(locale, { cn: p.cn, original: p.name, i18n: p.i18n }),
          alternateName: p.cn && p.name ? p.name : undefined,
          url: `${url}?p=${p.id}`,
          geo: { "@type": "GeoCoordinates", latitude: p.lat, longitude: p.lng },
          image: p.image ? `${p.image}?plan=h360` : undefined,
        },
      })),
    },
  });
}
