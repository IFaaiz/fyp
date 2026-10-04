# GLiNER MailEx safe DEV metrics

These scores are from the frozen FYP-safe DEV view only: 361 messages and 828
gold event records. The native MailEx evaluator independently rescored both
prediction files. Their SHA-256 values were stable during this export. No TEST
rows were read. This report contains aggregate counts only, without message text,
identifiers, or local checkpoint paths.

| Confidence threshold | Predicted events | Predicted argument spans | Type F1 | Exact record F1 | Partial record F1 | Role exact F1 | Role partial F1 | Trigger exact F1 | Trigger partial F1 | Empty-message rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | 1,486 | 1,329 | 0.4494 | 0.0389 | 0.1837 | 0.2235 | 0.2378 | 0.3768 | 0.4235 | 0.2022 |
| 0.50 | 504 | 296 | 0.4790 | 0.0195 | 0.1299 | 0.1500 | 0.1519 | 0.4324 | 0.4655 | 0.3934 |

Threshold 0.20 predicts more records and arguments, with higher partial record
and role scores. Threshold 0.50 has higher event-type and trigger scores. All
prediction segments passed source-offset validation at both thresholds.
These are DEV threshold diagnostics; they do not use TEST or imply final model
selection.

Aggregate values are also available in
[`mailex_extraction_gliner_dev_metrics.json`](mailex_extraction_gliner_dev_metrics.json).
