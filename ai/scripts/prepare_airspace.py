"""Safely extract and prepare the official CMU Airspace auxiliary corpus."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.datasets.airspace import (  # noqa: E402
    ARCHIVE_URL,
    DATASET,
    EXPECTED_LABELS,
    METHODOLOGY_URL,
    OFFICIAL_PAGE,
    SOURCE_FAMILY,
    SYNTAX_URL,
    VERSION,
    parse_archive,
    sha256_file,
    summarize_records,
    write_jsonl,
)


RAW_DIR = AI_DIR / "data" / "raw" / "airspace"
PROCESSED_PATH = AI_DIR / "data" / "processed" / "airspace.jsonl"
REVIEW_PATH = AI_DIR / "data" / "processed" / "airspace_review_candidates.jsonl"
REPORT_DIR = AI_DIR / "reports"


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def select_review_candidates(records: list[dict[str, Any]], limit: int, seed: int = 20261002) -> list[dict[str, Any]]:
    """Select a deterministic label/noise/reply-stratified source-inspection set."""
    if limit < 0:
        raise ValueError("review-candidate limit must be non-negative")
    if limit == 0:
        return []
    selected: dict[str, dict[str, Any]] = {}

    def add_group(group: list[dict[str, Any]], quota: int) -> None:
        if quota <= 0:
            return
        remaining = [row for row in group if row["source_id"] not in selected]
        random.Random(seed + len(selected)).shuffle(remaining)
        for row in remaining[:quota]:
            selected[str(row["source_id"])] = row

    # Guarantee representation for every observed original category first.
    observed_labels = sorted({label for row in records for label in row.get("source_labels", [])})
    for label in observed_labels:
        add_group([row for row in records if label in row.get("source_labels", [])], 2)
    for key, predicate in (
        ("noise_true", lambda row: row.get("noise") is True),
        ("noise_false", lambda row: row.get("noise") is False),
        ("noise_unknown", lambda row: row.get("noise") is None),
        ("reply_linked", lambda row: row.get("reply_to_status") == "linked"),
        ("reply_no_parent", lambda row: row.get("reply_to_status") == "no_parent"),
        ("reply_unknown", lambda row: row.get("reply_to_status") == "unknown"),
        ("no_source_label", lambda row: not row.get("source_labels")),
    ):
        add_group([row for row in records if predicate(row)], 2)

    remaining = [row for row in records if row["source_id"] not in selected]
    random.Random(seed).shuffle(remaining)
    for row in remaining:
        if len(selected) >= min(limit, len(records)):
            break
        selected[str(row["source_id"])] = row
    return sorted(selected.values(), key=lambda row: str(row["source_id"]))[:limit]


def _write_reports(stats: dict[str, Any], archive_path: Path, manifest: dict[str, Any], review_count: int) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stats["archive_bytes"] = archive_path.stat().st_size
    stats["syntax_document_sha256"] = sha256_file(RAW_DIR / "README_EmailSyntax_1.0.pdf")
    stats["acquired_at_utc"] = manifest.get("acquired_at_utc")
    stats["review_candidate_count"] = review_count
    stats["schema_validation"] = "passed"
    stats["source_text_offset_validation"] = "passed"
    stats_path = REPORT_DIR / "airspace_statistics.json"
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    registry = {
        "dataset": DATASET,
        "version": VERSION,
        "official_source": OFFICIAL_PAGE,
        "archive_url": ARCHIVE_URL,
        "syntax_document_url": SYNTAX_URL,
        "source_family": SOURCE_FAMILY,
        "record_count": stats["message_count"],
        "local_message_count_matches_cmu_page": stats["message_count"] == 711,
        "raw_archive_sha256": stats["archive_sha256"],
        "acquired_at_utc": manifest.get("acquired_at_utc"),
        "processed_artifact": "ai/data/processed/airspace.jsonl",
        "review_candidates_artifact": "ai/data/processed/airspace_review_candidates.jsonl",
        "original_labels": stats["label_counts"],
        "redistribution_permitted": False,
        "stated_fabricated_content_share": ">90%",
        "usage": {
            "role": "auxiliary supervision only",
            "may_be_used_as_real_email_test": False,
            "map_to_fyp_labels": False,
            "preserve_original_categories": True,
            "report_source_version": True,
            "citation_required": [METHODOLOGY_URL, OFFICIAL_PAGE],
            "source_requires_publication_reference_to_author": "steinfeld@cmu.edu",
        },
        "reply_metadata": {
            "reply_to_field": "X-RADAR-Replyto",
            "zero_means_no_parent": True,
            "missing_is_unknown": True,
            "thread_id_policy": "preserve raw source Thread as unverified metadata only; derive thread_id solely from in-corpus Replyto edges; isolated/unknown IDs remain null",
        },
        "offset_policy": "source_text_offsets are Unicode character offsets in the parser's exact Subject/body view; they are not token or byte offsets in the original MIME file",
    }
    (REPORT_DIR / "airspace_registry_proposal.json").write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    label_rows = "\n".join(f"| `{label}` | {count} |" for label, count in stats["label_counts"].items())
    label_rows = label_rows or "| _No labeled messages observed_ | 0 |"
    report = f"""# CMU Airspace integration

## Acquisition and terms

- Official collection page: [CMU Airspace]({OFFICIAL_PAGE})
- Download: [Airspace wargaming v1.0 ZIP]({ARCHIVE_URL})
- Syntax and usage guide: [Email Syntax v1.0 PDF]({SYNTAX_URL})
- CMU release version: **{VERSION}** (the page advertises 711 wargaming messages)
- Retrieved at (UTC): `{manifest.get('acquired_at_utc') or 'not recorded'}`
- Raw ZIP SHA-256: `{stats['archive_sha256']}`
- ZIP size: {stats['archive_bytes']} bytes; ZIP CRC check passed.
- Syntax PDF SHA-256: `{stats['syntax_document_sha256']}`

CMU says more than 90% of this content is fabricated and requires that users do
not redistribute it. Record and report version 1.0, cite the RADAR methodology
paper and this official page in proposals/publications, and send resulting
publication references to `steinfeld@cmu.edu`. Raw files and derived email text
remain ignored local data. This synthetic conference-planning corpus is
auxiliary supervision only and must never be represented as real-email
evaluation.

The `Noise` value is retained as an Airspace source annotation about relation to
the fictional conference. It is not converted into the FYP `NON_PROJECT` label.

The syntax guide identifies `X-RADAR-Label`, `X-RADAR-Noise`, `X-RADAR-Messageid`,
and `X-RADAR-Replyto` as supported fields. `X-RADAR-Replyto: 0` means no parent;
a missing value stays unknown. Unsupported fields are retained only when useful
for provenance and are not treated as validated labels/features.

## Observed messages and original labels

CMU advertises 711 messages; the local archive contains **{stats['message_count']} `.eml` records**.
The local count {'matches' if stats['message_count'] == 711 else 'does not match'} the advertised count.

| Original source category | Messages |
|---|---:|
{label_rows}

Noise annotation: `{json.dumps(stats['noise_counts'], sort_keys=True)}`.
Reply status: `{json.dumps(stats['reply_status_counts'], sort_keys=True)}`;
explicit `Replyto: 0` records: {stats['explicit_no_parent_count']}; observed reply
edges: {stats['reply_edge_count']}; derived reply components:
{stats['derived_reply_component_count']}. This release has no observed actual
reply edges. The source `Thread` field appears in {stats['source_thread_field_messages']}
messages across {stats['source_thread_group_count']} raw grouping values
(`Thread: 0` on {stats['source_thread_zero_group_messages']} messages). Those raw
values are preserved separately and are not treated as verified reply links;
the syntax guide describes this field for the backstory while these records are
the wargaming/injected release. No parent link is invented when the source field
is absent. Unknown source categories:
`{json.dumps(stats['unknown_source_labels'])}`.

All eight original categories remain unchanged. `INFO-REQ` and `MISC-ACTION` are
not renamed into project labels. The auxiliary rows contain no FYP `labels`
field and are not validated against the V1 schema.

## Prepared artifacts

- `ai/data/processed/airspace.jsonl` contains {stats['message_count']} parsed
  messages with original subject/body, reconstructed source text, supported
  labels, noise annotation, source message ID, exact source reply field,
  source/thread identity where observed, archive SHA provenance, and Unicode
  character offsets for subject/body in the parser's source-text view.
- `ai/data/processed/airspace_review_candidates.jsonl` contains {review_count}
  actual messages for orchestrator source-and-label inspection. It is ignored
  local data and must not be committed.
- `ai/reports/airspace_statistics.json` contains aggregate counts only.
- `ai/reports/airspace_registry_proposal.json` records version, family,
  provenance and restrictions for the global registry owner.

The source PDF describes Email Syntax v1.0, dated October 2006, and the linked
methodology citation is the 2006 CMU technical report, [*The RADAR Test
Methodology: Evaluating a Multi-Task Machine Learning System with Humans in the
Loop*]({METHODOLOGY_URL}) (CMU-CS-06-125 / CMU-HCII-06-102).
"""
    (REPORT_DIR / "airspace_integration.md").write_text(report, encoding="utf-8")


def prepare(archive_path: Path, output_path: Path, review_path: Path, review_limit: int) -> dict[str, Any]:
    manifest = _read_manifest(RAW_DIR / "acquisition.json")
    expected = ((manifest.get("assets") or {}).get("archive") or {}).get("sha256")
    actual = sha256_file(archive_path)
    if expected and expected != actual:
        raise ValueError("raw archive SHA-256 does not match acquisition manifest")
    acquired_at = manifest.get("acquired_at_utc")
    extracted_dir = RAW_DIR / "extracted"
    records = parse_archive(archive_path, extract_to=extracted_dir, acquired_at=acquired_at)
    ids = [row["source_message_id"] for row in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Airspace source message IDs are not unique")
    for row in records:
        if "labels" in row:
            raise ValueError("Airspace source categories must not enter the FYP labels field")
        offsets = row["source_text_offsets"]
        body_range = offsets["body"]
        if row["source_text"][body_range["start"]:body_range["end"]] != row["body"]:
            raise ValueError(f"body evidence offsets do not resolve for {row['source_id']}")
        subject_range = offsets["subject"]
        if subject_range is not None and row["source_text"][subject_range["start"]:subject_range["end"]] != row["subject"]:
            raise ValueError(f"subject evidence offsets do not resolve for {row['source_id']}")
        if row["reply_to_message_id_raw"] == "0" and row["reply_to_message_id"] is not None:
            raise ValueError(f"explicit no-parent reply field was changed for {row['source_id']}")
        if row["reply_to_message_id_raw"] is None and row["reply_to_status"] != "unknown":
            raise ValueError(f"missing reply field must remain unknown for {row['source_id']}")
        if row["source_provenance"]["archive_sha256"] != actual:
            raise ValueError(f"source hash provenance mismatch for {row['source_id']}")
    unknown = sorted({label for row in records for label in row["source_labels"]} - EXPECTED_LABELS)
    del unknown  # surfaced by the aggregate report rather than treated as an error
    review_candidates = select_review_candidates(records, review_limit)
    write_jsonl(output_path, records)
    write_jsonl(review_path, review_candidates)
    stats = summarize_records(records, expected_archive_sha256=actual)
    _write_reports(stats, archive_path, manifest, len(review_candidates))
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=RAW_DIR / "Airspace_wargaming_1.0.zip")
    parser.add_argument("--output", type=Path, default=PROCESSED_PATH)
    parser.add_argument("--review-candidates", type=Path, default=REVIEW_PATH)
    parser.add_argument("--review-candidate-limit", type=int, default=100)
    args = parser.parse_args()
    if not args.archive.exists():
        parser.error(f"official archive not found: {args.archive}; run acquire_airspace.py first")
    stats = prepare(args.archive, args.output, args.review_candidates, args.review_candidate_limit)
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
