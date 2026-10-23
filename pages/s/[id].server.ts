import { defineHandler, defineHead, type InferProps } from "void";
import type { Locale } from "../../src/i18n";
import { getGroup } from "../../src/server/bangumi";
import { bangumiHead } from "../../src/server/seo";

export type Props = InferProps<typeof loader>;

// 系列页（简体中文）：系列里所有作品的地标合在一起
export const loader = defineHandler(async (c) => {
  const lang: Locale = "zh-Hans";
  const id = Number(c.req.param("id"));
  const group = Number.isInteger(id) && id > 0 ? await getGroup(id, true) : null;
  if (!group) return c.notFound();
  return { group, filter: null as number | null, lang };
});

export const head = defineHead<Props>((_c, { group, filter, lang }) => bangumiHead(lang, group, filter));
