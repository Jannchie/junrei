import { defineHandler } from "void";
import { LOCALES, localePath } from "../src/i18n";
import { listBangumi, listSeriesKeys, SITE } from "../src/server/bangumi";

// 首页 + 每个系列页 + 每个作品页，每个页面列出全部语言版本（xhtml:link 互链）；随部署缓存（见 void.config.ts）
export const GET = defineHandler(async () => {
  const [rows, series] = await Promise.all([listBangumi(), listSeriesKeys()]);
  const paths = ["/", ...series.map((id) => `/s/${id}`), ...rows.map((b) => `/b/${b.id}`)];
  const entry = (path: string) => {
    const links = LOCALES.map((l) => `<xhtml:link rel="alternate" hreflang="${l}" href="${SITE}${localePath(l, path)}"/>`).join("");
    return LOCALES.map((l) => `  <url><loc>${SITE}${localePath(l, path)}</loc>${links}</url>`).join("\n");
  };
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${paths.map(entry).join("\n")}
</urlset>
`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
});
