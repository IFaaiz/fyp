# MailEx extractor runtime measurements

## Final runtime candidates

These are measured fresh-process inference timings on the FYP-safe DEV split only.
Both models use the same 1-, 39-, and 721-word messages and same evenly spaced
eight-message cohort. The compact model uses its selected seed23 checkpoint at
threshold 0.7. GLiNER uses its best seed42 fine-tuned checkpoint at threshold 0.2.
No TEST rows were read. Public results contain aggregate timings and source-grounding
diagnostic counts only; no text, IDs, predictions, or checkpoint paths are included.

| Model and device | Cold model load | 1-word message | 39-word message | 721-word message | Batch 8 | Emails/s |
|---|---:|---:|---:|---:|---:|---:|
| Compact categorical seed23, CPU | 0.864 s | 11.3 ms | 25.5 ms | 0.393 s | 1.532 s | 5.22 |
| Compact categorical seed23, NVIDIA GeForce RTX 5070 | 1.036 s | 6.3 ms | 14.1 ms | 0.072 s | 0.112 s | 71.75 |
| GLiNER fine-tuned seed42 best, CPU | 4.486 s | 685.3 ms | 828.4 ms | 5.917 s | 11.833 s | 0.68 |
| GLiNER fine-tuned seed42 best, NVIDIA GeForce RTX 5070 | 4.908 s | 293.7 ms | 874.4 ms | 2.643 s | 7.241 s | 1.10 |

GLiNER timing includes all seven TRAIN-derived schema passes, per-message window
selection, extraction, overlap merge, native event/argument mapping, and strict
source-offset grounding diagnostics. Its longest message spans 31 windows across
the seven packs; the batch-eight run spans 80 windows. The measured sample had zero
ungrounded prediction segments and zero messages silently truncated. Batch-eight
inference is sequential through the current production API, not parallel batching.
Compact batches encoder windows, then decodes events per message. Its benchmark
excludes one warm-up call; these scope details are verified from the benchmark
and compact encoder code. Its runtime runner does not record a grounding counter.

The selected compact checkpoint has 66,601,862 parameters and 266,443,579 weight
bytes. The fine-tuned GLiNER checkpoint has 73,881,879 parameters and 295,567,700
weight bytes. The machine-readable JSON includes per-device repeated timings,
startup/readiness boundaries, window counts, memory peaks, and aggregate grounding
diagnostics. It contains no absolute checkpoint path.

## Historical baseline measurements

The earlier seed17 compact and zero-shot GLiNER CPU results are retained below as
historical measurements. Their GLiNER timer predates the native event/argument
mapping and grounding addition, so it is not directly equivalent to the final
fine-tuned GLiNER timings above. Its old 69.159-second process duration was sampled
after inference while serializing the report; it was not model readiness time.

| Historical model and device | Cold model load | Short | Median | Long | Batch 8 | Emails/s |
|---|---:|---:|---:|---:|---:|---:|
| Compact categorical seed17, CPU | 1.088 s | 15.9 ms | 36.3 ms | 0.608 s | 2.047 s | 3.91 |
| Compact categorical seed17, RTX 5070 | 1.340 s | 8.0 ms | 13.0 ms | 0.079 s | 0.148 s | 54.00 |
| GLiNER2.5 Small zero-shot, CPU | 6.793 s | 925.0 ms | 1130.1 ms | 8.583 s | 16.259 s | 0.49 |

The earlier pretrained GLiNER Small GPU timing remains not measured. Historical measurements
also use the same message lengths, but the pretrained Small CPU record excludes native
conversion and must be treated as a narrower timing scope.

Machine-readable aggregates: [`mailex_extraction_runtime.json`](mailex_extraction_runtime.json).
