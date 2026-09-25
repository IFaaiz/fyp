# Enron candidate pool report

- Canonical input records: 517,401
- Input threads: 515,291
- Cue candidates available: 213,630
- Direct matches available: 213,036
- Context only candidates available: 594
- No cue records available: 303,771
- Selected records: 8,000 (target 8,000; overage 0)
- Selected direct matches: 5,973
- Selected context only matches: 19
- Selected random nonmatches: 2,000 (requested 2,000)
- Selected thread expansion records: 8
- Multi cue records: 3,745 selected / 109,323 available
- Thread-ID groups: 7,962 selected; 7,962 fully selected groups; 0 partial groups (0.0% partial)
- Selection mode: whole — whole derived thread-ID groups; target can be exceeded by complete selected groups
- Secondary thread suggestions enabled: True
- Input pairs suggested: 2,110 (4,220 records; confidence high_unverified)
- Eligible singleton rows / buckets: 320,971 / 94,519
- Oversized subject buckets skipped: 39 (7,892 records)
- Link coverage among eligible rows: 1.31%
- Deterministic seed: 2026
- Candidate pool JSONL: ai/data/interim/enron_candidates.jsonl
- Sampling metadata sidecar: ai/data/interim/enron_candidates.metadata.jsonl

## Thread sizes

> Complete is relative to derived thread IDs, which may include unverified heuristic pairs. Original canonical IDs are preserved in source_thread_id.

| Measure | Input thread-ID groups | Selected thread-ID groups |
| --- | ---: | ---: |
| Minimum | 1 | 1 |
| Median | 1 | 1 |
| 90th percentile | 1 | 1 |
| Maximum | 2 | 2 |

## Sampling category coverage

| Category | Available | Selected with any category cue | Primary-category selections | Coverage |
| --- | ---: | ---: | ---: | ---: |
| Meeting | 91,967 | 2,269 | 749 | 2.5% |
| Deadline | 7,393 | 809 | 748 | 10.9% |
| Report / document | 99,745 | 3,159 | 749 | 3.2% |
| Department / input | 4,239 | 749 | 747 | 17.7% |
| Follow-up | 42,627 | 1,334 | 748 | 3.1% |
| Approval | 49,138 | 1,618 | 751 | 3.3% |
| Update | 23,888 | 962 | 751 | 4.0% |
| Action / task | 55,211 | 2,040 | 749 | 3.7% |
| Random | 303,771 | 2,000 | 2,000 | 0.7% |

Counts for Selected with any category cue can overlap because one record may match multiple categories. Primary-category selections are exclusive: 5,992 primary-category rows + 2,000 random rows + 8 thread-expansion rows = 8,000 unique selected rows.

## Candidate recall risk

- Nonempty current_message but empty authored prefix after quote trimming: 35,309 / 517,401.
- Records with any raw lexical cue: 269,445; remaining direct candidates after quote trimming and precision guards: 213,036.
- Records losing cues at quote trimming: 16,123; records losing cues at precision guards: 43,788.

Quote trimming can miss a task if it appears only inside forwarded or quoted text. Precision guards can suppress implicit or subject-only tasks. These are potential candidate-recall risks; the affected records are not known false negatives.

| Cue | Lost at quote trimming | Suppressed by precision guards |
| --- | ---: | ---: |
| action | 1,252 | 502 |
| action_item | 12 | 1 |
| agenda | 301 | 135 |
| approval | 1,545 | 656 |
| assigned | 531 | 85 |
| attached | 6,142 | 13,529 |
| complete | 1,795 | 2,709 |
| deadline | 357 | 77 |
| due | 163 | 24 |
| follow_up | 174 | 109 |
| input | 411 | 528 |
| meeting | 1,737 | 659 |
| minutes | 1,113 | 576 |
| pending | 245 | 130 |
| presentation | 551 | 807 |
| provide | 3,126 | 4,508 |
| reminder | 322 | 260 |
| report | 2,065 | 10,025 |
| reschedule | 90 | 132 |
| review | 2,539 | 802 |
| schedule | 1,710 | 1,219 |
| send | 3,298 | 8,149 |
| submit | 825 | 565 |
| task | 1,251 | 336 |
| update | 1,570 | 8,844 |

## Qualitative cue audit

Manual review across two rounds and multiple sampled records in each category found useful examples such as meeting reschedules, explicit deadlines, and approval requests, alongside noise from blood-drive meetings, market and execution notices, Datek margin calls, Economist HTML, newsletters, access requests, generic report attachments, mailing-list notices, product ads, and attachment-list removal requests. Follow-up subjects without task context also produced hits. Duplicate-looking records with identical bodies can remain as separate candidates when they have distinct source Message-IDs; the canonical identity contract is ID-based, so review pools may still contain near-duplicates.

The random stratum means no current cue matched; it is not a set of verified negatives. It contains implicit actions (for example, requests to discuss something), meeting messages including a subject abbreviated ‘Mtg’, and ordinary personal mail.

When secondary linking is enabled, derived thread IDs group only strict one-to-one heuristic pairs. The output preserves each original ID in source_thread_id, marks thread_link_method='heuristic' and thread_link_confidence='high_unverified', and adds prior-message context to the later record. The rule confidence is uncalibrated; it does not recover all real conversations.

## Fine-grained cue coverage

| Cue | Direct available | Direct selected | Context available | Context selected | Unique available | Unique selected | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| meeting | 46,348 | 1,208 | 240 | 5 | 46,438 | 1,209 | 2.6% |
| schedule | 43,159 | 1,099 | 146 | 3 | 43,269 | 1,101 | 2.5% |
| reschedule | 2,478 | 49 | 13 | 0 | 2,486 | 49 | 2.0% |
| agenda | 5,442 | 210 | 30 | 0 | 5,461 | 210 | 3.8% |
| minutes | 12,686 | 406 | 32 | 3 | 12,710 | 408 | 3.2% |
| deadline | 4,841 | 530 | 10 | 3 | 4,848 | 533 | 11.0% |
| due | 2,904 | 321 | 16 | 0 | 2,916 | 321 | 11.0% |
| submit | 10,974 | 508 | 37 | 1 | 11,008 | 509 | 4.6% |
| report | 26,023 | 954 | 101 | 1 | 26,090 | 955 | 3.7% |
| presentation | 10,721 | 353 | 44 | 0 | 10,748 | 353 | 3.3% |
| approval | 20,957 | 729 | 93 | 2 | 21,024 | 731 | 3.5% |
| review | 34,613 | 1,159 | 179 | 4 | 34,748 | 1,161 | 3.3% |
| follow_up | 6,259 | 194 | 28 | 0 | 6,278 | 194 | 3.1% |
| reminder | 7,463 | 243 | 23 | 0 | 7,477 | 243 | 3.2% |
| input | 4,223 | 747 | 17 | 3 | 4,239 | 749 | 17.7% |
| action_item | 495 | 18 | 2 | 0 | 497 | 18 | 3.6% |
| action | 12,932 | 568 | 30 | 0 | 12,954 | 568 | 4.4% |
| task | 20,145 | 766 | 76 | 1 | 20,214 | 766 | 3.8% |
| assigned | 8,813 | 319 | 26 | 1 | 8,831 | 320 | 3.6% |
| pending | 4,313 | 191 | 9 | 0 | 4,322 | 191 | 4.4% |
| update | 23,796 | 959 | 118 | 6 | 23,888 | 962 | 4.0% |
| attached | 44,934 | 1,264 | 244 | 7 | 45,157 | 1,270 | 2.8% |
| send | 31,306 | 984 | 164 | 3 | 31,452 | 987 | 3.1% |
| provide | 37,234 | 1,392 | 130 | 4 | 37,355 | 1,395 | 3.7% |
| complete | 21,354 | 938 | 56 | 1 | 21,402 | 939 | 4.4% |

## Sender distribution

Selected sender counts by rank (addresses omitted):

- Rank 1: 223
- Rank 2: 190
- Rank 3: 172
- Rank 4: 147
- Rank 5: 133
- Rank 6: 129
- Rank 7: 115
- Rank 8: 100
- Rank 9: 96
- Rank 10: 95
- Rank 11: 84
- Rank 12: 62
- Rank 13: 59
- Rank 14: 59
- Rank 15: 57
- Rank 16: 55
- Rank 17: 54
- Rank 18: 54
- Rank 19: 52
- Rank 20: 48
- Rank 21: 47
- Rank 22: 46
- Rank 23: 45
- Rank 24: 42
- Rank 25: 40
- Rank 26: 40
- Rank 27: 38
- Rank 28: 38
- Rank 29: 35
- Rank 30: 35
- Rank 31: 35
- Rank 32: 34
- Rank 33: 33
- Rank 34: 32
- Rank 35: 31
- Rank 36: 31
- Rank 37: 29
- Rank 38: 28
- Rank 39: 28
- Rank 40: 28
- Rank 41: 27
- Rank 42: 26
- Rank 43: 25
- Rank 44: 25
- Rank 45: 24
- Rank 46: 24
- Rank 47: 23
- Rank 48: 22
- Rank 49: 21
- Rank 50: 21

Input sender counts by rank, top 50 (addresses omitted):

- Rank 1: 16,735
- Rank 2: 14,368
- Rank 3: 11,411
- Rank 4: 9,149
- Rank 5: 8,801
- Rank 6: 8,777
- Rank 7: 8,587
- Rank 8: 8,490
- Rank 9: 6,759
- Rank 10: 5,438
- Rank 11: 5,265
- Rank 12: 5,158
- Rank 13: 5,112
- Rank 14: 4,387
- Rank 15: 4,343
- Rank 16: 4,111
- Rank 17: 4,000
- Rank 18: 3,888
- Rank 19: 3,706
- Rank 20: 3,578
- Rank 21: 3,564
- Rank 22: 3,427
- Rank 23: 3,262
- Rank 24: 3,112
- Rank 25: 3,069
- Rank 26: 2,963
- Rank 27: 2,812
- Rank 28: 2,742
- Rank 29: 2,681
- Rank 30: 2,636
- Rank 31: 2,585
- Rank 32: 2,496
- Rank 33: 2,435
- Rank 34: 2,195
- Rank 35: 1,941
- Rank 36: 1,840
- Rank 37: 1,829
- Rank 38: 1,824
- Rank 39: 1,799
- Rank 40: 1,728
- Rank 41: 1,719
- Rank 42: 1,701
- Rank 43: 1,687
- Rank 44: 1,655
- Rank 45: 1,456
- Rank 46: 1,454
- Rank 47: 1,388
- Rank 48: 1,346
- Rank 49: 1,325
- Rank 50: 1,247

Keyword cues and random sampling strata are review-sampling aids. They do not assign project labels; the canonical record labels and annotation status remain unchanged.
