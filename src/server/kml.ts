// 作品的地标导出成 KML：可导入 Google My Maps（手机 Google Maps「已保存 → 地图」里能看到），也能被 Google Earth 等打开
import { formatEpisode, formatTime, imageUrl } from "../format";
import { type Locale, localePath, markFor, pickNameFor, subNameFor } from "../i18n";
import { type BangumiDetail, SITE } from "./bangumi";

const esc = (s: string) => s.replace(/[&<>"']/g, (m) => `&#${m.charCodeAt(0)};`);
// 描述里放 HTML（截图、出处、链接），用 CDATA 包起来；正文里不能出现 "]]>"
const cdata = (s: string) => `<![CDATA[${s.replaceAll("]]>", "]]]]><![CDATA[>")}]]>`;

export function bangumiKml(locale: Locale, d: BangumiDetail): { name: string; kml: string } {
  const names = { cn: d.cn, original: d.title, en: d.en, i18n: d.i18n };
  const name = pickNameFor(locale, names);
  const page = SITE + localePath(locale, `/b/${d.id}`);
  const placemarks = d.points.map((p) => {
    const sub = subNameFor(locale, { cn: p.cn, original: p.name, i18n: p.i18n });
    const meta = [p.ep && formatEpisode(p.ep), p.s && formatTime(p.s)].filter(Boolean).join(" · ");
    const html = [
      sub && `<p>${esc(sub)}</p>`,
      meta && `<p>${esc(meta)}</p>`,
      p.image && `<img src="${esc(imageUrl(p.image, "h360"))}" width="320"/>`,
      markFor(locale, p).text && `<p>${esc(markFor(locale, p).text!)}</p>`,
      p.origin && `<p>© ${esc(p.origin)}</p>`,
      p.sourceUrl && `<p>Source: <a href="${esc(p.sourceUrl)}">${esc(p.source ?? p.sourceUrl)}</a></p>`,
      `<p><a href="${esc(`${page}?p=${p.id}`)}">${esc(page)}</a></p>`,
    ]
      .filter(Boolean)
      .join("");
    return `    <Placemark>
      <name>${esc(pickNameFor(locale, { cn: p.cn, original: p.name, i18n: p.i18n }) || name)}</name>
      <description>${cdata(html)}</description>
      <Point><coordinates>${p.lng},${p.lat},0</coordinates></Point>
    </Placemark>`;
  });
  const kml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${esc(name)}</name>
    <description>${cdata(`<a href="${esc(page)}">${esc(page)}</a>`)}</description>
${placemarks.join("\n")}
  </Document>
</kml>
`;
  return { name, kml };
}
