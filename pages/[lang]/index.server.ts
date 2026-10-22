import { defineHandler, defineHead, type InferProps } from "void";
import { localeFromSegment } from "../../src/i18n";
import { listBangumi } from "../../src/server/bangumi";
import { homeHead } from "../../src/server/seo";

export type Props = InferProps<typeof loader>;

// 其他语言的首页：/zh-hant、/ja、/en
export const loader = defineHandler(async (c) => {
  const lang = localeFromSegment(c.req.param("lang"));
  if (!lang) return c.notFound();
  return { popular: await listBangumi(24), lang };
});

export const head = defineHead<Props>((_c, { lang }) => homeHead(lang));
