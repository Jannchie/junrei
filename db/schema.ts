import { integer, primaryKey, real, sqliteTable, text } from "void/schema-d1";

// 数据由 sync/ 同步自 Anitabi，再经 sync/export.py 生成 SQL 全量导入；应用只读。
// 地标名搜索用的 FTS5 虚表 point_fts 不在 Drizzle 里，见 db/migrations 中的 point_fts 迁移。

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
  },
  (t) => [primaryKey({ columns: [t.bangumiId, t.id] })],
);
