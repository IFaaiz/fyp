# MailEx extractor runtime measurements

## Scope

These are measured local inference times on the FYP-safe DEV split only. The safe DEV fingerprint is `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`. No TEST rows were read. Timing output contains aggregate measurements only; it does not contain message IDs, text, or predictions.

Both models use the same three messages and same eight-message cohort: the minimum, median, and maximum length safe DEV messages, plus eight evenly spaced entries from the canonical length-sorted split. The historical GLiNER2.5 Small CPU run used two repetitions at each individual size, one excluded warmup pass, and processed the shared cohort sequentially through the production inference path. Each GLiNER message ran all seven TRAIN-derived schema packs. Its timer covers per-schema window selection, extraction, and overlap-record merging; it does not include native event/argument mapping or source-offset grounding. A corrected benchmark now includes those production steps and accepts an explicit checkpoint path. Final-checkpoint timings are pending until model selection and the GPU training window ends.

## Measurements

| Model and device | Cold model load | Short message | Median message | Long message | Eight-message cohort |
|---|---:|---:|---:|---:|---:|
| Compact categorical seed 17, CPU | 1.088 s | 15.9 ms (1 word) | 36.3 ms (39 words) | 607.5 ms (721 words, 2 windows) | 2.047 s; 3.91 messages/s |
| Compact categorical seed 17, RTX 5070 | 1.340 s | 8.0 ms (1 word) | 13.0 ms (39 words) | 78.6 ms (721 words, 2 windows) | 148.1 ms; 54.00 messages/s |
| GLiNER2.5 Small, CPU | 6.793 s | 925.0 ms (1 word, 7 passes) | 1.130 s (39 words, 7 passes) | 8.583 s (721 words, 31 windows across 7 packs) | 16.259 s; 0.492 messages/s |
| GLiNER2.5 Small, RTX 5070 | Not measured | — | — | — | — |

The compact figures cover the seed 17 candidate checkpoint while final checkpoint selection is pending. That checkpoint has 66,601,862 parameters and 266,443,579 weight bytes. GLiNER2.5 Small has 73,881,879 parameters and 295,567,700 weight bytes. GLiNER CPU peak process working set was 1.468 GB. The historical GLiNER process-duration value of 69.159 s was sampled while serializing results after inference, so it is not readiness time; that run did not capture model readiness. The corrected benchmark records both model-loaded and seven-schema-packs-ready timestamps. Compact peak working set was 1.412 GB on CPU and 1.901 GB on GPU; compact GPU peak allocated device memory was 427 MB.

The GLiNER eight-message result is a sequential cohort, not parallel model batching: the current production path calls `extract` for each message and schema pack. GLiNER GPU timing is not included; the isolated GPU timing is reserved for the final selected checkpoint. The earlier GLiNER CPU numbers are retained as historical measurements with their narrower timing scope. Final checkpoint CPU and GPU results will use the same 1-, 39-, and 721-word messages and batch-eight cohort, with prediction-row grounding included.

All timings are from fresh benchmark processes, but the operating system file cache was not flushed. The compact and GLiNER short, median, and long measurements use the same message indices. The longest message exercises the full windowing path for both models. Windowing did not silently truncate any measured message.

The machine-readable aggregate table is in [mailex_extraction_runtime.json](mailex_extraction_runtime.json).
