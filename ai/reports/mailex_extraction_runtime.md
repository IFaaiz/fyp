# MailEx extractor runtime measurements

## Scope

These are measured local inference times on the FYP-safe DEV split only. The safe DEV fingerprint is `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`. No TEST rows were read. Timing output contains aggregate measurements only; it does not contain message IDs, text, or predictions.

The compact extractor numbers are from five repetitions on one short, one median, and one long message, with a batch of eight. The GLiNER2.5 Small CPU run used two repetitions at each size, one excluded warmup pass, and a batch of eight messages processed sequentially through the same production inference path. Each GLiNER message ran all seven TRAIN-derived schema packs. Timed work includes per-schema window selection, extraction, and overlap-record merging. The long GLiNER sample is the DEV p90 at 144 words; it required one window per pack.

## Measurements

| Model and device | Cold model load | Short message | Median message | Long message | Eight-message cohort |
|---|---:|---:|---:|---:|---:|
| Compact categorical seed 17, CPU | 1.088 s | 15.9 ms (1 word) | 36.3 ms (39 words) | 607.5 ms (721 words, 2 windows) | 2.047 s; 3.91 messages/s |
| Compact categorical seed 17, RTX 5070 | 1.340 s | 8.0 ms (1 word) | 13.0 ms (39 words) | 78.6 ms (721 words, 2 windows) | 148.1 ms; 54.00 messages/s |
| GLiNER2.5 Small, CPU | 11.771 s | 926.9 ms (6 words, 7 passes) | 1.094 s (39 words, 7 passes) | 1.607 s (144 words, 7 passes) | 9.505 s; 0.842 messages/s |
| GLiNER2.5 Small, RTX 5070 | Not measured yet | — | — | — | — |

The compact figures cover the seed 17 candidate checkpoint while final checkpoint selection is pending. That checkpoint has 66,601,862 parameters and 266,443,579 weight bytes. GLiNER2.5 Small has 73,881,879 parameters and 295,567,700 weight bytes. GLiNER CPU peak process working set was 1.471 GB. The model load timing starts after Python imports; process start through imports and model readiness was 41.825 s. Compact peak working set was 1.412 GB on CPU and 1.901 GB on GPU; compact GPU peak allocated device memory was 427 MB.

The GLiNER eight-message result is a sequential cohort, not parallel model batching: the current production path calls `extract` for each message and schema pack. A GPU run is pending until the shared RTX 5070 is free; no GPU latency is inferred from the CPU result.

All timings are from fresh benchmark processes, but the operating system file cache was not flushed. The compact and GLiNER “short”, “median”, and “long” choices use their respective benchmark sampling rules, so the word counts differ. Windowing did not silently truncate any measured message.

The machine-readable aggregate table is in [mailex_extraction_runtime.json](mailex_extraction_runtime.json).
