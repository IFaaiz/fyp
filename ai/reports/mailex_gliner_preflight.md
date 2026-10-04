# GLiNER2.5 Small preflight

## Pinned model and runtime

- Model: `fastino/gliner2.5-small-v1`, Hugging Face revision
  `7132dc4561c3f94563c6147e75ffa8ef34c4964a`.
- Model weights: 295,567,700 bytes, SHA-256
  `4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b`;
  73,881,879 parameters; Apache-2.0 model card.
- Model architecture: GLiNER2 boundary extractor with a DeBERTa-v2 encoder.
  The checkpoint's training config advertises `max_len=4096`, while its nested
  encoder has `max_position_embeddings=512`. This benchmark checks the final
  schema-plus-body encoding against 512 positions and windows long source text;
  it does not rely on silent tokenizer truncation.
- Runtime: private `gliner2==2.0.0` source under `ai/data/cache`, using the
  existing `torch==2.11.0+cu128` and `transformers==4.57.6` environment.
  The shared environment was not upgraded. Inference can load from the private
  local checkpoint without hosted APIs.
- The installed distribution metadata identifies `gliner2==2.0.0`; upstream
  release `v2.0.0` points to source commit
  [`3c913c7369301133d3b7699252074c4303ada50e`](https://github.com/fastino-ai/GLiNER2/commit/3c913c7369301133d3b7699252074c4303ada50e).
  The private vendored Python source files are individually hash-frozen in the
  eventual selection manifest.
- Current native record mode uses one natural structure per event type, with a
  required trigger anchor, all trigger occurrences, and role/qualifier fields
  derived from the safe TRAIN view. Event schemas are packed into seven prompts
  of at most 320 measured subwords each.

## API and offset checks

The checked upstream API is `AutoExtractor.from_pretrained`, natural
`SchemaBuilder.structure(..., anchor="trigger", occurrence_policy="all")`,
and the `ExtractorTrainer` / `TrainingConfig` interfaces documented in the
[official JSON extraction tutorial](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/3-json_extraction.md),
[training data tutorial](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/8-train_data.md),
and [trainer tutorial](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/9-training.md).
The released surface-search target converter cannot distinguish two identical
mentions, so the private adapter replaces its target builder with explicit
source `[start,end)` targets mapped to GLiNER word IDs. A synthetic repeated
text fixture with two same-type records and repeated `I` mentions passed
forward/backward with finite gradients and distinct expected word positions.

Model load, extraction, save/reload, and another extraction passed on CPU; a
save/reload extraction also passed on CUDA. The extraction runner processes
messages sequentially at inference batch size 1. Training uses batch size 4 in
the bounded fit. An eight-item 512-token forward/backward probe passed, with a
4,510 MiB peak allocation; the full batch-8 training run exceeded the shared
10 GiB ceiling and was stopped before producing a checkpoint. The active
batch-4 fit and its eventual runtime are documented separately in
[`mailex_extraction_training.md`](mailex_extraction_training.md).

Transformers 4.57.6 prints a generic Mistral-regex warning while loading the
checkpoint tokenizer. A compatibility comparison against the pinned
pretrained tokenizer found identical pre-tokenizer, normalizer, added-token,
decoder, and post-processor settings; token strings matched across the 128k
vocabulary, with serialized unigram scores differing by at most `3.55e-15`.
All 361 safe DEV message bodies produced identical token IDs and offsets in
both versions. The tokenizer was kept unchanged. The model also falls back
from configured SDPA to eager attention because this DeBERTa-v2 implementation
does not support the SDPA path; training and extraction use the same fallback.

The prediction adapter accepts only model-emitted source offsets whose
surface exactly matches the body slice. It does not search for a replacement
occurrence when offsets are absent or inconsistent. It retains an event even
when its trigger is ungrounded and records the grounding diagnostic. Native
gold retains the full trigger geometry; the model's natural anchor target is
the first contiguous source trigger segment because the upstream record anchor
is contiguous.

MailEx text is the reconstructed body only. The tokenizer offset contract is
half-open character spans over that exact body string. No subject/header text
is prepended. Empty and whitespace-only bodies yield no predictions and are
kept in the gold/evaluator input. Long bodies are split at GLiNER word
boundaries into overlapping windows; predictions from overlap are merged only
when the complete type, anchor, and argument record is identical. Records
sharing a trigger but carrying different arguments remain separate.
