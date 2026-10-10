CREATE TABLE `direct_label_reviews` (
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
CREATE TABLE `direct_label_review_revisions` (
	`id` text PRIMARY KEY NOT NULL,
	`source_id` text NOT NULL,
	`user_id` text NOT NULL,
	`revision` integer NOT NULL,
	`annotation_json` text NOT NULL,
	`status` text NOT NULL,
	`created_at` text NOT NULL
);
