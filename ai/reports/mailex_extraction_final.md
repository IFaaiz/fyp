# Native MailEx extraction: final measured comparison

**Completed 5 October 2026, Asia/Karachi. Decision D: none of the tested
extractors is good enough for reliable unattended Outlook extraction.**

The conventional compact model is the strongest measured baseline and is much
faster on this PC. GLiNER Small improves substantially after real fine-tuning,
but loses on argument and event-record extraction. Stop this GLiNER recipe.
The next architecture is **one shared compact encoder, explicit argument span
candidates, and event-conditioned multi-label argument role/link scoring**.
This is a recommendation; that replacement has not been trained in this sprint.
The [machine-readable decision index](mailex_extraction_final.json) links the
closed TEST receipts and records the result and preservation checks.

## Final TEST results

Both candidates were selected entirely on TRAIN/DEV, then fixed in
[the selection lock](../config/mailex_extraction_selection_lock.json), committed
and pushed as `f6b4bde` before either TEST inference. Each candidate ran inference
once and the independent evaluator scored its saved predictions once. TEST is
now closed. Neither thresholds nor gold labels were changed afterward.

All F1 values are proportions. Event F1 is event-type micro F1. Argument exact
and overlap scores ignore role but retain event association. Argument-role F1
uses exact argument boundaries and role. Primary record scores require exact
event type and attached role/qualifier records; triggers are assessed separately.
Overlap means character IoU >= 0.50. CPU time is the matched 39-word DEV email,
not an average over TEST. Size is the saved weight file in decimal MB.

| Model | Event F1 | Arg exact F1 | Arg overlap F1 | Arg-role F1 | Partial record F1 | Exact record F1 | CPU ms/email | Size MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Compact categorical BIO, seed 23, epoch 8, threshold 0.7 | 0.648363 | 0.341750 | 0.439269 | 0.339138 | 0.472232 | 0.199578 | 25.5 | 266.44 |
| GLiNER Small FT, seed 42, epoch 3, threshold 0.2 | 0.434128 | 0.234614 | 0.256375 | 0.231894 | 0.186966 | 0.035132 | 828.4 | 295.57 |

Compact exceeds GLiNER by 10.72 absolute argument-role F1 points, 28.53 partial
record points, and 16.44 exact-record points. These are one held-out subset's
results, without a statistical significance claim. Compact role precision is
only 0.2652 and recall 0.4701; exact-record precision is 0.1684. Those measured
errors prevent a production recommendation despite its relative lead.

### TEST precision, recall and supporting diagnostics

Each cell below is precision / recall / F1. Both outputs contain all 363 gold
messages and no extra message rows. Gold contains 772 events and 1,657 arguments.

| Measure | Compact | GLiNER Small FT |
|---|---|---|
| Trigger exact | 0.378234 / 0.549935 / 0.448203 | 0.279084 / 0.584955 / 0.377880 |
| Trigger partial | 0.459411 / 0.667964 / 0.544397 | 0.309406 / 0.648508 / 0.418936 |
| Event type | 0.547237 / 0.795337 / 0.648363 | 0.320568 / 0.672280 / 0.434128 |
| Argument span exact | 0.267280 / 0.473748 / 0.341750 | 0.268692 / 0.208208 / 0.234614 |
| Argument span overlap | 0.343548 / 0.608932 / 0.439269 | 0.293614 / 0.227520 / 0.256375 |
| Argument role exact | 0.265237 / 0.470127 / 0.339138 | 0.265576 / 0.205794 / 0.231894 |
| Partial record | 0.376206 / 0.634080 / 0.472232 | 0.158215 / 0.228487 / 0.186966 |
| Exact record | 0.168449 / 0.244819 / 0.199578 | 0.025942 / 0.054404 / 0.035132 |
| Event-type macro F1, gold-supported types | 0.517033 | 0.333016 |
| Argument-role macro F1, gold-supported roles | 0.185786 | 0.077515 |
| Predicted events / arguments | 1,122 / 2,937 | 1,619 / 1,284 |
| Empty prediction rate | 0.170799 | 0.198347 |
| Non-source prediction segments | 0 | 0 |

Zero non-source segments verifies substring grounding. It does not establish
correct roles, event association, completeness, or calibrated confidence.
Full per-event-type and per-argument-role precision, recall, F1, support and
macro/micro aggregates are in the source-free
[compact TEST metrics](mailex_extraction_results/compact_selected_test.metrics.json)
and [GLiNER TEST metrics](mailex_extraction_results/gliner_small_selected_test.metrics.json).
No TEST source-level error audit or oracle experiment was performed.

## DEV selection and untested candidates

DEV uses 361 messages, 828 events and 1,758 arguments. These are the complete
native gold subset, including examples unsupported by GLiNER's trainer view.

| Model | Event F1 | Arg exact F1 | Arg overlap F1 | Arg-role F1 | Partial record F1 | Exact record F1 | CPU ms/email | Size MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Selected compact | 0.663425 | 0.348210 | 0.456032 | 0.345117 | 0.500899 | 0.189087 | 25.5 | 266.44 |
| GLiNER Small strict zero-shot | 0.002339 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | Not measured under final timing scope | 295.57 |
| GLiNER Small FT | 0.449438 | 0.227405 | 0.242954 | 0.223518 | 0.183657 | 0.038894 | 828.4 | 295.57 |
| GLiNER Base FT | Not trained | Not trained | Not trained | Not trained | Not trained | Not trained | Not measured | Not measured |

The corrected strict zero-shot pass produced 27 event records and no arguments.
The earlier punctuation-normalized pass is preserved separately as historical
evidence. Neither zero-shot pass was run on TEST. Base was not justified:
Small's selected DEV role and record extraction clearly trail the compact
baseline, satisfying the requested fail-fast condition.

Compact's three independently completed seeds 17, 23 and 41 have DEV role F1
mean **0.341117**, sample SD **0.003487**; partial-record mean **0.497042**, SD
**0.007873**; exact-record mean **0.187490**, SD **0.007444**. Seed 23 was chosen
by the declared maximum DEV exact-role rule, with no ensemble. Selection among
seeds makes its DEV score optimistic; the seed mean is separately reported.

The same paired subject ablation cohort used 2,683 TRAIN and 352 DEV messages.
Subject+body improved exact-role F1 by 0.78 absolute points in one seed but
provided no partial/exact record gain. Body-only input was retained. The
LR 1e-5 compact comparison lost to LR 2e-5. All completed grids, configs, curves
and hashes are retained in [the results index](mailex_extraction_results/compact_runs.json).

## Selected compact DEV oracle experiment

All three rows use seed 23 and threshold 0.7, without fitting or TEST access.

| Setup | Exact argument-role F1 | Argument overlap F1 | Partial record F1 |
|---|---:|---:|---:|
| End-to-end | 0.345117 | 0.456032 | 0.500899 |
| Gold event type only | 0.234947 | 0.314837 | 0.380747 |
| Gold event type + complete native trigger | 0.461000 | 0.624500 | 0.681018 |

Gold type alone does not distinguish repeated same-type event instances and
provides no anchor. It is not a pure classifier upper bound. Fitting used 20%
trigger-conditioning dropout. Supplying both type and trigger adds 11.59 role
F1 points, but role F1 remains 0.461: improving event detection alone is
insufficient. See [actual baseline and oracle evidence](mailex_extraction_baseline.md).

## Actual fitting and representation limits

Compact uses one DistilBERT encoder and categorical BIO trigger heads, with a
type/trigger-conditioned global role/qualifier BIO head. Its 512-wordpiece
overlapping windows cover every nonempty source word. BIO decoding fragments
some long action spans and cannot group discontinuous triggers into one event.
The first independent-BCE trial genuinely failed and was replaced; its failed
checkpoint and metrics are preserved, with no TEST run.

GLiNER uses pinned `gliner2==2.0.0` boundary code and the pinned
`fastino/gliner2.5-small-v1` checkpoint. A verified native processor override
retains annotated occurrences and source text instead of surface-search
targets or appended punctuation. The final batch-4 fit completed three epochs
and 14,010 optimizer updates; epoch 3 minimized trainer DEV loss. Native DEV
thresholds 0.2 and 0.5 were independently scored; 0.2 won exact-role F1.
Saved weights are real. Report serialization failed after checkpoint saving,
so returned epoch histories are unavailable and were not reconstructed.

GLiNER's TRAIN view represents 98.31% of events and 97.80% of arguments;
its DEV trainer view represents 98.31% / 98.18%. Incompatible windows, missing
triggers, and an unseen DEV role/qualifier pair are counted, not removed from
final scoring. First-intact-window assignment can create negative supervision
for the same trigger in another overlapping window. Its checkpoint criterion
(trainer loss) differs from compact's native role F1. The Small result covers
one bounded completed fit, rather than a matched multi-seed search.

The saved DeBERTa tokenizer emitted a Transformers Mistral-regex warning.
The supervisor compared original and saved tokenizers on all 361 DEV bodies:
zero token-ID or offset differences. No regex change was made after fitting.
Details and actual configs are in [the training report](mailex_extraction_training.md).

## Measured desktop runtime

Fresh processes on the actual Windows PC, four CPU threads, RTX 5070. Same
1-/39-/721-word DEV emails and same eight-message cohort. Warm-up is excluded;
filesystem caches were not flushed. Timings include source tokenization and
native decoding; GLiNER includes all seven schema packs, window merge and
strict grounding. Compact uses five single-message repetitions, GLiNER two.

| Candidate/device | Load s | Process ready s | 39-word ms | 721-word ms | Eight-email s | Emails/s | Peak process RSS GB |
|---|---:|---:|---:|---:|---:|---:|---:|
| Compact CPU | 0.864 | 5.747 | 25.5 | 393.1 | 1.532 | 5.22 | 1.417 |
| Compact RTX 5070 | 1.036 | 5.953 | 14.1 | 72.2 | 0.112 | 71.75 | 1.890 |
| GLiNER CPU | 4.486 | 9.607 | 828.4 | 5,916.9 | 11.833 | 0.68 | 1.412 |
| GLiNER RTX 5070 | 4.908 | 10.147 | 874.4 | 2,642.9 | 7.241 | 1.10 | 1.971 |

Both run on CPU without CUDA. Compact has 66,601,862 parameters and GLiNER
73,881,879. Peak allocated CUDA memory is approximately 427 MB / 362 MB.
Process readiness includes imports and model load; GLiNER also includes schema
preparation. Its earlier model-only readiness is 9.418 s CPU / 9.969 s GPU.
Compact's longest measured message uses two encoder windows; GLiNER needs
31 schema-window passes. GLiNER's eight-message API is sequential; compact's
encoder windows are batched, with event decoding per message. These implementation
costs are part of the measured comparison. No silently truncated runtime messages
were observed. GLiNER's runtime sample had zero ungrounded segments; compact's
runtime runner records no grounding counter (its quality runs independently
report zero non-source segments). Compact warm-up and encoder batching are
verified from the benchmark/encoder code and identified as such in runtime JSON.
CPU inference was unquantized. These small cohorts
are desktop diagnostics, not guaranteed deployment latency or maximum email
length. See [runtime details](mailex_extraction_runtime.md) and
[machine-readable repetitions/memory](mailex_extraction_runtime.json).

## Why decision D, and the specific next architecture

The supervisor personally reviewed 100 usable TRAIN conversions, 100 frozen
seed-17 DEV errors, another 100 selected seed-23 DEV errors from 80 messages,
and targeted full-source GLiNER probes at both thresholds. Gold was retained.
The selected compact audit found fragmented actions, participants attached to
the wrong event, missed records and duplicates. Some plausible facts are not
annotated, so the native benchmark also has annotation limitations. The
stratified sample is diagnostic and does not estimate error prevalence.
See [source-level findings](mailex_extraction_error_analysis.md).

Use **one shared DistilBERT encoder with explicit bounded span candidates and
event-conditioned multi-label role/link scoring** as the next candidate.
Reuse the native TRAIN conversion and existing encoder baseline. Score each
candidate argument against an individual event representation; allow one span
to attach to multiple events and carry distinct native role/qualifier pairs.
Decode complete span candidates instead of a single global BIO sequence.
This directly addresses the observed fragmentation, shared-argument and
wrong-event-link failures, while retaining a CPU-capable shared encoder.
It must be measured before adopting it; no gain is claimed in advance.

FYP schema adaptation and Outlook integration are deferred because native
record extraction is insufficient. MailEx does not supply the complete FYP
approval/department/project ontology. Future architecture selection must not
tune on this now-closed TEST; use a new independent holdout for another cycle.

## Boundaries, preservation and reproducibility

Official MailEx has 1,200/150/150 TRAIN/DEV/TEST threads and 3,117/414/405 turns.
Its 11 native event types, 25 case-sensitive role names, qualifiers, segment
offsets and event associations are preserved. Faithful BIO conversion yields
18,149 argument runs; 50 additional runs correct earlier role-case folding.
Orphan I tags and malformed-case flags are retained under documented policies.

The named `mailex_native_fyp_safe_v1` view has 1,061/131/135 threads and
2,762/361/363 messages. Known protected FYP fingerprint matches and their
connected leakage components were excluded by whole thread. Official cross-split
duplicates remain documented. These scores are not untouched official MailEx
results or proof of complete isolation of every original Enron identity.
See [native source audit](mailex_native_extraction_audit.md).

Final preservation checks: **77 closed V1 files and 231 snapshotted V2 files,
zero changed or missing**. Verification hashed bytes only, without inference
on old V1 TEST or reading protected V2 source text. The independent agent's
31 focused synthetic tests passed; their TEST fixtures are synthetic only.

Lock SHA-256: `e54c69b0192670a10fd90ece92138fd3d1cf58fbfed55808d36043f0cfe34de9`.
Compact weight SHA-256:
`e02537b0bb70a45f94d6714a807499ea316661fddf08dc4a7ec4ad9743e2d05c`.
GLiNER weight SHA-256:
`907904ef8c171c9ca9aa61f33856ce2819882bccd5d077c44ce4343b4fe437a4`.
The [compact receipt](mailex_extraction_results/compact_selected_test.receipt.json)
and [GLiNER receipt](mailex_extraction_results/gliner_small_selected_test.receipt.json)
bind lock, gold, saved predictions and complete aggregate metrics. The exporter
checks the pre-TEST committed lock and actual artifact bytes; it neither
reruns inference nor rescores examples.

GitHub contains code, native schemas, actual sanitized configurations, aggregates,
hashes and reports. Raw email text, source-bearing predictions/IDs, full reviews,
private exclusion metadata, dependency caches and weights remain local and
ignored. Public receipts contain no source examples. A fresh clone cannot
reconstruct the private protected-boundary subset or checkpoints by itself;
[reproduction instructions](mailex_extraction_reproduction.md) state this limit.
