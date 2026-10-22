import { defineHandler, defineHead, type InferProps } from "void";
import type { Locale } from "../../src/i18n";
import { getBangumi } from "../../src/server/bangumi";
import { bangumiHead } from "../../src/server/seo";

export type Props = InferProps<typeof loader>;

// 作品页（简体中文）：服务端渲染作品与地标，供搜索引擎与 LLM 读取；地图在浏览器里挂载
export const loader = defineHandler(async (c) => {
  const id = Number(c.req.param("id"));
  const detail = Number.isInteger(id) && id > 0 ? await getBangumi(id) : null;
  if (!detail) return c.notFound();
  return { detail, lang: "zh-Hans" as Locale };
});

export const head = defineHead<Props>((_c, { detail, lang }) => bangumiHead(lang, detail));
