import { defineHandler, defineHead, type InferProps } from "void";
import { localeFromSegment } from "../../../src/i18n";
import { getBangumi } from "../../../src/server/bangumi";
import { bangumiHead } from "../../../src/server/seo";

export type Props = InferProps<typeof loader>;

// 其他语言的作品页：/zh-hant/b/:id、/ja/b/:id、/en/b/:id
export const loader = defineHandler(async (c) => {
  const lang = localeFromSegment(c.req.param("lang"));
  const id = Number(c.req.param("id"));
  const detail = lang && Number.isInteger(id) && id > 0 ? await getBangumi(id) : null;
  if (!lang || !detail) return c.notFound();
  return { detail, lang };
});

export const head = defineHead<Props>((_c, { detail, lang }) => bangumiHead(lang, detail));
