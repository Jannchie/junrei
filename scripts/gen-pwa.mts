// 生成各语言的 PWA 清单与 OpenSearch 描述：public/manifest-<lang>.webmanifest、public/opensearch-<lang>.xml。
// 每种语言的应用名、简介和启动页不同（从英文页安装，打开的就是英文首页）。改了文案后重跑：
//   node --experimental-strip-types scripts/gen-pwa.mts
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { LOCALES, type Locale, localePath } from "../src/i18n.ts";

const SITE = "https://junrei.jannchie.com";
const OUT = fileURLToPath(new URL("../public/", import.meta.url));

const TEXT: Record<Locale, { name: string; short: string; description: string; search: string }> = {
  "zh-Hans": { name: "圣地巡礼地图", short: "圣地巡礼", description: "动画、游戏取景地（圣地巡礼）地图", search: "搜索动画、游戏的取景地（圣地巡礼）" },
  "zh-Hant": { name: "聖地巡禮地圖", short: "聖地巡禮", description: "動畫、遊戲取景地（聖地巡禮）地圖", search: "搜尋動畫、遊戲的取景地（聖地巡禮）" },
  ja: { name: "聖地巡礼マップ", short: "聖地巡礼", description: "アニメ・ゲームの舞台（聖地）を地図で", search: "アニメ・ゲームの舞台（聖地）を検索" },
  en: { name: "Anime Pilgrimage Map", short: "Pilgrimage", description: "Real-world locations from anime and games on a map", search: "Search real-world locations from anime and games" },
};

/** 文件名里的语言键：zh-hans、zh-hant、ja、en */
export const key = (l: Locale) => l.toLowerCase();

const ICONS = [
  { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
  { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
  { src: "/icons/maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
  { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
];

const xml = (s: string) => s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

for (const l of LOCALES) {
  const t = TEXT[l];
  const home = localePath(l, "/");
  const manifest = {
    // 各语言是不同的应用：id 与启动页都是该语言的首页
    id: home,
    name: t.name,
    short_name: t.short,
    description: t.description,
    start_url: home,
    scope: "/",
    display: "standalone",
    orientation: "any",
    background_color: "#f2f4f6",
    theme_color: "#f2f4f6",
    lang: l,
    categories: ["travel", "navigation", "entertainment"],
    icons: ICONS,
  };
  writeFileSync(`${OUT}manifest-${key(l)}.webmanifest`, `${JSON.stringify(manifest, null, 2)}\n`);
  writeFileSync(
    `${OUT}opensearch-${key(l)}.xml`,
    `<?xml version="1.0" encoding="UTF-8"?>
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>${xml(t.name)}</ShortName>
  <Description>${xml(t.search)}</Description>
  <InputEncoding>UTF-8</InputEncoding>
  <Language>${l}</Language>
  <Image width="32" height="32" type="image/png">${SITE}/icons/favicon-32.png</Image>
  <Url type="text/html" method="get" template="${SITE}${home}?q={searchTerms}"/>
  <Url type="application/json" method="get" template="${SITE}/v1/search?q={searchTerms}"/>
</OpenSearchDescription>
`,
  );
}
console.log("pwa ->", OUT);
