# Orchestrator source audits — 2026-10-03

The user explicitly authorized brief Airspace, Parakweet and CEREC excerpts in this private chat. The orchestrator inspected the samples below personally. Source text remains private and excluded from Git. Machine-readable sample hashes and positions are in `auxiliary_source_audits.json`.

These are partial AI inspections of source semantics and format, not exhaustive annotation validation. There are zero human gold labels. Raw-byte fidelity is a separate check in `auxiliary_source_fidelity.json`.

## Airspace: 51 messages

Reviewed the first 50 rows of the existing sorted 100-row review file, plus its WEB-WBE example at row 63. The sample covers all eight source labels. Brief bodies and subjects show conference scheduling, room and microphone arrangements, website corrections, and briefing requests.

CHANGE-ROOM includes informational capacity and dimension updates; the label does not always establish a current change request. BRIEFING can ask for progress information without requesting a formal document. Noise describes relevance to the source conference scenario; some noise messages contain dates and action requests. It cannot establish FYP NON_PROJECT automatically. WEB-WBE simulator URLs were not fetched. All sampled Replyto fields are zero; raw Thread values do not establish reply edges.

The source audit gate is complete for private use of the original auxiliary tasks. This grants no FYP label mapping, evaluation membership, or particular training run. Global exclusions and explicit partition assignment still apply.

## Parakweet: 50 sentence fragments

Reviewed the existing balanced sample: 25 rows from each source split, with both binary labels. Yes spans requests, proposals, commitments and generic instructions, including commercial calls to action. No can contain meeting/date mentions or imperative language. The binary task does not establish project scope or an exhaustive speech-act taxonomy. Preserve encoding artifacts and native labels.

All 4,649 records remain quarantined from training against the new Enron evaluation: sentence row IDs cannot resolve their original emails. The four exact sentences crossing source splits remain documented. The semantic source audit is complete; identity quarantine remains.

## CEREC: 50 thread samples

Reviewed brief pair windows, then reconstructed complete mention spans from the source CoNLL cluster markers to avoid misleading first-token comparisons. All 50 sampled documents had balanced markers. This is a sample check, not validation of the complete corpus.

Seven sample documents contain suspicious links between different named entities in the same source cluster. Their hashed document IDs, cluster IDs and token positions are recorded without names or excerpts. These are suspected annotation merges requiring full-context review, not a measured corpus error rate. No source labels were repaired or discarded.

The first 50 documents come from one custodian group and are not representative of the full corpus. Header repetition, quoted messages and automatic message/speaker features complicate interpretation; these features do not establish authentic RFC IDs or reply edges. Training remains prohibited pending embedded-text rights, original-message identity, global-index integration and annotation-quality review.

## Enron V2 source audit: 50 training candidates

The orchestrator inspected subject/current-message excerpts from the first 50 source-random TRAIN_SCREEN records after full assigned-email review was authorized. The text-free evidence is in `enron_v2_source_audit.json`. The sample includes social mail, newsletters, commercial spam, automatic logs, routine business and potentially useful project work. This is a source audit, not complete structured annotation.

Some derived current-message views retain forwarded headers or older quoted content. Reviewers must identify authored current functions rather than inheriting old requests. No authentic earlier-message context is supplied in these reservoir rows. The sample also contains an exact repeated subject/message; baseline feature preparation now counts it once and rejects conflicting targets. No project prevalence, accepted support or model accuracy is inferred from these excerpts.

CMU currently offers the corpus as a research resource and asks users to respect the people represented. It provides no named standard open license; raw text remains private. The source gate is documented, but V2 training permission remains disabled until reviewed annotations and an explicit export authorization exist. [CMU source](https://www.cs.cmu.edu/~enron/).
