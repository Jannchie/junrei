import { defineHandler } from "void";
import { listBangumi, SITE } from "../src/server/bangumi";

// 首页 + 每个作品页；随部署缓存（见 void.config.ts）
export const GET = defineHandler(async () => {
  const rows = await listBangumi();
  const urls = [`${SITE}/`, ...rows.map((b) => `${SITE}/b/${b.id}`)];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map((u) => `  <url><loc>${u}</loc></url>`).join("\n")}
</urlset>
`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
});
