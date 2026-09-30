# Silver classification baseline infrastructure

The first reusable baseline is TF-IDF over `subject` and the authored prefix of
`current_message`, followed by nine one-vs-rest logistic regressions. It uses a
deterministic sparse Python standard-library implementation, with full-batch
gradient descent and L2 regularization. It is not scikit-learn. The model can be
saved, loaded, and used from the training script's prediction options.

The loader accepts canonical AI-silver JSONL and joins a text-free acceptance
manifest to canonical source records. A manifest row is eligible only when both
`status` and `training_provenance` equal `ai_silver`; abstentions, uncertain
decisions, human-reviewed rows, and gold rows do not train this prototype. The
curated expansion exclusion manifest is applied before leakage lookup or split
assignment. For feature extraction, the model uses the current message and
subject only. Standard quote markers and obvious Lotus `date` / `To` / `Cc` /
`Subject` header blocks are trimmed, including a sender/email/date line followed
by multiple mail headers; unmarked quoted prose remains a limitation.

The split code requires a leakage sidecar and forms connected groups from both
source-qualified thread IDs and `leakage_group_id`. This keeps thread messages
and cross-source duplicates together. It writes an ID-only split manifest and
does not create validation metrics unless `--evaluate` is explicitly supplied.
The CLI also requires at least 1,000 eligible silver records, unless a concrete
shortage report is provided.

Example, once the leakage audit and dataset gate are complete:

```powershell
ai/.venv/Scripts/python.exe ai/scripts/train_silver_classifier.py `
  --input ai/data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl `
  --accepted-manifest ai/annotation/training_expansion_100_silver_decisions.jsonl `
    ai/annotation/training_silver_first300_decisions.jsonl `
    ai/annotation/training_silver_second300_decisions.jsonl `
    ai/annotation/training_silver_extension_first300_decisions.jsonl `
  --source-records ai/data/interim/enron_full.jsonl `
  --leakage-groups ai/data/interim/leakage_groups.jsonl `
  --evaluate
```

As of 30 September, the pilot and four audited acceptance manifests provide
452 eligible AI-silver records after supervisor corrections. This
does not meet the baseline's 1,000-record gate; rare project labels still have
limited support. Add future audited acceptance manifests to the command only
after their gates pass. No model has been trained on the real silver data and no validation
metrics have been generated. A future AI-silver validation score will remain a
diagnostic comparison, not a gold accuracy claim. Final FYP claims still need
independent human-reviewed calibration data and a leakage-isolated human gold
set.
