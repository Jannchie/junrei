// 界面语言：简体、繁体、日语、英语。界面文字很少（多为图标的无障碍名称），重点是作品名与地标名按语言取值。
import { inject, type InjectionKey, provide, type Ref, ref } from "vue";

export const LOCALES = ["zh-Hans", "zh-Hant", "ja", "en"] as const;
export type Locale = (typeof LOCALES)[number];

/** 语言选择器里显示各自的本名，不需要翻译 */
export const LOCALE_NAMES: Record<Locale, string> = {
  "zh-Hans": "简体中文",
  "zh-Hant": "繁體中文",
  ja: "日本語",
  en: "English",
};

const MESSAGES = {
  "zh-Hans": {
    brand: "圣地巡礼地图",
    search: "搜索",
    clear: "清除",
    back: "返回",
    locate: "定位",
    zoomIn: "放大",
    zoomOut: "缩小",
    language: "语言",
    credits: "数据来源与授权",
    source: "源代码",
    themeAuto: "外观：跟随系统",
    themeLight: "外观：浅色",
    themeDark: "外观：深色",
    openInMaps: "在地图 App 中打开",
    exportKml: "导出 KML，可导入 Google 地图",
  },
  "zh-Hant": {
    brand: "聖地巡禮地圖",
    search: "搜尋",
    clear: "清除",
    back: "返回",
    locate: "定位",
    zoomIn: "放大",
    zoomOut: "縮小",
    language: "語言",
    credits: "資料來源與授權",
    source: "原始碼",
    themeAuto: "外觀：跟隨系統",
    themeLight: "外觀：淺色",
    themeDark: "外觀：深色",
    openInMaps: "在地圖 App 中開啟",
    exportKml: "匯出 KML，可匯入 Google 地圖",
  },
  ja: {
    brand: "聖地巡礼マップ",
    search: "検索",
    clear: "クリア",
    back: "戻る",
    locate: "現在地",
    zoomIn: "拡大",
    zoomOut: "縮小",
    language: "言語",
    credits: "データ出典・ライセンス",
    source: "ソースコード",
    themeAuto: "外観：システムに合わせる",
    themeLight: "外観：ライト",
    themeDark: "外観：ダーク",
    openInMaps: "地図アプリで開く",
    exportKml: "KML を書き出す（Google マップに取り込めます）",
  },
  en: {
    brand: "Anime Pilgrimage Map",
    search: "Search",
    clear: "Clear",
    back: "Back",
    locate: "My location",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    language: "Language",
    credits: "Sources and licenses",
    source: "Source code",
    themeAuto: "Appearance: system",
    themeLight: "Appearance: light",
    themeDark: "Appearance: dark",
    openInMaps: "Open in Maps",
    exportKml: "Export KML (import into Google My Maps)",
  },
} satisfies Record<Locale, Record<string, string>>;

export type MessageKey = keyof (typeof MESSAGES)["zh-Hans"];

// ---- 路径：语言写在 URL 里，简体中文是默认语言、不带前缀 ----

/** 各语言的路径前缀 */
export const LOCALE_PREFIX: Record<Locale, string> = { "zh-Hans": "", "zh-Hant": "/zh-hant", ja: "/ja", en: "/en" };

/** URL 第一段（如 "ja"）→ 语言；不是语言前缀时返回 null */
export function localeFromSegment(segment: string | undefined): Locale | null {
  return LOCALES.find((l) => l !== "zh-Hans" && LOCALE_PREFIX[l] === `/${segment?.toLowerCase()}`) ?? null;
}

/** 去掉语言前缀后的路径（"/ja/b/1" → "/b/1"） */
export function stripLocale(pathname: string): string {
  const first = pathname.split("/")[1];
  return localeFromSegment(first) ? pathname.slice(first.length + 1) || "/" : pathname;
}

/** 某语言下的路径（"/b/1" → "/ja/b/1"） */
export const localePath = (locale: Locale, path: string) => `${LOCALE_PREFIX[locale]}${path === "/" && LOCALE_PREFIX[locale] ? "" : path}` || "/";

// ---- 按名称挑语言（纯函数，服务端生成 head 时也用） ----

type Names = { cn?: string | null; original?: string | null; en?: string | null };

/**
 * 按界面语言挑名称：中文界面优先中文名，日语界面优先原名，英语界面优先英文名，都没有时依次回退。
 * 繁体译名还没有数据时回退到简体。
 */
export function pickNameFor(locale: Locale, n: Names): string {
  const order = locale.startsWith("zh") ? [n.cn, n.original, n.en] : locale === "en" ? [n.en, n.original, n.cn] : [n.original, n.cn, n.en];
  return order.find((s) => s) ?? "";
}

/** 主名称之外再显示的副名称：中文界面显示原名，其他界面显示中文名；与主名称相同则不显示 */
export function subNameFor(locale: Locale, n: Names): string | null {
  const main = pickNameFor(locale, n);
  const sub = locale.startsWith("zh") ? n.original : n.original !== main ? n.original : null;
  return sub && sub !== main ? sub : null;
}

export const translate = (locale: Locale, key: MessageKey) => MESSAGES[locale][key];

// ---- 组件里用：当前语言由页面按 URL 提供，每次渲染各自一份（服务端并发渲染时不会串语言） ----

const LOCALE_KEY: InjectionKey<Ref<Locale>> = Symbol("locale");

/** 页面根组件调用：把语言交给子组件，并返回自己用的 i18n（组件拿不到自己 provide 的值） */
export function provideLocale(initial: Locale) {
  const locale = ref(initial);
  provide(LOCALE_KEY, locale);
  return i18n(locale);
}

export const useI18n = () => i18n(inject(LOCALE_KEY, ref<Locale>("zh-Hans")));

function i18n(locale: Ref<Locale>) {
  return {
    locale,
    t: (key: MessageKey) => translate(locale.value, key),
    pickName: (n: Names) => pickNameFor(locale.value, n),
    subName: (n: Names) => subNameFor(locale.value, n),
  };
}
