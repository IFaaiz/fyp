# MailEx GLiNER2.5 zero-shot extraction (DEV)

## Current result

The pinned `fastino/gliner2.5-small-v1` checkpoint was run without fine-tuning
on the 361-message FYP-safe DEV view (828 gold events). The schema vocabulary
was derived from TRAIN only and packed into seven measured prompts, each at or
below 320 subwords. Body text was split into overlapping windows whose encoded
sequence, including prompt and special tokens, stayed at or below the encoder's
512-position limit. The run used one inference example at a time on the RTX
5070, four CPU threads, and threshold 0.5.

The initial, pre-adapter DEV pass produced 28 records and 28 grounded trigger
spans, but no argument spans. On the independent DEV evaluator, exact event
type identification F1 was 0.234%; exact argument role F1 was 0%; and exact
event record F1 was 0%. This was provisional because the upstream collator
appended a period to some inputs.

That first pass used the upstream GLiNER2.0 collator, which appends a period to
text that lacks terminal punctuation. Its original output and metadata remain
preserved for audit. The corrected pass used a strict adapter that keeps the
source body byte-exact and skips whitespace-only bodies. It produced 27
records across 9 messages, all with grounded trigger spans, and no arguments.
On the independent full-gold DEV evaluator, exact event-type F1 was 0.234%
(one correct type among 828 gold events), trigger partial F1 was 0.468%,
argument role F1 was 0%, and primary event-record partial F1 was 0%. This is
not useful extraction quality; it establishes the source-exact zero-shot
baseline for the fine-tuned comparison.

The corrected prediction is
`ai/data/experiments/mailex_extraction_v1/predictions/zero_shot_gliner2_5_small_native_text_dev.jsonl`
(SHA-256 `ef0a4b25a2ba5a1c88f83642aba6cf712e66d8012665bd74d35c62b307166b9a`).
Its aggregate metrics are in the matching `.metrics.json` file. The original
pre-adapter prediction and metadata have not been overwritten.

## Run identity

- Safe TRAIN SHA-256: `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333`
- Safe DEV SHA-256: `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`
- Checkpoint revision: `7132dc4561c3f94563c6147e75ffa8ef34c4964a`
- Checkpoint weight SHA-256: `4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b`
- Original prediction SHA-256: `005669c3852e23c57887b8f3dbabfaea23883066c869498b8dd5b43acda2b9ab`
- Original output: `ai/data/experiments/mailex_extraction_v1/predictions/zero_shot_gliner2_5_small_dev.jsonl`
- Corrected source-exact prediction SHA-256: `ef0a4b25a2ba5a1c88f83642aba6cf712e66d8012665bd74d35c62b307166b9a`
- Runtime: `gliner2==2.0.0`, `torch==2.11.0+cu128`, `transformers==4.57.6`

The model is the Apache-2.0 GLiNER2.5-small checkpoint. The extraction
configuration uses natural record mode with the trigger as anchor and
`occurrence_policy="all"`; record identity and argument association are kept
per returned record. Across overlapping windows, only fully identical records
are deduplicated. Each contiguous model-emitted list span becomes a separate
native argument record, and offsets are accepted only when the original source
slice equals the returned surface.

The model card and primary API guides are [GLiNER2.5-small](https://huggingface.co/fastino/gliner2.5-small-v1),
[structured extraction](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/3-json_extraction.md),
[training data](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/8-train_data.md),
and [training](https://github.com/fastino-ai/GLiNER2/blob/main/tutorial/9-training.md).

Neither zero-shot variant was run on TEST. The two fitted finalists were
locked in commit `f6b4bde` and evaluated once; see
[the final comparison](mailex_extraction_final.md).
