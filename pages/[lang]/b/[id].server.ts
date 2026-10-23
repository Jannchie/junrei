import { defineHandler, defineHead, type InferProps } from "void";
import { localeFromSegment } from "../../../src/i18n";
import { getGroup } from "../../../src/server/bangumi";
import { bangumiHead } from "../../../src/server/seo";
import { buildView } from "../../../src/series";

export type Props = InferProps<typeof loader>;

// 其他语言的作品页：/zh-hant/b/:id、/ja/b/:id、/en/b/:id
export const loader = defineHandler(async (c) => {
  const lang = localeFromSegment(c.req.param("lang"));
  const id = Number(c.req.param("id"));
  const group = lang && Number.isInteger(id) && id > 0 ? await getGroup(id, false) : null;
  if (!lang || !group) return c.notFound();
  return { group, filter: id as number | null, lang };
});

export const head = defineHead<Props>((_c, { group, filter, lang }) => bangumiHead(lang, buildView(group, filter)!));
