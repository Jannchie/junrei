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
    search: "搜索作品或地标",
    clear: "清除",
    back: "返回",
    undo: "撤销",
    redo: "重做",
    wentBack: "已返回",
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
    moreLinks: "更多：Bangumi、Anitabi、导出 KML",
    kmlShort: "导出 KML",
    shortcuts: "键盘快捷键",
    kbSearch: "搜索",
    kbPoints: "上一个 / 下一个地标",
    kbTheme: "切换外观",
    popular: "热门作品",
    inView: "这片区域的作品",
    outOfView: "视野外的地标",
    recent: "最近更新",
    updatedOn: "更新于",
    noSpots: "还没有收录这部作品的巡礼地标",
    sourceLabel: "来源",
    report: "报告问题",
    allWorks: "全部",
    roleOriginal: "原作",
    roleDirector: "监督",
    roleComposition: "系列构成",
    roleStudio: "动画制作",
    roleOriginalDesign: "人物原案",
    roleCharacterDesign: "人物设定",
    roleMusic: "音乐",
    cast: "角色",
    showAll: "展开全部",
    series: "同系列作品",
    adultShow: "显示成人向作品",
    adultNotice: "这部作品是成人向内容（18 禁），默认隐藏。",
    adultContinue: "已满 18 岁，继续查看",
  },
  "zh-Hant": {
    brand: "聖地巡禮地圖",
    search: "搜尋作品或地標",
    clear: "清除",
    back: "返回",
    undo: "復原",
    redo: "重做",
    wentBack: "已返回",
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
    moreLinks: "更多：Bangumi、Anitabi、匯出 KML",
    kmlShort: "匯出 KML",
    shortcuts: "鍵盤快速鍵",
    kbSearch: "搜尋",
    kbPoints: "上一個 / 下一個地標",
    kbTheme: "切換外觀",
    popular: "熱門作品",
    inView: "這片區域的作品",
    outOfView: "視野外的地標",
    recent: "最近更新",
    updatedOn: "更新於",
    noSpots: "還沒有收錄這部作品的巡禮地標",
    sourceLabel: "來源",
    report: "回報問題",
    allWorks: "全部",
    roleOriginal: "原作",
    roleDirector: "監督",
    roleComposition: "系列構成",
    roleStudio: "動畫製作",
    roleOriginalDesign: "人物原案",
    roleCharacterDesign: "人物設定",
    roleMusic: "音樂",
    cast: "角色",
    showAll: "展開全部",
    series: "同系列作品",
    adultShow: "顯示成人向作品",
    adultNotice: "這部作品是成人向內容（18 禁），預設隱藏。",
    adultContinue: "已滿 18 歲，繼續查看",
  },
  ja: {
    brand: "聖地巡礼マップ",
    search: "作品やスポットを検索",
    clear: "クリア",
    back: "戻る",
    undo: "元に戻す",
    redo: "やり直す",
    wentBack: "戻りました",
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
    moreLinks: "その他：Bangumi・Anitabi・KML 書き出し",
    kmlShort: "KML を書き出す",
    shortcuts: "キーボードショートカット",
    kbSearch: "検索",
    kbPoints: "前 / 次のスポット",
    kbTheme: "外観を切り替え",
    popular: "人気の作品",
    inView: "このエリアの作品",
    outOfView: "表示範囲外のスポット",
    recent: "最近の更新",
    updatedOn: "更新日",
    noSpots: "この作品の聖地はまだ登録されていません",
    sourceLabel: "出典",
    report: "問題を報告",
    allWorks: "すべて",
    roleOriginal: "原作",
    roleDirector: "監督",
    roleComposition: "シリーズ構成",
    roleStudio: "アニメーション制作",
    roleOriginalDesign: "キャラクター原案",
    roleCharacterDesign: "キャラクターデザイン",
    roleMusic: "音楽",
    cast: "キャラクター",
    showAll: "すべて表示",
    series: "シリーズ作品",
    adultShow: "成人向け作品を表示",
    adultNotice: "この作品は成人向け（18 禁）のため、通常は表示されません。",
    adultContinue: "18 歳以上なので表示する",
  },
  en: {
    brand: "Anime Pilgrimage Map",
    search: "Search titles or spots",
    clear: "Clear",
    back: "Back",
    undo: "Undo",
    redo: "Redo",
    wentBack: "Went back",
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
    moreLinks: "More: Bangumi, Anitabi, KML export",
    kmlShort: "Export KML",
    shortcuts: "Keyboard shortcuts",
    kbSearch: "Search",
    kbPoints: "Previous / next spot",
    kbTheme: "Switch appearance",
    popular: "Popular",
    inView: "In this area",
    outOfView: "Outside the map view",
    recent: "Recently updated",
    updatedOn: "Updated",
    noSpots: "No pilgrimage spots for this title yet",
    sourceLabel: "Source",
    report: "Report an issue",
    allWorks: "All",
    roleOriginal: "Original work",
    roleDirector: "Director",
    roleComposition: "Series composition",
    roleStudio: "Studio",
    roleOriginalDesign: "Original character design",
    roleCharacterDesign: "Character design",
    roleMusic: "Music",
    cast: "Characters",
    showAll: "Show all",
    series: "In this series",
    adultShow: "Show adult titles",
    adultNotice: "This title is adult (18+) content and is hidden by default.",
    adultContinue: "I'm 18 or older, show it",
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

/** 多语言文本（同 db/schema.ts 的 I18n）：name 名称、mark 备注、mt 机器翻译的条目（如 "name.en"） */
export interface I18n {
  name?: Partial<Record<Locale, string>>;
  mark?: Partial<Record<Locale, string>>;
  city?: Partial<Record<Locale, string>>;
  mt?: string[];
  /** 地标原名的语言（导出时判断）；原名本身见 name[src] */
  src?: Locale;
}

type Names = { cn?: string | null; original?: string | null; en?: string | null; i18n?: I18n | null };
/** 作品、地标各自的字段转成 Names（作品的原名在 title，地标在 name） */
export const workNames = (w: { cn?: string | null; title?: string | null; en?: string | null; i18n?: I18n | null }): Names =>
  ({ cn: w.cn, original: w.title, en: w.en, i18n: w.i18n });
export const spotNames = (p: { cn?: string | null; name?: string | null; i18n?: I18n | null }): Names =>
  ({ cn: p.cn, original: p.name, i18n: p.i18n });

/**
 * 按界面语言挑名称：先用翻译表里该语言的文本（人工优先，其次机翻）；没有时按
 * 中文界面优先中文名、日语界面优先原名、英语界面优先英文名依次回退。
 */
export function pickNameFor(locale: Locale, n: Names): string {
  const translated = n.i18n?.name?.[locale];
  if (translated) return translated;
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

/** 地标的当地原名（原文语言的纯净版本），与当前语言不同时才有，用作对照 */
export function localNameFor(locale: Locale, p: { i18n?: I18n | null }) {
  const src = p.i18n?.src;
  const text = src && src !== locale ? p.i18n?.name?.[src] : null;
  return text && text !== p.i18n?.name?.[locale] ? text : null;
}

/** 作品所在城市：该语言的名称，没有就用原文 */
export const cityFor = (locale: Locale, b: { city: string | null; i18n?: I18n | null }) => b.i18n?.city?.[locale] ?? b.city;

// 作品类别（Anitabi 的分类，简体中文）→ 各语言；没列出的原样显示
const CATEGORIES: Record<string, Record<Exclude<Locale, "zh-Hans">, string>> = {
  TV: { "zh-Hant": "TV", ja: "TV", en: "TV" },
  WEB: { "zh-Hant": "WEB", ja: "WEB", en: "Web" },
  OVA: { "zh-Hant": "OVA", ja: "OVA", en: "OVA" },
  MV: { "zh-Hant": "MV", ja: "MV", en: "MV" },
  AVG: { "zh-Hant": "AVG", ja: "ADV", en: "Visual novel" },
  游戏: { "zh-Hant": "遊戲", ja: "ゲーム", en: "Game" },
  剧场版: { "zh-Hant": "劇場版", ja: "劇場版", en: "Movie" },
  电影: { "zh-Hant": "電影", ja: "映画", en: "Film" },
  漫画: { "zh-Hant": "漫畫", ja: "漫画", en: "Manga" },
  漫画系列: { "zh-Hant": "漫畫系列", ja: "漫画シリーズ", en: "Manga series" },
  小说: { "zh-Hant": "小說", ja: "小説", en: "Novel" },
  小说系列: { "zh-Hant": "小說系列", ja: "小説シリーズ", en: "Novel series" },
  日剧: { "zh-Hant": "日劇", ja: "日本のドラマ", en: "Japanese drama" },
  华语剧: { "zh-Hant": "華語劇", ja: "中国語ドラマ", en: "Chinese drama" },
  欧美剧: { "zh-Hant": "歐美劇", ja: "海外ドラマ", en: "Western drama" },
  电视剧: { "zh-Hant": "電視劇", ja: "テレビドラマ", en: "TV drama" },
  音乐: { "zh-Hant": "音樂", ja: "音楽", en: "Music" },
  演出: { "zh-Hant": "演出", ja: "公演", en: "Live show" },
  画集: { "zh-Hant": "畫集", ja: "画集", en: "Art book" },
  扩展包: { "zh-Hant": "擴充包", ja: "拡張パック", en: "Expansion" },
  其他: { "zh-Hant": "其他", ja: "その他", en: "Other" },
};
export const categoryFor = (locale: Locale, cat: string | null) =>
  cat && locale !== "zh-Hans" ? (CATEGORIES[cat]?.[locale] ?? cat) : cat;

/** 地标备注：该语言的译文（没有就用原文），以及它是不是机器翻译的 */
export function markFor(locale: Locale, p: { mark: string | null; i18n?: I18n | null }) {
  const text = p.i18n?.mark?.[locale];
  return text ? { text, machine: !!p.i18n?.mt?.includes(`mark.${locale}`) } : { text: p.mark, machine: false };
}

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
    markOf: (p: Parameters<typeof markFor>[1]) => markFor(locale.value, p),
    cityOf: (b: Parameters<typeof cityFor>[1]) => cityFor(locale.value, b),
    localName: (p: Parameters<typeof localNameFor>[1]) => localNameFor(locale.value, p),
    categoryOf: (cat: string | null) => categoryFor(locale.value, cat),
    subName: (n: Names) => subNameFor(locale.value, n),
  };
}
