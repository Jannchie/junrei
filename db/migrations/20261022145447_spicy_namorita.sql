ALTER TABLE `bangumi` ADD `popularity` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `bangumi` ADD `air_date` text;--> statement-breakpoint
-- 手写：作品名全文索引（Bangumi 全部动画约 3 万行，搜索不能每次全表扫描）。外部内容表，由 d1-import.sql 末尾的 rebuild 填充。
CREATE VIRTUAL TABLE `bangumi_fts` USING fts5(`search`, content='bangumi', tokenize='trigram');
