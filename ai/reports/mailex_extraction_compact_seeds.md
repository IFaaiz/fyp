# Native MailEx compact model seed robustness

**Status: full-safe seeds 17, 23, and 41 are complete. The first seed41 attempt OOMed before optimization; a fresh run completed after exclusive GPU release. No TEST inference or selection lock is included in this report.**

## Data and protocol

All runs use the separate `mailex_native_fyp_safe_v1` TRAIN and DEV views, after excluding whole threads connected to the protected FYP boundary. The safe inputs are 2,762 TRAIN messages and 361 DEV messages. Their current SHA-256 hashes are TRAIN `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333` and DEV `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`.

The recipe is the shared DistilBERT categorical BIO extractor with encoder learning rate `2e-5`, head learning rate `1e-3`, batch size 8, up to 8 epochs, patience 2, and seed-specific shuffling. Each checkpoint is first selected at threshold `0.5` by DEV role-exact micro F1. A separate, predeclared DEV-only grid (`0.3`, `0.5`, `0.7`, `0.9`) selects the reported inference threshold by the same metric. TEST rows are not read or scored.

## Results

| Seed | Best epoch at 0.5 | Selected DEV threshold | Role-exact F1 | Partial record F1 | Exact record F1 | Checkpoint SHA-256 | Status |
|---:|---:|---:|---:|---:|---:|---|---|
| 17 | 6 | 0.7 | 0.338717 | 0.487985 | 0.179377 | `ac17ba4dbf09a45d9311ef186487b9c9dbc40ecb3bb69d1b3900588313e2c698` | Complete |
| 23 | 8 | 0.7 | 0.345117 | 0.500899 | 0.189087 | `e02537b0bb70a45f94d6714a807499ea316661fddf08dc4a7ec4ad9743e2d05c` | Complete; fresh resumed run |
| 41 | 6 | 0.7 | 0.339516 | 0.502243 | 0.194005 | `0e638864d56aea403961ad2eec12282b60b4340a94862741daafa08ec091cc60` | Complete; fresh resumed run |

## Three-seed DEV summary

Metrics below use each seed's DEV-selected threshold (0.7) and report the sample standard deviation across the three seeds.

| Metric | Mean | Sample SD | Seeds |
|---|---:|---:|---:|
| Role-exact F1 | 0.341117 | 0.003487 | 3 |
| Partial event-record F1 | 0.497042 | 0.007873 | 3 |
| Exact event-record F1 | 0.187490 | 0.007444 | 3 |

The complete per-seed threshold grids, prediction hashes, checkpoint hashes, shared input hashes, and exact numeric summaries are in [compact_seed_robustness_2e5.json](mailex_extraction_results/compact_seed_robustness_2e5.json). Seed23 has the highest role-exact DEV score under this declared selection rule; final model selection and TEST reservation remain with the parent task.

The first seed23 attempt was interrupted before checkpoint hashing, oracle output, and DEV calibration finished. Its partial local output is preserved and excluded from the three-seed summary. The first seed41 attempt OOMed during the first optimizer step while another GPU fit was active; its config-only output is also preserved and excluded. The fresh completed runs used separate directories. The exporter reads only aggregate run metadata, never JSONL rows.

## Privacy and scope

This report contains aggregate metrics and hashes only. It contains no source email text, message IDs, or thread IDs. The benchmark is the named FYP-safe variant, not the untouched official MailEx split and not proof of original Enron identity separation. Model choice and any later TEST evaluation remain governed by the separate pre-TEST selection process.
