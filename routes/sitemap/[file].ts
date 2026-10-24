import { defineHandler } from "void";
import { LOCALES, localePath } from "../../src/i18n";
import { listBangumi, listSeriesKeys, listSpots, SITE } from "../../src/server/bangumi";

/** 每份地标 sitemap 的地标数：各语言一个网址，4 种语言共 4.8 万个，不超过上限 5 万 */
export const SPOTS_PER_SITEMAP = 12000;

const xmlEscape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const urlset = (body: string, xhtml = false) =>
  new Response(
    `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"${xhtml ? ` xmlns:xhtml="http://www.w3.org/1999/xhtml"` : ""}>
${body}
</urlset>
`,
    { headers: { "Content-Type": "application/xml; charset=utf-8" } },
  );

// pages.xml：首页、最近更新、每个系列页与作品页，各语言版本互链（xhtml:link）；
// spots-N.xml：地标页 /b/:作品?p=:地标（各语言互链写在页面 head 里，这里不重复，文件小一些），lastmod 取地标的更新时间。随部署缓存（见 void.config.ts）
export const GET = defineHandler(async (c) => {
  const file = c.req.param("file") ?? "";
  if (file === "pages.xml") {
    const [rows, series] = await Promise.all([listBangumi(), listSeriesKeys()]);
    const paths = ["/", "/recent", ...series.map((id) => `/s/${id}`), ...rows.map((b) => `/b/${b.id}`)];
    const entry = (path: string) => {
      const links = LOCALES.map((l) => `<xhtml:link rel="alternate" hreflang="${l}" href="${SITE}${localePath(l, path)}"/>`).join("");
      return LOCALES.map((l) => `  <url><loc>${SITE}${localePath(l, path)}</loc>${links}</url>`).join("\n");
    };
    return urlset(paths.map(entry).join("\n"), true);
  }
  const m = /^spots-(\d+)\.xml$/.exec(file);
  if (!m) return c.notFound();
  const spots = await listSpots(Number(m[1]) * SPOTS_PER_SITEMAP, SPOTS_PER_SITEMAP);
  if (!spots.length) return c.notFound();
  const body = spots.flatMap((p) => {
    const path = `/b/${p.bangumiId}?p=${encodeURIComponent(p.id)}`;
    const lastmod = p.updated ? `<lastmod>${new Date(p.updated * 1000).toISOString().slice(0, 10)}</lastmod>` : "";
    return LOCALES.map((l) => `  <url><loc>${xmlEscape(SITE + localePath(l, path))}</loc>${lastmod}</url>`);
  });
  return urlset(body.join("\n"));
});
