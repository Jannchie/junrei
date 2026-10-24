import { index, integer, primaryKey, real, sqliteTable, text } from "void/schema-d1";

// 数据由 sync/ 同步自 Anitabi，再经 sync/export.py 生成 SQL 全量导入；应用只读。
// 地标名搜索用的 FTS5 虚表 point_fts（建在 point.search 上）不在 Drizzle 里，见 db/migrations 末尾的手写部分。

/**
 * 多语言文本（sync/export.py 从 data/enrich.sqlite 的 translation 表挑出每种语言最可信的一条）。
 * name：作品标题或地标名；mark：地标备注；city：作品所在城市（Wikidata）；mt：机器翻译的条目，如 "name.en"。
 */
export interface I18n {
  name?: Partial<Record<"zh-Hans" | "zh-Hant" | "ja" | "en", string>>;
  mark?: Partial<Record<"zh-Hans" | "zh-Hant" | "ja" | "en", string>>;
  city?: Partial<Record<"zh-Hans" | "zh-Hant" | "ja" | "en", string>>;
  mt?: string[];
  src?: "zh-Hans" | "zh-Hant" | "ja" | "en"; // 地标原名的语言
}

export const bangumi = sqliteTable("bangumi", {
  id: integer("id").primaryKey(), // Bangumi subject ID
  cn: text("cn"),
  title: text("title"),
  en: text("en"),
  city: text("city"),
  cat: text("cat"),
  color: text("color"),
  cover: text("cover"), // 不带尺寸参数，前端用 src/format.ts 的 imageUrl 生成
  pointCount: integer("point_count").notNull(),
  popularity: integer("popularity").notNull().default(0), // Bangumi 上看过 + 在看 + 想看的人数，没有地标的作品按它排序
  airDate: text("air_date"), // 首播日期 YYYY-MM-DD
  seriesId: integer("series_id"), // 所属系列的代表作 id（Bangumi 条目关系连成的系列，sync/bgm_archive.py）；单独一部为空
  seriesPoints: integer("series_points").notNull().default(0), // 所在系列的地标总数（不在系列里就是自己的地标数）
  seriesWorks: integer("series_works").notNull().default(1), // 所在系列的作品数
  nsfw: integer("nsfw", { mode: "boolean" }).notNull().default(false), // 成人向（Bangumi 标为 nsfw，或 manual.json 显式标注）：网站默认隐藏
  i18n: text("i18n", { mode: "json" }).$type<I18n>(), // 各语言标题（含机翻），见 sync/export.py
  search: text("search"), // 各语言名称折叠后的搜索键（sync/fold.py）
});

export const point = sqliteTable(
  "point",
  {
    bangumiId: integer("bangumi_id").notNull(),
    id: text("id").notNull(),
    name: text("name"),
    cn: text("cn"),
    lat: real("lat").notNull(),
    lng: real("lng").notNull(),
    priority: integer("priority"),
    ep: text("ep"),
    s: real("s"), // 画面在该集中的秒数
    image: text("image"), // 不带尺寸参数，同 cover
    origin: text("origin"),
    originLink: text("origin_link"),
    mark: text("mark"),
    source: text("source"), // 地标数据的出处（Anitabi、探访博客的网站名…），与截图署名 origin 分开
    sourceUrl: text("source_url"), // 出处原文链接
    updated: integer("updated"), // 地标最近一次新增或改动的时间（Unix 秒，sync/export.py 的 point_updated）；不知道时为空
    i18n: text("i18n", { mode: "json" }).$type<I18n>(), // 各语言地标名与备注（含机翻）
    search: text("search"), // 名称折叠后的搜索键，FTS5 索引建在这一列上
  },
  // updated 索引供「最近更新」按时间倒序翻页，只读最前面的若干行
  (t) => [primaryKey({ columns: [t.bangumiId, t.id] }), index("point_updated").on(t.updated)],
);
