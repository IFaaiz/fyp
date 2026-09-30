# Dataset engineering progress — 25 September 2026

## Status

**30 September current status:** The accepted count is **618** after a further
supervisor scope veto during the rare-label reread and strict acceptance of
166 rows from the replacement seed's second tranche. All accepted records remain
AI silver. The remaining replacement tranches have resumed two blind Luna
reviews and independent third audit. A concrete Lotus quoted-header defect in
baseline feature cleaning was repaired, and the standard scikit-learn optimizer
can now export portable model weights; the full suite passed **107 tests**.
The historical counts below describe their respective earlier checkpoints.

The [second replacement-tranche audit](training_silver_extension_second300_third_audit.md)
covered all 202 required cases. It retained 166 rows (98 project-related, 68
`NON_PROJECT`) and excluded 134. The current source join passes canonical
validation with zero errors and resolves 618 distinct leakage groups. Current
label supports are `NON_PROJECT` 323, `MEETING` 90, `ACTION_REQUEST` 105,
`GENERAL_UPDATE` 195, `DEADLINE` 56, `DEPARTMENTAL_INPUT` 8,
`REPORT_REQUEST` 10, `FOLLOW_UP` 11, and `APPROVAL` 17. Counts overlap; the
1,000-row gate and rare-label coverage work remain outstanding.

The AI/NLP workstream has an annotation schema, a verified MailEx conversion, and a fully ingested and validated official Enron corpus. The 50,000-file staged pass and the 517,401-file full pass both validate. Candidate sampling, Label Studio conversion, and independent-review tooling exist; the full-corpus candidate pool and first independent human assignments have been prepared. No model has been trained and no human gold labels have been claimed.

**27 September update:** Two blind AI pilots and a direct AI correctness audit are complete. A classification-only silver batch now contains 41 AI suggestions and 9 held-back records; its spans are empty pending semantic review. See the [silver-batch report](ai_silver_classification.md) and [v3 protocol](../annotation/ai_review_protocol_v3.md). No gold set or model-accuracy estimate has been created.

**28 September update:** A further 100 Enron messages received two independent classification-only AI reviews. A strict agreement and supervisor gate retained 66 provisional AI-silver decisions (65 `NON_PROJECT`, one multi-label project message) and excluded 34 uncertain cases; a second AI audit read all accepted rows. A text-free provisional manifest now selects 1,400 distinct messages for a larger, project-enriched review, with source messages kept in ignored data paths. Cross-source Enron/MailEx leakage grouping is in progress and remains a hard gate before a split or model evaluation. TF-IDF plus one-vs-rest logistic-regression infrastructure is implemented but has not been trained on real silver data. See [first expansion audit](training_expansion_100_audit.md), [baseline infrastructure](silver_classifier_training_baseline.md), and [extraction status](extraction_readiness.md).

**28 September selection correction:** The [full cross-source leakage audit](cross_source_leakage_audit.md) is complete and its 521,337-record group sidecar is available locally. The first 600 rows of the 1,400 selection have two blind reviews, but 601–1,100 are almost entirely sparse calendar/task exports. Review of that low-value segment stopped. A replacement 1,200-record seed was selected from the full Enron source using authored-text and leakage-group checks; two blind reviews and independent third audit are in progress. See the [selection correction report](training_silver_selection_correction.md). The 1,000-accepted-record training gate has not yet been reached; no model or accuracy metric has been produced.

**First audited 300:** The [third-audit gate](training_silver_first300_third_audit.md) retained 145 text-free AI-silver decisions from the first 300 reviewed candidates. Combined with 41 pilot and 66 earlier expansion decisions, 252 AI-silver rows are available for classification prototyping; the new batch contributes 56 project-related records and 89 `NON_PROJECT`. The strict 1,000-row training gate still applies.

**Second audited 300:** The [second third audit](training_silver_second300_third_audit.md) covered all 215 required cases. Excluding the calendar/task-export selection error and applying the same strict disagreement, audit, supervisor, and leakage gates retained 61 more AI-silver rows (45 project-related, 16 `NON_PROJECT`). The cumulative accepted count is **313**. Blind review of the replacement 1,200-record authored-text seed continues; no model or validation metric has been produced.

**Replacement seed, first audited 300:** The [independent third audit](training_silver_extension_first300_third_audit.md) covered all 216 required cases. Strict adjudication retained 140 further rows (74 project-related, 66 `NON_PROJECT`) and excluded 160 uncertain or vetoed cases. The cumulative accepted count is **453**, with one distinct full-corpus leakage group per accepted record. A further 600-message, leakage-disjoint rare-function reserve pool has been selected for blind review. The 1,000-row gate still applies; no model or validation metric has been produced.

## Correctness and schema

- A source-qualified thread containing any real `annotation.status == "gold"` record is assigned wholly to test. The validator rejects gold in train/validation and synthetic records in test. Synthetic gold is invalid.
- Annotation status, source, and annotator must agree: AI prelabels identify AI; human-reviewed and gold records identify a human annotator. AI prelabelling cannot overwrite human-reviewed or gold records. An unlabelled record has `labels=[]`, though verified provisional source-dataset spans may remain.
- MailEx canonical spans with the same field, offsets, and label are deduplicated; each unique span retains all mapped event provenance.
- The schema now has eight project labels plus exclusive `NON_PROJECT`, including `ACTION_REQUEST`, and eleven extraction types, including `DEADLINE_TIME`. The rationale and alternatives are in [schema decisions](schema_decisions.md). Thirteen synthetic examples demonstrate the revised boundaries; none is gold.

## Source acquisition and measured data

| Source/stage | Files scanned | Unique records | Duplicates removed | Parser defects | Threads | Singleton threads | Runtime | Peak working set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MailEx full | 1,500 source threads | 3,936 | — | — | 1,500 | — | — | — |
| Enron 1,000 | 1,000 | 1,000 | 0 | 0 | 1,000 | 1,000 | 6.478 s | 29,323,264 B |
| Enron 10,000 | 10,000 | 10,000 | 0 | 0 | 10,000 | 10,000 | 62.556 s | 49,291,264 B |
| Enron 50,000 | 50,000 | 50,000 | 0 | 6 | 50,000 | 50,000 | 317.295 s | 116,670,464 B |
| Enron full | 517,401 | 517,401 | 0 key-based | 30 | 517,401 | 517,401 | 5,776.93 s | 923,627,520 B |

MailEx: 3,609 nonempty and 327 empty messages; 8,392 source events and 18,099 source argument spans. Of those argument spans, 2,979 mapped directly to provisional canonical spans before deduplication, 13,928 were ambiguous, and 1,192 were unmapped. Deduplication removed 57 repeated canonical instances, leaving **2,922 unique canonical spans** and zero duplicate canonical keys. All FYP classification labels remain unlabelled. MailEx messages are reconstructed from source tokens; social/non-project activities illustrate why mapped spans require human project-scope review. Details: [source report](mailex_source.md), [stats](mailex_stats.json).

Enron: the official CMU CALO archive is 443,254,787 bytes with locally computed SHA-256 `b3da1b3fe0369ec3140bb4fbce94702c33b7da810ec15d718b3fadf5cd748ca7`. Its safe extraction produced 517,401 files and 3,500 directories (1,421,183,736 uncompressed file bytes), with zero extraction errors. The checksum was not compared with a publisher checksum. Raw and generated email text live under ignored `ai/data/**`. The zero duplicate count is for the Message-ID/body-digest key; manual review found identical-looking content under distinct IDs, so semantic duplicates may remain. The full validator checked 517,401 records with zero errors, though 10,201 derived `current_message` fields are empty at quote/forward boundaries while their raw bodies remain present. Details: [source provenance](../data/raw/enron/README.md), [acquisition measurements](enron_acquisition.json), [staged runs](enron_scale_staged.json), [full run](enron_full_stats.json).

### Metadata and thread quality in Enron runs

| Stage | Raw body present | Current message empty | Subject present | Sender present | Recipients present | CC present | Timestamp present | Message-ID present | References | In-Reply-To | Multi-message threads |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1,000 | 12 | 698 | 1,000 | 1,000 | 38 | 1,000 | 1,000 | 0 | 0 | 0 |
| 10,000 | 10,000 | 243 | 8,097 | 10,000 | 9,742 | 933 | 10,000 | 10,000 | 0 | 0 | 0 |
| 50,000 | 50,000 | 889 | 46,873 | 50,000 | 47,435 | 10,274 | 50,000 | 50,000 | 0 | 0 | 0 |
| Full | 517,401 | 10,201 | 498,214 | 517,399 | 502,681 | 128,824 | 517,401 | 517,401 | 0 | 0 | 0 |

The full CMU release contains no RFC `References` or `In-Reply-To` values, so explicit-only reconstruction yields **517,401 single-message threads, zero two-message threads, and zero threads with three or more messages**. The optional secondary rule uses a normalized subject plus a later `Re:` within seven days, reciprocal participant addresses, distinct senders, and an unambiguous one-to-one match. In the 50,000-file audit, it suggested 249 pairs among 30,022 eligible singleton records (1.66%); one common-subject bucket of 186 records was skipped. These links are marked `heuristic` and `high_unverified`, preserve original thread IDs, and remain uncalibrated. Thirty manually reviewed suggested pairs had no clearly unrelated pair and one ambiguous pair; this is a qualitative check, not a precision estimate. The full derived candidate pool used 2,110 suggested pairs across the input (4,220 records, 1.31% of 320,971 eligible singleton records), and selected 38 complete pairs; the original canonical input remains singleton-only.

## Candidate pool and annotation preparation

A capped, deterministic candidate selector retains direct cue, context-cue, random, and thread-expansion reasons in a JSONL sidecar while leaving canonical `labels` unchanged. The **full-corpus pool** has 8,000 records across 7,962 complete derived thread groups: 5,973 direct-cue records, 19 context-only cue records, 2,000 seeded no-cue records (25%), and 8 thread-expansion records. The eight exclusive primary cue strata have 747–751 selections each; cue membership counts overlap when one email matches several categories. The whole-thread mode selected 38 complete two-message heuristic pairs (76 records), zero partial groups, and zero target overage. The full input offered 213,630 cue candidates and 303,771 no-cue records. Full-pool cue inspection again found useful project emails mixed with newsletters, marketing, routine system approvals, and unrelated documents; random/no-cue is a sampling category, not verified `NON_PROJECT`. A manual sample of 10 selected pairs appeared conversational, but the link rule remains uncalibrated and could join parallel messages about the same subject. Quote trimming and precision guards reduce cue coverage; see the [full candidate report](enron_candidate_pool.md) for measured potential recall risks and distribution. The [50,000-file linked audit](../data/interim/enron_scale/enron_50000_candidates_heuristic_audit.md) records staged behavior.

Label Studio has a multi-label classification and two-field span configuration, separate thread context/metadata display, canonical import/export conversion, UTF-16 offset handling, and tests. The final **250-record real Enron seed** was drawn from the validated full pool with deterministic seed 2026. It contains 172 direct-cue, 7 context-only cue, 8 thread-expansion, and 63 no-cue records, including 12 complete two-message heuristic pairs (24 records). A and B task files have identical email IDs and order, blank annotations and predictions, and no synthetic, AI-prelabelled, human-reviewed, or gold records. The [assignment manifest](../data/annotated/human/label_studio_seed/manifest.json) uses repository-relative paths. The final A-file blank-task transport import reproduced all 250 canonical records exactly; an earlier 250-record staged dry run also round-tripped losslessly. Agreement and adjudication scripts are implemented, but no human agreement score exists yet. See [Label Studio setup](../annotation/label_studio/README.md).

## Verification and remaining work

- Unit suite: 107 tests passed in the 30 September supervisor run, including gold isolation, validator invariants, MailEx span deduplication, same-sender thread-link rejection, complete-pair seed selection, Label Studio conversion/agreement logic, cross-source leakage fixtures, the silver-classifier loader/split and abstention-filtering fixtures, Lotus sender/date quoted-header isolation, and scikit-learn coefficient export equivalence.
- Canonical validator: 3,936 MailEx records, 517,401 full Enron records, 8,000 full candidate-pool records, and 13 synthetic examples each passed with zero errors. The supervisor reran the full Enron and candidate validators after final generation. The full pool sidecar covers exactly the selected IDs and thread IDs; an in-memory thread split of 6,000/800/1,200 records had zero isolation errors.
- Full Enron ingestion and validation are complete. The full candidate pool is built and validated. The human seed and blank-task transport verification are complete. Human annotation, adjudication, and gold reservation remain the gates for a defensible accuracy estimate; the AI-only silver batch is available for prototyping while that work is deferred.
- The planned human protocol calls for independent seed labels, adjudication, and 300–500 real thread-isolated gold emails before a final training/evaluation claim. Historical Enron text needs institutional use/redistribution review before sharing. No training metric is reported from unreviewed data.
- A targeted secret-pattern scan of code, scripts, annotation files, and reports found no API keys. Generated corpus and assignment files are under `ai/data/**`, which `.gitignore` excludes. The workspace was initialized as a local Git repository for publication; the staged path list was reviewed to confirm generated corpora and reviewer assignments are excluded. Report paths were checked for developer-machine absolute Windows paths and use repository-relative references.
- The revised FYP proposal also requires extraction from attachment contents and hierarchy-aware access. This pass captures attachment names and addresses but does not yet cover document/OCR spans or organizational roles; see [proposal alignment](proposal_alignment.md).
