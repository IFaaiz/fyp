# CEREC thread/coreference corpus inspection

Reviewed 2026-10-02 from the author repository pinned at
`d86bdcdf963b4181aa7d6a3e3ca761c971ab27d9`. The author README describes an
Enron-derived CoNLL-style thread corpus with token, message/section feature,
speaker, entity-type, mention, and coreference columns. The adapter preserves
all seven observed source columns and the file role of each document. It keeps
the author's document identifier as a thread identifier, leaves message IDs
null, and does not infer a reply graph.

The repository declares Apache-2.0 and the COLING paper says CC BY 4.0, but the
available materials do not clearly establish that either grant covers the
embedded Enron message text. Text rights are unresolved. The archive and a
50-thread source/coreference review sample are local for inspection only;
The root's 50-sample source audit is complete. Redistribution and training
remain disabled pending rights, original identity/global-index integration
and review of suspicious entity links. No FYP labels are generated.

## Files and counts

| Author file | Preserved role | Documents | Token rows | Mention-annotated rows | Coreference-annotated rows | Distinct coreference IDs |
|---|---|---:|---:|---:|---:|---:|
| `cerec.conll` | Full corpus | 6,001 | 6,567,125 | 749,368 | 665,247 | 60,383 |
| `cerec.validation.14.conll` | Validation set 14 | 14 | 13,420 | 1,829 | 1,825 | 306 |
| `cerec.validation.20.conll` | Validation set 20 | 20 | 20,510 | 2,786 | 2,782 | 422 |
| `mention.corrected.94.conll` | Mention-corrected set | 94 | 92,374 | 13,362 | 0 | 0 |
| `seed.conll` | Seed corpus | 43 | 42,301 | 5,232 | 5,232 | 765 |

Each of the five files contains seven tab-delimited columns on every token
row. The README once calls the format eight-column but enumerates seven
columns; the pinned archive consistently has seven. The README says message,
section, speaker, and entity features in columns 2–5 are only supplied for the
validation and seed files or may contain system-generated values elsewhere.
The parser preserves those cells verbatim rather than treating feature counts
as authoritative message counts.

The README and 2020 paper report 38,996 chains for the 6,001-thread corpus; an
updated author paper reports 60,383. In the pinned `cerec.conll`, counting
distinct numeric IDs in the seventh-column coreference annotation separately
within each document yields 60,383. This matches the updated figure under that
explicit counting rule; it does not explain how the earlier paper obtained its
count. The main file has 6,001 document blocks, each with coreference
annotations. The archive's source roles are preserved and no test/validation
partition is invented.

Across the five files, source document identifiers are unique to their file in
this release (6,172 in the union; no repeated document IDs were observed).
This check compares only document-header IDs. It does not establish that
message content, Enron messages, or feature-level identities do not overlap.
Use the root-owned ENRON leakage controls before any eventual training or
evaluation.

## Acquisition details and disposition

The pinned author ZIP is 16,994,267 bytes with SHA-256
`6719223815d6a2301c01a596892d76c0cf33a03fff0ac53f7b43de4b93bc830b` and
GitHub blob SHA `4b86f155028285e93b50396a8bc5a4975875ed41`. It contains five
CoNLL files totaling 153,140,578 uncompressed bytes. Extraction checked archive
CRC, member paths, duplicate paths, and size limits. The parser streams source
files rather than loading the full 6.5-million-row corpus into memory.

The adapter is `ai/src/datasets/cerec.py`; `ai/scripts/acquire_cerec.py`
downloads the pinned archive and author documentation, and
`ai/scripts/prepare_cerec.py` writes text-free statistics plus the ignored
local review sample at `ai/data/processed/cerec_review_50.jsonl`. There is no
full prepared corpus output. Tracked reports and fixtures contain no source
message text.

Sources: [author repository](https://github.com/paragdakle/emailcoref),
[pinned archive](https://raw.githubusercontent.com/paragdakle/emailcoref/d86bdcdf963b4181aa7d6a3e3ca761c971ab27d9/data/COLING/cerec.zip),
[COLING paper](https://aclanthology.org/2020.coling-main.30.pdf),
[updated author paper](https://arxiv.org/abs/2105.10606).

## Orchestrator audit update — 2026-10-03

The user approved brief private excerpts. Personal audits now cover 51 Airspace, 50 Parakweet and 50 CEREC samples. See `auxiliary_source_audits.md` and the canonical registry for current gates; earlier pending-audit statements above describe the initial integration state. Airspace permits private original-task auxiliary use subject to global exclusions. Parakweet remains in original-identity quarantine. CEREC remains inspection-only pending rights, identity/global-index integration and review of suspected entity merges. No new FYP labels or human gold were created.
