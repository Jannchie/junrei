import { defineHandler, defineHead, type InferProps } from "void";
import { listBangumi, SITE } from "../src/server/bangumi";
import { siteHead } from "../src/server/seo";

export type Props = InferProps<typeof loader>;

// 服务端渲染概览与热门作品（真实链接，爬虫能走到每个作品页）；地图在浏览器里挂载
export const loader = defineHandler(async () => ({ popular: await listBangumi(24) }));

export const head = defineHead(() =>
  siteHead({
    title: "junrei · 动画圣地巡礼地图",
    description: "在地图上浏览和搜索动画、游戏取景地（圣地巡礼）：数千部作品、数万个地标，附截图、集数与时间点。",
    url: `${SITE}/`,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: "junrei",
      url: `${SITE}/`,
      inLanguage: ["zh-Hans", "zh-Hant", "ja", "en"],
    },
  }),
);
