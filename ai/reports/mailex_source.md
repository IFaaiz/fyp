# MailEx source, preparation, and provenance

## Source and license

MailEx is a public Enron email corpus annotated for event and argument extraction. The dataset and instructions were obtained from the [official MailEx repository](https://github.com/salokr/Email-Event-Extraction), which points to the [dataset archive](https://drive.google.com/file/d/1a336g4-wlEwsVbXLPB9wPQnBDRE933mb/view). The dataset paper is Srivastava et al., [“MailEx: Email Event and Argument Extraction,” EMNLP 2023](https://aclanthology.org/2023.emnlp-main.801/). The repository declares [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); preserve attribution and share-alike terms when distributing adapted material.

The original archive was downloaded on 2026-09-24 and is preserved locally at `ai/data/raw/mailex/data.zip` (5,476,134 bytes; SHA-256 `DDA3CE5DA5FFC3452DD9E5A58CD69E19E68BD655EAFE1DEEC48E87204F6C37B4`). The untouched archive and its extracted files are ignored by Git to keep the Enron-derived source data local. Extraction output is under `ai/data/raw/mailex/extracted/`.

## What the converter reads

The official archive's `data/full_data/*.json` contains one thread per file, with `sentences` token lists and `events.turn_N` event/argument annotations. It does not contain the original RFC822 message bodies. The converter reconstructs `raw_body`, `current_message`, and `clean_body` by joining each turn's tokens with one space; earlier reconstructed turns populate `thread_context`. Thus, token spacing and source formatting are lost, and the canonical body is a reconstruction rather than an original raw email.

The archive also includes `data/raw_threads/` plain-text exports with some From/To/CC/Subject/Date headers. These are not RFC822 messages. The converter uses a raw thread's headers only if its block count matches the annotated turns and each reverse-ordered body reaches at least 0.75 normalized text alignment. The executed run aligned 1,457 threads and verified headers for 3,824 messages. The other threads' metadata remains empty or null. Date is present for 13 aligned messages; attachment names are never inferred from text.

The transformation preserves source trigger, event type, role, qualifier, argument text/offset, and mapping rationale under `annotation.source_annotations`. Token character offsets are computed against the token-joined `current_message`, with exclusive end offsets. Source spans that begin with an orphan BIO `I` are retained as source-only arguments and suppressed from canonical spans. Standalone pronouns and generic pronoun phrases in participant arguments are also retained as source-only arguments. The executed archive had 184 malformed BIO argument segments and 624 pronoun participant segments suppressed by these rules.

Only a narrow set of roles produce canonical extraction span proposals: Meeting Date, Meeting Time, Meeting Members, Meeting Agenda, and Action Description in Request_Action events. Uncertain concepts such as deadlines, requested documents, and responsible parties remain as candidate mappings in `ai/annotation/mailex_mapping.json`. Even emitted spans are weak, provisional proposals, not FYP gold. Each span is marked `requires_project_scope_human_review`, and every MailEx record carries `annotation.needs_review=true`; a human must decide whether its email concerns a university project. Classification `labels` remain empty and `annotation.status` remains `unlabelled` throughout. In particular, event mentions like a social lunch do not establish FYP project relevance.

## Observed counts and source anomalies

The executed converter produced 3,936 message records from 1,500 thread files: 3,609 non-empty usable messages and 327 empty messages. It retained 8,392 event instances and 18,099 source argument segments. Of those arguments, 2,979 mapped directly to provisional spans, 13,928 were retained as ambiguous candidates, and 1,192 were unmapped or suppressed. Identical canonical entities repeated by source events were collapsed: 57 duplicate span instances before normalization, 0 afterward, leaving 2,922 unique provisional canonical spans. Each retained entity lists all contributing source-event provenance entries. No FYP classification labels were inferred.

The paper and repository summarize 10 event types, while the downloaded `full_data` contains 11 observed non-O types, including three `Amend_Action_Data` instances. The archive also contains 776 `O` markers, but four turns have both an `O` marker and a non-O event trigger. Therefore the converter reports 776 marker turns separately from 772 O-only turns (and 772 messages without a non-O event). These source details are represented in `ai/reports/mailex_stats.json` rather than silently normalized away.

The stats also record 242 duplicate non-empty message copies across 159 text groups. Duplicates are preserved because they are distinct source turns; no cross-message deduplication is performed by this converter.

## Reproduction

From the repository root in PowerShell, starting from the preserved ZIP:

```powershell
Expand-Archive -LiteralPath ai\data\raw\mailex\data.zip -DestinationPath ai\data\raw\mailex\extracted -Force
python ai\scripts\prepare_mailex.py
python ai\scripts\validate_dataset.py ai\data\processed\mailex.jsonl
python -m unittest discover -s ai\tests -t ai -v
```

The preparation script writes `ai/data/processed/mailex.jsonl` and the executed statistics to `ai/reports/mailex_stats.json`. If the project runtime's Python executable is not on `PATH`, substitute its full path for `python`.
