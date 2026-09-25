"""Canonical JSONL and Label Studio task conversion helpers.

Label Studio reports JavaScript UTF-16 offsets for text regions. The project
JSONL contract uses Python Unicode code-point offsets, so this module converts
and validates every imported span before writing a canonical record.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from typing import Any

from ..datasets.schemas import LABELS, SPAN_LABELS
from ..datasets.validation import validate_record

CLASSIFICATION_CONTROL = "classification"
REVIEW_CONTROL = "review_decision"
NOTE_CONTROL = "review_note"
MESSAGE_SPAN_CONTROL = "message_spans"
SUBJECT_SPAN_CONTROL = "subject_spans"
SPAN_FIELDS = {
    MESSAGE_SPAN_CONTROL: "current_message",
    SUBJECT_SPAN_CONTROL: "subject",
}
REVIEWED = "Reviewed"
NEEDS_REVIEW = "Needs review"
COMPLETE_MULTIMESSAGE_THREAD_TARGET = 12
COMPLETE_MULTIMESSAGE_EMAIL_CAP = 30


def source_thread_key(record: dict[str, Any]) -> tuple[str, str]:
    """Return the record's current source-qualified thread key."""
    return (str(record.get("source_dataset", "")), str(record.get("thread_id", "")))


def source_thread_keys(record: dict[str, Any]) -> set[tuple[str, str]]:
    """Return current and original source-qualified thread keys when present.

    ``source_thread_id`` is optional and is added by heuristic thread linking.
    Ordinary canonical records need only the standard ``thread_id`` field.
    """
    source = str(record.get("source_dataset", ""))
    return {
        (source, value.strip())
        for field in ("thread_id", "source_thread_id")
        if isinstance((value := record.get(field)), str) and value.strip()
    }


def assert_no_gold_threads(records: Iterable[dict[str, Any]], gold_records: Iterable[dict[str, Any]] = ()) -> None:
    """Fail if any task record shares a current or original source thread with gold."""
    rows = list(records)
    gold_rows = list(gold_records)
    gold_threads = {
        key for row in gold_rows if row.get("annotation", {}).get("status") == "gold"
        for key in source_thread_keys(row)
    }
    blocked = sorted({str(row.get("email_id")) for row in rows
                      if source_thread_keys(row) & gold_threads
                      or row.get("annotation", {}).get("status") == "gold"})
    if blocked:
        raise ValueError(f"annotation tasks include records from gold threads: {blocked[:10]}")


def _allocate_quotas(total: int, capacities: dict[str, int]) -> dict[str, int]:
    """Allocate total proportionally, redistributing quotas from sparse groups."""
    allocated = {key: 0 for key in capacities}
    remaining = total
    while remaining:
        active = [key for key, capacity in capacities.items() if allocated[key] < capacity]
        if not active:
            break
        weight_total = sum(capacities[key] for key in active)
        ideals = {key: remaining * capacities[key] / weight_total for key in active}
        added = 0
        for key in active:
            amount = min(capacities[key] - allocated[key], int(ideals[key]))
            allocated[key] += amount
            added += amount
        remaining -= added
        if not remaining:
            break
        order = sorted(active, key=lambda key: (-(ideals[key] % 1), key))
        for key in order:
            if remaining and allocated[key] < capacities[key]:
                allocated[key] += 1
                remaining -= 1
        if not added and not order:
            break
    return allocated


def _sample_thread_expansion(
    rows: list[dict[str, Any]], count: int, metadata_by_id: dict[str, dict[str, Any]], rng: random.Random,
) -> list[dict[str, Any]]:
    """Pick expansion rows in thread groups so multi-message examples survive."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(source_thread_key(row), []).append(row)
    bundles = list(groups.values())
    rng.shuffle(bundles)
    bundles.sort(key=lambda bundle: (
        not all(metadata_by_id.get(row["email_id"], {}).get("thread_complete") is True for row in bundle),
        len(bundle) < 2, -len(bundle),
    ))
    selected: list[dict[str, Any]] = []
    unused = bundles[:]
    while len(selected) < count and unused:
        remaining = count - len(selected)
        fitting = [bundle for bundle in unused if len(bundle) <= remaining]
        bundle = fitting[0] if fitting else unused[0]
        if len(bundle) <= remaining:
            selected.extend(bundle)
        else:
            selected.extend(rng.sample(bundle, remaining))
        unused.remove(bundle)
    return selected


def _complete_multimessage_groups(
    rows: list[dict[str, Any]], metadata_by_id: dict[str, dict[str, Any]],
    *, metadata_available: bool,
) -> list[list[dict[str, Any]]]:
    """Find candidate threads fully represented by the pool and metadata."""
    if not metadata_available:
        return []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(source_thread_key(row), []).append(row)
    complete: list[list[dict[str, Any]]] = []
    for bundle in groups.values():
        if len(bundle) < 2:
            continue
        metadata = [metadata_by_id[row["email_id"]] for row in bundle]
        if all(
            item.get("thread_complete") is True
            and item.get("thread_total_count") == len(bundle)
            for item in metadata
        ):
            complete.append(bundle)
    return complete


def _reserve_complete_multimessage_groups(
    groups: list[list[dict[str, Any]]], stratum_by_id: dict[str, str],
    special_targets: dict[str, int], rng: random.Random,
    *, thread_target: int = COMPLETE_MULTIMESSAGE_THREAD_TARGET,
    email_cap: int = COMPLETE_MULTIMESSAGE_EMAIL_CAP,
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """Reserve up to 12 complete groups without exceeding special strata targets."""
    rng.shuffle(groups)
    groups.sort(key=lambda bundle: (
        len(bundle) != 2,
        not any(stratum_by_id[row["email_id"]] not in special_targets for row in bundle),
        sum(stratum_by_id[row["email_id"]] == "random_nonmatching" for row in bundle),
        len(bundle),
    ))
    selected_rows: list[dict[str, Any]] = []
    selected_groups: list[list[dict[str, Any]]] = []
    reserved_special_counts: dict[str, int] = {key: 0 for key in special_targets}
    for bundle in groups:
        if len(selected_groups) >= thread_target:
            break
        if len(selected_rows) + len(bundle) > email_cap:
            continue
        group_counts: dict[str, int] = {}
        for row in bundle:
            stratum = stratum_by_id[row["email_id"]]
            group_counts[stratum] = group_counts.get(stratum, 0) + 1
        if any(
            reserved_special_counts.get(stratum, 0) + group_counts.get(stratum, 0) > target
            for stratum, target in special_targets.items()
        ):
            continue
        selected_groups.append(bundle)
        selected_rows.extend(bundle)
        for stratum in special_targets:
            reserved_special_counts[stratum] += group_counts.get(stratum, 0)
    return selected_rows, selected_groups


def _allocate_seed_quotas(
    count: int, capacities: dict[str, int], reserved_by_stratum: dict[str, int],
    special_targets: dict[str, int],
) -> dict[str, int]:
    """Allocate remaining records around reserved groups and special strata."""
    remaining_count = count - sum(reserved_by_stratum.values())
    residual_capacities = {
        key: max(0, capacity - reserved_by_stratum.get(key, 0))
        for key, capacity in capacities.items()
    }
    residual_quotas = {key: 0 for key in capacities}
    for stratum, target in special_targets.items():
        target_left = max(0, target - reserved_by_stratum.get(stratum, 0))
        residual_quotas[stratum] = min(target_left, residual_capacities.get(stratum, 0))
    slots_left = remaining_count - sum(residual_quotas.values())
    ordinary = {
        key: value for key, value in residual_capacities.items()
        if key not in special_targets
    }
    ordinary_quotas = _allocate_quotas(min(slots_left, sum(ordinary.values())), ordinary)
    for stratum, quota in ordinary_quotas.items():
        residual_quotas[stratum] = quota
    slots_left = remaining_count - sum(residual_quotas.values())
    if slots_left:
        unused_capacity = {
            key: residual_capacities[key] - residual_quotas.get(key, 0)
            for key in capacities
        }
        redistributed = _allocate_quotas(slots_left, unused_capacity)
        for stratum, quota in redistributed.items():
            residual_quotas[stratum] += quota
    if sum(residual_quotas.values()) != remaining_count:
        raise ValueError("could not allocate the requested seed count around complete threads")
    return {
        key: reserved_by_stratum.get(key, 0) + residual_quotas.get(key, 0)
        for key in capacities
    }


def select_enron_seed_records(
    candidate_records: Iterable[dict[str, Any]], gold_records: Iterable[dict[str, Any]],
    *, count: int = 250, seed: int = 2026,
    metadata_records: Iterable[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], int, dict[str, Any]]:
    """Select a reproducible Enron seed with cue, random, and thread strata."""
    if not 200 <= count <= 300:
        raise ValueError("seed count must be between 200 and 300 inclusive")
    rows = list(candidate_records)
    ids = [row.get("email_id") for row in rows]
    if any(not isinstance(email_id, str) or not email_id for email_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("candidate pool must contain unique, nonempty email_id values")
    meta_rows = list(metadata_records or ())
    metadata_by_id: dict[str, dict[str, Any]] = {}
    for metadata in meta_rows:
        if not isinstance(metadata, dict):
            raise ValueError("candidate metadata records must be objects")
        email_id = metadata.get("email_id")
        if not isinstance(email_id, str) or not email_id or email_id in metadata_by_id:
            raise ValueError("candidate metadata must have unique, nonempty email_id values")
        metadata_by_id[email_id] = metadata
    metadata_available = metadata_records is not None
    if metadata_available:
        candidate_ids = set(ids)
        metadata_ids = set(metadata_by_id)
        missing_metadata = sorted(candidate_ids - metadata_ids)
        unexpected_metadata = sorted(metadata_ids - candidate_ids)
        if missing_metadata or unexpected_metadata:
            raise ValueError(
                "candidate metadata must cover exactly the candidate pool; "
                f"missing metadata for {missing_metadata[:5]}, "
                f"unexpected metadata for {unexpected_metadata[:5]}"
            )
        candidate_by_id = {row["email_id"]: row for row in rows}
        for email_id, metadata in metadata_by_id.items():
            if metadata.get("thread_id") != candidate_by_id[email_id].get("thread_id"):
                raise ValueError(f"metadata thread_id mismatch for {email_id}")
            if not isinstance(metadata.get("sampling_stratum"), str) or not metadata["sampling_stratum"].strip():
                raise ValueError(f"metadata sampling_stratum is missing for {email_id}")
            if not isinstance(metadata.get("primary_sampling_cue"), str) or not metadata["primary_sampling_cue"].strip():
                raise ValueError(f"metadata primary_sampling_cue is missing for {email_id}")
    gold_rows = list(gold_records) + [row for row in rows if row.get("annotation", {}).get("status") == "gold"]
    gold_threads = {
        key for row in gold_rows if row.get("annotation", {}).get("status") == "gold"
        for key in source_thread_keys(row)
    }
    eligible: list[dict[str, Any]] = []
    excluded = {"non_enron": 0, "not_unlabelled": 0, "has_labels_or_ai": 0, "gold_thread": 0}
    for row in rows:
        if row.get("source_dataset") != "enron":
            excluded["non_enron"] += 1
            continue
        if source_thread_keys(row) & gold_threads:
            excluded["gold_thread"] += 1
            continue
        annotation = row.get("annotation", {})
        if not isinstance(annotation, dict) or annotation.get("status") != "unlabelled":
            excluded["not_unlabelled"] += 1
            continue
        if row.get("labels") or annotation.get("annotation_source") == "ai":
            excluded["has_labels_or_ai"] += 1
            continue
        eligible.append(row)
    if len(eligible) < count:
        raise ValueError(f"need {count} eligible real Enron emails; found {len(eligible)} after exclusions {excluded}")

    stratum_by_id: dict[str, str] = {}
    cue_by_id: dict[str, str] = {}
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        metadata = metadata_by_id.get(row["email_id"], {})
        stratum = str(metadata.get("sampling_stratum") or ("unclassified" if metadata_available else "unstratified"))
        cue = str(metadata.get("primary_sampling_cue") or stratum)
        stratum_by_id[row["email_id"]] = stratum
        cue_by_id[row["email_id"]] = cue
        by_stratum.setdefault(stratum, []).append(row)

    capacities = {key: len(group) for key, group in by_stratum.items()}
    special_targets = {
        "random_nonmatching": int(count * 0.25 + 0.5),
        "thread_expansion": int(count * 0.125 + 0.5),
    }
    rng = random.Random(seed)
    complete_groups = _complete_multimessage_groups(
        eligible, metadata_by_id, metadata_available=metadata_available,
    )
    reserved_rows, reserved_groups = _reserve_complete_multimessage_groups(
        complete_groups, stratum_by_id, special_targets, rng,
    )
    reserved_ids = {row["email_id"] for row in reserved_rows}
    reserved_by_stratum: dict[str, int] = {}
    for row in reserved_rows:
        stratum = stratum_by_id[row["email_id"]]
        reserved_by_stratum[stratum] = reserved_by_stratum.get(stratum, 0) + 1
    quotas = _allocate_seed_quotas(count, capacities, reserved_by_stratum, special_targets)

    sample: list[dict[str, Any]] = list(reserved_rows)
    for stratum in sorted(quotas):
        quota = quotas[stratum] - reserved_by_stratum.get(stratum, 0)
        if not quota:
            continue
        group = [row for row in by_stratum[stratum] if row["email_id"] not in reserved_ids]
        if stratum == "thread_expansion":
            sample.extend(_sample_thread_expansion(group, quota, metadata_by_id, rng))
        elif stratum in {"direct_match", "thread_context_match"}:
            cue_groups: dict[str, list[dict[str, Any]]] = {}
            for row in group:
                cue_groups.setdefault(cue_by_id[row["email_id"]], []).append(row)
            cue_quotas = _allocate_quotas(quota, {key: len(value) for key, value in cue_groups.items()})
            for cue in sorted(cue_quotas):
                sample.extend(rng.sample(cue_groups[cue], cue_quotas[cue]))
        else:
            sample.extend(rng.sample(group, quota))
    if len(sample) != count or len({row["email_id"] for row in sample}) != count:
        raise AssertionError("stratified seed selection did not produce the requested unique records")
    assert_no_gold_threads(sample, gold_rows)
    selected_counts: dict[str, int] = {}
    cue_counts: dict[str, int] = {}
    stratum_cue_counts: dict[str, int] = {}
    for row in sample:
        stratum, cue = stratum_by_id[row["email_id"]], cue_by_id[row["email_id"]]
        selected_counts[stratum] = selected_counts.get(stratum, 0) + 1
        cue_counts[cue] = cue_counts.get(cue, 0) + 1
        combined = f"{stratum}:{cue}"
        stratum_cue_counts[combined] = stratum_cue_counts.get(combined, 0) + 1
    multi_message_threads: dict[tuple[str, str], int] = {}
    for row in sample:
        key = source_thread_key(row)
        multi_message_threads[key] = multi_message_threads.get(key, 0) + 1
    expansion_thread_counts: dict[tuple[str, str], int] = {}
    for row in sample:
        if stratum_by_id[row["email_id"]] == "thread_expansion":
            key = source_thread_key(row)
            expansion_thread_counts[key] = expansion_thread_counts.get(key, 0) + 1
    expansion_complete_threads = {
        key for key, selected_count in expansion_thread_counts.items()
        if selected_count > 1 and all(
            metadata_by_id.get(row["email_id"], {}).get("thread_complete") is True
            for row in sample if source_thread_key(row) == key
            and stratum_by_id[row["email_id"]] == "thread_expansion"
        )
    }
    sample_ids = {row["email_id"] for row in sample}
    selected_complete_groups = [
        bundle for bundle in complete_groups
        if all(row["email_id"] in sample_ids for row in bundle)
    ]
    selected_complete_pair_groups = [
        bundle for bundle in selected_complete_groups if len(bundle) == 2
    ]
    report = {
        "metadata_sidecar_available": metadata_available,
        "available_by_stratum": dict(sorted(capacities.items())),
        "target_by_stratum": dict(sorted(quotas.items())),
        "selected_by_stratum": dict(sorted(selected_counts.items())),
        "selected_by_primary_cue": dict(sorted(cue_counts.items())),
        "selected_by_stratum_and_primary_cue": dict(sorted(stratum_cue_counts.items())),
        "selected_thread_expansion_emails": selected_counts.get("thread_expansion", 0),
        "selected_threads_with_multiple_emails": sum(count > 1 for count in multi_message_threads.values()),
        "selected_complete_thread_expansion_threads": len(expansion_complete_threads),
        "available_complete_multimessage_threads": len(complete_groups),
        "complete_multimessage_thread_target": COMPLETE_MULTIMESSAGE_THREAD_TARGET,
        "complete_multimessage_email_cap": COMPLETE_MULTIMESSAGE_EMAIL_CAP,
        "reserved_complete_multimessage_threads": len(reserved_groups),
        "reserved_complete_multimessage_emails": len(reserved_rows),
        "selected_complete_multimessage_threads": len(selected_complete_groups),
        "selected_complete_multimessage_emails": sum(len(bundle) for bundle in selected_complete_groups),
        "selected_complete_pair_threads": len(selected_complete_pair_groups),
        "selected_complete_pair_emails": sum(len(bundle) for bundle in selected_complete_pair_groups),
        "random_nonmatching_target": special_targets["random_nonmatching"],
        "thread_expansion_target": special_targets["thread_expansion"],
        "selected_email_count": len(sample),
    }
    return sample, excluded, len(eligible), report

def python_to_utf16_offset(text: str, offset: int) -> int:
    """Convert a Python code-point offset into a JavaScript UTF-16 offset."""
    if not isinstance(offset, int) or not 0 <= offset <= len(text):
        raise ValueError("Python offset is outside the source text")
    return len(text[:offset].encode("utf-16-le")) // 2


def utf16_to_python_offset(text: str, offset: int) -> int:
    """Convert a UTF-16 offset to a Python code-point offset.

    Offsets in the middle of a surrogate pair are invalid and rejected.
    """
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("UTF-16 offset must be a nonnegative integer")
    units = 0
    if offset == 0:
        return 0
    for index, character in enumerate(text, 1):
        units += 2 if ord(character) > 0xFFFF else 1
        if units == offset:
            return index
        if units > offset:
            raise ValueError("UTF-16 offset splits a surrogate pair")
    if units == offset:
        return len(text)
    raise ValueError("UTF-16 offset is outside the source text")


def _metadata_text(record: dict[str, Any]) -> str:
    values = (
        ("From", record.get("sender", "")),
        ("To", "; ".join(record.get("recipients", []))),
        ("CC", "; ".join(record.get("cc", []))),
        ("Sent", record.get("sent_at") or ""),
        ("Attachments", "; ".join(record.get("attachment_names", []))),
        ("Thread", record.get("thread_id", "")),
    )
    return "\n".join(f"{name}: {value}" for name, value in values)


def canonical_to_task(record: dict[str, Any], *, task_id: int, assignment: str) -> dict[str, Any]:
    """Create a blank Label Studio task while retaining the full source record."""
    if assignment not in {"A", "B"}:
        raise ValueError("assignment must be A or B")
    errors = validate_record(record)
    if errors:
        raise ValueError(f"invalid canonical record {record.get('email_id')}: {'; '.join(errors)}")
    if record.get("annotation", {}).get("status") == "gold":
        raise ValueError(f"record {record['email_id']} is gold and cannot enter a Label Studio task")
    if (record.get("labels") or record.get("annotation", {}).get("status") == "ai_prelabelled"
            or record.get("annotation", {}).get("annotation_source") == "ai"):
        raise ValueError(f"record {record['email_id']} has existing labels or AI prelabels")
    data = {
        "email_id": record["email_id"],
        "thread_id": record["thread_id"],
        "source_dataset": record["source_dataset"],
        "assignment": assignment,
        "subject": record["subject"],
        "current_message": record["current_message"],
        "thread_context": record["thread_context"],
        "metadata_display": _metadata_text(record),
        "canonical_record_json": json.dumps(record, ensure_ascii=False, separators=(",", ":")),
    }
    return {"id": task_id, "data": data, "annotations": [], "predictions": []}


def records_to_tasks(records: Iterable[dict[str, Any]], *, assignment: str,
                    gold_records: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Convert safe records to blank tasks with stable order-local integer IDs."""
    rows = list(records)
    assert_no_gold_threads(rows, gold_records)
    return [canonical_to_task(record, task_id=index, assignment=assignment)
            for index, record in enumerate(rows, 1)]


def _canonical_record(task: dict[str, Any]) -> dict[str, Any]:
    data = task.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("canonical_record_json"), str):
        raise ValueError("task data must include canonical_record_json from this exporter")
    try:
        record = json.loads(data["canonical_record_json"])
    except json.JSONDecodeError as exc:
        raise ValueError("task canonical_record_json is invalid JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("task canonical_record_json must contain an object")
    if record.get("email_id") != data.get("email_id"):
        raise ValueError("task email_id does not match its canonical record")
    for field in ("source_dataset", "thread_id", "subject", "current_message", "thread_context"):
        if data.get(field) != record.get(field):
            raise ValueError(f"task data field {field} does not match its canonical record")
    return record


def _result_values(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    result = annotation.get("result", [])
    if not isinstance(result, list):
        raise ValueError("annotation result must be a list")
    if not all(isinstance(item, dict) for item in result):
        raise ValueError("annotation result entries must be objects")
    return result


def _single_choices(item: dict[str, Any], name: str) -> list[str]:
    value = item.get("value", {})
    choices = value.get("choices", []) if isinstance(value, dict) else None
    if not isinstance(choices, list) or any(not isinstance(choice, str) for choice in choices):
        raise ValueError(f"{name} result must contain a choices list")
    if len(choices) != len(set(choices)):
        raise ValueError(f"{name} result contains duplicate choices")
    return choices


def task_to_canonical(task: dict[str, Any], *, annotator: str, annotation_id: int | None = None,
                     allow_unannotated: bool = False) -> dict[str, Any]:
    """Import one completed Label Studio annotation as human-reviewed data.

    Ambiguous reviews stay unlabelled, and completed reviews are never promoted
    to gold by import.
    """
    if not annotator.strip():
        raise ValueError("annotator must be a nonempty human reviewer identifier")
    record = _canonical_record(task)
    errors = validate_record(record)
    if errors:
        raise ValueError(f"invalid embedded canonical record: {'; '.join(errors)}")
    annotations = task.get("annotations", [])
    if not isinstance(annotations, list):
        raise ValueError("task annotations must be a list")
    completed = [
        annotation for annotation in annotations
        if isinstance(annotation, dict)
        and not annotation.get("was_cancelled", False)
        and annotation.get("result") is not None
    ]
    if annotation_id is not None:
        completed = [annotation for annotation in completed if annotation.get("id") == annotation_id]
    if not completed and allow_unannotated and annotation_id is None:
        return record
    if len(completed) != 1:
        raise ValueError(
            f"task {record['email_id']} must have exactly one selected completed annotation; "
            f"found {len(completed)}. Use annotation_id when multiple annotations exist."
        )

    labels: list[str] = []
    field_spans: list[dict[str, Any]] = []
    review_decisions: list[str] = []
    notes: list[str] = []
    for item in _result_values(completed[0]):
        control = item.get("from_name")
        if control == CLASSIFICATION_CONTROL:
            choices = _single_choices(item, control)
            if any(choice not in LABELS for choice in choices):
                raise ValueError("classification result contains an unknown label")
            labels.extend(choices)
        elif control == REVIEW_CONTROL:
            choices = _single_choices(item, control)
            if len(choices) != 1 or choices[0] not in {REVIEWED, NEEDS_REVIEW}:
                raise ValueError("review_decision must select Reviewed or Needs review")
            review_decisions.extend(choices)
        elif control == NOTE_CONTROL:
            value = item.get("value", {})
            text = value.get("text", []) if isinstance(value, dict) else None
            if not isinstance(text, list) or any(not isinstance(note, str) for note in text):
                raise ValueError("review_note result must contain a text list")
            notes.extend(note for note in text if note.strip())
        elif control in SPAN_FIELDS:
            source_field = SPAN_FIELDS[control]
            value = item.get("value", {})
            if not isinstance(value, dict):
                raise ValueError(f"{control} result value must be an object")
            labels_for_span = value.get("labels", [])
            if (not isinstance(labels_for_span, list) or len(labels_for_span) != 1
                    or not isinstance(labels_for_span[0], str) or labels_for_span[0] not in SPAN_LABELS):
                raise ValueError(f"{control} span must have exactly one known extraction label")
            try:
                start16 = value["start"]
                end16 = value["end"]
                start = utf16_to_python_offset(record[source_field], start16)
                end = utf16_to_python_offset(record[source_field], end16)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{control} span has invalid UTF-16 offsets: {exc}") from exc
            text = value.get("text")
            if not isinstance(text, str) or record[source_field][start:end] != text:
                raise ValueError(f"{control} span text does not match its source offsets")
            field_spans.append({
                "label": labels_for_span[0], "text": text, "start": start, "end": end,
                "field": source_field,
            })
        else:
            raise ValueError(f"unsupported Label Studio control {control!r}")

    if len(review_decisions) != 1:
        raise ValueError("completed annotation must select exactly one review decision")
    if len(labels) != len(set(labels)):
        raise ValueError("classification result repeats a label")
    decision = review_decisions[0]
    if decision == NEEDS_REVIEW:
        if labels or field_spans:
            raise ValueError("Needs review annotations must not carry labels or extraction spans")
        status = "unlabelled"
    else:
        if not labels:
            raise ValueError("Reviewed annotations must select at least one classification label")
        status = "human_reviewed"

    imported = dict(record)
    imported["labels"] = labels
    imported["spans"] = field_spans
    imported_annotation = {
        "status": status,
        "annotator": annotator,
        "annotation_source": "human",
        "confidence": None,
    }
    if decision == NEEDS_REVIEW:
        imported_annotation["needs_review"] = True
        if notes:
            imported_annotation["ambiguity_note"] = "\n".join(notes)
    imported["annotation"] = imported_annotation
    errors = validate_record(imported)
    if errors:
        raise ValueError(f"imported annotation for {record['email_id']} is invalid: {'; '.join(errors)}")
    return imported


def task_to_annotated_canonical_jsonl(
    tasks: Iterable[dict[str, Any]], *, annotator: str, annotation_id: int | None = None,
    allow_unannotated: bool = False,
) -> list[dict[str, Any]]:
    return [task_to_canonical(task, annotator=annotator, annotation_id=annotation_id,
                               allow_unannotated=allow_unannotated) for task in tasks]
