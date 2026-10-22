import { defineHandler, defineHead, type InferProps } from "void";
import { displayName, getBangumi, SITE } from "../../src/server/bangumi";
import { siteHead } from "../../src/server/seo";

export type Props = InferProps<typeof loader>;

// 作品页：服务端渲染作品与全部地标，供搜索引擎与 LLM 读取；地图在浏览器里挂载
export const loader = defineHandler(async (c) => {
  const id = Number(c.req.param("id"));
  const detail = Number.isInteger(id) && id > 0 ? await getBangumi(id) : null;
  if (!detail) return c.notFound();
  return { detail };
});

export const head = defineHead<Props>((_c, { detail }) => {
  const name = displayName(detail);
  const url = `${SITE}/b/${detail.id}`;
  const spots = detail.points
    .slice(0, 6)
    .map((p) => p.cn ?? p.name)
    .filter(Boolean)
    .join("、");
  return siteHead({
    title: `${name} · 圣地巡礼地图`,
    description: [
      `${name}${detail.title && detail.title !== name ? `（${detail.title}）` : ""}的圣地巡礼地图`,
      detail.city ? `主要位于${detail.city}` : null,
      `共 ${detail.pointCount} 个取景地`,
      spots ? `包括${spots}等` : null,
    ]
      .filter(Boolean)
      .join("，") + "。",
    url,
    image: detail.cover ? `${detail.cover}?plan=h360` : undefined,
    jsonLd: {
      "@context": "https://schema.org",
      "@type": "ItemList",
      name: `${name} 圣地巡礼取景地`,
      url,
      about: { "@type": "CreativeWork", name: detail.title ?? name, alternateName: [detail.cn, detail.en].filter(Boolean), sameAs: `https://bgm.tv/subject/${detail.id}` },
      numberOfItems: detail.points.length,
      itemListElement: detail.points.slice(0, 200).map((p, i) => ({
        "@type": "ListItem",
        position: i + 1,
        item: {
          "@type": "TouristAttraction",
          name: p.cn ?? p.name,
          alternateName: p.cn && p.name ? p.name : undefined,
          url: `${url}?p=${p.id}`,
          geo: { "@type": "GeoCoordinates", latitude: p.lat, longitude: p.lng },
          image: p.image ? `${p.image}?plan=h360` : undefined,
        },
      })),
    },
  });
});
