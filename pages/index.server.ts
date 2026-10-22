import { defineHead } from "void";

// 地图只能在浏览器里渲染；统计数字构建时从 data/stats.json 打进前端，不查 D1
export const ssr = false;

export const head = defineHead(() => ({
  title: "junrei · 动画圣地巡礼地图",
  meta: [{ name: "description", content: "动画圣地巡礼地图：在地图上浏览、搜索动画取景地" }],
  link: [{ rel: "preload", href: "/data/points.geojson", as: "fetch", crossorigin: "anonymous" }],
}));
