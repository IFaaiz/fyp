# RADAR Action-Item Integration

## Status and provenance

The official CMU RADAR Action-Item page and its linked archive were reachable on 2026-10-02. The local acquisition is pinned by archive SHA-256 `1cee24880166b982ea25feaae0a0b23a04b7edf4de7b6c8ca098c390c5667e43` (428,285 bytes). The page does not publish a numbered release version or an upstream checksum, so this digest identifies the exact local source snapshot. Provenance and the saved copy of the official page are under ignored `ai/data/raw/radar_action/`.

- Official documentation: <https://www.cs.cmu.edu/~pbennett/action-item-dataset.html>
- Official archive link: <http://www.cs.cmu.edu/~pbennett/action-item-dataset.tgz>
- Citation requested by the source: Bennett and Carbonell, “Detecting Action-Items in E-mail,” SIGIR 2005 Beyond the Bag of Words Workshop.

The source page and README say an IRB panel review found the anonymized release exempt from further review and suitable for research distribution. They do not state an open-source license or grant general redistribution rights. The project therefore keeps raw and processed email text in ignored local data directories and does not add corpus text to Git. This is conservative handling based on the published wording, not a legal determination.

## What the release contains

The archive contains 744 message files, 744 action-item judgment rows, 744 message-to-annotation mappings, and 744 additional-annotation files. The parser found 328 messages judged action-item-positive and 416 judged negative. The 328 positive messages contain 416 source action-item spans: 259 messages have one span, 55 have two, 11 have three, two have four, and one has six.

The additional files contain 20,815 character spans. They cover sentence boundaries (6,308) and structured types such as person (2,063), organization (3,437), date (1,529), time (329), contact information (1,166), locations, quantities, and other entity types. See [radar_action_statistics.json](radar_action_statistics.json) for the full aggregate type counts. Every released action-item span and every additional span was checked against the corresponding original message text; all 21,231 slices were in bounds and matched the recorded start/length.

## Anonymization and transfer value

CMU documents that names were first replaced using corresponding dictionaries and then each unique token was consistently mapped to a random string of the same length. The released messages preserve sequence and approximate surface structure, but meaningful lexical content is obscured. The message files are ASCII with LF newlines, so UTF-8 decoding is strict and byte lengths match character counts for this snapshot.

This corpus can support experiments with action-item presence and span extraction, especially sequence structure and offset handling. It should not be presented as an ordinary useful text corpus for pretrained encoder training or as strong semantic transfer to FYP emails: the token substitutions remove the lexical meanings that such transfer depends on. Its 744-message size also limits the evidence available for broad transfer claims.

An action item means a span judged to contain an action item. It is not necessarily an explicit request made by the current sender. The adapter keeps the source judgment and span annotations intact and applies no direct mapping to FYP `ACTION_REQUEST`.

## Offset and message-field handling

The official documentation says character offsets point into the message file. It does not explicitly state whether indexing begins at zero. The released start/length values are consistent with zero-based slicing, and every span matched that interpretation when applied to the full decoded source file. The adapter records zero-based, end-exclusive Unicode-code-point intervals as a validated interpretation of this release.

Offsets are measured against the complete original `text` value, including header lines, subject, blank separator, and body. The parser reads bytes and decodes UTF-8 without universal-newline translation; it does not strip headers or trim source text. Parsed `subject` and `body` values are convenience fields only. Consumers must use `offset_basis: "text"`, never the parsed body, to resolve a span.

The source states that threading, From/To/Date details, headers other than subject, and inline quoted prior-message portions were removed. Source filenames such as `msg-0.txt` are dataset filenames, not RFC Message-IDs. The adapter sets `source_message_id_kind` to `dataset_filename`, `rfc_message_id` to null, and `source_thread_id` to null; it does not infer threads.

## Local outputs and reproduction

- Full auxiliary records: ignored `ai/data/processed/radar_action.jsonl` (744 records).
- Review sample: ignored `ai/data/processed/radar_action_review_50.jsonl` (50 full records, deterministically alternating 25 positive and 25 negative messages when available).
- Text-free aggregates: [radar_action_statistics.json](radar_action_statistics.json).
- Dataset registry proposal for the root-owned registry: [radar_action_registry_proposal.json](radar_action_registry_proposal.json).

From the repository root, use the project's Python environment:

```powershell
& 'ai/.venv/Scripts/python.exe' ai/scripts/acquire_radar_action.py
& 'ai/.venv/Scripts/python.exe' ai/scripts/prepare_radar_action.py
```

Acquisition checks the pinned archive digest, refuses a changed archive, safely extracts only regular files/directories, and records local provenance. Preparation preserves full-file text, validates the source judgment and annotation offsets, writes auxiliary JSONL, and emits aggregate counts. No source labels are translated into FYP labels, and no shared schema, leakage helper, V1 artifact, or model was changed.
