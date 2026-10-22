ALTER TABLE `bangumi` ADD `series_id` integer;--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `bangumi_series` ON `bangumi` (`series_id`);
