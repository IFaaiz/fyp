# Structured pipeline evaluation â€” source boundary checkpoint

Source-boundary checkpoint: 2026-10-02. Annotation/training update: 2026-10-04. New experiment: structured V2, schema `2-alpha`.

Latest results are in `structured_annotation_pilot.json`: 47 accepted / 31 excluded / 0 pending from 78 TRAIN sources; 23 PROJECT / 24 NON_PROJECT. The authorized export passed root and independent subagent provenance/preflight checks and supported one local scope-baseline fit. All speech heads remain below support. Accepted EVAL annotations and new evaluation predictions are zero, so no performance result exists. The new assignment overlaps the earlier pilot; counts and training inputs are not added. The following table records the earlier2026-10-02 source-only checkpoint.

## What is measured now

The original 2026-10-02 checkpoint below verified source isolation and executable annotation contracts. At that historical checkpoint, no structured annotation was accepted and no model was fitted. Current 2026-10-04 annotation and fitting counts are reported above; neither checkpoint measures predictive performance. There are zero human gold classification labels.

| Item | Observed result |
| --- | --- |
| Full Enron rows scanned for new candidate reservation | 517,401 |
| Historical exposed source identities recovered | 11,889 |
| Initially reserved unseen evaluation sources | 1,200 |
| Retained evaluation source candidates | 600 |
| Screening candidates before overlap exclusions | 5,000 |
| Retained training-screen source candidates | 4,285 |
| Training-screen records excluded by protected component overlap | 715 |
| Indexed records across declared current inputs | 28,129 |
| Global connected leakage components | 22,434 |
| Cross-partition component conflicts in frozen assignments | 0 |
| Accepted structured annotations / new trained models | 0 / 0 |

These counts come from `structured_candidate_reservation.json`, `structured_candidate_isolation.json`, and `global_leakage_audit.json`. They describe candidate sources, not usable training labels or a frozen annotated TEST. The 4,285 source-random screening candidates subsequently received computational semantic retrieval; 78 selected candidates received full structured source review. Computational screening is not a source-read label or accepted annotation. They must not be reported as 4,285 project emails.

The current private source boundary is `ai/data/experiments/structured_v2_candidates_20261002_v2/isolated_v2/boundary_manifest.json`. Its actual index is `ai/data/processed/structured_v2_expanded_leakage_index_v2.json`, SHA-256 `d864f94d4bc68bcca2d3f017fe7b5b7ef69bad5bcd41fde80f8b0905cfe2a0f1`. Both supersede the earlier isolation snapshot; no training or accepted review occurred between snapshots. The candidate source bytes were unchanged by the final conservative identity-policy update.

## Isolation scope and limits

All 1,200 original reserved sources remain protected, including those not selected among the 600. Historical records and their matched connected components are protected. Exact normalized content, token/compact fingerprints, authentic origin/RFC identifiers, verified thread grouping, ordered containment, fragments and near-duplicate checks contribute to the global components.

MailEx's 3,936 records and Parakweet's 4,649 records remain quarantined from component training against this Enron evaluation because their underlying original email identities are unresolved. Long reconstructed text cannot establish an independent origin. CEREC is inspection-only and must enter a new reviewed index before any use. The index covers declared development/evaluation inputs rather than every full-corpus Enron record; unknown paraphrase/origin links can remain undetected. Zero observed conflicts is not proof of semantic independence.

## Required annotation boundary

Every evaluation record needs two independent source-only reviews and a third adjudicator. The third initial verdict is frozen before access to A/B answers. Exact current-message evidence, temporal targets, project scope and primitive disagreements are checked separately from derived FYP labels. High-risk report requests, follow-ups, approvals, departmental contributions, deadline relations and ambiguities require orchestrator review. Invalid or unresolved annotations cannot enter an accepted training export.

The 600-source sample is prevalence-oriented. No labels or model scores were used to select its source boundary. A deliberately enriched challenge set needs separate sources and a separately declared sampling policy. Naturally observed support shortages must be reported without inventing rare positives.

## Future metric protocol

Freeze the accepted evaluation annotation policy, review hashes and model choice before inference. Report primitive precision/recall/F1, exact and overlap action spans, date-to-target relations and available authentic thread-state relations, then derived FYP-label micro/macro/per-label metrics with support. Keep an enriched challenge set separate. All AI-adjudicated results must be titled **AI-SILVER DIAGNOSTIC PERFORMANCE**; they cannot establish final human-reviewed accuracy.

The historical flat TF-IDF V1 figures remain historical evidence only. They use a different closed TEST and cannot support a direct improvement claim on V2. The original inspected V1 TEST remains closed; its preserved artifacts are checked by byte hashes without fitting or inference. A fair future architecture comparison would require a preregistered reference on the new frozen evaluation, reported as a new experiment.

## Current blockers

The user approved brief private excerpts on 2026-10-03. Personal source audits now cover 51 Airspace, 50 Parakweet and 50 CEREC examples; details are in `auxiliary_source_audits.md`. Parakweet remains quarantined for unresolved original identity. CEREC remains inspection-only pending embedded-text rights, identity/global-index integration and review of suspicious entity links. BC3 needs valid registration details, CSpace has no established authorized release, and Avocado needs institutional access/agreements. Enron permission now covers only explicitly authorized accepted TRAIN exports for the two primitive baselines; three such exports have been issued; current fitting uses only the latest 47-row export. Unlabelled candidates and protected/evaluation sources remain ineligible.

Source-grounded review, an authorized 47-row TRAIN export and one scope-baseline fit are complete. Next work is natural TRAIN support expansion for speech/rare primitives, followed by independent EVAL annotation under its already reserved boundary. Scope-only fitting is not the complete extraction pipeline. No current predictive metric or improvement claim is justified.
