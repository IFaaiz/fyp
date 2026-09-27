"""Compare two independent AI annotations of the fixed 50-email pilot.

Run this only after both AI reviewers have finished writing their canonical
JSONL outputs. The comparison measures agreement between the two outputs; it
does not measure accuracy against gold labels.

Example from the repository root:

    python ai/scripts/compare_ai_pilot.py --reviewer-a path/to/a.jsonl --reviewer-b path/to/b.jsonl --report ai/reports/ai_pilot_agreement.json

The email-text disagreement queue defaults to the ignored generated-data tree
at ai/data/annotated/ai_reviewed/project_pilot_50.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.datasets.schemas import LABELS, SPAN_LABELS, read_jsonl
from src.datasets.validation import validate_record

PILOT_SIZE = 50
DATA_DIR = AI_DIR / "data"
MUTABLE_FIELDS = frozenset({"labels", "spans", "annotation"})
DEFAULT_PILOT_SEED = AI_DIR / "data" / "annotated" / "human" / "project_pilot_50" / "annotation_seed_50.jsonl"
DEFAULT_QUEUE = AI_DIR / "data" / "annotated" / "ai_reviewed" / "project_pilot_50" / "disagreements.jsonl"


def _read_records(path: Path, description: str) -> list[dict[str, Any]]:
    try:
        return list(read_jsonl(path))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read {description} {path}: {exc}") from exc


def _span_key(span: dict[str, Any]) -> tuple[Any, ...]:
    return (
        span.get("label"), span.get("field", "current_message"),
        span.get("start"), span.get("end"), span.get("text"),
    )


def _require_unique_ids(rows: list[dict[str, Any]], description: str) -> list[str]:
    ids = [row.get("email_id") for row in rows]
    if any(not isinstance(email_id, str) or not email_id for email_id in ids):
        raise ValueError(f"{description} contains a missing or invalid email_id")
    duplicates = sorted(email_id for email_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"{description} contains duplicate email_id values: {duplicates[:5]}")
    return ids  # type: ignore[return-value]


def _check_records(
    seed_rows: list[dict[str, Any]], reviewer_rows: list[dict[str, Any]], reviewer_name: str,
) -> None:
    expected_ids = _require_unique_ids(seed_rows, "pilot seed")
    actual_ids = _require_unique_ids(reviewer_rows, f"reviewer {reviewer_name}")
    if len(reviewer_rows) != len(seed_rows):
        raise ValueError(
            f"reviewer {reviewer_name} has {len(reviewer_rows)} records; expected {len(seed_rows)}"
        )
    if actual_ids != expected_ids:
        first_difference = next(
            index for index, (expected, actual) in enumerate(zip(expected_ids, actual_ids), 1)
            if expected != actual
        )
        raise ValueError(
            f"reviewer {reviewer_name} email_id order differs at record {first_difference}: "
            f"expected {expected_ids[first_difference - 1]!r}, got {actual_ids[first_difference - 1]!r}"
        )

    for index, (seed, reviewed) in enumerate(zip(seed_rows, reviewer_rows), 1):
        email_id = expected_ids[index - 1]
        for field in seed:
            if field in MUTABLE_FIELDS:
                continue
            if field not in reviewed:
                raise ValueError(
                    f"reviewer {reviewer_name} record {index} ({email_id}) is missing source field {field!r}"
                )
            if reviewed[field] != seed[field]:
                raise ValueError(
                    f"reviewer {reviewer_name} record {index} ({email_id}) changed source field {field!r}"
                )

        errors = validate_record(reviewed)
        if errors:
            raise ValueError(
                f"reviewer {reviewer_name} record {index} ({email_id}) is invalid: {'; '.join(errors)}"
            )
        annotation = reviewed.get("annotation", {})
        if "needs_review" in annotation and not isinstance(annotation["needs_review"], bool):
            raise ValueError(
                f"reviewer {reviewer_name} record {index} ({email_id}) needs_review must be boolean"
            )
        if annotation.get("annotation_source") != "ai":
            raise ValueError(
                f"reviewer {reviewer_name} record {index} ({email_id}) must have annotation_source='ai'"
            )
        if annotation.get("status") not in {"ai_prelabelled", "unlabelled"}:
            raise ValueError(
                f"reviewer {reviewer_name} record {index} ({email_id}) status must be "
                "'ai_prelabelled' or 'unlabelled'"
            )


        if annotation["status"] == "ai_prelabelled" and not reviewed["labels"]:
            raise ValueError(
                f"reviewer {reviewer_name} record {index} ({email_id}) has empty labels while "
                "marked ai_prelabelled; mark unresolved records unlabelled"
            )

def _check_seed(seed_rows: list[dict[str, Any]]) -> None:
    if len(seed_rows) != PILOT_SIZE:
        raise ValueError(f"pilot seed must contain exactly {PILOT_SIZE} records; found {len(seed_rows)}")
    ids = _require_unique_ids(seed_rows, "pilot seed")
    for index, row in enumerate(seed_rows, 1):
        errors = validate_record(row)
        if errors:
            raise ValueError(f"pilot seed record {index} ({ids[index - 1]}) is invalid: {'; '.join(errors)}")
        if row.get("source_dataset") != "enron":
            raise ValueError(f"pilot seed record {index} ({ids[index - 1]}) is not an Enron record")
        if row.get("labels") != [] or row.get("spans") != []:
            raise ValueError(f"pilot seed record {index} ({ids[index - 1]}) must have empty labels and spans")
        annotation = row.get("annotation", {})
        if annotation.get("status") != "unlabelled" or annotation.get("annotation_source") is not None:
            raise ValueError(
                f"pilot seed record {index} ({ids[index - 1]}) must be an unlabelled source record"
            )


def _agreement_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    """Compute pairwise raw agreement for exactly the supplied record pairs."""
    n = len(pairs)
    label_counts: dict[str, Counter[str]] = {label: Counter() for label in LABELS}
    label_set_matches = 0
    span_label_counts: dict[str, Counter[str]] = {label: Counter() for label in SPAN_LABELS}
    span_set_matches = 0
    total_shared_spans = total_a_only_spans = total_b_only_spans = 0

    for a, b in pairs:
        labels_a, labels_b = set(a["labels"]), set(b["labels"])
        spans_a = Counter(_span_key(span) for span in a["spans"])
        spans_b = Counter(_span_key(span) for span in b["spans"])
        label_set_matches += labels_a == labels_b
        span_set_matches += spans_a == spans_b
        for label in LABELS:
            a_has, b_has = label in labels_a, label in labels_b
            if a_has and b_has:
                label_counts[label]["both_present"] += 1
            elif not a_has and not b_has:
                label_counts[label]["both_absent"] += 1
            elif a_has:
                label_counts[label]["a_only"] += 1
            else:
                label_counts[label]["b_only"] += 1
        for label in SPAN_LABELS:
            spans_for_label_a = Counter(key for key in spans_a.elements() if key[0] == label)
            spans_for_label_b = Counter(key for key in spans_b.elements() if key[0] == label)
            span_label_counts[label]["records_exact_match"] += spans_for_label_a == spans_for_label_b
            shared = spans_for_label_a & spans_for_label_b
            a_only = spans_for_label_a - spans_for_label_b
            b_only = spans_for_label_b - spans_for_label_a
            span_label_counts[label]["shared_spans"] += sum(shared.values())
            span_label_counts[label]["a_only_spans"] += sum(a_only.values())
            span_label_counts[label]["b_only_spans"] += sum(b_only.values())
        total_shared_spans += sum((spans_a & spans_b).values())
        total_a_only_spans += sum((spans_a - spans_b).values())
        total_b_only_spans += sum((spans_b - spans_a).values())

    per_label: dict[str, Any] = {}
    for label in sorted(LABELS):
        counts = label_counts[label]
        agreed = counts["both_present"] + counts["both_absent"]
        per_label[label] = {
            "both_present": counts["both_present"],
            "both_absent": counts["both_absent"],
            "a_only": counts["a_only"],
            "b_only": counts["b_only"],
            "agreement_records": agreed,
            "agreement_rate": agreed / n if n else None,
        }

    per_span_label: dict[str, Any] = {}
    for label in sorted(SPAN_LABELS):
        counts = span_label_counts[label]
        per_span_label[label] = {
            "records_exact_match": counts["records_exact_match"],
            "exact_match_rate": counts["records_exact_match"] / n if n else None,
            "shared_spans": counts["shared_spans"],
            "a_only_spans": counts["a_only_spans"],
            "b_only_spans": counts["b_only_spans"],
        }

    return {
        "records": n,
        "classification": {
            "label_set_exact_match_records": label_set_matches,
            "label_set_exact_match_rate": label_set_matches / n if n else None,
            "per_label": per_label,
        },
        "spans": {
            "record_exact_span_set_match_records": span_set_matches,
            "record_exact_span_set_match_rate": span_set_matches / n if n else None,
            "shared_span_instances": total_shared_spans,
            "a_only_span_instances": total_a_only_spans,
            "b_only_span_instances": total_b_only_spans,
            "per_span_label": per_span_label,
        },
    }


def compare_ai_pilot_records(
    seed_rows: Iterable[dict[str, Any]],
    reviewer_a_rows: Iterable[dict[str, Any]],
    reviewer_b_rows: Iterable[dict[str, Any]],
    *,
    reviewer_a_name: str = "A",
    reviewer_b_name: str = "B",
) -> dict[str, Any]:
    """Validate outputs and report raw and clean inter-AI agreement."""
    seed = list(seed_rows)
    reviewer_a = list(reviewer_a_rows)
    reviewer_b = list(reviewer_b_rows)
    _check_seed(seed)
    _check_records(seed, reviewer_a, reviewer_a_name)
    _check_records(seed, reviewer_b, reviewer_b_name)

    queue: list[dict[str, Any]] = []
    status_counts = {reviewer_a_name: Counter(), reviewer_b_name: Counter()}
    reviewer_flag_ids = {reviewer_a_name: [], reviewer_b_name: []}
    unresolved_ids: list[str] = []
    both_ai_prelabelled_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    clean_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    all_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for row in reviewer_a:
        status_counts[reviewer_a_name][row["annotation"]["status"]] += 1
    for row in reviewer_b:
        status_counts[reviewer_b_name][row["annotation"]["status"]] += 1

    for seed_row, a, b in zip(seed, reviewer_a, reviewer_b):
        email_id = seed_row["email_id"]
        annotation_a, annotation_b = a["annotation"], b["annotation"]
        status_a, status_b = annotation_a["status"], annotation_b["status"]
        flag_a = annotation_a.get("needs_review") is True
        flag_b = annotation_b.get("needs_review") is True
        if flag_a:
            reviewer_flag_ids[reviewer_a_name].append(email_id)
        if flag_b:
            reviewer_flag_ids[reviewer_b_name].append(email_id)

        labels_a, labels_b = set(a["labels"]), set(b["labels"])
        spans_a = Counter(_span_key(span) for span in a["spans"])
        spans_b = Counter(_span_key(span) for span in b["spans"])
        labels_differ = labels_a != labels_b
        spans_differ = spans_a != spans_b
        all_pairs.append((a, b))

        both_ai_prelabelled = status_a == status_b == "ai_prelabelled"
        unresolved_by = [
            name for name, status in ((reviewer_a_name, status_a), (reviewer_b_name, status_b))
            if status != "ai_prelabelled"
        ]
        if unresolved_by:
            unresolved_ids.append(email_id)
        if both_ai_prelabelled:
            both_ai_prelabelled_pairs.append((a, b))
            if not flag_a and not flag_b:
                clean_pairs.append((a, b))

        needs_review_by = [
            name for name, flagged in ((reviewer_a_name, flag_a), (reviewer_b_name, flag_b))
            if flagged
        ]
        if unresolved_by or needs_review_by or labels_differ or spans_differ:
            queue.append({
                "email_id": email_id,
                "thread_id": seed_row["thread_id"],
                "source_dataset": seed_row["source_dataset"],
                "subject": seed_row["subject"],
                "current_message": seed_row["current_message"],
                "thread_context": seed_row["thread_context"],
                "metadata": {
                    key: seed_row[key]
                    for key in ("sender", "recipients", "cc", "sent_at", "attachment_names")
                },
                "review_status": {reviewer_a_name: status_a, reviewer_b_name: status_b},
                "unresolved": bool(unresolved_by),
                "unresolved_by": unresolved_by,
                "needs_review": bool(needs_review_by),
                "needs_review_by": needs_review_by,
                "labels": {reviewer_a_name: sorted(labels_a), reviewer_b_name: sorted(labels_b)},
                "spans": {
                    reviewer_a_name: sorted(a["spans"], key=_span_key),
                    reviewer_b_name: sorted(b["spans"], key=_span_key),
                },
                "classification_disagreement": labels_differ,
                "span_disagreement": spans_differ,
            })

    flag_a_ids = set(reviewer_flag_ids[reviewer_a_name])
    flag_b_ids = set(reviewer_flag_ids[reviewer_b_name])
    any_flag_ids = [
        row["email_id"] for row in seed
        if row["email_id"] in flag_a_ids or row["email_id"] in flag_b_ids
    ]
    reviewer_flags = {
        name: {"count": len(email_ids), "email_ids": email_ids}
        for name, email_ids in reviewer_flag_ids.items()
    }

    return {
        "pilot_records": len(seed),
        "paired_records": len(all_pairs),
        "both_ai_prelabelled_records": len(both_ai_prelabelled_pairs),
        "clean_subset_records": len(clean_pairs),
        "unresolved_records": len(unresolved_ids),
        "unresolved_email_ids": unresolved_ids,
        "needs_review_flags": {
            "flagged_records": len(any_flag_ids),
            "flagged_email_ids": any_flag_ids,
            "by_reviewer": reviewer_flags,
        },
        "reviewer_status_counts": {
            name: dict(sorted(counts.items())) for name, counts in status_counts.items()
        },
        "raw_pairwise_agreement": {
            "basis": "All paired records, including unresolved and needs_review records. Empty labels on unresolved rows are raw output values, not verified negatives.",
            **_agreement_metrics(all_pairs),
        },
        "clean_subset_agreement": {
            "basis": "Both reviewers marked ai_prelabelled and neither set needs_review=true.",
            **_agreement_metrics(clean_pairs),
        },
        "metric_interpretation": "Agreement between the two AI outputs only; not accuracy against gold labels.",
        "comparison_is_inter_ai_agreement_only": True,
        "gold_labels_used": False,
        "accuracy_reported": False,
        "disagreement_count": len(queue),
        "disagreements": queue,
    }

def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-seed", type=Path, default=DEFAULT_PILOT_SEED,
                        help="fixed canonical 50-record pilot seed (default: %(default)s)")
    parser.add_argument("--reviewer-a", type=Path, required=True,
                        help="AI reviewer A canonical JSONL, read after both reviewers finish")
    parser.add_argument("--reviewer-b", type=Path, required=True,
                        help="AI reviewer B canonical JSONL, read after both reviewers finish")
    parser.add_argument("--report", type=Path, required=True, help="JSON metrics report output")
    parser.add_argument("--disagreements", type=Path,
                        help="readable email-text queue JSONL; defaults under ignored ai/data/annotated/ai_reviewed/project_pilot_50")
    args = parser.parse_args(argv)

    input_paths = [args.pilot_seed.resolve(), args.reviewer_a.resolve(), args.reviewer_b.resolve()]
    if input_paths[1] == input_paths[2]:
        parser.error("--reviewer-a and --reviewer-b must be different files")
    report_path = args.report.resolve()
    queue_path = (args.disagreements or DEFAULT_QUEUE).resolve()
    try:
        queue_path.relative_to(DATA_DIR.resolve())
    except ValueError:
        parser.error("the email-text disagreement queue must be under ignored ai/data/")
    if queue_path.suffix.lower() != ".jsonl":
        parser.error("the email-text disagreement queue must use a .jsonl filename")
    if report_path == queue_path:
        parser.error("--report and --disagreements must be different files")
    if report_path in input_paths or queue_path in input_paths:
        parser.error("output paths must not overwrite the pilot seed or reviewer inputs")

    try:
        seed = _read_records(args.pilot_seed, "pilot seed")
        reviewer_a = _read_records(args.reviewer_a, "reviewer A output")
        reviewer_b = _read_records(args.reviewer_b, "reviewer B output")
        report = compare_ai_pilot_records(seed, reviewer_a, reviewer_b)
    except ValueError as exc:
        parser.error(str(exc))

    disagreements = report.pop("disagreements")
    _write_json(report_path, report)
    _write_jsonl(queue_path, disagreements)
    print(json.dumps({
        "paired_records": report["paired_records"],
        "both_ai_prelabelled_records": report["both_ai_prelabelled_records"],
        "clean_subset_records": report["clean_subset_records"],
        "unresolved_records": report["unresolved_records"],
        "review_flagged_records": report["needs_review_flags"]["flagged_records"],
        "disagreement_count": report["disagreement_count"],
        "report": str(report_path),
        "disagreement_queue": str(queue_path),
        "metric_interpretation": "Agreement between the two AI outputs only; not accuracy against gold labels.",
        "comparison_is_inter_ai_agreement_only": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
