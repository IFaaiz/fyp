# FYP calibration V1 source curation — iteration 3

Date: 2026-10-06
Status: root-approved unlabelled pilot; all 47 sources imported into the owner-private review app.

## Final aggregate

The frozen pilot contains 47 unlabelled sources from a historical Enron public-corpus fallback. It is an enriched retrieval sample for calibration workflow review, not a prevalence sample. It does not support claims about modern workplace email, university email, FYP-domain coverage, human label support, or model accuracy.

| Assignment | Sources | Review arrangement |
|---|---:|---|
| Common blind set | 24 | All three reviewers label independently |
| Personal calibration TRAIN | 12 | Assigned round-robin |
| Sealed human holdout | 11 | Assigned round-robin; content was not shown to root |
| Scope-boundary controls | 3 | Included in the 47-source total |

Root reviewed 38 TRAIN/common sources, removed 2 weak-relevance sources, and applied 36 evidence-range overrides. A conservative programmatic named-topic overlap screen removed one holdout candidate; the topic is intentionally not disclosed. No holdout source text was opened for that review.

## Source and label limits

The source bodies and subjects remain unchanged. The pilot has no human labels, no AI prelabels, and zero GOLD annotations. Training export is not permitted. Human agreement, adjudication, and accuracy have not been measured.

Authored-prefix ranges come from a heuristic. Every heldout prefix range needs independent human verification and adjudication before evaluation. The iteration 3 aggregate records zero protected-candidate overlap.

## Site and desktop status

Curation is root-approved. The native private deployment succeeded for pushed Site source `c7a9e41d1880d6e8989dd926371e6af7682fa611`, environment revision 3. Import accepted and inserted all 47 sources in two batches. No human submission or agreement is claimed. The two teammates still need private access configured. Use the [offline desktop prototype](../../desktop/README.md) to review individual V1 packets locally.

## Reproduction note

Source inspection of `ai/scripts/prepare_fyp_calibration_v1.py` shows that the allocation formula adapts after selection: for 47 selected sources it computes 24 common blind, 12 personal TRAIN, and 11 holdout. The selection stage still targets exactly 187 candidates (108 project-context, 51 project-adjacent, and 28 scope-boundary). If fewer eligible independent groups are available, the script raises instead of reducing that target. The split counts are dynamic; small-pool candidate selection is not. This note comes from source inspection only; the script was not run to regenerate the approved pilot.

The former [iteration 2 report](fyp_calibration_v1_curation_iteration2.md) is retained as historical context and is superseded by this aggregate.

## Frozen import receipt

Import SHA-256: `b52a4ed9faf9cda9080ec7e669e81960d56d36c45abfe09936deef33f7195a0b`. Source-free provenance and counts are in [the aggregate manifest](fyp_calibration_v1_curation.json). Source bodies, identities, private topic hints and reviewer answers are excluded from Git.

Re-import verification accepted all 47 frozen sources and inserted zero additional rows; immutable source text, authored ranges and assignments matched.
