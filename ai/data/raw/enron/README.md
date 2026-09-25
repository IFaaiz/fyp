# Enron source provenance

## Source

- Dataset: CMU CALO Enron Email Dataset, May 7, 2015 release.
- Official project page: <https://www.cs.cmu.edu/~enron/>
- Official archive linked by that page: <https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz>
- Collection history: the source page says the underlying mail was made public by the U.S. Federal Energy Regulatory Commission during its investigation, then corrected and prepared by the CALO project with help from SRI.
- The source page reports approximately 0.5 million messages and about 1.7 GB for its tarred/gzipped release. The complete linked archive was downloaded locally. Its actual size is 443,254,787 bytes; the page's size is approximate and differs from the linked endpoint.
- License: the official page does not state a standard open-source or Creative Commons license. It describes the corpus as a research resource and asks users to be sensitive to the people represented. Confirm institutional use and redistribution terms before sharing derived email text.
- Source version/date checked: May 7, 2015 release; project page checked September 24, 2026.

## Corpus notes and use here

The CMU page says the release omits attachments and some messages removed after employee requests. It says invalid addresses were normalized when possible, with `no_address@enron.com` used when no recipient could be recovered. The `enrondata` source documentation also records that the CALO release replaced message IDs, canonicalized dates, and omitted some headers. These changes can limit thread reconstruction and exact metadata comparisons.

Use the corpus only as realistic corporate email text for candidate discovery and human annotation under the FYP's custom taxonomy. The preparation code extracts RFC 822 subject, body, sender, recipients, CC, date, attachment filenames when present, and explicit reply/reference links. When standard address headers are missing, it falls back to Enron's `X-From`, `X-To`, and `X-cc` headers. It does not infer classification labels from keywords. Records remain `labels: []` with `annotation.status: "unlabelled"`; random nonmatching samples are not gold `NON_PROJECT` examples. Candidate patterns search subject, current-message text, and explicit thread context, so quoted or earlier-thread wording can add a message to the review pool.

The official page currently links two 2026 papers questioning corpus authenticity and integrity. Treat the collection as historically useful but not as verified evidence about the authenticity of every message. Document this limitation in any report that uses the corpus.

## Local acquisition and staged checks

The archive is stored locally at `ai/data/raw/enron/enron_mail_20150507.tar.gz`. Its local SHA-256 is `b3da1b3fe0369ec3140bb4fbce94702c33b7da810ec15d718b3fadf5cd748ca7`. The checksum was computed locally and was not compared with a publisher checksum. Extraction completed to `ai/data/raw/enron/full/maildir`: 520,901 archive members, 517,401 files, 3,500 directories, and 1,421,183,736 uncompressed file bytes. No extraction error was reported. Machine-readable details are in `ai/reports/enron_acquisition.json` and `ai/data/raw/enron/extraction_stats.json`.

Deterministic staged runs processed the first sorted 1,000, 10,000, and 50,000 source files. The following counts were measured from their canonical JSONL records; parser-defect totals come from the preparation stats.

| Stage | Records | Recipients present | CC present | Empty raw bodies | Parser defects |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1,000 | 1,000 (100%) | 38 (3.80%) | 0 | 0 |
| 10,000 | 10,000 | 9,742 (97.42%) | 933 (9.33%) | 0 | 0 |
| 50,000 | 50,000 | 47,435 (94.87%) | 10,274 (20.55%) | 0 | 6 |

The stage outputs and stats are in ignored `ai/data/interim/enron_scale/`; the aggregate report is `ai/reports/enron_scale_staged.json`.

Deduplication removes source copies only when normalized Message-ID and decoded-body SHA-256 match; messages without Message-ID use the generated `email_id` fallback based on sender, recipients, CC, subject, date, and body. This is not semantic deduplication. Distinct Message-IDs or body digests can leave otherwise identical or near-duplicate messages in the output, so `duplicate_messages_removed` is a key-based count rather than a semantic duplicate count. No `References` or `In-Reply-To` values appeared in these sorted prefixes, so all staged records have singleton threads. This does not establish thread statistics for the full corpus.

An initial 256 KiB HTTP range check on September 24, 2026 yielded one real RFC 822 message. It parsed with a Message-ID, subject, sender, and 572 decoded body characters; it had no attachment filename. The retained sample is `ai/data/raw/enron/maildir/sample-mailbox/1`; its CLI output and stats are under `ai/data/processed/enron_sample.*`. The shared validator reported 1 Enron record and zero errors. The full archive was downloaded and extracted after this initial check.

## Full-corpus preparation and validation

The full maildir contained 517,401 message files and 1,421,183,736 source bytes. `prepare_enron.py` wrote all 517,401 files as canonical records to ignored `ai/data/interim/enron_full.jsonl` (2,918,125,901 bytes) in 5,776.93 seconds, with peak working set 923,627,520 bytes (about 881 MiB). The detailed machine-readable measurements are in `ai/reports/enron_full_stats.json`.

| Full-run measure | Result |
| --- | ---: |
| Source files / records written | 517,401 / 517,401 |
| Key-based duplicate copies removed | 0 |
| Records with nonempty raw body | 517,401 (100%) |
| Records with recipients | 502,681 (97.16%) |
| Records with CC | 128,824 (24.90%) |
| Records with subject | 498,214 |
| Records with sender | 517,399 |
| Parser defects | 30 |
| `References` / `In-Reply-To` values | 0 / 0 |
| Explicit-link threads | 0 multi-message; 517,401 singleton |
| Empty derived `current_message` | 10,201 (1.97%) |
| Validator result | 517,401 records, 0 errors |

The empty `current_message` values are derived-field gaps; each raw body is nonempty and remains in `raw_body`. Five sampled boundary cases showed `Forwarded by` and `-----Original Message-----` markers cut from `current_message` while retained in `raw_body`; their record IDs and boundary marker types are in the stats report. Explicit-reference threading cannot recover conversations without `References` or `In-Reply-To` headers, so the singleton counts do not imply that the underlying messages were unrelated.

The ingestion walks directories and filenames in sorted order without materializing every path, then writes records one at a time. It retains compact metadata for cross-file thread reconstruction and re-reads source files in a second pass. `ai/reports/enron_full_stats.json` contains runtime, peak memory, completeness, sampled-boundary, validation, and deduplication details. Use `--max-messages` for a bounded local sample. Candidate pool generation streams keyword matches and keeps only the requested-size reservoir of nonmatching records.

## Local setup

1. Download the official archive from the page above if it is not already available locally.
2. If it has not already been extracted, run `python ai/scripts/extract_enron_archive.py --stats-output ai/data/raw/enron/extraction_stats.json`; the expected input path is `ai/data/raw/enron/full/maildir/`.
3. Run `python ai/scripts/prepare_enron.py --maildir ai/data/raw/enron/full/maildir --output ai/data/interim/enron_full.jsonl --stats-output ai/reports/enron_full_stats.json` for the full corpus.
4. Build the full-corpus review pool with `python ai/scripts/create_candidate_pool.py --input ai/data/interim/enron_full.jsonl --output ai/data/interim/enron_candidates.jsonl --target-count 8000 --random-sample-count 2000 --seed 2026 --thread-mode whole --secondary-thread-links --report ai/reports/enron_candidate_pool.md`. The optional secondary links are strict one-to-one heuristic suggestions, not verified reply relationships; original canonical IDs are preserved in `source_thread_id`.

The archive and extracted files are ignored local data and are not committed to this repository. Avoid redistributing raw messages. The pipeline reads the maildir without changing its files. The resulting JSONL contains historical email text and should be handled with the same care as the source corpus.
