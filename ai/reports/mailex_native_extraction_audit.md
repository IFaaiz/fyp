# Native MailEx Extraction Audit

This report audits a faithful adapter of the published MailEx event annotations. It does not map MailEx roles to FYP labels. Converted message text and identifiers remain under the ignored private experiment directory.

## Official split inventory

| Split | Source files / threads | Messages | Native events (excluding O markers) | O markers | Source aggregate SHA-256 |
|---|---:|---:|---:|---:|---|
| train | 1200 | 3117 | 6571 | 636 | `8069053e945c079ed7410b6d535e5e61bf8dc2b5c87658ae2d0be76cac0d3710` |
| dev | 150 | 414 | 946 | 70 | `bf031ec8363be29d35ee1c26eabf31b218211a3277de81086d9eb695a0e4e681` |
| test | 150 | 405 | 875 | 70 | `3d46f583177397ec67f1eb345c674e7c57e154621959a614bc15b7fe3b5a18d5` |

Each source JSON file represents a thread. Each entry in `sentences` is a turn token sequence aligned to `events.turn_N`; the adapter emits one row per turn. Row text is reconstructed with a single ASCII space between source tokens, and every character offset is half-open relative to that reconstruction.

The extracted benchmark has 11 non-O event types, including `Amend_Action_Data` (2 train, 1 dev, 0 test instances). The source also stores O marker records; these are preserved separately and excluded from event counts. The extracted event inventory therefore differs from the 10 event types described in the referenced documentation.

## Native event type counts

| Event type (source spelling) | Train | Dev | Test |
|---|---:|---:|---:|
| `Amend_Action_Data` | 2 | 1 | 0 |
| `Amend_Data` | 148 | 24 | 21 |
| `Amend_Meeting_Data` | 41 | 7 | 7 |
| `Deliver_Action_Data` | 2482 | 385 | 328 |
| `Deliver_Data` | 1474 | 172 | 174 |
| `Deliver_Meeting_Data` | 373 | 57 | 57 |
| `Request_Action` | 1080 | 147 | 149 |
| `Request_Action_Data` | 177 | 29 | 27 |
| `Request_Data` | 555 | 86 | 80 |
| `Request_Meeting` | 200 | 31 | 28 |
| `Request_Meeting_Data` | 39 | 7 | 4 |

## Case-sensitive raw role inventory (25 values)

Role strings below are exact native values, with counts of contiguous BIO argument runs. Case is preserved; the similarly named capitalization variants remain separate values.

| Raw role | Train | Dev | Test |
|---|---:|---:|---:|
| `Action Date` | 618 | 74 | 79 |
| `Action Description` | 3813 | 571 | 511 |
| `Action Members` | 3191 | 482 | 424 |
| `Action Time` | 98 | 9 | 11 |
| `Amend Date` | 14 | 2 | 1 |
| `Amend Members` | 93 | 16 | 14 |
| `Amend Time` | 4 | 0 | 1 |
| `Data Owner` | 12 | 2 | 1 |
| `Data Type` | 35 | 2 | 1 |
| `Data Value` | 1275 | 156 | 131 |
| `Data idString` | 2103 | 266 | 266 |
| `Deliver Date` | 20 | 4 | 2 |
| `Deliver Members` | 169 | 22 | 18 |
| `Deliver Time` | 5 | 1 | 2 |
| `Deliver members` | 366 | 34 | 47 |
| `Meeting Agenda` | 292 | 43 | 37 |
| `Meeting Date` | 292 | 51 | 48 |
| `Meeting Location` | 142 | 22 | 18 |
| `Meeting Members` | 933 | 142 | 160 |
| `Meeting Name` | 159 | 29 | 22 |
| `Meeting Time` | 189 | 28 | 25 |
| `Request Date` | 26 | 2 | 1 |
| `Request Members` | 94 | 7 | 12 |
| `Request Time` | 8 | 1 | 1 |
| `Request members` | 328 | 34 | 37 |

## Case-sensitive role-run comparison

The unchanged mapper parser joins BIO runs using case-folded role equality. The native adapter preserves exact role case, so a mid-span change between source spellings starts a separate flagged I run rather than merging roles.

| Split | Native case-sensitive runs | Legacy case-folded runs | Additional native runs | Native orphan-I runs | Legacy orphan-I runs | Additional native orphan-I runs | Case-fold-only restart starts |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 14279 | 14240 | 39 | 182 | 143 | 39 | 39 |
| dev | 2000 | 1996 | 4 | 25 | 21 | 4 | 4 |
| test | 1870 | 1863 | 7 | 27 | 20 | 7 | 7 |
| **Total** | 18149 | 18099 | 50 | 234 | 184 | 50 | 50 |

Totals are 18,149 native case-sensitive BIO runs versus 18,099 legacy case-folded runs. The 50-run difference matches 50 additional orphan-I restarts when source role capitalization changes. The adapter retains all raw source tags and labels; no runs are suppressed.

Context and revision are retained as argument qualifiers. Raw tags use forms such as `EventType:Context: B-Role` and `EventType:Revision: I-Role`; the adapter stores both the normalized qualifier and its source spelling, plus every original BIO tag.

## Parse and structure audit

| Split | Threads | Messages | Events | Empty token arrays | Empty reconstructed text | Empty token values | Misaligned arrays | Trigger parse errors | Out-of-range indices | Trigger text/index mismatches | Malformed BIO events | Orphan I events | Label length mismatches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 1200 | 3117 | 6571 | 0 | 272 | 273 | 0 | 0 | 0 | 0 | 0 | 148 | 0 |
| dev | 150 | 414 | 946 | 0 | 25 | 25 | 0 | 0 | 0 | 0 | 0 | 19 | 0 |
| test | 150 | 405 | 875 | 0 | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 20 | 0 |

Any malformed annotation is retained in its source fields and marked on the converted row or event. The adapter does not shift indices, repair BIO transitions, normalize role case, or drop malformed markers. O records are stored under `outside_markers` because they are source negative markers rather than event instances.

Argument spans are created as contiguous runs from BIO labels. Trigger indices are kept in source order and split into contiguous segments; out-of-range indices are flagged and omitted only from derived segments, while the raw source trigger is retained. Offsets describe reconstructed text, not byte offsets into an unavailable original message string.

## Event and argument geometry

Pairs are counted within each message. A trigger or argument overlap means the two token-index sets share at least one token. Nesting means one nonidentical set is a strict subset of the other; partial overlap means intersection without containment. Shared arguments across events have identical token-index sets; role-and-span matches additionally require exact role and qualifier equality.

| Split | Trigger overlap pairs | Trigger nested pairs | Trigger partial pairs | Argument overlap pairs | Argument nested pairs | Argument partial pairs | Exact shared argument spans across events | Duplicate event instances | Repeated role runs within event | Discontinuous triggers | Discontinuous BIO spans | Argument overlaps own trigger |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 154 | 16 | 131 | 1355 | 318 | 11 | 1026 | 2 | 699 | 151 | 0 | 6374 |
| dev | 24 | 0 | 24 | 128 | 33 | 0 | 95 | 0 | 91 | 27 | 0 | 940 |
| test | 13 | 0 | 12 | 150 | 38 | 1 | 111 | 1 | 92 | 17 | 0 | 851 |

## Split hygiene and source equivalence

| Check | Result |
|---|---:|
| Thread ID overlap dev__test | 0 |
| Thread ID overlap train__dev | 0 |
| Thread ID overlap train__test | 0 |
| Empty-content message pairs dev__test (reported separately) | 750 pairs |
| Nonempty exact token-sequence duplicate pairs dev__test | 19 pairs across 8 groups; affected messages 11 / 10 |
| Nonempty normalized text duplicate pairs dev__test | 37 pairs across 8 groups; affected messages 13 / 12 |
| Empty-content message pairs train__dev (reported separately) | 6800 pairs |
| Nonempty exact token-sequence duplicate pairs train__dev | 113 pairs across 29 groups; affected messages 53 / 32 |
| Nonempty normalized text duplicate pairs train__dev | 301 pairs across 27 groups; affected messages 80 / 34 |
| Empty-content message pairs train__test (reported separately) | 8160 pairs |
| Nonempty exact token-sequence duplicate pairs train__test | 102 pairs across 25 groups; affected messages 53 / 28 |
| Nonempty normalized text duplicate pairs train__test | 230 pairs across 24 groups; affected messages 66 / 28 |
| Empty-content messages in dev | 25 |
| Nonempty exact duplicate pairs within dev | 7 pairs; excess copies 4 |
| Empty-content messages in test | 30 |
| Nonempty exact duplicate pairs within test | 6 pairs; excess copies 5 |
| Empty-content messages in train | 272 |
| Nonempty exact duplicate pairs within train | 377 pairs; excess copies 148 |
| Cross-split near duplicates, 5-token-shingle Jaccard ≥ 0.90 | 42 pairs |
| `full_data` files | 1500 |
| `raw_threads` files | 1506 |
| Official split files exactly present in `full_data` | 1500 / 1500 |
| `full_data` exactly equals official split union by filename and bytes | True |

Empty reconstructed text is kept in the converted dataset and excluded from nonempty duplicate-leakage counts; its split pair counts are reported separately because repeated blank turns are not evidence of copied email content. Normalized duplicates use case-folded alphanumeric content. Near duplicates use distinct 5-token shingles, Jaccard ≥ 0.90, at least 20 tokens, and a length ratio of at least 0.85. These checks are aggregate-only and do not print source text or identifiers.

The source provides message-turn boundaries but no sentence boundary field inside a turn. `arguments_outside_trigger_sentence_estimate` is therefore based on punctuation-derived sentence estimates and is a diagnostic only; turn-level annotation membership is exact.

| Split | Arguments outside estimated trigger sentence | Events with an argument outside estimated trigger sentence |
|---|---:|---:|
| train | 1671 | 1274 |
| dev | 187 | 139 |
| test | 187 | 133 |

## Unfiltered global registry fingerprint inventory

This comparison read metadata only from index version `global-leakage-v2.1` across all 28129 global registry records. It is not filtered to boundary protected membership; the matches include existing MailEx registry rows and must not be read as protected overlap. No protected message text or source IDs were accessed.

| Split | Global body exact hash matches | Global body token hash matches | Global raw text-view hash matches |
|---|---:|---:|---:|
| train | 2215 | 2215 | 1173 |
| dev | 295 | 295 | 145 |
| test | 290 | 290 | 148 |

These are whole-index inventory counts, not protected-subset matches. MailEx original Enron identities are unresolved; unmatched hashes do not establish FYP isolation.

## FYP-safe exclusion variant

This separate model view filters native messages against only `boundary_manifest.protected_ids`, then expands hits through the global index's `leakage_group_id` and explicit links. If one message in a thread matches that connected component, every message from the thread is excluded from its split's safe view. It is an exclusion variant; the official native split rows and counts above remain intact.

The membership comparison found 13089 boundary records, of which 13089 exist in the global index; 14611 records are in their connected index components.

| Split | Direct protected messages / threads | Component matched messages / threads | Excluded messages / threads | Retained messages / threads | Retained events | FYP-safe JSONL SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| train | 31 / 31 | 286 / 139 | 355 / 139 | 2762 / 1061 | 5729 | `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333` |
| dev | 4 / 4 | 40 / 19 | 53 / 19 | 361 / 131 | 828 | `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d` |
| test | 3 / 3 | 34 / 15 | 42 / 15 | 363 / 135 | 772 | `1d728079223c64892d1925b0d6bee90c8e3f1e95253a9629256be7de6d882f68` |

The safe files are `train_fyp_safe.jsonl`, `dev_fyp_safe.jsonl`, and `test_fyp_safe.jsonl` under the ignored experiment directory. The manifest contains hashes and aggregate counts, no IDs or message text. This policy uses exact body, token, and raw text-view fingerprints; expansion only covers associations recorded in the index and does not resolve hidden Enron identities or paraphrases.

## Protected FYP boundary

This adapter lives under the ignored private experiment directory for converted data and under a separate native module. It does not alter MailEx V1/V2 outputs, their registry, FYP label mappings, or model artifacts. Original Enron identity resolution remains unverified; this audit makes no claim of additional FYP isolation.
