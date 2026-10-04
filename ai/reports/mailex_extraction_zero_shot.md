# MailEx GLiNER2.5 zero-shot extraction (DEV)

## Current result

The pinned `fastino/gliner2.5-small-v1` checkpoint was run without fine-tuning
on the 361-message FYP-safe DEV view (828 gold events). The schema vocabulary
was derived from TRAIN only and packed into seven measured prompts, each at or
below 320 subwords. Body text was split into overlapping windows whose encoded
sequence, including prompt and special tokens, stayed at or below the encoder's
512-position limit. The run used one inference example at a time on the RTX
5070, four CPU threads, and threshold 0.5.

The first DEV pass produced 28 records and 28 grounded trigger spans, but no
argument spans. On the independent DEV evaluator, exact event type
identification F1 was 0.234%; exact argument role F1 was 0%; and exact event
record F1 was 0%. All 28 predicted triggers were source-grounded; the evaluator
reported zero non-source prediction segments. This is a poor initial result,
not evidence of useful extraction quality.

That pass used the upstream GLiNER2.0 collator, which appends a period to text
that lacks terminal punctuation. Its original output and metadata remain
preserved for audit. A strict adapter now keeps the source body byte-exact and
skips whitespace-only bodies. The corrected zero-shot pass has not been run:
the shared GPU is allocated to the bounded fine-tune, and the initial metrics
are retained as provisional. They are not treated as a source-exact result.

## Run identity

- Safe TRAIN SHA-256: `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333`
- Safe DEV SHA-256: `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`
- Checkpoint revision: `7132dc4561c3f94563c6147e75ffa8ef34c4964a`
- Checkpoint weight SHA-256: `4ee982787ace270d4bf15dbcb28ced38e0aa201372347114ceedd6336055de2b`
- Original prediction SHA-256: `005669c3852e23c57887b8f3dbabfaea23883066c869498b8dd5b43acda2b9ab`
- Original output: `ai/data/experiments/mailex_extraction_v1/predictions/zero_shot_gliner2_5_small_dev.jsonl`
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

TEST remains sealed pending the committed selection lock.
