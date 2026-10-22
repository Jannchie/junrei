import type { HeadDescriptor } from "void";

/** 页面通用的 SEO head：description、canonical、Open Graph、Twitter 卡片与 JSON-LD */
export function siteHead(o: { title: string; description: string; url: string; image?: string; jsonLd?: object }): HeadDescriptor {
  const image = o.image ?? "https://junrei.jannchie.com/icons/og.png";
  return {
    title: o.title,
    meta: [
      { name: "description", content: o.description },
      { property: "og:type", content: "website" },
      { property: "og:site_name", content: "junrei" },
      { property: "og:title", content: o.title },
      { property: "og:description", content: o.description },
      { property: "og:url", content: o.url },
      { property: "og:image", content: image },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    link: [{ rel: "canonical", href: o.url }],
    // JSON 里的 "</" 要转义，避免提前结束 script 标签
    script: o.jsonLd ? [{ type: "application/ld+json", innerHTML: JSON.stringify(o.jsonLd).replace(/</g, "\\u003c") }] : [],
  };
}
