# MailEx GLiNER2.5 fine-tuning (TRAIN / DEV)

## Current status

Fine-tuning is not yet complete. The first trainer launch stopped before any
optimizer update because GLiNER2.0's default collator appended synthetic
punctuation, which invalidated the explicit source-offset word map. The
private processor now preserves input bytes, rejects implicit truncation and
encoded windows above 512 tokens, and refuses fabricated fallback text. A
two-event synthetic fixture with the repeated source surface “I” passed
forward and backward: both event records and the correct first/second `I`
occurrence were retained, with finite loss and gradients.

A subsequent batch-2 run completed more than 800 optimizer updates from the
pinned pretrained checkpoint, with finite but noisy early losses. It stopped
before completing an epoch and before writing a fitted checkpoint. A batch-8
forward/backward probe on a 512-token positive window passed in 2.28 seconds
for eight copies of the sample (3.51 examples/second), with a 4,510 MiB peak
allocation. The negative-window probe also passed.

The full batch-8 run then reached approximately 1,111 of 7,005 updates in its
first epoch. Total shared GPU use reached 11,655 MiB of 12,227 MiB, above the
10 GiB team limit, so the run was stopped before the epoch finished. It wrote
no model checkpoint and is not selected. Its configuration and an aggregate
attempt-status record are preserved privately under
`ai/data/cache/mailex_gliner/checkpoints/`.

A fresh bounded three-epoch batch-4 fit is now running from the pinned
pretrained checkpoint in a separate output directory. It uses the TRAIN-only
ontology, all seven schema packs, 1e-5 encoder learning rate, 2e-5 task-head
learning rate, seed 42, four CPU threads, and early stopping patience 2. No
DEV model-selection claim is available until a checkpoint completes and the
independent full-gold DEV evaluator scores it.

## Prepared supervision and representability

The private source-to-model adapter retains the complete original gold rows.
Training windows use a contiguous first trigger segment as the natural record
anchor; other native trigger geometry remains intact in gold and benchmark
scoring. Events are trained only when one window contains the anchor and every
argument segment. Events absent from a window are omitted as whole records,
not represented with silently missing argument labels. DEV-only role / qualifier
combinations remain outside the TRAIN-derived schema and are counted as
unsupported in the trainer's DEV loss view. The independent evaluator retains
all original DEV gold.

| View | Messages | Prepared examples | Represented events | Gold events | Represented argument segments | Gold argument segments |
|---|---:|---:|---:|---:|---:|---:|
| TRAIN | 2,762 | 18,680 | 5,632 (98.31%) | 5,729 | 12,207 (97.80%) | 12,482 |
| DEV | 361 | 2,520 | 814 (98.31%) | 828 | 1,726 (98.18%) | 1,758 |

TRAIN omitted 9 events without triggers and 88 events whose trigger plus every
argument could not fit intact in one encoder window (256 argument segments).
DEV omitted 13 such window-incompatible events (30 argument segments) and one
event whose `(Action Date, revision)` label combination is absent from TRAIN
(2 argument segments). These are training-view limits only; independent DEV
metrics use the full gold set. Whitespace-only message bodies create no model
examples; they contain no gold events or argument segments in these safe views.
The largest prepared example has 21 event records, below the boundary model's
32-record query capacity.

Every example includes the same inference schema pack, including event types
with no gold record, so those types receive negative supervision. Schema
descriptions and role / qualifier fields come only from TRAIN. Prompt packing
uses seven groups of the eleven event types, with each measured prompt capped
at 320 subwords; input windows are verified at no more than 512 encoded tokens.

## Reproducibility

- Safe TRAIN SHA-256: `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333`
- Safe DEV SHA-256: `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`
- Initial checkpoint: `fastino/gliner2.5-small-v1`, revision `7132dc4561c3f94563c6147e75ffa8ef34c4964a`
- Weight SHA-256: `4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b`
- Parameters: 73,881,879; architecture: boundary DeBERTa-v2
- Runtime: `gliner2==2.0.0`, shared `torch==2.11.0+cu128`, `transformers==4.57.6`; CPU threads capped at 4
- Trainer: GLiNER2 `ExtractorTrainer` / `TrainingConfig`, with a private
  `SchemaTransformer` offset-target override because the public surface-search
  converter labels every repeated occurrence instead of the annotated one.

The official training and natural-record interfaces are documented in
[GLiNER2 tutorial 3](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/3-json_extraction.md),
[tutorial 8](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/8-train_data.md),
and [tutorial 9](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/9-training.md).

No TEST rows or TEST predictions have been read or generated. A result is not
selected until the full native DEV evaluator scores a saved checkpoint.
