# Compact native MailEx baseline

## Task and model

The baseline is a shared DistilBERT encoder with categorical O/B/I trigger
outputs for each of the 11 native event types, followed by an event-conditioned
argument BIO classifier over TRAIN role/qualifier keys. There are 66,601,862
parameters; the complete fine-tuned weight file occupies 266,443,579 bytes.
Encoder revision: `12040accade4e8a0f71eabdb258fecc2e7e948be`.

Each predicted contiguous trigger creates a separate event instance. Argument
classification uses the predicted type, pooled trigger embedding, a signed
log-distance embedding, and a word/trigger interaction. The encoder is shared
across events. Evidence is always an exact substring with half-open source
offsets. Role names retain native case and qualifiers.

Every nonempty source word is covered by overlapping 512-wordpiece windows,
stride 128. Window embeddings are averaged, and the argument head sees all
message word vectors. This does not create transformer attention between
different windows. Discontinuous trigger grouping and overlapping same-type
trigger instances are representation limits, retained in evaluation gold.

## Actual fitting and controlled DEV selection

Fitting uses `mailex_native_fyp_safe_v1`: 2,762 TRAIN turns, 5,729 events;
DEV has 361 turns, 828 events and 1,758 argument runs. The official split
membership is preserved for included threads. This filtered variant is not
the untouched official benchmark; see the native audit for duplicate leakage
and known protected FYP exclusions.

Common recipe: batch 8, up to 8 epochs, early stopping patience 2, AdamW,
weight decay 0.01, head LR 1e-3, gradient clipping 1, bf16 training and encoder
gradient checkpointing. Class weights use TRAIN only: square root of the
negative/positive ratio capped at 50; O weight 1. Trigger conditioning is
removed for 20% of TRAIN event instances to support the type-only diagnostic.
Checkpoint selection uses DEV exact argument-role micro F1 at threshold 0.5.
The fixed checkpoint then receives the declared DEV grid 0.3/0.5/0.7/0.9.

| Encoder LR | Seed | Selected epoch | DEV-selected threshold | Exact argument-role F1 | Partial record F1 | Exact record F1 |
|---|---:|---:|---:|---:|---:|---:|
| 2e-5 | 17 | 6 | 0.7 | 0.338717 | 0.487985 | 0.179377 |
| 1e-5 | 17 | 6 | 0.7 | 0.289388 | 0.438334 | 0.144867 |
| 2e-5 | 23 | 8 | 0.7 | 0.345117 | 0.500899 | 0.189087 |
| 2e-5 | 41 | 6 | 0.7 | 0.339516 | 0.502243 | 0.194005 |

All three LR-2e-5 robustness seeds are complete. Exact role F1 is
0.341117 mean and 0.003487 sample SD. The declared highest-DEV-role criterion
selects seed 23, epoch 8, threshold 0.7; there is no ensemble. Its source-level
100-case audit is complete. Selection by the highest seed score can make DEV
optimistic; the seed mean is reported separately and TEST remains the final
one-time comparison.

The earlier independent-BCE attempt was rejected after prediction inspection
showed fragmented BIO spans and excessive events. Its checkpoint is preserved
privately; repaired decoding reached only 0.019985 exact role F1. It has no TEST
score and is not a finalist.

## Required oracle diagnostics (seed 17, threshold 0.7)

| DEV mode | Argument-role exact F1 | Argument overlap F1 | Partial record F1 |
|---|---:|---:|---:|
| End to end | 0.338717 | 0.449008 | 0.487985 |
| Gold type, one slot per gold event, no trigger | 0.212274 | 0.292140 | 0.349838 |
| Gold type and full native trigger | 0.443041 | 0.604578 | 0.657952 |

Knowing the trigger and type adds 10.43 absolute role-F1 points, but argument
extraction still has substantial errors. Supplying only a type does not
identify repeated same-type instances, so that diagnostic produces repeated
type-conditioned arguments. It is neither a pure type-classification score
nor an upper bound on argument extraction.

### Selected seed 23, threshold 0.7

| DEV mode | Argument-role exact F1 | Argument overlap F1 | Partial record F1 |
|---|---:|---:|---:|
| End to end | 0.345117 | 0.456032 | 0.500899 |
| Gold type, one slot per gold event, no trigger | 0.234947 | 0.314837 | 0.380747 |
| Gold type and full native trigger | 0.461000 | 0.624500 | 0.681018 |

These are actual selected-checkpoint DEV inferences. Gold type and trigger
add 11.59 absolute role-F1 points; argument extraction remains a bottleneck.
The type-only diagnostic has the same repeated-instance limitation as above.

Historical fit configurations used both repository-relative and ai-relative
encoder-cache paths. The inference loader now resolves either uniquely to
the local encoder directory without changing saved configurations or weights.
A complete selected DEV replay reproduced the original prediction bytes:
SHA-256 `5226ae5c1714e9faf6a2b424716906413b5f405ae8e9a04ab706f4e6a1886212`.

## Evidence and reproducibility

Seed-17 LR-2e-5 weight SHA-256:
`ac17ba4dbf09a45d9311ef186487b9c9dbc40ecb3bb69d1b3900588313e2c698`.
Threshold-0.7 DEV prediction SHA-256:
`1ba0824e0e74f1fdc64b649cfc9c464ed4748f7a1ebb146b2a1bc4984fd1382a`.
An independently implemented evaluator reproduced the scores. Twenty focused
synthetic conversion, exclusion, and adversarial metric tests passed.

Public aggregate configurations and metrics are in `mailex_extraction_results/`.
Corpus text, source/prediction identifiers, predictions, checkpoints and review
samples remain in ignored private experiment directories. The supervisor
personally reviewed 100 usable TRAIN conversions and 100 frozen DEV errors.
TEST requires a committed selection manifest and an exclusive run reservation.

The inference loader constructs the encoder from configuration and loads the
complete fine-tuned weights once. It reproduced the original DEV prediction
bytes exactly; deployment does not require the original pretrained weight
file in addition to the fine-tuned checkpoint.
