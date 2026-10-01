# Silver classification baseline

**2 October measured result:** The baseline has now been fitted on actual corrected AI silver with a shared leakage-safe split. At the fixed threshold its micro/macro F1 is 0.507/0.111; training-only tuned thresholds yield 0.626/0.363. These are AI-silver diagnostics. [Full TF-IDF and DistilBERT comparison](tonight_training_comparison.md). The infrastructure notes and 30 September counts below are historical.

The first reusable baseline is TF-IDF over `subject` and the authored prefix of
`current_message`, followed by nine one-vs-rest logistic regressions. It uses a
deterministic sparse Python implementation with L2 regularization. Fitting can
use either the original standard-library gradient-descent routine or the
optional scikit-learn `lbfgs` optimizer. The latter fits independent binary
logistic regressions on the same TF-IDF vectors and exports coefficients to the
same JSON model format. Loading and prediction need no scikit-learn package.
The optimizer name, dependency versions, iteration counts, and convergence
status are saved with the model. `learning_rate` applies only to the Python
optimizer. See the [official solver documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html).

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
ai/.venv/Scripts/python.exe -m pip install -r ai/requirements-training.txt
ai/.venv/Scripts/python.exe ai/scripts/train_silver_classifier.py `
  --input ai/data/annotated/ai/project_pilot_50_v2/silver_classification_only.jsonl `
  --accepted-manifest ai/annotation/training_expansion_100_silver_decisions.jsonl `
    ai/annotation/training_silver_first300_decisions.jsonl `
    ai/annotation/training_silver_second300_decisions.jsonl `
    ai/annotation/training_silver_extension_first300_decisions.jsonl `
    ai/annotation/training_silver_extension_second300_decisions.jsonl `
  --source-records ai/data/interim/enron_full.jsonl `
  --leakage-groups ai/data/interim/leakage_groups.jsonl `
  --optimizer sklearn --max-iter 1000 `
  --evaluate
```

A synthetic export test compares portable-model probabilities with the
independently fitted scikit-learn estimator and checks save/load behavior,
including labels absent from training. The full suite passed 107 tests on
30 September. This verifies implementation transport; it is not a real-data
quality metric.

As of 30 September, the pilot and five audited acceptance manifests provide
617 eligible AI-silver records after supervisor corrections. This
does not meet the baseline's 1,000-record gate; rare project labels still have
limited support. Add future audited acceptance manifests to the command only
after their gates pass. No model has been trained on the real silver data and no validation
metrics have been generated. A future AI-silver validation score will remain a
diagnostic comparison, not a gold accuracy claim. Final FYP claims still need
independent human-reviewed calibration data and a leakage-isolated human gold
set.
