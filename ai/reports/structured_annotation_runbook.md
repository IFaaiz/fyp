# Structured annotation workflow

Run commands from the repository root with `ai/.venv/Scripts/python.exe`. Raw text, review packets, envelopes, accepted annotations and models remain below ignored `ai/data/`. Reports contain aggregate progress and provenance only.

## Current source inputs

Use the V2 boundary at `ai/data/experiments/structured_v2_candidates_20261002_v2/isolated_v2/boundary_manifest.json`. Its `evaluation_candidates.jsonl` contains 600 source candidates and `train_screen_candidates.jsonl` contains 4,285. Their exact file hashes and the actual index are bound by the boundary. Earlier `isolated/` files are superseded.

These files have no accepted structured labels. Creating packets does not grant training permission. The entire source file is hash-bound; do not truncate or edit it to manufacture a smaller run. Use `--record-offset` and `--record-limit` to select a deterministic contiguous batch from that exact file. The manifest records its full input count and selected offset/count. Individual email text is preserved without truncation; unusually long messages may need a dedicated packet.

## Review order

1. Prepare a fresh `TRAIN_SCREEN` or `EVAL` run with `prepare_structured_review.py`; use the declared boundary partition (`TRAIN_SCREEN` or `EVAL_RESERVED`). This produces distinct private source-only reviewer A/B packets with matching source records and schema hashes.
2. Dispatch independent GPT-6 Luna/xhigh reviewers. Each reads its assigned packet and supplies an envelope with exact evidence offsets, source-read attestations, source/packet hashes, model and reviewer identity. Dispatch must keep reviewers isolated from previous labels and other answers. The shared filesystem and self-reported attestations alone cannot prove independence.
3. Ingest each envelope with `adjudicate_structured_reviews.py ingest`, then run `compare`. The comparison concerns primitives and evidence, including disagreements that happen to derive identical final labels.
4. Run `prepare-third` for all EVAL/CHALLENGE records and TRAIN primitive disagreements. Dispatch a third independent reviewer on its source-only packet, freeze that verdict with `ingest-third-initial`, then use `prepare-adjudication` to reveal A/B. Ingest the third resolution with `ingest-adjudication`.
5. The orchestrator personally inspects high-risk selected assertions and disagreements. Record a hash-bound approval, rejection or review-required decision with `root-decision`. Uncertainty cannot be cleared merely by writing approval.
6. Run `finalize`. Invalid or unresolved rows remain review-required. A complete decision manifest is required for an accepted handoff. `prepare-handoff` writes `accepted_annotations_for_orchestrator_review.jsonl`; this remains review material rather than training permission.
7. After actual source, rights, isolation and annotation review, the orchestrator may issue an explicit authorization bound to the exact run, decisions, registry, index, source boundary, accepted file and source IDs. `export-train` rechecks the provenance and creates `accepted_train.jsonl` with its adjacent manifest. No such real authorization exists at this checkpoint.
8. `train_scope_speech_baselines.py` consumes only that authorized export and defaults to preflight. `--fit` is a separate explicit step with a new ignored output directory. It must never discover candidates or read evaluation message text.

Every command offers `--help`. The current implementation is offline envelope tooling; it does not automatically create reviewer agents, manufacture annotations or claim source-reading when only hashes were inspected.

The orchestrator successfully prepared separate 16-record TRAIN_SCREEN and EVAL smoke batches on 2026-10-03. Their private paths are `ai/data/structured_review/root_train_smoke_20261003/` and `ai/data/structured_review/root_eval_smoke_20261003/`. Both bind the full candidate file and actual frozen source boundary. This smoke check displayed hashes/counts only and created no annotations.

## Remaining data work

The current train-screen reservoir is random, not already relevant project supervision. Apply source-grounded relevance screening and diversity/semantic retrieval on training sources before promoting useful annotations. Declare any retrieval model inputs and audit their overlap first. Keep evaluation prevalence sources untouched by label quotas or model scores, and reserve separate challenge sources if needed.

Before training, report accepted/rejected/review-required totals and natural support for every primitive and rare mapping. Scope needs both PROJECT and NON_PROJECT examples; supported speech-act heads may train while rare heads stay explicitly untrained. Date-to-target, entity extraction and authentic thread-state models require their own reviewed supervision. Source labels from auxiliary corpora cannot be renamed into FYP truth.

All eventual AI evaluation remains **AI-SILVER DIAGNOSTIC PERFORMANCE**, with zero human gold claims. This workflow prepares the required evidence trail; it does not establish semantic correctness or predictive performance by itself.
