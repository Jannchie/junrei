import { defineHandler } from "void";
import { countSpots, SITE } from "../src/server/bangumi";
import { SPOTS_PER_SITEMAP } from "./sitemap/[file]";

// sitemap 索引：页面（首页、最近更新、系列页、作品页）一份，地标页按 SPOTS_PER_SITEMAP 个一份（单个 sitemap 最多 5 万个网址）
export const GET = defineHandler(async () => {
  const files = ["pages.xml", ...Array.from({ length: Math.ceil((await countSpots()) / SPOTS_PER_SITEMAP) }, (_, i) => `spots-${i}.xml`)];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${files.map((f) => `  <sitemap><loc>${SITE}/sitemap/${f}</loc></sitemap>`).join("\n")}
</sitemapindex>
`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
});
