// 界面语言：简体、繁体、日语、英语。界面文字很少（多为图标的无障碍名称），重点是作品名与地标名按语言取值。
import { computed, ref, watch } from "vue";

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
  },
} satisfies Record<Locale, Record<string, string>>;

export type MessageKey = keyof (typeof MESSAGES)["zh-Hans"];

const STORAGE_KEY = "junrei:locale";

function detect(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (LOCALES.includes(saved as Locale)) return saved as Locale;
  } catch {}
  for (const tag of navigator.languages) {
    const t = tag.toLowerCase();
    if (t.startsWith("zh")) return /hant|tw|hk|mo/.test(t) ? "zh-Hant" : "zh-Hans";
    if (t.startsWith("ja")) return "ja";
    if (t.startsWith("en")) return "en";
  }
  return "zh-Hans";
}

// 服务端渲染统一用简体中文，浏览器挂载后再按用户偏好切换（见 initLocale）
export const locale = ref<Locale>("zh-Hans");

let initialized = false;

export function initLocale() {
  if (initialized) return;
  initialized = true;
  locale.value = detect();
  document.documentElement.lang = locale.value;
  watch(locale, (l) => {
    document.documentElement.lang = l;
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {}
  });
}

export const t = (key: MessageKey) => MESSAGES[locale.value][key];

export const isChinese = computed(() => locale.value.startsWith("zh"));

/**
 * 按界面语言挑名称：中文界面优先中文名，日语界面优先原名，英语界面优先英文名，都没有时依次回退。
 * 繁体译名还没有数据时回退到简体。
 */
export function pickName(n: { cn?: string | null; original?: string | null; en?: string | null }): string {
  const order = isChinese.value ? [n.cn, n.original, n.en] : locale.value === "en" ? [n.en, n.original, n.cn] : [n.original, n.cn, n.en];
  return order.find((s) => s) ?? "";
}

/** 主名称之外再显示的副名称：中文界面显示原名，其他界面显示中文名；与主名称相同则不显示 */
export function subName(n: { cn?: string | null; original?: string | null; en?: string | null }): string | null {
  const main = pickName(n);
  const sub = isChinese.value ? n.original : n.original !== main ? n.original : null;
  return sub && sub !== main ? sub : null;
}

