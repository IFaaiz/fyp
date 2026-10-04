# Native MailEx compact model seed robustness

**Status: seed 17 and fresh resumed seed 23 are complete; seed 41 is pending after a first-step OOM during overlapping GPU use. No TEST inference or selection lock is included in this report.**

## Data and protocol

All runs use the separate `mailex_native_fyp_safe_v1` TRAIN and DEV views, after excluding whole threads connected to the protected FYP boundary. The safe inputs are 2,762 TRAIN messages and 361 DEV messages. Their current SHA-256 hashes are TRAIN `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333` and DEV `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d`.

The recipe is the shared DistilBERT categorical BIO extractor with encoder learning rate `2e-5`, head learning rate `1e-3`, batch size 8, up to 8 epochs, patience 2, and seed-specific shuffling. Each checkpoint is first selected at threshold `0.5` by DEV role-exact micro F1. A separate, predeclared DEV-only grid (`0.3`, `0.5`, `0.7`, `0.9`) selects the reported inference threshold by the same metric. TEST rows are not read or scored.

## Results

| Seed | Best epoch at 0.5 | Selected DEV threshold | Role-exact F1 | Partial record F1 | Exact record F1 | Checkpoint SHA-256 | Status |
|---:|---:|---:|---:|---:|---:|---|---|
| 17 | 6 | 0.7 | 0.338717 | 0.487985 | 0.179377 | `ac17ba4dbf09a45d9311ef186487b9c9dbc40ecb3bb69d1b3900588313e2c698` | Complete |
| 23 | 8 | 0.7 | 0.345117 | 0.500899 | 0.189087 | `e02537b0bb70a45f94d6714a807499ea316661fddf08dc4a7ec4ad9743e2d05c` | Complete; fresh resumed run |
| 41 | — | — | — | — | — | — | Pending; first attempt OOM before optimization |

The first seed 23 attempt was interrupted before checkpoint hashing, oracle output, and DEV calibration finished. Its partial local output is preserved and excluded from all three-seed calculations. The fresh completed run uses a separate output directory. The first seed 41 attempt ran out of CUDA memory during its first optimizer step while another GPU fit was active; that incomplete directory is preserved and has no model checkpoint. Seed 41 will be retried separately after the GPU is released, without changing the recipe.

## Privacy and scope

This report contains aggregate metrics and hashes only. It contains no source email text, message IDs, or thread IDs. The benchmark is the named FYP-safe variant, not the untouched official MailEx split and not proof of original Enron identity separation. Model choice and any later TEST evaluation remain governed by the separate pre-TEST selection process.
