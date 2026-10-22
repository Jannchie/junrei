CREATE TABLE `bangumi` (
	`id` integer PRIMARY KEY NOT NULL,
	`cn` text,
	`title` text,
	`en` text,
	`city` text,
	`cat` text,
	`color` text,
	`cover` text,
	`point_count` integer NOT NULL,
	`search` text
);
--> statement-breakpoint
CREATE TABLE `point` (
	`bangumi_id` integer NOT NULL,
	`id` text NOT NULL,
	`name` text,
	`cn` text,
	`lat` real NOT NULL,
	`lng` real NOT NULL,
	`priority` integer,
	`ep` text,
	`s` real,
	`image` text,
	`origin` text,
	`origin_link` text,
	`mark` text,
	`search` text,
	PRIMARY KEY(`bangumi_id`, `id`)
);
--> statement-breakpoint
-- 手写：地标名全文索引，建在折叠后的搜索键上（trigram 支持中日文子串匹配，查询需至少 3 个字符）。
-- 外部内容表，数据由 data/d1-import.sql 末尾的 rebuild 填充。
CREATE VIRTUAL TABLE `point_fts` USING fts5(`search`, content='point', tokenize='trigram');
