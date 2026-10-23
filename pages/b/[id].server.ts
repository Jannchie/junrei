import { defineHandler, defineHead, type InferProps } from "void";
import type { Locale } from "../../src/i18n";
import { getGroup } from "../../src/server/bangumi";
import { bangumiHead } from "../../src/server/seo";
import { buildView } from "../../src/series";

export type Props = InferProps<typeof loader>;

// 作品页（简体中文）：所在系列筛选到这一部。服务端渲染作品与地标，供搜索引擎与 LLM 读取；地图在浏览器里挂载
export const loader = defineHandler(async (c) => {
  const lang: Locale = "zh-Hans";
  const id = Number(c.req.param("id"));
  const group = Number.isInteger(id) && id > 0 ? await getGroup(id, false) : null;
  if (!group) return c.notFound();
  return { group, filter: id as number | null, lang };
});

export const head = defineHead<Props>((_c, { group, filter, lang }) => bangumiHead(lang, buildView(group, filter)!));
