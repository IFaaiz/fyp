# Label Studio annotation workflow

This workflow creates independent human assignments from canonical email JSONL, imports Label Studio results back into the canonical schema, measures reviewer agreement, and prepares disagreements for human adjudication.

## Install and start Label Studio locally

Use an isolated virtual environment from the project root so the annotation server's packages do not mix with the AI pipeline environment:

```powershell
python -m venv ai/.venv
.\ai\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install label-studio
label-studio start
```

On first launch, follow the CLI prompt to create the local account, then open the local URL it prints. The [official quick start](https://labelstud.io/guide/quick_start) documents the install and start commands. If PowerShell reports that `python` is not found or opens the Microsoft Store, install Python 3 with its command-line launcher or executable on `PATH`, then reopen PowerShell.

Create two projects, for example `Enron review A` and `Enron review B`. In each project, open the labeling interface editor, switch to Code, paste the contents of `ai/annotation/label_studio/config.xml`, and save. Import `reviewer_a_tasks.json` into project A and `reviewer_b_tasks.json` into project B. Give each project to a different reviewer and keep their project access separate until agreement is calculated. The classification control uses Label Studio's multiple-choice mode, documented in the [Choices reference](https://labelstud.io/tags/choices).

Email text and metadata are historical private communications. Keep the server on a trusted machine and network, limit project membership, and keep task exports in approved local storage. Do not expose the server through a public tunnel or share project links publicly. Files under `ai/data/` are ignored by Git so task and reviewer exports are not committed by accident.

## Interface

The project configuration is generated from `ai/annotation/label_schema.json` and is checked in at `config.xml`. Rebuild it after changing the label inventory:

```powershell
python ai/scripts/write_label_studio_config.py
```

The task view keeps subject and current message as separate span sources. Thread context and email metadata are visible in separate reference panels. Some candidate groups may use secondary heuristic links; these are unverified associations for sampling and context, not confirmed original thread relationships. Treat them as helpful context and base the decision on the current message, recording uncertainty with `Needs review` when appropriate. Annotators must select either `Reviewed` or `Needs review`; a reviewed item needs at least one classification choice. Select all supported project labels. `NON_PROJECT` is exclusive and the importer rejects it if combined with a project label. For `Needs review`, leave classification and spans empty and record the reason.

Spans may be drawn over `subject` or `current_message`. Use the exact source text. The importer converts Label Studio UTF-16 offsets to the canonical Python Unicode code-point offsets and rejects offset/text mismatches. Thread context and metadata are never span sources.

## Seed independent reviewers

The seed size is constrained to 200–300 real Enron records, with a default of 250. When stratifying by candidate metadata, the matching sidecar must cover the candidate pool and provide a stratum and primary cue for every record. The default allocation reserves about 25% for `random_nonmatching` and 12.5% for `thread_expansion`; the remaining slots are split across `direct_match` and `thread_context_match` in proportion to their available cue counts. Cue groups are sampled proportionally, and thread expansion rows are selected in thread groups to retain multi-message examples. The selector also reserves up to 12 complete multi-message groups (up to 30 emails) when the sidecar confirms that every message is present; it includes all eligible partner messages even when their candidate strata differ, and the manifest reports available, reserved, and selected group counts. If fewer complete groups are available, the manifest reports the actual count. Sparse strata donate their unused quota to available groups. Without a sidecar, the script falls back to a reproducible unstratified sample. `random_nonmatching` means none of the configured lexical cues matched; it is a sampling category, not a verified `NON_PROJECT` label. Annotators must classify these emails from their content like any other task. Candidate records stay unlabelled; the script does not prefill model or dataset labels. Gold records and any candidate in the same source-qualified thread as a known gold record are excluded. It discovers gold JSONL under `ai/data/annotated/human/`; add other gold locations with `--gold-records`.

### Smoke-test real-record transport

The `enron_10000_candidates_audit.jsonl` audit subset can be used to check the A/B export and lossless import while the full candidate pool is being prepared. It may not contain every sampling stratum, so use this command only for transport checks:

```powershell
python ai/scripts/seed_label_studio_batch.py `
  --input ai/data/interim/enron_10000_candidates_audit.jsonl `
  --output-dir ai/data/annotated/human/seed_stage_dry_run `
  --count 250 --seed 2026
python ai/scripts/import_label_studio.py `
  --input ai/data/annotated/human/seed_stage_dry_run/reviewer_a_tasks.json `
  --output ai/data/annotated/human/seed_stage_dry_run/reviewer_a_transport.jsonl `
  --annotator transport-check --allow-unannotated
```

For the actual review batch, use the full `enron_candidates.jsonl` pool and its matching metadata sidecar:

```powershell
python ai/scripts/seed_label_studio_batch.py `
  --input ai/data/interim/enron_candidates.jsonl `
  --output-dir ai/data/annotated/human/label_studio_seed `
  --count 250 --seed 2026
```

The output contains identical email IDs and order in the A and B files, empty `annotations` and `predictions`, the generated XML config, and a manifest with repository-relative paths, selected IDs, per-stratum and cue counts, thread expansion counts, and the seed. The files are generated under `ai/data/` and are excluded from Git.

## Import reviewer results and calculate agreement

Pass an explicit reviewer identifier when importing each project's Label Studio task export. Import sets completed annotations to `human_reviewed`, or leaves them `unlabelled` when the reviewer chose `Needs review`. It never marks a record `gold`.

```powershell
python ai/scripts/import_label_studio.py `
  --input reviewer-a-export.json `
  --output ai/data/annotated/human/reviewer_a.jsonl `
  --annotator reviewer-a
python ai/scripts/import_label_studio.py `
  --input reviewer-b-export.json `
  --output ai/data/annotated/human/reviewer_b.jsonl `
  --annotator reviewer-b
python ai/scripts/compare_annotations.py `
  --reviewer-a ai/data/annotated/human/reviewer_a.jsonl `
  --reviewer-b ai/data/annotated/human/reviewer_b.jsonl `
  --report ai/reports/enron_seed_agreement.json
```

The report gives TP/FP/FN, precision, recall, F1, observed agreement, specificity, and binary Cohen's kappa for each classification label. A is treated as the prediction and B as the reference for directional counts. It also reports exact label-set agreement, mean Jaccard similarity, and extraction-span exact and overlap precision/recall/F1. Span overlap matches only spans with the same type and source field; matched character IoU is summarized separately. Pairs with either reviewer status still `unlabelled` do not enter agreement denominators and are included in the disagreement queue for review.

The command also writes a `.disagreements.jsonl` queue and `.adjudication_template.jsonl` alongside the report. Agreement is a measurement only; it does not create a gold set.

## Apply adjudication

Review the A/B decisions in the template and fill `adjudicator`, `labels`, `spans`, and `resolution_note`. Set `final` to `true` only after a human has made the decision. Spans use canonical Python offsets and include `field` (`current_message` or `subject`). Then apply the finalized decisions:

```powershell
python ai/scripts/apply_adjudication.py `
  --base ai/data/annotated/human/reviewer_a.jsonl `
  --decisions ai/reports/enron_seed_agreement.adjudication_template.jsonl `
  --output ai/data/annotated/human/enron_seed_adjudicated.jsonl
```

The output contains only finalized rows, uses `human_reviewed`, and never promotes rows to `gold`. Empty classification labels are not accepted as final decisions; unresolved items remain unlabelled until a human can resolve them.

## General export and lossless transport

For another blank assignment, export canonical records with an assignment slot. Export refuses records that already carry classification labels or AI prelabels and checks the known human gold JSONLs for thread overlap. Supply any additional gold file paths explicitly:

```powershell
python ai/scripts/export_label_studio.py `
  --input ai/data/interim/enron_candidates.jsonl `
  --output ai/data/annotated/human/tasks.json `
  --assignment A --gold-records path/to/other_gold.jsonl
```

Each task retains the full canonical record as JSON in its data. `import_label_studio.py --allow-unannotated` can be used to verify transport of an unfinished task without changing its record. Normal annotation imports reject unfinished tasks.