# Auxiliary intent data: Parakweet

Reviewed and parsed 2026-10-02 from the author repository at pinned commit
`055f62857b3214c1682a0b18a2c5fc2c9f0c00e6`. The deterministic adapter reads
the author train and test files as UTF-8, preserves each released `Yes` / `No`
label, and treats one line as one sentence-level fragment. It does not infer a
fine-grained act or assign any FYP label.

The repository declares Apache-2.0 in its pinned `LICENSE`, README, and GitHub
metadata. The examples are Enron-derived, so this declaration is recorded as
the author release's license evidence; it is not treated as permission to
publish these message fragments in this project. Raw source, processed text,
and the balanced review sample remain in ignored local data directories.
The independent 50-example source-text audit is complete. Training stays
disabled pending resolution of original-email identity against the protected
Enron evaluation.

## Source files and observed counts

| Split | Parsed rows | `Yes` | `No` | Author wiki count |
|---|---:|---:|---:|---:|
| Train (`Ask0729-fixed.txt`) | 3,657 | 1,719 | 1,938 | 4,213 rows; 1,631 positive |
| Test (`testSet-qualifiedBatch-fixed.txt`) | 992 | 309 | 683 | 991 rows; 277 positive |
| Total parsed | 4,649 | 2,028 | 2,621 | — |

The count differences are material and unresolved. The values above describe
the pinned bytes actually parsed, not a correction to the author wiki. Four
exact sentence strings occur in both splits; retain the original split and
require global leakage checks before use.

Neither source file supplies an email or thread identifier. The adapter marks
every row as a fragment, sets RFC/message/thread IDs to null, and marks
identity incomplete. A row number is only a stable ID within this pinned
release; it is not presented as an email ID. The output keeps source `Yes` / `No`
and a boolean convenience field only; `normalized_auxiliary_act` is null and
`fyp_labels` is empty.

## Acquisition and local outputs

The pinned `Ask0729-fixed.txt` is 347,997 bytes (SHA-256
`1dafc1b367cf2fb1e8b4a944b67e14578bcb1085f2f02ea150be45c373fbe8cd`); the
pinned `testSet-qualifiedBatch-fixed.txt` is 95,679 bytes (SHA-256
`1b5ebc45a80c1e7fdeed656b7db7cec8e50eb18f562daa20070f1e3187e01e4a`). The
commit-pinned README and LICENSE are also retained in the ignored acquisition
directory. Acquisition metadata records the exact URLs and UTC timestamp.

The parser and acquisition/prepare scripts are under `ai/src/datasets/` and
`ai/scripts/`. `ai/reports/parakweet_statistics.json` contains text-free
aggregates. The 4,649-row prepared JSONL and balanced 50-row source review
sample are under ignored `ai/data/processed/`; the review sample contains
actual source text and was used for the root's completed local audit. No sample
text is included in this report or any tracked fixture.

Sources: [author repository](https://github.com/ParakweetLabs/EmailIntentDataSet),
[author task definition and counts](https://github.com/ParakweetLabs/EmailIntentDataSet/wiki),
[pinned README](https://raw.githubusercontent.com/ParakweetLabs/EmailIntentDataSet/055f62857b3214c1682a0b18a2c5fc2c9f0c00e6/README.md),
[pinned LICENSE](https://raw.githubusercontent.com/ParakweetLabs/EmailIntentDataSet/055f62857b3214c1682a0b18a2c5fc2c9f0c00e6/LICENSE).

## Orchestrator audit update — 2026-10-03

The user approved brief private excerpts. Personal audits now cover 51 Airspace, 50 Parakweet and 50 CEREC samples. See `auxiliary_source_audits.md` and the canonical registry for current gates; earlier pending-audit statements above describe the initial integration state. Airspace permits private original-task auxiliary use subject to global exclusions. Parakweet remains in original-identity quarantine. CEREC remains inspection-only pending rights, identity/global-index integration and review of suspected entity merges. No new FYP labels or human gold were created.
