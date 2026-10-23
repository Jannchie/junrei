import { defineHandler, defineHead, type InferProps } from "void";
import { localeFromSegment } from "../../../src/i18n";
import { getGroup } from "../../../src/server/bangumi";
import { bangumiHead } from "../../../src/server/seo";

export type Props = InferProps<typeof loader>;

// 其他语言的系列页：/zh-hant/s/:id、/ja/s/:id、/en/s/:id
export const loader = defineHandler(async (c) => {
  const lang = localeFromSegment(c.req.param("lang"));
  const id = Number(c.req.param("id"));
  const group = lang && Number.isInteger(id) && id > 0 ? await getGroup(id, true) : null;
  if (!lang || !group) return c.notFound();
  return { group, filter: null as number | null, lang };
});

export const head = defineHead<Props>((_c, { group, filter, lang }) => bangumiHead(lang, group, filter));
