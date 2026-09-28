# Cross-source leakage and duplicate audit

## Scope and method

Scanned the full canonical Enron and MailEx JSONL inputs: 517,401 Enron records and 3,936 MailEx records (521,337 total). The audit reads `current_message` as the primary authored-body field and `raw_body` as a separate whole-body signature. It never uses quote containment or partial-body matching. Reports and the sidecar contain identifiers and aggregate counts only; no email text is emitted.

Exact matching uses NFKC Unicode normalization, case folding, and whitespace collapse while preserving punctuation. Strong matching hashes the ordered alphanumeric token stream with punctuation and spacing removed; spaced-token hashes are also retained as a diagnostic. Subject-plus-body matching combines a reply-prefix-normalized subject with the compact token signature. Only bodies with at least 80 normalized characters and 12 alphanumeric tokens are linkable. Short-message signatures are measured but excluded from grouping. Same-source Enron near matches require the same normalized subject, at least 120 characters and 20 tokens, 0.90 token-length ratio, and at least 0.92 Jaccard overlap of five-token shingles. Subject buckets larger than 40 are skipped to avoid ambiguous mass merges.

`raw_body` is compared only as a complete independent signature. Because the canonical Enron schema does not expose original Message-ID as a separate field, exact duplicate content with different Message-IDs is detected by matching content signatures; distinct Enron `email_id` values provide the available identity distinction. This cannot verify Message-ID differences directly.

## Results

| Measure | Result |
|---|---:|
| Leakage components across all records | 261,027 |
| Cross-source components with Enron and MailEx members | 943 |
| Exact current/raw signature groups with cross-source matches | 9 |
| Unique MailEx records with an exact current/raw match | 7 |
| Unique Enron records with an exact current/raw match | 8 |
| Potential exact record pairs, summed by signature | 10 |
| Compact-token current/raw signature groups (includes exact) | 1,789 |
| Unique MailEx records with compact-token match | 1,475 |
| Unique Enron records with compact-token match | 2,441 |
| Spaced-token current/raw signature groups | 1,565 |
| Subject + compact-token signature groups | 1,669 |
| Unique MailEx records with subject + body match | 1,381 |
| Short/under-threshold cross-source signature groups excluded | 533 |
| Short/under-threshold record hits by signature (not unique) | 9,051 |
| Largest excluded short signature group | 5,411 |
| Enron same-subject near-match links added | 2,196 |
| Enron subject buckets skipped as too large | 407 |
| Enron near-match pairs tested | 581,395 |
| Enron content-duplicate components with at least two Enron records | 119,637 |
| Enron records in those duplicate components | 376,490 |
| Largest Enron duplicate component (Enron records) | 311 |
| Source thread groups joined | 1,500 |

Exact and compact-token unique-record counts are independently deduplicated within their signature families. A MailEx record may match multiple Enron records. Potential pair count is summed per signature and can count one record pair more than once when it matches both `current_message` and `raw_body` signatures; it is not a count of unique record pairs.

## Candidate-pool overlap

| Measure | Result |
|---|---:|
| Candidate IDs in candidate file | 8,000 |
| Candidate IDs found in full Enron | 8,000 |
| Candidate records in a cross-source leakage component | 28 |
| Candidate records with an exact current/raw cross-source signature | 0 |
| Candidate records with a compact-token cross-source signature | 28 |
| Candidate records with a subject + body cross-source signature | 28 |
| Candidate records in an Enron duplicate component | 6,196 |
| Candidate groups overlapping MailEx | 27 |
| Candidate groups with duplicate Enron records | 5,692 |

## Sidecar integrity and 1,400-record seed coverage

Validated all 521,337 sidecar rows against the canonical source files: every `source_dataset`, `email_id`, and `thread_id` matches its source record; all source-qualified IDs are unique; all rows in each component have consistent component-level `match_kind`. There are 261,027 leakage groups and 943 cross-source groups.

The 1,400-record `training_silver_1400/annotation_seed_1400.jsonl` was checked using only source IDs and thread metadata. All 1,400 unique IDs resolve to the sidecar. The seed has 1,396 distinct leakage groups: 1,392 singleton seed groups and four groups containing two seed records each. Six seed records belong to groups that also contain a record from the other source. Four seed records carry candidate-generated heuristic thread IDs that differ from the canonical Enron thread IDs in this sidecar; their source IDs resolve correctly. Downstream joins should retain canonical IDs and union any approved derived-thread aliases separately.

## Sidecar and limitations

The ignored sidecar `ai/data/interim/leakage_groups.jsonl` has one row per source record with `source_dataset`, `email_id`, `thread_id`, stable `leakage_group_id`, and component-level `match_kind`. Component IDs are deterministic hashes of the lexicographically smallest source-qualified email identity. Downstream splitting must union both source-qualified thread IDs and these leakage IDs.

Near-duplicate matching is a conservative token-shingle heuristic, not semantic identity detection. It misses paraphrases, body edits outside the thresholds, records with changed subjects, and subject buckets over the size cap. Compact-token matching can collapse token-boundary differences; the minimum length/token thresholds and subject-body diagnostic reduce short generic collisions. No metric here is a human-reviewed correctness estimate.

A supervisor sampled eight deterministic cross-source components and the two largest components. The largest Enron component (311 records) shares an identical legal-signature body across different subjects. It remains grouped because the body matches exactly, which is conservative for split isolation but can over-group boilerplate or extraction artifacts. Large same-body, multi-subject groups should be treated as possible boilerplate during dataset curation; this audit does not reinterpret their content identity or remove them from the sidecar.
