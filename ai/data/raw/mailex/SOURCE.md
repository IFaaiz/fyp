# MailEx source and transformation note

- Dataset: MailEx, a 1,500-thread subset of Enron annotated for email event and argument extraction.
- Official repository: https://github.com/salokr/Email-Event-Extraction
- Paper: S. Srivastava et al., “MailEx: Email Event and Argument Extraction,” EMNLP 2023, https://aclanthology.org/2023.emnlp-main.801/
- Dataset archive: https://drive.google.com/file/d/1a336g4-wlEwsVbXLPB9wPQnBDRE933mb/view
- License: CC BY-SA 4.0, as declared in the official repository README: https://creativecommons.org/licenses/by-sa/4.0/
- Download date: 2026-09-24
- Archive file: `ai/data/raw/mailex/data.zip`
- Archive size: 5,476,134 bytes
- SHA-256: `DDA3CE5DA5FFC3452DD9E5A58CD69E19E68BD655EAFE1DEEC48E87204F6C37B4`

The untouched archive is retained beside an extracted copy in `ai/data/raw/mailex/extracted/`. The preparation script reads `data/full_data/*.json` once per thread. It reconstructs each message by joining the annotation token list with spaces, keeps that same conservative text in `raw_body`, `current_message`, and `clean_body`, and places earlier turns in `thread_context`. It does not infer classification labels. Source triggers, event types, meta-semantic role strings, and all recovered argument spans remain in `annotation.source_annotations`.

Direct canonical extraction mappings are limited to MailEx Meeting Date, Meeting Time, Meeting Members, and Meeting Agenda, plus Action Description in Request_Action events. The mapping file records uncertain candidates such as Action Date to DEADLINE_DATE and Data IdString to REQUESTED_DOCUMENT; these are retained as source arguments but are not emitted as canonical spans. This avoids treating MailEx event semantics as FYP gold annotations.

The archive also contains `data/raw_threads/` files with simple From/To/CC/Subject/Date lines and message text. These files are plain-text thread exports rather than RFC822 messages. The script copies header values only when the reversed raw-message order has the same number of turns and every normalized message body aligns above the configured threshold. Missing, miscounted, or poorly aligned metadata remains empty or null. Date and CC are often absent; attachment filenames are not inferred from message text.

The official repository and paper describe 10 event types. The downloaded `full_data` contains 11 non-O event keys, including three `Amend_Action_Data` trigger instances. The parser preserves and reports the observed source type instead of dropping it. MailEx is an Enron-derived English email dataset, so examples may contain personal or organizational details; keep the raw data local and retain attribution and share-alike terms when distributing adapted data.
