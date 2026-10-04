# Structured primitive baseline harness

Status: two real accepted-export preflights completed; both blocked by class support. No model fit performed.

## Result

As of 2026-10-03, two private orchestrator-authorized exports (8 accepted rows each) passed the full real-data provenance loader and preflight. The first contains 0 PROJECT / 8 NON_PROJECT; the second 1 PROJECT / 7 NON_PROJECT. Both fail the predeclared 20-per-class minimum. **Models trained: 0. Evaluation performed: no.** There are no model scores, predictions or accuracy claims. A 78-source enriched TRAIN seed is being independently reviewed; none of its rows is yet claimed accepted.

The local runtime reports Python 3.12.14 and scikit-learn 1.9.1. No model artifact was created.

## Preregistered baselines

The harness defines two word-level TF-IDF unigram baselines with logistic regression:

1. Binary `PROJECT` / `NON_PROJECT` scope classification, using all accepted and supported training rows.
2. One-vs-rest speech-act classification for `REQUEST`, `INFORM`, `COMMIT`, `APPROVE`, `REJECT`, `DELIVER`, `PROPOSE`, `REMIND`, `SCHEDULE`, `CANCEL`, and `RESCHEDULE`, using only supported `PROJECT` rows.

These are primitive predictions. The harness does not predict the nine final FYP label functions. It reads no TEST/EVAL data, computes no evaluation metrics, and does not load any closed V1 artifacts.

The scope baseline requires at least 20 examples of each scope class. Speech-act heads are assessed individually: a head with at least 20 positives and 20 negatives is eligible to fit; a rare head is listed as untrained and does not block scope or other eligible speech-act heads. `--minimum-per-class` may raise the threshold; the script rejects values below the preregistered 20.

On 2026-10-04 root found retained quoted/forwarded history in some assigned current-message fields, with no explicit authored ranges. The harness now quarantines PROJECT inputs with known history markers from speech-act fitting unless explicit authored ranges are supplied. This includes retained Outlook address/subject headers even when no forwarding separator survives. Scope fitting can still use the contextual input. Preflight and fit metadata report the quarantine count. This marker screen is conservative and incomplete: genuine authored header-like lines can also be quarantined, marker absence does not prove clean authorship, and explicit ranges still require source review. Regressions cover unbounded old requests, Outlook reply headers, and recovery through exact authored offsets. The existing two actual exports passed the corrected loader and remain blocked by their unchanged scope shortages, with zero quarantined speech rows in those exports.

## Authorization and source gates

The CLI requires paths to an `accepted_train.jsonl` and explicit `training_authorization.json` in the same run directory. Before using the rows, the loader calls the public `workflow.verify_accepted_train_provenance` function and requires its independently reconstructed rows and manifest to match the supplied export and sidecar. That function rechecks the current run, decision and reviewer artifacts, source hashes, leakage index, partition assignments, protected membership, exact frozen boundary bytes and canonical registry. The loader then repeats the export, authorization, registry, row identity and annotation checks needed by the model code. It never loads evaluation source text. A review handoff filename is rejected.

Scope features retain the subject and authored body for context. Speech-act features use only the authored body, so old request wording in a forwarded subject cannot supervise current acts. Repeated whitespace-normalized scope inputs count once; repeated authored bodies independently count once for speech support even when their subjects differ. Conflicting targets on identical component inputs fail closed. Authorized export rows remain separately recorded from unique feature rows. This prevents exact source copies from manufacturing support; it does not establish independent near-duplicate or thread-level support. Both actual exports passed this corrected preflight on 2026-10-04 with unchanged counts.

Before preparing targets, the loader:

- compares all eight authorization hashes against the adjacent export manifest;
- rechecks the current registry bytes and accepted JSONL bytes, and recalculates the canonical sorted native-source-ID digest;
- requires both `structured_scope_baseline` and `structured_speech_act_baseline` in the orchestrator's permitted component list;
- runs `require_training_source` for each row's dataset;
- requires `TRAIN_SCREEN`, a complete source identity, a leakage group ID, no partition conflicts, and no training exclusions;
- validates every structured annotation and its exact source evidence, rejects review-required or uncertain annotations, and requires supported scope and primitive confidence;
- trains speech-act heads only from `PROJECT` rows and uses only the current message's authored ranges when supplied.

Fitting is opt-in with `--fit`. Artifacts can be saved only to a new directory below `ai/data/`; the default run is preflight-only. No corpus candidates, review handoffs, or other partitions are discovered or loaded by this script.

If a later authorized run fits models, its private `training_metadata.json` will include the verified authorization, export, run, decision, source, registry, index, partition and frozen-boundary hashes, plus SHA-256 digests for every saved model artifact. No fit has been performed for this report.

## Files and verification

- Implementation: `ai/src/structured_models.py`
- Entry point: `ai/scripts/train_scope_speech_baselines.py`
- Gate and synthetic preparation tests: `ai/tests/test_structured_model_gates.py`

Focused command from `ai/`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_structured_model_gates
```

The suite exercises authorization and hash failures, protected paths, review-handoff rejection, uncertainty and partition gates, source-evidence validation, authored-range feature preparation, project-only speech targets, per-head support selection, and minimum-count enforcement. It also builds a complete synthetic review-to-export chain, passes it through the real public provenance verifier and model preflight, then confirms that changing the immutable decision manifest blocks loading. These synthetic tests do not fit models. The two actual preflights above separately verified the accepted exports and reported insufficient support.

Latest focused results: `tests.test_structured_model_gates` - 26 passed on 2026-10-04, including forwarded-subject exclusion, retained Outlook reply headers, authored-range recovery and body-only support deduplication; `tests.test_structured_review_workflow` - 11 passed at the prior checkpoint. Both suites use synthetic records only.
