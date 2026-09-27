# AI-only classification silver batch

The [direct correctness audit](ai_pilot_v2_correctness_audit.md) has been converted into a versioned classification-only batch for prototyping. The [source-free decision manifest](../annotation/project_pilot_50_v2_silver_decisions.jsonl) records the primary agent's proposed labels and review flags for all 50 second-pilot emails. The reproducible [builder](../scripts/build_ai_silver_classification.py) applies those decisions to the ignored local seed and writes an ignored canonical JSONL file at `ai/data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl`.

| Output status | Count | Use |
| --- | ---: | --- |
| `ai_prelabelled` | 41 | Classification prototype only |
| `unlabelled` with `needs_review=true` | 9 | Exclude from positive and negative training |
| Human-reviewed or gold | 0 | None claimed |

The nine held-back records include the four direct-audit abstentions plus five suggested classifications still flagged for scope or label uncertainty. All output spans are empty: the direct audit checked high-impact span types and found semantic errors, but did not verify every extraction span. Empty spans in this batch mean **not adjudicated**, not confirmed absence of meetings, dates, owners, documents, or other extractable text. The builder sets `span_review_status=not_adjudicated` and `intended_use=classification_prototype_only` on every output record.

The 41 provisional records contain 19 `NON_PROJECT` labels and 22 project-labelled records. Among project labels, `GENERAL_UPDATE` appears 17 times, `ACTION_REQUEST` 10, `MEETING` 9, `DEADLINE` 9, `DEPARTMENTAL_INPUT` 3, `REPORT_REQUEST` 3, and `FOLLOW_UP` 1. There are no `APPROVAL` examples in the included batch. These counts show why this small historical sample is useful for pipeline wiring and label-boundary checks, not a balanced final training or evaluation set.

The [v3 AI review protocol](../annotation/ai_review_protocol_v3.md) now gives contrastive rules for the mistakes observed in the direct audit. Apply it to future fresh batches; do not overwrite the two independent reviewer files or treat the corrected silver batch as a held-out accuracy reference.

## Rebuild

From the repository root, after generating the second-pilot seed locally:

```powershell
ai/.venv/Scripts/python.exe ai/scripts/build_project_pilot_v2.py
ai/.venv/Scripts/python.exe ai/scripts/build_ai_silver_classification.py
```

The builder checks IDs/order, source status, decision provenance, label inventory, `NON_PROJECT` exclusivity, and canonical output validity. It does not read either reviewer file, copy their spans, or modify the seed. The original blind outputs and direct audit remain available locally for investigation.
