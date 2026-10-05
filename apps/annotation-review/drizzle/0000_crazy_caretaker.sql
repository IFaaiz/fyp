CREATE TABLE `reviewers` (
	`user_id` text PRIMARY KEY NOT NULL,
	`email` text NOT NULL,
	`display_name` text NOT NULL,
	`slot` integer NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `reviewer_slots` ON `reviewers` (`slot`);--> statement-breakpoint
CREATE UNIQUE INDEX `reviewer_emails` ON `reviewers` (`email`);--> statement-breakpoint
CREATE TABLE `reviews` (
	`source_id` text NOT NULL,
	`user_id` text NOT NULL,
	`annotation_json` text NOT NULL,
	`status` text NOT NULL,
	`revision` integer NOT NULL,
	`active_ms` integer NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`submitted_at` text,
	PRIMARY KEY(`source_id`, `user_id`),
	FOREIGN KEY (`source_id`) REFERENCES `sources`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`user_id`) REFERENCES `reviewers`(`user_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `review_revisions` (
	`id` text PRIMARY KEY NOT NULL,
	`source_id` text NOT NULL,
	`user_id` text NOT NULL,
	`revision` integer NOT NULL,
	`annotation_json` text NOT NULL,
	`status` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `sources` (
	`id` text PRIMARY KEY NOT NULL,
	`position` integer NOT NULL,
	`subject` text NOT NULL,
	`body` text NOT NULL,
	`source_json` text NOT NULL,
	`sha256` text NOT NULL,
	`allocation` text NOT NULL,
	`common_blind` integer NOT NULL,
	`owner_slot` integer NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `source_positions` ON `sources` (`position`);