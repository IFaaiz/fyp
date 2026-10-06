CREATE TABLE `calibration_round_sources` (
	`round_id` text NOT NULL,
	`source_id` text NOT NULL,
	`source_sha256` text NOT NULL,
	`position` integer NOT NULL,
	`created_at` text NOT NULL,
	PRIMARY KEY(`round_id`, `source_id`),
	FOREIGN KEY (`source_id`) REFERENCES `sources`(`id`) ON UPDATE no action ON DELETE no action
);
