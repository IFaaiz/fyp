# AI email dataset foundation

This directory prepares English Outlook-style project emails for a future multi-label classifier and information extractor. V1 uses subject, body, thread context, Outlook metadata, and attachment filenames. It does not read attachment contents. The 22-page *FYP Proposal Report* controls this V1 scope; the 10-page revised proposal describes later attachment extraction.

## Canonical JSONL

Each line is one email with source-qualified `email_id`, `thread_id`, `turn_index`, `subject`, preserved `raw_body`, derived `current_message` and `clean_body`, `thread_context`, metadata (`sender`, `recipients`, `cc`, `sent_at`, `attachment_names`), independent `labels`, exact `spans`, and `annotation` status. Span `start` is inclusive and `end` exclusive in `current_message`, or `subject` when `field` says so. Empty labels on an unlabelled record mean unknown. Human-reviewed unrelated mail uses `NON_PROJECT`. MailEx `raw_body` is reconstructed from official annotation tokens because its JSON does not contain the original RFC822 body; the downloaded archive itself is preserved unchanged.

The nine classification labels are MEETING, DEADLINE, REPORT_REQUEST, DEPARTMENTAL_INPUT, ACTION_REQUEST, FOLLOW_UP, APPROVAL, GENERAL_UPDATE, and NON_PROJECT. The eleventh extraction type is DEADLINE_TIME. All project labels may co-occur; NON_PROJECT stands alone. See [annotation guidelines](annotation/annotation_guidelines.md) and [schema decisions](reports/schema_decisions.md) for operational decisions. Source datasets do not automatically supply gold FYP classification labels. AI prelabels are review candidates only.

## Run

Use Python 3.10+ from the repository root:

```powershell
python -m unittest discover -s ai/tests -t ai -v
python ai/scripts/prepare_mailex.py
python ai/scripts/prepare_enron.py --maildir ai/data/raw/enron/maildir
python ai/scripts/create_candidate_pool.py --input ai/data/interim/enron.jsonl
python ai/scripts/validate_dataset.py ai/data/processed/mailex.jsonl
# After human-reviewed records exist:
python ai/scripts/create_splits.py ai/data/annotated/human/reviewed.jsonl
```

MailEx defaults to the extracted official release under `ai/data/raw/mailex/extracted/data/full_data`. Enron defaults to the extracted CMU maildir under `ai/data/raw/enron/maildir`; the full archive has not yet been downloaded. Source provenance is in [MailEx source](reports/mailex_source.md) and [Enron source](data/raw/enron/README.md). Raw downloaded data and generated JSONL under `ai/data/` are ignored by Git. Keep original input files unchanged. Validate records before splitting. Splits group all messages from a source-qualified thread; synthetic records are restricted to training and never become gold.

## Workflow

1. Obtain MailEx and Enron from the documented sources and retain their raw files.
2. Run preparation scripts to create canonical, initially unlabelled records and source-specific extraction proposals where justified.
3. Select project candidates and random negatives for independent human annotation. Keyword selection is only for sampling.
4. Review a 200–300 email seed with two annotators where feasible. Resolve disagreements and freeze guidelines.
5. Build a real, human-reviewed 300–500 email gold test set, isolated by thread, before model development.

See [dataset progress](reports/dataset_progress.md) for executed counts and current limitations.
