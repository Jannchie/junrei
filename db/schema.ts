import { integer, primaryKey, real, sqliteTable, text } from "void/schema-d1";

// 数据由 sync/ 同步自 Anitabi，再经 sync/export.py 生成 SQL 全量导入；应用只读。
// 地标名搜索用的 FTS5 虚表 point_fts（建在 point.search 上）不在 Drizzle 里，见 db/migrations 末尾的手写部分。

/**
 * 多语言文本（sync/export.py 从 data/enrich.sqlite 的 translation 表挑出每种语言最可信的一条）。
 * name：作品标题或地标名；mark：地标备注；mt：机器翻译的条目，如 "name.en"。
 */
export interface I18n {
  name?: Partial<Record<"zh-Hans" | "zh-Hant" | "ja" | "en", string>>;
  mark?: Partial<Record<"zh-Hans" | "zh-Hant" | "ja" | "en", string>>;
  mt?: string[];
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
    i18n: text("i18n", { mode: "json" }).$type<I18n>(), // 各语言地标名与备注（含机翻）
    search: text("search"), // 名称折叠后的搜索键，FTS5 索引建在这一列上
  },
  (t) => [primaryKey({ columns: [t.bangumiId, t.id] })],
);
