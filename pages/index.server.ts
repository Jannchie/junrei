import { defineHandler, defineHead, type InferProps } from "void";
import type { Locale } from "../src/i18n";
import { listBangumi } from "../src/server/bangumi";
import { homeHead } from "../src/server/seo";

export type Props = InferProps<typeof loader>;

// 首页（简体中文，无语言前缀）：服务端渲染概览与热门作品（真实链接，爬虫能走到每个作品页）；地图在浏览器里挂载
export const loader = defineHandler(async () => ({ popular: await listBangumi(24), lang: "zh-Hans" as Locale }));

export const head = defineHead<Props>((_c, { lang }) => homeHead(lang));
