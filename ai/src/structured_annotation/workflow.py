"""Hash-bound blind structured review and adjudication primitives.

All source-bearing artifacts are private and must remain below ``ai/data``.
Public reports emitted by the CLIs contain counts and hashes only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import copy
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.structured import map_labels, validate_annotation
from src.structured.mapper import MappingResult


MODEL_REQUIRED = "gpt-6-luna"
REASONING_REQUIRED = "xhigh"
WORKFLOW_VERSION = "structured-blind-review-v1"
ANNOTATION_VERSION = "2-alpha"
RISK_LABELS = {"REPORT_REQUEST", "FOLLOW_UP", "APPROVAL", "DEPARTMENTAL_INPUT"}
TOP_COLLECTIONS = (
    "actors", "actions", "documents", "departments", "temporal_entities",
    "meetings", "deadlines", "approvals", "status_updates", "thread_changes", "acts",
)
_SOURCE_TEXT_FIELDS = ("authored_message", "current_message", "body", "text")
_FORBIDDEN_LABEL_KEYS = {
    "label", "labels", "fyp_label", "fyp_labels", "gold", "gold_label",
    "gold_labels", "structured_annotation", "annotation", "annotations",
    "prediction", "predictions", "candidate_score", "candidate_scores",
    "score", "scores", "probability", "probabilities", "rank", "ranking",
}
_CONTEXT_METADATA_FIELDS = (
    "source_message_id", "rfc_message_id", "message_id", "reply_to_message_id",
    "thread_id", "source_thread_id", "source_thread_verified",
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json_bytes(value))


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _write_json_new(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(data)
    return digest_bytes(data)


def _write_json_replace(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with temporary.open("xb") as stream:
        stream.write(data)
    os.replace(temporary, path)
    return digest_bytes(data)


def _write_ingest_receipt(
    *, directory: Path, role: str, payload_path: Path, payload_sha256: str,
    envelope_sha256: str, packet_sha256: str, source_manifest_sha256: str,
    reviewer_identity: str,
) -> str:
    receipt = {
        "workflow_version": WORKFLOW_VERSION,
        "role": role,
        "reviewer_identity": reviewer_identity,
        "payload_path": payload_path.relative_to(directory).as_posix(),
        "payload_sha256": payload_sha256,
        "submitted_envelope_sha256": envelope_sha256,
        "packet_sha256": packet_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "model": MODEL_REQUIRED,
        "reasoning": REASONING_REQUIRED,
    }
    return _write_json_new(directory / "receipts" / f"{role}.json", receipt)


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"source line {line_no} must be a JSON object")
            rows.append(value)
    if not rows:
        raise ValueError("source JSONL is empty")
    return rows


def _ensure_private(path: str | Path, *, root: Path) -> Path:
    resolved = Path(path).resolve()
    private = (root / "ai" / "data").resolve()
    if resolved != private and private not in resolved.parents:
        raise ValueError(f"private artifact must be under {private}")
    return resolved


def _source_id(row: Mapping[str, Any]) -> str:
    value = row.get("source_id") or row.get("email_id") or row.get("record_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("every review source needs a stable source_id/email_id")
    return value


def _check_no_prior_labels(value: Any, *, path: str = "source") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _FORBIDDEN_LABEL_KEYS and child not in (None, [], {}, ""):
                raise ValueError(f"source contains prior label, answer, or score at {path}.{key}")
            _check_no_prior_labels(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_prior_labels(child, path=f"{path}[{index}]")


def _text(value: Any, field: str, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"source {field} must be a string")
    if required and not value.strip():
        raise ValueError(f"source {field} must be non-empty")
    return value


def _authored_ranges(row: Mapping[str, Any]) -> Any:
    value = row.get("authored_ranges")
    if value is not None and not isinstance(value, list):
        raise ValueError("authored_ranges must be an array when present")
    return value


def _minimal_source(item: Mapping[str, Any], source_id: str, *, require_text: bool) -> dict[str, Any]:
    message = None
    for field in _SOURCE_TEXT_FIELDS:
        if field in item and item[field] is not None:
            message = item[field]
            break
    if message is None and require_text:
        raise ValueError(f"source {source_id!r} has no current_message/authored_message text")
    source = {
        "subject": _text(item.get("subject", ""), "subject"),
        "current_message": _text(message, "current_message", required=require_text),
    }
    ranges = _authored_ranges(item)
    if ranges is not None:
        source["authored_ranges"] = ranges
    return source


def _normalize_context(row: Mapping[str, Any], current_id: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    context = row.get("thread_context") or []
    if isinstance(context, dict):
        context = context.get("messages", context.get("items", []))
    if isinstance(context, str):
        context = [context]
    if not isinstance(context, list):
        raise ValueError(f"thread_context for {current_id!r} must be an array, object, or string")
    sources: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, item in enumerate(context):
        if isinstance(item, str):
            raw: Mapping[str, Any] = {"current_message": item}
        elif isinstance(item, dict):
            raw = item
        else:
            raise ValueError(f"thread_context[{index}] must be a text string or source object")
        sid = raw.get("source_id") or raw.get("email_id") or raw.get("record_id")
        if not isinstance(sid, str) or not sid.strip():
            # This is a local evidence reference only; it is never presented as a source ID or reply link.
            sid = f"context-ref:{digest_json([current_id, index, raw])[:20]}"
        normalized = _minimal_source(raw, sid, require_text=True)
        for field in _CONTEXT_METADATA_FIELDS:
            if field in raw:
                normalized[field] = raw[field]
        normalized["source_id_kind"] = "source_id" if (raw.get("source_id") or raw.get("email_id") or raw.get("record_id")) else "local_context_ref"
        if sid in sources and sources[sid] != normalized:
            raise ValueError(f"conflicting context content for source ID {sid!r}")
        sources[sid] = normalized
        if sid not in order:
            order.append(sid)
    return sources, order


def _normalize_record(row: Mapping[str, Any]) -> dict[str, Any]:
    _check_no_prior_labels(row)
    sid = _source_id(row)
    current_id = row.get("current_source_id", sid)
    if current_id != sid:
        raise ValueError("current_source_id must equal this candidate's stable source_id")
    current = _minimal_source(row, sid, require_text=True)
    current["source_id_kind"] = "source_id"
    for field in _CONTEXT_METADATA_FIELDS:
        if field in row:
            current[field] = row[field]
    sources, context_ids = _normalize_context(row, sid)
    if sid in sources and sources[sid] != current:
        raise ValueError(f"thread_context duplicates current source {sid!r} with different content")
    sources[sid] = current
    source_order = [sid] + [context_id for context_id in context_ids if context_id != sid]
    source_hashes = {source_id: digest_json({"source_id": source_id, **sources[source_id]}) for source_id in source_order}
    metadata = {field: row[field] for field in _CONTEXT_METADATA_FIELDS if field in row}
    return {
        "source_id": sid,
        "current_source_id": sid,
        "current_source_hash": source_hashes[sid],
        "source_hashes": source_hashes,
        "source_order": source_order,
        "sources": sources,
        "source_metadata": metadata,
    }


def _qualified_id(dataset_id: str, source_id: str) -> str:
    return source_id if source_id.startswith(dataset_id + ":") else f"{dataset_id}:{source_id}"


def _verify_candidate_index_fingerprint(
    *, normalized_record: Mapping[str, Any], index_record: Mapping[str, Any],
) -> None:
    from src.datasets.leakage import fingerprint_content

    source = normalized_record["sources"][normalized_record["current_source_id"]]
    fp = fingerprint_content(source.get("subject", ""), source.get("current_message", ""))
    candidate_hashes = {
        "body_exact_sha256": fp.body_exact,
        "body_tokens_sha256": fp.body_tokens,
        "normalized_subject_sha256": hashlib.sha256(fp.normalized_subject.encode("utf-8")).hexdigest() if fp.normalized_subject else None,
    }
    for field, expected in candidate_hashes.items():
        if index_record.get(field) != expected:
            raise ValueError(f"candidate source text does not match verified index fingerprint: {normalized_record['source_id']!r}/{field}")


def _is_reserved_or_protected(row: Mapping[str, Any]) -> bool:
    for key in ("reserved", "protected", "is_reserved", "is_protected", "evaluation_only", "challenge_only"):
        if row.get(key) is True:
            return True
    status = row.get("candidate_status")
    if isinstance(status, str) and status.casefold() in {
        "reserved", "protected", "eval", "evaluation", "challenge", "test", "dev",
        "reserved_eval", "reserved_challenge", "reserved_fresh",
    }:
        return True
    partition = row.get("partition") or row.get("source_partition")
    return isinstance(partition, str) and partition.upper() not in {"TRAIN", "TRAIN_SCREEN"}


def _load_boundary(
    *, index_path: str | Path, assignments_path: str | Path, dataset_id: str, root: Path,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    from src.datasets.global_leakage import LeakageIndex

    index_file = _ensure_private(index_path, root=root)
    assignments_file = _ensure_private(assignments_path, root=root)
    index_sha = sha256_file(index_file)
    assignments_sha = sha256_file(assignments_file)
    index_payload = _read_json(index_file)
    assignments = _read_json(assignments_file)
    records = index_payload.get("records")
    if not isinstance(records, dict):
        raise ValueError("global leakage index must contain a records object")
    if not isinstance(index_payload.get("links", []), list):
        raise ValueError("global leakage index links must be an array")
    if assignments.get("index_sha256") != index_sha:
        raise ValueError("partition manifest is not bound to the actual global leakage index bytes")
    partitions = assignments.get("partitions")
    if not isinstance(partitions, dict):
        raise ValueError("partition manifest must contain a non-empty partitions object")
    effective_partitions = {str(source_id): str(value).upper() for source_id, value in partitions.items()}
    protected_global = assignments.get("protected_ids", [])
    protected_native = assignments.get("protected_source_ids", [])
    if not isinstance(protected_global, list) or not isinstance(protected_native, list):
        raise ValueError("protected_ids and protected_source_ids must be arrays when present")
    if (any(not isinstance(value, str) or not value.strip() for value in protected_global)
            or any(not isinstance(value, str) or not value.strip() for value in protected_native)):
        raise ValueError("protected global and native source IDs must be non-empty strings")
    if len(set(protected_global)) != len(protected_global) or len(set(protected_native)) != len(protected_native):
        raise ValueError("protected global and native source ID lists must not contain duplicates")
    protected_native_global = {_qualified_id(dataset_id, source_id) for source_id in protected_native}
    protected_for_dataset = {source_id for source_id in protected_global if source_id.startswith(dataset_id + ":")}
    if protected_for_dataset != protected_native_global:
        raise ValueError("protected native IDs do not match protected global IDs for this dataset")
    for source_id in protected_global:
        if source_id not in records:
            raise ValueError(f"protected global ID {source_id!r} is absent from the verified index")
        if effective_partitions.get(source_id) in {"TRAIN", "TRAIN_SCREEN"}:
            raise ValueError(f"protected global ID {source_id!r} is also assigned to a train screen")
        # Protection is tracked separately. Unused reserves are not members of
        # any named partition and can share components with selected reserves.
    assignments["partitions"] = effective_partitions
    assignments["protected_global_ids"] = list(protected_global)
    assignments["protected_source_ids"] = list(protected_native)
    leakage = LeakageIndex(records=records, links=index_payload.get("links", []), policy=index_payload.get("policy", {}))
    conflicts = leakage.partition_conflicts(effective_partitions)
    if conflicts:
        raise ValueError("global leakage components cross source partitions")
    return index_payload, assignments, index_sha, assignments_sha


def _verify_train_isolation(index_payload: Mapping[str, Any], assignments: Mapping[str, Any]) -> None:
    from src.datasets.global_leakage import LeakageIndex

    leakage = LeakageIndex(
        records=index_payload["records"],
        links=index_payload.get("links", []),
        policy=index_payload.get("policy", {}),
    )
    partitions = assignments["partitions"]
    train_ids = [source_id for source_id, partition in partitions.items() if str(partition).upper() in {"TRAIN", "TRAIN_SCREEN"}]
    protected_ids = sorted({
        source_id for source_id, partition in partitions.items()
        if str(partition).upper() not in {"TRAIN", "TRAIN_SCREEN"}
    } | set(assignments.get("protected_global_ids", [])))
    excluded = leakage.training_exclusions(train_ids, protected_ids)
    if excluded:
        reasons = Counter(excluded.values())
        raise ValueError(f"global training isolation failed: {dict(reasons)}")


def build_review_packet(
    *, run_id: str, role: str, reviewer_identity: str, purpose: str,
    source_manifest_sha256: str, source_bundle_sha256: str,
    records: list[dict[str, Any]], root: Path,
    prior_answers: Mapping[str, Any] | None = None,
    initial_envelope_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a single-role packet. A/B packets share identical records bytes."""
    packet: dict[str, Any] = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": run_id,
        "purpose": purpose,
        "packet_role": role,
        "reviewer_identity": reviewer_identity,
        "required_model": MODEL_REQUIRED,
        "required_reasoning": REASONING_REQUIRED,
        "schema_version": ANNOTATION_VERSION,
        "source_manifest_sha256": source_manifest_sha256,
        "source_bundle_sha256": source_bundle_sha256,
        "source_read_attestation_required": True,
        "instructions": [
            "Read every source object in this packet before annotating any record.",
            "Use only the supplied source text and the bound structured schema; do not infer missing facts.",
            "Return one annotation per listed source_id, preserving current_source_id exactly.",
            "Use exact Unicode code-point evidence offsets and evidence text from the supplied sources.",
            "Mark uncertainty explicitly; do not force a label to complete the packet.",
            "This packet contains no earlier labels, scores, or other reviewer answers unless its role is C_ADJUDICATION.",
        ],
        "records": records,
    }
    if role == "C_ADJUDICATION":
        if not prior_answers or not initial_envelope_sha256:
            raise ValueError("C adjudication packet requires frozen initial verdict and A/B answers")
        packet["review_visibility"] = "initial_blind_verdict_hash_frozen_then_A_B_visible"
        packet["adjudicator_initial_envelope_sha256"] = initial_envelope_sha256
        packet["prior_answers"] = prior_answers
    else:
        packet["review_visibility"] = "independent_source_only"
    packet["schema_source_sha256"] = sha256_file(root / "ai" / "src" / "structured" / "validation.py")
    packet["mapper_source_sha256"] = sha256_file(root / "ai" / "src" / "structured" / "mapper.py")
    schema_path = root / "ai" / "config" / "structured_primitive_schema.json"
    if not schema_path.is_file():
        raise FileNotFoundError("final structured primitive schema is missing")
    packet["annotation_schema_sha256"] = sha256_file(schema_path)
    packet["annotation_schema"] = _read_json(schema_path)
    return packet


def _packet_source_bundle(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    return packet.get("records", [])


def _load_run(run_dir: str | Path, *, root: Path) -> tuple[Path, dict[str, Any]]:
    directory = _ensure_private(run_dir, root=root)
    manifest_path = directory / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("run_manifest.json is missing")
    manifest = _read_json(manifest_path)
    if manifest.get("workflow_version") != WORKFLOW_VERSION or manifest.get("run_id") != directory.name:
        raise ValueError("run manifest version or run ID does not match its private directory")
    source_path = directory / str(manifest.get("source_manifest_path", ""))
    if not source_path.is_file() or sha256_file(source_path) != manifest.get("source_manifest_sha256"):
        raise ValueError("source manifest changed after the review run was prepared")
    source_manifest = _read_json(source_path)
    claimed = source_manifest.get("source_manifest_sha256")
    source_basis = dict(source_manifest)
    source_basis.pop("source_manifest_sha256", None)
    if claimed != digest_json(source_basis):
        raise ValueError("source manifest internal content hash mismatch")
    for key, expected in {
        "run_id": directory.name,
        "purpose": manifest.get("purpose"),
        "dataset_id": manifest.get("dataset_id"),
        "source_count": len(source_manifest.get("source_hashes", [])),
    }.items():
        if source_manifest.get(key) != expected:
            raise ValueError(f"run/source manifest mismatch for {key}")
    source_file = root / str(source_manifest.get("source_file", ""))
    if not source_file.is_file() or sha256_file(source_file) != source_manifest.get("source_file_sha256"):
        raise ValueError("original source JSONL changed after review run preparation")
    full_rows = _read_jsonl(source_file)
    offset = source_manifest.get("record_offset", 0)
    count = source_manifest.get("record_count", source_manifest.get("source_count"))
    if (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(count, bool) or not isinstance(count, int) or count <= 0
            or len(full_rows) != source_manifest.get("input_record_count", len(full_rows))
            or offset + count > len(full_rows)):
        raise ValueError("source manifest has an invalid source-file slice")
    normalized_rows = [_normalize_record(row) for row in full_rows[offset:offset + count]]
    expected_source_hashes = [
        {"source_id": row["source_id"], "source_hash": row["current_source_hash"], "source_hashes": row["source_hashes"]}
        for row in normalized_rows
    ]
    if (len(normalized_rows) != source_manifest.get("source_count")
            or digest_json(normalized_rows) != source_manifest.get("source_bundle_sha256")
            or expected_source_hashes != source_manifest.get("source_hashes")):
        raise ValueError("source manifest selected source hashes do not match the original JSONL slice")
    return directory, manifest


def _load_packet(run_dir: Path, manifest: Mapping[str, Any], role: str) -> tuple[dict[str, Any], str]:
    item = manifest.get("reviewers", {}).get(role)
    if not isinstance(item, dict):
        raise ValueError(f"no assigned packet for reviewer role {role!r}")
    path = run_dir / item["packet_path"]
    if not path.is_file():
        raise ValueError(f"packet for role {role!r} is missing")
    packet_sha = sha256_file(path)
    if packet_sha != item.get("packet_sha256"):
        raise ValueError(f"packet for role {role!r} changed after assignment")
    packet = _read_json(path)
    root = run_dir.parents[3]
    if packet.get("packet_role") != role:
        raise ValueError("packet role does not match assignment")
    for key, expected in {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": manifest.get("run_id"),
        "purpose": manifest.get("purpose"),
        "reviewer_identity": item.get("reviewer_identity"),
        "required_model": MODEL_REQUIRED,
        "required_reasoning": REASONING_REQUIRED,
        "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        "source_bundle_sha256": manifest.get("source_bundle_sha256"),
    }.items():
        if packet.get(key) != expected:
            raise ValueError(f"packet {role} binding mismatch for {key}")
    schema_path = root / "ai" / "config" / "structured_primitive_schema.json"
    validation_path = root / "ai" / "src" / "structured" / "validation.py"
    mapper_path = root / "ai" / "src" / "structured" / "mapper.py"
    for key, actual in {
        "annotation_schema_sha256": sha256_file(schema_path),
        "schema_source_sha256": sha256_file(validation_path),
        "mapper_source_sha256": sha256_file(mapper_path),
    }.items():
        if packet.get(key) != actual:
            raise ValueError(f"packet {role} is stale against current annotation schema/code: {key}")
    if packet.get("annotation_schema") != _read_json(schema_path):
        raise ValueError(f"packet {role} schema document changed")
    records = packet.get("records")
    if not isinstance(records, list) or packet.get("source_bundle_sha256") != digest_json(records):
        raise ValueError(f"packet {role} source bundle hash mismatch")
    source_manifest = _read_json(run_dir / manifest["source_manifest_path"])
    expected_hashes = {item["source_id"]: item for item in source_manifest.get("source_hashes", [])}
    if role in {"A", "B"}:
        if [record.get("source_id") for record in records] != list(expected_hashes):
            raise ValueError(f"packet {role} source IDs/order differ from the source manifest")
    for record in records:
        sid = record.get("source_id")
        sources = record.get("sources")
        if not isinstance(sources, dict) or record.get("source_hashes") != {
            source_id: digest_json({"source_id": source_id, **source}) for source_id, source in sources.items()
        }:
            raise ValueError(f"packet {role} source text hash mismatch")
        if record.get("current_source_hash") != record["source_hashes"].get(record.get("current_source_id")):
            raise ValueError(f"packet {role} current source hash mismatch")
        if role in {"A", "B"} and expected_hashes[sid].get("source_hashes") != record["source_hashes"]:
            raise ValueError(f"packet {role} differs from source manifest text hashes")
    return packet, packet_sha


def _annotation_map(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sources = record.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("packet record sources must be an object")
    return sources


def _validate_one(record: Mapping[str, Any], annotation: Any) -> tuple[dict[str, Any], MappingResult, str]:
    current_id = record.get("current_source_id")
    result = validate_annotation(annotation, current_source_id=current_id, sources=_annotation_map(record))
    if not result.valid:
        raise ValueError("invalid structured annotation: " + "; ".join(result.errors))
    if annotation.get("email_id") != current_id:
        raise ValueError("annotation email_id must match the bound current source ID")
    mapped = map_labels(annotation, current_source_id=current_id, sources=_annotation_map(record))
    if mapped.validation_errors:
        raise ValueError("mapper rejected annotation after validation")
    return annotation, mapped, digest_json(annotation)


def _validate_envelope(
    *, packet: Mapping[str, Any], packet_sha: str, envelope: Mapping[str, Any],
    role: str, expected_reviewer: str, source_manifest_sha256: str,
) -> list[dict[str, Any]]:
    expected_role = role
    if envelope.get("workflow_version") != WORKFLOW_VERSION:
        raise ValueError("review envelope workflow_version mismatch")
    if envelope.get("run_id") != packet.get("run_id"):
        raise ValueError("review envelope run_id mismatch")
    if envelope.get("packet_role") != expected_role:
        raise ValueError("review envelope role mismatch")
    if envelope.get("packet_sha256") != packet_sha:
        raise ValueError("review envelope is not bound to the assigned packet bytes")
    if envelope.get("source_manifest_sha256") != source_manifest_sha256:
        raise ValueError("review envelope source manifest hash mismatch")
    if envelope.get("reviewer_identity") != expected_reviewer:
        raise ValueError("reviewer identity does not match role assignment")
    if envelope.get("model") != MODEL_REQUIRED or envelope.get("reasoning") != REASONING_REQUIRED:
        raise ValueError("review envelope must attest gpt-6-luna with xhigh reasoning")
    attestation = envelope.get("source_read_attestation")
    if not isinstance(attestation, dict) or attestation.get("read_all_sources") is not True:
        raise ValueError("review envelope lacks source-read attestation")
    expected_source_ids = [record["source_id"] for record in packet.get("records", [])]
    if attestation.get("source_ids") != expected_source_ids:
        raise ValueError("source-read attestation must list packet source IDs in exact order")
    if attestation.get("source_bundle_sha256") != packet.get("source_bundle_sha256"):
        raise ValueError("source-read attestation source hash mismatch")
    submitted = envelope.get("records")
    if not isinstance(submitted, list):
        raise ValueError("review envelope records must be an array")
    expected = packet.get("records", [])
    if len(submitted) != len(expected):
        raise ValueError("review envelope must contain exactly one annotation per packet record")
    result = []
    for expected_record, answer in zip(expected, submitted):
        if not isinstance(answer, dict):
            raise ValueError("each submitted record must be an object")
        for field in ("source_id", "current_source_id", "current_source_hash", "source_hashes"):
            if answer.get(field) != expected_record.get(field):
                raise ValueError(f"review answer source binding mismatch for {field}")
        _annotation, mapped, annotation_hash = _validate_one(expected_record, answer.get("annotation"))
        result.append({
            "source_id": expected_record["source_id"],
            "current_source_id": expected_record["current_source_id"],
            "current_source_hash": expected_record["current_source_hash"],
            "source_hashes": expected_record["source_hashes"],
            "annotation": answer["annotation"],
            "annotation_sha256": annotation_hash,
            "mapped": mapped.to_dict(),
        })
    if [record["source_id"] for record in submitted] != expected_source_ids:
        raise ValueError("review envelope source order/IDs mismatch")
    return result


def prepare_run(
    *, source_path: str | Path, output_dir: str | Path, purpose: str,
    dataset_id: str, reviewer_a: str, reviewer_b: str,
    index_path: str | Path | None = None, assignments_path: str | Path | None = None,
    partition_name: str | None = None, record_offset: int = 0,
    record_limit: int | None = None, root: Path | None = None,
) -> dict[str, Any]:
    """Create isolated A/B source-only packets and immutable hash manifests."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    purpose = purpose.upper()
    if purpose not in {"TRAIN", "TRAIN_SCREEN", "EVAL", "CHALLENGE"}:
        raise ValueError("purpose must be TRAIN, TRAIN_SCREEN, EVAL, or CHALLENGE")
    if not dataset_id or not _canonical_identity(reviewer_a) or not _canonical_identity(reviewer_b) or _canonical_identity(reviewer_a) == _canonical_identity(reviewer_b):
        raise ValueError("two distinct dataset/reviewer identities are required")
    reviewer_a, reviewer_b = reviewer_a.strip(), reviewer_b.strip()
    source_file = _ensure_private(source_path, root=root)
    directory = _ensure_private(output_dir, root=root)
    if directory.exists():
        raise FileExistsError("review run directory is immutable; choose a new run ID")
    if isinstance(record_offset, bool) or not isinstance(record_offset, int) or record_offset < 0:
        raise ValueError("record_offset must be a non-negative integer")
    if record_limit is not None and (isinstance(record_limit, bool) or not isinstance(record_limit, int) or record_limit <= 0):
        raise ValueError("record_limit must be a positive integer when supplied")
    all_input_rows = _read_jsonl(source_file)
    all_raw_ids = [_source_id(row) for row in all_input_rows]
    if len(all_raw_ids) != len(set(all_raw_ids)):
        raise ValueError("source IDs must be unique within the review run")
    if record_offset >= len(all_input_rows):
        raise ValueError("record_offset is outside the source file record range")
    stop = len(all_input_rows) if record_limit is None else record_offset + record_limit
    if stop > len(all_input_rows):
        raise ValueError("record_offset + record_limit is outside the source file record range")
    input_rows = all_input_rows[record_offset:stop]
    raw_ids = [_source_id(row) for row in input_rows]
    input_sha = sha256_file(source_file)
    index_payload: dict[str, Any] | None = None
    assignments: dict[str, Any] | None = None
    index_sha = assignments_sha = None
    if purpose in {"TRAIN", "TRAIN_SCREEN"} and index_path is None and assignments_path is None:
        raise ValueError("TRAIN_SCREEN packet creation requires an actual global index and partition manifest")
    if index_path is None and assignments_path is not None:
        assignment_hint = _read_json(assignments_path)
        hinted_index = assignment_hint.get("index_path")
        if not isinstance(hinted_index, str) or not hinted_index:
            raise ValueError("boundary manifest must specify index_path when --index is omitted")
        index_candidate = Path(hinted_index)
        index_path = index_candidate if index_candidate.is_absolute() else root / index_candidate
    if (index_path is None) != (assignments_path is None):
        raise ValueError("index and partition manifest must be supplied together")
    if index_path is not None:
        index_payload, assignments, index_sha, assignments_sha = _load_boundary(
            index_path=index_path, assignments_path=assignments_path, dataset_id=dataset_id, root=root,
        )
        default_partition = (
            "TRAIN_SCREEN" if purpose in {"TRAIN", "TRAIN_SCREEN"}
            else "EVAL_RESERVED" if purpose == "EVAL"
            else purpose
        )
        partition_name = (partition_name or default_partition).upper()
        partitions = assignments["partitions"]
        requested_ids = [_qualified_id(dataset_id, sid) for sid in raw_ids]
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError("source IDs collide after dataset qualification")
        missing = sorted(set(requested_ids) - set(index_payload["records"]))
        if missing:
            raise ValueError(f"candidate IDs are absent from the verified global index: {missing[:5]}")
        wrong = [rid for rid in requested_ids if str(partitions.get(rid, "")).upper() != partition_name]
        if wrong:
            raise ValueError(f"candidate records are not assigned to requested partition {partition_name}: {wrong[:5]}")
        if purpose in {"TRAIN", "TRAIN_SCREEN"}:
            expected_file_hash = assignments.get("train_screen_candidates_sha256")
            if expected_file_hash and expected_file_hash != input_sha:
                raise ValueError("TRAIN_SCREEN candidate source file does not match its boundary-manifest hash")
            protected_global = set(assignments.get("protected_global_ids", []))
            protected_native = set(assignments.get("protected_source_ids", []))
            selected_protected = [sid for sid, rid in zip(raw_ids, requested_ids) if rid in protected_global or sid in protected_native]
            if selected_protected:
                raise ValueError(f"TRAIN_SCREEN packet includes known protected/reserved source IDs: {selected_protected[:5]}")
            _verify_train_isolation(index_payload, assignments)
            if any(_is_reserved_or_protected(row) for row in input_rows):
                raise ValueError("known reserved/protected source metadata cannot enter a TRAIN_SCREEN packet")
        elif purpose == "EVAL":
            expected_file_hash = assignments.get("evaluation_candidates_sha256")
            if expected_file_hash and expected_file_hash != input_sha:
                raise ValueError("EVAL candidate source file does not match its boundary-manifest hash")

    normalized = [_normalize_record(row) for row in input_rows]
    if index_payload is not None:
        for record in normalized:
            global_id = _qualified_id(dataset_id, record["source_id"])
            _verify_candidate_index_fingerprint(
                normalized_record=record, index_record=index_payload["records"][global_id],
            )
            for context_id in record["source_order"][1:]:
                context = record["sources"][context_id]
                if context.get("source_id_kind") != "source_id":
                    raise ValueError(
                        f"indexed review packets cannot include context text without a stable source ID: {record['source_id']!r}"
                    )
                context_global_id = _qualified_id(dataset_id, context_id)
                if context_global_id not in index_payload["records"]:
                    raise ValueError(f"context source is absent from the verified global index: {context_id!r}")
                if assignments["partitions"].get(context_global_id) != partition_name:
                    raise ValueError(f"context source crosses the assigned partition: {context_id!r}")
                _verify_candidate_index_fingerprint(
                    normalized_record={
                        "source_id": context_id,
                        "current_source_id": context_id,
                        "sources": {context_id: context},
                    },
                    index_record=index_payload["records"][context_global_id],
                )
    source_bundle_sha = digest_json(normalized)
    run_id = directory.name
    source_manifest: dict[str, Any] = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": run_id,
        "purpose": purpose,
        "dataset_id": dataset_id,
        "partition_name": partition_name or purpose,
        "source_file": source_file.relative_to(root).as_posix(),
        "source_file_sha256": input_sha,
        "source_bundle_sha256": source_bundle_sha,
        "source_count": len(normalized),
        "input_record_count": len(all_input_rows),
        "record_offset": record_offset,
        "record_count": len(normalized),
        "selection_policy": "contiguous_source_file_slice_hash_bound_to_full_input",
        "source_hashes": [
            {"source_id": record["source_id"], "source_hash": record["current_source_hash"],
             "source_hashes": record["source_hashes"]}
            for record in normalized
        ],
        "global_index": {"path": Path(index_path).resolve().relative_to(root).as_posix(), "sha256": index_sha} if index_path else None,
        "partition_manifest": {"path": Path(assignments_path).resolve().relative_to(root).as_posix(), "sha256": assignments_sha} if assignments_path else None,
        "protected_inputs_rejected_for_train": True,
    }
    source_manifest["source_manifest_sha256"] = digest_json(source_manifest)
    directory.mkdir(parents=True)
    source_manifest_sha = _write_json_new(directory / "source_manifest.json", source_manifest)
    reviewers: dict[str, dict[str, Any]] = {}
    for role, identity in (("A", reviewer_a), ("B", reviewer_b)):
        packet = build_review_packet(
            run_id=run_id, role=role, reviewer_identity=identity, purpose=purpose,
            source_manifest_sha256=source_manifest_sha,
            source_bundle_sha256=source_bundle_sha, records=normalized, root=root,
        )
        packet_path = directory / f"reviewer_{role}" / "packet.json"
        packet_sha = _write_json_new(packet_path, packet)
        reviewers[role] = {
            "reviewer_identity": identity,
            "model": MODEL_REQUIRED,
            "reasoning": REASONING_REQUIRED,
            "packet_path": packet_path.relative_to(directory).as_posix(),
            "packet_sha256": packet_sha,
        }
    a_packet = _read_json(directory / reviewers["A"]["packet_path"])
    b_packet = _read_json(directory / reviewers["B"]["packet_path"])
    if a_packet["records"] != b_packet["records"] or a_packet["source_bundle_sha256"] != b_packet["source_bundle_sha256"]:
        raise AssertionError("blind A/B packets must have byte-equivalent source records")
    manifest = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": run_id,
        "purpose": purpose,
        "dataset_id": dataset_id,
        "source_manifest_path": "source_manifest.json",
        "source_manifest_sha256": source_manifest_sha,
        "source_bundle_sha256": source_bundle_sha,
        "reviewers": reviewers,
        "required_model": MODEL_REQUIRED,
        "required_reasoning": REASONING_REQUIRED,
        "third_review_policy": {
            "EVAL_and_CHALLENGE": "required_for_every_record",
            "TRAIN": "required_for_primitive_disagreement",
        },
        "root_approval_policy": "required for risk flags; uncertainty never auto-accepts",
        "status": "packets_prepared_no_annotations",
        "accepted": 0,
        "rejected": 0,
        "review_required": len(normalized),
    }
    _write_json_new(directory / "run_manifest.json", manifest)
    return manifest


def _envelope_path(run_dir: Path, role: str) -> Path:
    name = {"A": "A.json", "B": "B.json", "C_INITIAL": "C_initial.json", "C_ADJUDICATION": "C_adjudication.json"}.get(role)
    if not name:
        raise ValueError("unsupported reviewer role")
    return run_dir / "envelopes" / name


def ingest_envelope(
    *, run_dir: str | Path, role: str, envelope_path: str | Path,
    root: Path | None = None,
) -> dict[str, Any]:
    """Verify, validate and immutably store an offline reviewer envelope."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    if role not in {"A", "B"}:
        raise ValueError("initial ingest accepts A or B only")
    packet, packet_sha = _load_packet(directory, manifest, role)
    envelope = _read_json(envelope_path)
    if not isinstance(envelope, dict):
        raise ValueError("review envelope must be a JSON object")
    if manifest["reviewers"]["A"]["reviewer_identity"] == manifest["reviewers"]["B"]["reviewer_identity"]:
        raise ValueError("reviewer identities must be distinct")
    answers = _validate_envelope(
        packet=packet, packet_sha=packet_sha, envelope=envelope, role=role,
        expected_reviewer=manifest["reviewers"][role]["reviewer_identity"],
        source_manifest_sha256=manifest["source_manifest_sha256"],
    )
    payload = {
        "workflow_version": WORKFLOW_VERSION,
        "role": role,
        "reviewer_identity": envelope["reviewer_identity"],
        "model": envelope["model"], "reasoning": envelope["reasoning"],
        "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "envelope_sha256": sha256_file(envelope_path),
        "records": answers,
    }
    stored_path = _envelope_path(directory, role)
    stored_sha = _write_json_new(stored_path, payload)
    receipt_sha = _write_ingest_receipt(
        directory=directory, role=role, payload_path=stored_path,
        payload_sha256=sha256_file(stored_path), envelope_sha256=payload["envelope_sha256"],
        packet_sha256=packet_sha, source_manifest_sha256=manifest["source_manifest_sha256"],
        reviewer_identity=envelope["reviewer_identity"],
    )
    return {"role": role, "stored_path": stored_path.relative_to(directory).as_posix(), "stored_sha256": stored_sha,
            "receipt_sha256": receipt_sha, "record_count": len(answers), "validated": True}


def _evidence_form(annotation: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [{key: value for key, value in item.items() if key != "id"} for item in annotation.get("evidence", [])],
        key=canonical_json_bytes,
    )


def _resolved_references(annotation: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Alpha-normalize local primitive IDs while retaining typed references."""
    evidence_by_id = {
        item["id"]: digest_json({key: value for key, value in item.items() if key != "id"})
        for item in annotation.get("evidence", [])
    }
    refs: dict[str, dict[str, str]] = {name: {} for name in TOP_COLLECTIONS}
    refs["evidence"] = evidence_by_id
    collections: dict[str, list[Mapping[str, Any]]] = {
        name: list(annotation.get(name, [])) for name in TOP_COLLECTIONS
    }

    def evs(ids: Iterable[str]) -> list[str]:
        return sorted(refs["evidence"].get(value, f"UNKNOWN:{value}") for value in ids)

    def entity_ref(collection: str, value: Any) -> Any:
        if value is None:
            return None
        return refs.get(collection, {}).get(value, f"UNKNOWN:{collection}:{value}")

    def material(collection: str, item: Mapping[str, Any]) -> dict[str, Any]:
        value = {key: child for key, child in item.items() if key != "id"}
        for key in ("evidence_ids", "name_evidence_ids", "context_evidence_ids", "due_relation_evidence_ids"):
            if key in value:
                value[key] = evs(value[key])
        if collection == "actions":
            value["actor_id"] = entity_ref("actors", value.get("actor_id"))
        elif collection == "meetings":
            for key in ("date_ids", "time_ids"):
                value[key] = sorted(entity_ref("temporal_entities", ref) for ref in value.get(key, []))
            value["participant_actor_ids"] = sorted(entity_ref("actors", ref) for ref in value.get("participant_actor_ids", []))
        elif collection == "deadlines":
            target_set = {"ACTION": "actions", "DOCUMENT": "documents"}.get(value.get("target_type"))
            value["target_id"] = entity_ref(target_set or "", value.get("target_id"))
            for key in ("due_date_ids", "due_time_ids"):
                value[key] = sorted(entity_ref("temporal_entities", ref) for ref in value.get(key, []))
        elif collection == "approvals":
            target_set = {"ACTION": "actions", "DOCUMENT": "documents"}.get(value.get("target_type"))
            value["target_id"] = entity_ref(target_set or "", value.get("target_id"))
        elif collection == "thread_changes":
            target_set = {"ACTION": "actions", "DOCUMENT": "documents", "DEPARTMENT": "departments",
                          "MEETING": "meetings", "APPROVAL": "approvals"}.get(value.get("target_type"))
            value["target_id"] = entity_ref(target_set or "", value.get("target_id"))
        elif collection == "acts":
            target_set = {"ACTION": "actions", "DOCUMENT": "documents", "DEPARTMENT": "departments",
                          "MEETING": "meetings", "DEADLINE": "deadlines", "APPROVAL": "approvals",
                          "STATUS_UPDATE": "status_updates", "THREAD_CHANGE": "thread_changes"}.get(value.get("target_type"))
            value["target_id"] = entity_ref(target_set or "", value.get("target_id"))
        return value

    order = ("actors", "documents", "departments", "temporal_entities", "status_updates",
             "actions", "meetings", "deadlines", "approvals", "thread_changes", "acts")
    for collection in order:
        normalized = [(item.get("id"), material(collection, item)) for item in collections[collection]]
        for local_id, value in normalized:
            refs[collection][local_id] = digest_json(value)
    primitive = {
        key: copy.deepcopy(value) for key, value in annotation.items()
        if key not in {*TOP_COLLECTIONS, "evidence"}
    }
    primitive["evidence"] = _evidence_form(annotation)
    for collection in TOP_COLLECTIONS:
        forms = [material(collection, item) for item in collections[collection]]
        primitive[collection] = sorted(forms, key=canonical_json_bytes)
    for key in ("evidence_ids",):
        if key in primitive.get("project_scope", {}):
            primitive["project_scope"][key] = evs(primitive["project_scope"][key])
    primitive["uncertainty_reasons"] = sorted(primitive.get("uncertainty_reasons", []))
    return primitive


def _diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if type(left) is not type(right):
        return [path or "/"]
    if isinstance(left, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}/{key}"
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(_diff_paths(left[key], right[key], child))
            if len(result) >= 100:
                return result[:100]
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [path or "/"]
        result = []
        for index, (l_value, r_value) in enumerate(zip(left, right)):
            result.extend(_diff_paths(l_value, r_value, f"{path}/{index}"))
            if len(result) >= 100:
                return result[:100]
        return result
    return [] if left == right else [path or "/"]


def compare_annotations(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Compare primitive semantics independent of local IDs and array order."""
    left_form = _resolved_references(left)
    right_form = _resolved_references(right)
    left_evidence = _evidence_form(left)
    right_evidence = _evidence_form(right)
    paths = _diff_paths(left_form, right_form)
    return {
        "agreement": not paths,
        "left_primitive_sha256": digest_json(left_form),
        "right_primitive_sha256": digest_json(right_form),
        "changed_paths": paths,
        "exact_evidence_disagreement": left_evidence != right_evidence,
        "left_evidence_sha256": digest_json(left_evidence),
        "right_evidence_sha256": digest_json(right_evidence),
    }


def _is_uncertain(annotation: Mapping[str, Any], mapped: MappingResult) -> bool:
    if annotation.get("needs_review") is True or annotation.get("uncertainty_reasons"):
        return True
    scope = annotation.get("project_scope", {})
    if scope.get("value") == "UNCERTAIN" or scope.get("confidence") == "uncertain":
        return True
    for collection in TOP_COLLECTIONS:
        if any(item.get("confidence") == "uncertain" for item in annotation.get(collection, [])):
            return True
    return mapped.needs_review


def risk_flags(annotation: Mapping[str, Any], mapped: MappingResult) -> list[str]:
    """Return mandatory root-review triggers from mapped labels/primitives."""
    flags: set[str] = set()
    labels = set(mapped.labels)
    for label in sorted(labels & RISK_LABELS):
        flags.add("high_risk_label:" + label)
    if annotation.get("deadlines") or "DEADLINE" in labels:
        flags.add("deadline_relation")
    if annotation.get("thread_changes") or "FOLLOW_UP" in labels:
        flags.add("thread_change_or_follow_up")
    if annotation.get("approvals") or "APPROVAL" in labels:
        flags.add("approval_primitive_or_label")
    if annotation.get("departments") or "DEPARTMENTAL_INPUT" in labels:
        flags.add("department_primitive_or_label")
    scope = annotation.get("project_scope", {})
    if scope.get("value") == "UNCERTAIN" or scope.get("confidence") == "uncertain":
        flags.add("uncertain_scope")
    if _is_uncertain(annotation, mapped):
        flags.add("flagged_ambiguity")
    if mapped.review_reasons:
        flags.add("mapper_review_reason")
    return sorted(flags)


def _load_review_artifact(run_dir: Path, role: str) -> dict[str, Any] | None:
    path = _envelope_path(run_dir, role)
    return _read_json(path) if path.is_file() else None


def _canonical_identity(value: Any) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def _verify_stored_review_artifact(
    *, directory: Path, manifest: Mapping[str, Any], role: str,
    packet: Mapping[str, Any], packet_sha: str,
) -> dict[str, Any]:
    artifact = _load_review_artifact(directory, role)
    if not isinstance(artifact, dict):
        raise ValueError(f"stored {role} review artifact is missing")
    reviewer = manifest["reviewers"][role]["reviewer_identity"]
    if _canonical_identity(reviewer) == "":
        raise ValueError("assigned reviewer identity cannot be blank")
    for key, expected in {
        "workflow_version": WORKFLOW_VERSION, "role": role,
        "reviewer_identity": reviewer, "model": MODEL_REQUIRED,
        "reasoning": REASONING_REQUIRED, "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
    }.items():
        if artifact.get(key) != expected:
            raise ValueError(f"stored {role} artifact binding mismatch for {key}")
    receipt_path = directory / "receipts" / f"{role}.json"
    if not receipt_path.is_file():
        raise ValueError(f"stored {role} artifact has no ingest receipt")
    receipt = _read_json(receipt_path)
    expected_receipt = {
        "workflow_version": WORKFLOW_VERSION, "role": role,
        "reviewer_identity": reviewer, "payload_path": _envelope_path(directory, role).relative_to(directory).as_posix(),
        "payload_sha256": sha256_file(_envelope_path(directory, role)),
        "submitted_envelope_sha256": artifact.get("envelope_sha256"),
        "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
    }
    if receipt != expected_receipt:
        raise ValueError(f"stored {role} artifact does not match its immutable ingest receipt")
    expected_records = packet.get("records", [])
    answers = artifact.get("records")
    if not isinstance(answers, list) or len(answers) != len(expected_records):
        raise ValueError(f"stored {role} artifact record count mismatch")
    for source, answer in zip(expected_records, answers):
        if not isinstance(answer, dict):
            raise ValueError(f"stored {role} artifact contains a non-object answer")
        for key in ("source_id", "current_source_id", "current_source_hash", "source_hashes"):
            if answer.get(key) != source.get(key):
                raise ValueError(f"stored {role} artifact source binding mismatch for {key}")
        annotation, mapped, annotation_sha = _validate_one(source, answer.get("annotation"))
        if answer.get("annotation_sha256") != annotation_sha or answer.get("mapped") != mapped.to_dict():
            raise ValueError(f"stored {role} annotation or mapper output hash mismatch")
    return artifact


def _compute_pair_comparison(directory: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute A/B annotations and per-source gates without writing files."""
    a_packet, a_packet_sha = _load_packet(directory, manifest, "A")
    b_packet, b_packet_sha = _load_packet(directory, manifest, "B")
    if a_packet["records"] != b_packet["records"]:
        raise ValueError("A/B packets do not contain identical source records")
    a = _verify_stored_review_artifact(
        directory=directory, manifest=manifest, role="A", packet=a_packet, packet_sha=a_packet_sha,
    )
    b = _verify_stored_review_artifact(
        directory=directory, manifest=manifest, role="B", packet=b_packet, packet_sha=b_packet_sha,
    )
    a_by_id = {item["source_id"]: item for item in a["records"]}
    b_by_id = {item["source_id"]: item for item in b["records"]}
    rows = []
    required_third = manifest["purpose"] in {"EVAL", "CHALLENGE"}
    for record in a_packet["records"]:
        sid = record["source_id"]
        ar, br = a_by_id[sid], b_by_id[sid]
        primitive = compare_annotations(ar["annotation"], br["annotation"])
        a_mapped = map_labels(ar["annotation"], current_source_id=sid, sources=record["sources"])
        b_mapped = map_labels(br["annotation"], current_source_id=sid, sources=record["sources"])
        flags = sorted(set(risk_flags(ar["annotation"], a_mapped)) | set(risk_flags(br["annotation"], b_mapped)))
        uncertain = _is_uncertain(ar["annotation"], a_mapped) or _is_uncertain(br["annotation"], b_mapped)
        disagreement = not primitive["agreement"]
        third_required = required_third or disagreement
        rows.append({
            "source_id": sid,
            "current_source_hash": record["current_source_hash"],
            "reviewer_A_annotation_sha256": ar["annotation_sha256"],
            "reviewer_B_annotation_sha256": br["annotation_sha256"],
            "reviewer_A_labels": list(a_mapped.labels),
            "reviewer_B_labels": list(b_mapped.labels),
            "primitive_comparison": primitive,
            "primitive_disagreement": disagreement,
            "uncertain": uncertain,
            "risk_flags": flags,
            "third_required": third_required,
            "root_decision_required": bool(flags),
            "provisional_status": "review_required" if (uncertain or third_required or flags) else "ready_for_acceptance",
        })
    result = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": manifest["run_id"],
        "purpose": manifest["purpose"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "reviewer_A_packet_sha256": a_packet_sha,
        "reviewer_B_packet_sha256": b_packet_sha,
        "reviewer_A_envelope_sha256": sha256_file(_envelope_path(directory, "A")),
        "reviewer_B_envelope_sha256": sha256_file(_envelope_path(directory, "B")),
        "reviewer_A_receipt_sha256": sha256_file(directory / "receipts" / "A.json"),
        "reviewer_B_receipt_sha256": sha256_file(directory / "receipts" / "B.json"),
        "records": rows,
    }
    return result


def compare_run(*, run_dir: str | Path, root: Path | None = None) -> dict[str, Any]:
    """Compare A/B validated annotations and report per-source gates, no text."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    result = _compute_pair_comparison(directory, manifest)
    _write_json_replace(directory / "pair_comparison.json", result)
    return result


def _load_verified_pair_comparison(
    *, directory: Path, manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Recompute the A/B comparison and reject stale or hand-edited artifacts."""
    saved = _read_json(directory / "pair_comparison.json")
    expected = _compute_pair_comparison(directory, manifest)
    if saved != expected:
        raise ValueError("stored pair comparison is stale or changed after review")
    return saved, _load_review_artifact(directory, "A"), _load_review_artifact(directory, "B"), _read_json(directory / "reviewer_A" / "packet.json")


def _third_assignment_path(run_dir: Path) -> Path:
    return run_dir / "third_reviewer_assignment.json"


def prepare_third_initial(*, run_dir: str | Path, reviewer_identity: str, root: Path | None = None) -> dict[str, Any]:
    """Prepare source-only adjudicator packet before revealing A/B answers."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    if (directory / "pair_comparison.json").is_file():
        comparison, _a, _b, a_packet = _load_verified_pair_comparison(directory=directory, manifest=manifest)
    else:
        comparison = compare_run(run_dir=directory, root=root)
        a_packet, _ = _load_packet(directory, manifest, "A")
    needs = [row for row in comparison["records"] if row["third_required"]]
    if not needs:
        raise ValueError("no source requires a third review")
    reviewers = {_canonical_identity(item["reviewer_identity"]) for item in manifest["reviewers"].values()}
    if not _canonical_identity(reviewer_identity) or _canonical_identity(reviewer_identity) in reviewers:
        raise ValueError("third reviewer identity must be distinct from reviewers A and B")
    reviewer_identity = reviewer_identity.strip()
    if _third_assignment_path(directory).exists():
        raise FileExistsError("third reviewer assignment is immutable")
    required_ids = {row["source_id"] for row in needs}
    source_records = [record for record in a_packet["records"] if record["source_id"] in required_ids]
    third_source_bundle_sha = digest_json(source_records)
    packet = build_review_packet(
        run_id=manifest["run_id"], role="C_INITIAL", reviewer_identity=reviewer_identity,
        purpose=manifest["purpose"], source_manifest_sha256=manifest["source_manifest_sha256"],
        source_bundle_sha256=third_source_bundle_sha, records=source_records, root=root,
    )
    path = directory / "reviewer_C_initial" / "packet.json"
    packet_sha = _write_json_new(path, packet)
    assignment = {
        "workflow_version": WORKFLOW_VERSION,
        "reviewer_identity": reviewer_identity,
        "model": MODEL_REQUIRED,
        "reasoning": REASONING_REQUIRED,
        "packet_path": path.relative_to(directory).as_posix(),
        "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "source_bundle_sha256": third_source_bundle_sha,
        "third_initial_is_source_only": True,
        "required_source_ids": [record["source_id"] for record in packet["records"]],
    }
    _write_json_new(_third_assignment_path(directory), assignment)
    return assignment


def _load_third_packet(run_dir: Path, *, role: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    assignment = _read_json(_third_assignment_path(run_dir))
    path = run_dir / assignment["packet_path"]
    if not path.is_file() or sha256_file(path) != assignment["packet_sha256"]:
        raise ValueError("third reviewer packet changed or is missing")
    packet = _read_json(path)
    if packet.get("packet_role") != role:
        raise ValueError(f"third reviewer packet is not in role {role}")
    for key, expected in {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": run_dir.name,
        "reviewer_identity": assignment.get("reviewer_identity"),
        "required_model": MODEL_REQUIRED,
        "required_reasoning": REASONING_REQUIRED,
        "source_manifest_sha256": assignment.get("source_manifest_sha256"),
    }.items():
        if packet.get(key) != expected:
            raise ValueError(f"third packet assignment mismatch for {key}")
    root = run_dir.parents[3]
    schema_path = root / "ai" / "config" / "structured_primitive_schema.json"
    if packet.get("annotation_schema_sha256") != sha256_file(schema_path) or packet.get("annotation_schema") != _read_json(schema_path):
        raise ValueError("third reviewer packet schema changed after preparation")
    if packet.get("schema_source_sha256") != sha256_file(root / "ai" / "src" / "structured" / "validation.py") or packet.get("mapper_source_sha256") != sha256_file(root / "ai" / "src" / "structured" / "mapper.py"):
        raise ValueError("third reviewer packet validator/mapper changed after preparation")
    if packet.get("run_id") != run_dir.name or packet.get("source_bundle_sha256") != digest_json(packet.get("records", [])):
        raise ValueError("third reviewer packet run or source bundle hash mismatch")
    for record in packet.get("records", []):
        sources = record.get("sources")
        if not isinstance(sources, dict) or record.get("source_hashes") != {
            source_id: digest_json({"source_id": source_id, **source}) for source_id, source in sources.items()
        }:
            raise ValueError("third reviewer packet source text hash mismatch")
    return packet, assignment["packet_sha256"], assignment


def _verify_third_initial_artifact(
    *, directory: Path, manifest: Mapping[str, Any], comparison: Mapping[str, Any],
    a_packet: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    packet, packet_sha, assignment = _load_third_packet(directory, role="C_INITIAL")
    expected_ids = [row["source_id"] for row in comparison["records"] if row["third_required"]]
    expected_records = [row for row in a_packet["records"] if row["source_id"] in set(expected_ids)]
    if assignment.get("source_manifest_sha256") != manifest["source_manifest_sha256"]:
        raise ValueError("third reviewer assignment is not bound to this source manifest")
    if assignment.get("source_bundle_sha256") != digest_json(expected_records):
        raise ValueError("third reviewer assignment source bundle hash mismatch")
    if assignment.get("required_source_ids") != expected_ids or packet.get("records") != expected_records:
        raise ValueError("third reviewer packet IDs or source records do not match the required rows")
    if packet.get("source_bundle_sha256") != digest_json(expected_records):
        raise ValueError("third reviewer packet source bundle hash mismatch")
    reviewer = assignment.get("reviewer_identity")
    ab_ids = {_canonical_identity(item["reviewer_identity"]) for item in manifest["reviewers"].values()}
    if not _canonical_identity(reviewer) or _canonical_identity(reviewer) in ab_ids:
        raise ValueError("third reviewer identity is blank or duplicates A/B")
    initial_path = _envelope_path(directory, "C_INITIAL")
    if not initial_path.is_file():
        raise ValueError("third adjudicator's source-only initial verdict is missing")
    initial = _read_json(initial_path)
    for key, expected in {
        "workflow_version": WORKFLOW_VERSION, "role": "C_INITIAL",
        "reviewer_identity": reviewer, "model": MODEL_REQUIRED,
        "reasoning": REASONING_REQUIRED, "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "visibility": "independent_source_only",
    }.items():
        if initial.get(key) != expected:
            raise ValueError(f"stored third initial artifact binding mismatch for {key}")
    receipt_path = directory / "receipts" / "C_INITIAL.json"
    if not receipt_path.is_file():
        raise ValueError("third initial artifact has no ingest receipt")
    receipt = _read_json(receipt_path)
    expected_receipt = {
        "workflow_version": WORKFLOW_VERSION, "role": "C_INITIAL",
        "reviewer_identity": reviewer,
        "payload_path": initial_path.relative_to(directory).as_posix(),
        "payload_sha256": sha256_file(initial_path),
        "submitted_envelope_sha256": initial.get("envelope_sha256"),
        "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
    }
    if receipt != expected_receipt:
        raise ValueError("third initial artifact does not match its immutable ingest receipt")
    answers = initial.get("records")
    if not isinstance(answers, list) or len(answers) != len(expected_records):
        raise ValueError("stored third initial artifact record count mismatch")
    for source, answer in zip(expected_records, answers):
        for key in ("source_id", "current_source_id", "current_source_hash", "source_hashes"):
            if answer.get(key) != source.get(key):
                raise ValueError(f"stored third initial source binding mismatch for {key}")
        _, mapped, annotation_sha = _validate_one(source, answer.get("annotation"))
        if answer.get("annotation_sha256") != annotation_sha or answer.get("mapped") != mapped.to_dict():
            raise ValueError("stored third initial annotation or mapper output hash mismatch")
    return packet, initial, sha256_file(initial_path)


def ingest_third_initial(*, run_dir: str | Path, envelope_path: str | Path, root: Path | None = None) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    comparison, _a, _b, a_packet = _load_verified_pair_comparison(directory=directory, manifest=manifest)
    packet, packet_sha, assignment = _load_third_packet(directory, role="C_INITIAL")
    expected_ids = [row["source_id"] for row in comparison["records"] if row["third_required"]]
    expected_records = [row for row in a_packet["records"] if row["source_id"] in set(expected_ids)]
    if assignment.get("source_manifest_sha256") != manifest["source_manifest_sha256"] or assignment.get("required_source_ids") != expected_ids or packet.get("records") != expected_records:
        raise ValueError("third initial assignment does not bind the current source-only rows")
    envelope = _read_json(envelope_path)
    answers = _validate_envelope(
        packet=packet, packet_sha=packet_sha, envelope=envelope, role="C_INITIAL",
        expected_reviewer=assignment["reviewer_identity"], source_manifest_sha256=manifest["source_manifest_sha256"],
    )
    if envelope.get("review_visibility", "independent_source_only") != "independent_source_only":
        raise ValueError("third initial verdict must attest source-only visibility")
    payload = {
        "workflow_version": WORKFLOW_VERSION,
        "role": "C_INITIAL",
        "reviewer_identity": assignment["reviewer_identity"],
        "model": envelope["model"], "reasoning": envelope["reasoning"],
        "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "visibility": "independent_source_only",
        "envelope_sha256": sha256_file(envelope_path),
        "records": answers,
    }
    path = directory / "envelopes" / "C_initial.json"
    sha = _write_json_new(path, payload)
    receipt_sha = _write_ingest_receipt(
        directory=directory, role="C_INITIAL", payload_path=path,
        payload_sha256=sha256_file(path), envelope_sha256=payload["envelope_sha256"],
        packet_sha256=packet_sha, source_manifest_sha256=manifest["source_manifest_sha256"],
        reviewer_identity=assignment["reviewer_identity"],
    )
    return {"stored_path": path.relative_to(directory).as_posix(), "stored_sha256": sha,
            "receipt_sha256": receipt_sha, "record_count": len(answers), "visibility": payload["visibility"]}


def prepare_adjudication(*, run_dir: str | Path, root: Path | None = None) -> dict[str, Any]:
    """Create phase-two packet only after the third blind verdict is frozen."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    comparison, a, b, a_packet = _load_verified_pair_comparison(directory=directory, manifest=manifest)
    c_initial_packet, initial, initial_sha = _verify_third_initial_artifact(
        directory=directory, manifest=manifest, comparison=comparison, a_packet=a_packet,
    )
    a_by_id = {item["source_id"]: item for item in a["records"]}
    b_by_id = {item["source_id"]: item for item in b["records"]}
    c_by_id = {item["source_id"]: item for item in initial["records"]}
    compare_by_id = {item["source_id"]: item for item in comparison["records"]}
    prior_answers = {}
    for record in a_packet["records"]:
        sid = record["source_id"]
        if not compare_by_id[sid]["third_required"]:
            continue
        prior_answers[sid] = {
            "review_A_annotation": a_by_id[sid]["annotation"],
            "review_B_annotation": b_by_id[sid]["annotation"],
            "adjudicator_initial_annotation": c_by_id[sid]["annotation"],
            "review_A_annotation_sha256": a_by_id[sid]["annotation_sha256"],
            "review_B_annotation_sha256": b_by_id[sid]["annotation_sha256"],
            "adjudicator_initial_annotation_sha256": c_by_id[sid]["annotation_sha256"],
        }
    records = [record for record in a_packet["records"] if record["source_id"] in prior_answers]
    reviewer_identity = initial["reviewer_identity"]
    packet = build_review_packet(
        run_id=manifest["run_id"], role="C_ADJUDICATION", reviewer_identity=reviewer_identity,
        purpose=manifest["purpose"], source_manifest_sha256=manifest["source_manifest_sha256"],
        source_bundle_sha256=digest_json(records), records=records, root=root,
        prior_answers=prior_answers, initial_envelope_sha256=initial_sha,
    )
    path = directory / "reviewer_C_adjudication" / "packet.json"
    packet_sha = _write_json_new(path, packet)
    assignment = {
        "workflow_version": WORKFLOW_VERSION,
        "reviewer_identity": reviewer_identity,
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
        "packet_path": path.relative_to(directory).as_posix(),
        "packet_sha256": packet_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "initial_envelope_sha256": initial_sha,
        "a_envelope_sha256": sha256_file(_envelope_path(directory, "A")),
        "b_envelope_sha256": sha256_file(_envelope_path(directory, "B")),
        "visibility": "initial_blind_verdict_hash_frozen_then_A_B_visible",
        "source_ids": [record["source_id"] for record in records],
    }
    _write_json_new(directory / "adjudication_assignment.json", assignment)
    return assignment


def _verify_adjudication_packet_context(
    *, directory: Path, manifest: Mapping[str, Any], root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    comparison, a, b, a_packet = _load_verified_pair_comparison(directory=directory, manifest=manifest)
    _c_packet, initial, initial_sha = _verify_third_initial_artifact(
        directory=directory, manifest=manifest, comparison=comparison, a_packet=a_packet,
    )
    a_by_id = {item["source_id"]: item for item in a["records"]}
    b_by_id = {item["source_id"]: item for item in b["records"]}
    c_by_id = {item["source_id"]: item for item in initial["records"]}
    compare_by_id = {item["source_id"]: item for item in comparison["records"]}
    prior_answers = {}
    for source in a_packet["records"]:
        sid = source["source_id"]
        if compare_by_id[sid]["third_required"]:
            prior_answers[sid] = {
                "review_A_annotation": a_by_id[sid]["annotation"],
                "review_B_annotation": b_by_id[sid]["annotation"],
                "adjudicator_initial_annotation": c_by_id[sid]["annotation"],
                "review_A_annotation_sha256": a_by_id[sid]["annotation_sha256"],
                "review_B_annotation_sha256": b_by_id[sid]["annotation_sha256"],
                "adjudicator_initial_annotation_sha256": c_by_id[sid]["annotation_sha256"],
            }
    records = [source for source in a_packet["records"] if source["source_id"] in prior_answers]
    reviewer = initial["reviewer_identity"]
    expected_packet = build_review_packet(
        run_id=manifest["run_id"], role="C_ADJUDICATION", reviewer_identity=reviewer,
        purpose=manifest["purpose"], source_manifest_sha256=manifest["source_manifest_sha256"],
        source_bundle_sha256=digest_json(records), records=records, root=root,
        prior_answers=prior_answers, initial_envelope_sha256=initial_sha,
    )
    assignment_path = directory / "adjudication_assignment.json"
    packet_path = directory / "reviewer_C_adjudication" / "packet.json"
    if not assignment_path.is_file() or not packet_path.is_file():
        raise ValueError("phase-two adjudication packet and assignment are required")
    assignment = _read_json(assignment_path)
    actual_packet = _read_json(packet_path)
    expected_assignment = {
        "workflow_version": WORKFLOW_VERSION,
        "reviewer_identity": reviewer,
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
        "packet_path": "reviewer_C_adjudication/packet.json",
        "packet_sha256": sha256_file(packet_path),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "initial_envelope_sha256": initial_sha,
        "a_envelope_sha256": sha256_file(_envelope_path(directory, "A")),
        "b_envelope_sha256": sha256_file(_envelope_path(directory, "B")),
        "visibility": "initial_blind_verdict_hash_frozen_then_A_B_visible",
        "source_ids": [source["source_id"] for source in records],
    }
    if actual_packet != expected_packet:
        raise ValueError("phase-two packet does not match frozen source/A/B/C bindings")
    if assignment != expected_assignment or sha256_file(packet_path) != assignment.get("packet_sha256"):
        raise ValueError("phase-two adjudication assignment hash or binding mismatch")
    return assignment, actual_packet, prior_answers, {row["source_id"]: row for row in a_packet["records"]}, comparison


def _verify_adjudication_artifact(
    *, directory: Path, manifest: Mapping[str, Any], root: Path,
) -> dict[str, Any]:
    assignment, packet, prior, source_by_id, _comparison = _verify_adjudication_packet_context(
        directory=directory, manifest=manifest, root=root,
    )
    stored = _envelope_path(directory, "C_ADJUDICATION")
    if not stored.is_file():
        raise ValueError("third adjudication resolution artifact is missing")
    artifact = _read_json(stored)
    for key, expected in {
        "workflow_version": WORKFLOW_VERSION, "role": "C_ADJUDICATION",
        "reviewer_identity": assignment["reviewer_identity"],
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
        "packet_sha256": assignment["packet_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "initial_envelope_sha256": assignment["initial_envelope_sha256"],
        "a_envelope_sha256": assignment["a_envelope_sha256"],
        "b_envelope_sha256": assignment["b_envelope_sha256"],
        "visibility": assignment["visibility"],
    }.items():
        if artifact.get(key) != expected:
            raise ValueError(f"third adjudication artifact binding mismatch for {key}")
    receipt_path = directory / "receipts" / "C_ADJUDICATION.json"
    if not receipt_path.is_file():
        raise ValueError("third adjudication artifact has no ingest receipt")
    receipt = _read_json(receipt_path)
    expected_receipt = {
        "workflow_version": WORKFLOW_VERSION, "role": "C_ADJUDICATION",
        "reviewer_identity": assignment["reviewer_identity"],
        "payload_path": stored.relative_to(directory).as_posix(),
        "payload_sha256": sha256_file(stored),
        "submitted_envelope_sha256": artifact.get("envelope_sha256"),
        "packet_sha256": assignment["packet_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
    }
    if receipt != expected_receipt:
        raise ValueError("third adjudication artifact does not match its immutable ingest receipt")
    answers = artifact.get("records")
    expected_ids = assignment["source_ids"]
    if not isinstance(answers, list) or len(answers) != len(expected_ids):
        raise ValueError("third adjudication artifact record count mismatch")
    for source_id, answer in zip(expected_ids, answers):
        source = source_by_id[source_id]
        bound = prior[source_id]
        if not isinstance(answer, dict) or answer.get("source_id") != source_id:
            raise ValueError("third adjudication source order/ID mismatch")
        for key in ("current_source_id", "current_source_hash", "source_hashes"):
            if answer.get(key) != source.get(key):
                raise ValueError(f"third adjudication source binding mismatch for {key}")
        if answer.get("initial_envelope_sha256") != assignment["initial_envelope_sha256"] or answer.get("review_visibility") != assignment["visibility"]:
            raise ValueError("third adjudication row does not bind the frozen initial verdict and visibility")
        if answer.get("initial_annotation_sha256") != bound["adjudicator_initial_annotation_sha256"]:
            raise ValueError("third adjudication row initial annotation hash mismatch")
        resolution = answer.get("resolution")
        annotation = answer.get("annotation")
        if resolution == "select_a":
            if annotation != bound["review_A_annotation"]:
                raise ValueError("select_a result differs from the frozen A answer")
        elif resolution == "select_b":
            if annotation != bound["review_B_annotation"]:
                raise ValueError("select_b result differs from the frozen B answer")
        elif resolution == "amend":
            _validate_one(source, annotation)
        elif resolution in {"reject", "unresolved"}:
            if annotation is not None:
                raise ValueError("reject/unresolved adjudication must not carry an annotation")
        else:
            raise ValueError("invalid stored third adjudication resolution")
        if annotation is None:
            if answer.get("annotation_sha256") is not None or answer.get("mapped") is not None:
                raise ValueError("empty adjudication resolution has annotation metadata")
        else:
            _, mapped, annotation_sha = _validate_one(source, annotation)
            if answer.get("annotation_sha256") != annotation_sha or answer.get("mapped") != mapped.to_dict():
                raise ValueError("third adjudication annotation hash or mapper output mismatch")
    return artifact


def ingest_adjudication(*, run_dir: str | Path, envelope_path: str | Path, root: Path | None = None) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    assignment, packet, prior, source_by_id, _comparison = _verify_adjudication_packet_context(
        directory=directory, manifest=manifest, root=root,
    )
    packet_path = directory / assignment["packet_path"]
    if not packet_path.is_file() or sha256_file(packet_path) != assignment["packet_sha256"]:
        raise ValueError("adjudication packet changed or is missing")
    if sha256_file(_envelope_path(directory, "A")) != assignment["a_envelope_sha256"] or sha256_file(_envelope_path(directory, "B")) != assignment["b_envelope_sha256"]:
        raise ValueError("A/B envelopes changed after adjudication packet creation")
    initial_path = _envelope_path(directory, "C_INITIAL")
    if sha256_file(initial_path) != assignment["initial_envelope_sha256"]:
        raise ValueError("third adjudicator's independent initial verdict changed")
    envelope = _read_json(envelope_path)
    if envelope.get("initial_envelope_sha256") != assignment["initial_envelope_sha256"]:
        raise ValueError("adjudication envelope must link the frozen independent initial verdict")
    # Common binding checks do not validate annotations until resolution selection is applied.
    expected_reviewer = assignment["reviewer_identity"]
    for key, expected in {
        "workflow_version": WORKFLOW_VERSION, "run_id": manifest["run_id"],
        "packet_role": "C_ADJUDICATION", "packet_sha256": assignment["packet_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "reviewer_identity": expected_reviewer, "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
    }.items():
        if envelope.get(key) != expected:
            raise ValueError(f"adjudication envelope mismatch for {key}")
    attestation = envelope.get("source_read_attestation")
    if not isinstance(attestation, dict) or attestation.get("read_all_sources") is not True:
        raise ValueError("adjudicator must attest reading all sources again for phase two")
    if attestation.get("source_bundle_sha256") != packet.get("source_bundle_sha256"):
        raise ValueError("adjudication source bundle hash mismatch")
    expected_ids = assignment["source_ids"]
    if attestation.get("source_ids") != expected_ids:
        raise ValueError("adjudication source-read IDs/order mismatch")
    answer_rows = envelope.get("records")
    if not isinstance(answer_rows, list) or len(answer_rows) != len(expected_ids) or any(not isinstance(item, dict) for item in answer_rows) or [item.get("source_id") for item in answer_rows] != expected_ids:
        raise ValueError("adjudication envelope must resolve the assigned source IDs in order")
    output = []
    for record, answer in zip(packet["records"], answer_rows):
        sid = record["source_id"]
        if answer.get("current_source_id") != sid or answer.get("current_source_hash") != record["current_source_hash"] or answer.get("source_hashes") != record["source_hashes"]:
            raise ValueError("adjudication answer source hash binding mismatch")
        resolution = answer.get("resolution")
        if resolution not in {"select_a", "select_b", "amend", "reject", "unresolved"}:
            raise ValueError(f"invalid adjudication resolution for {sid!r}")
        annotation = answer.get("annotation")
        if resolution == "select_a":
            if annotation not in (None, prior[sid]["review_A_annotation"]):
                raise ValueError("select_a may not substitute or alter the A annotation")
            annotation = prior[sid]["review_A_annotation"]
        elif resolution == "select_b":
            if annotation not in (None, prior[sid]["review_B_annotation"]):
                raise ValueError("select_b may not substitute or alter the B annotation")
            annotation = prior[sid]["review_B_annotation"]
        elif resolution == "amend":
            _validate_one(source_by_id[sid], annotation)
        else:
            if annotation is not None:
                raise ValueError("reject/unresolved resolutions must not carry an accepted annotation")
        annotation_hash = digest_json(annotation) if annotation is not None else None
        mapped = map_labels(annotation, current_source_id=sid, sources=record["sources"]) if annotation is not None else None
        output.append({
            "source_id": sid, "current_source_id": sid,
            "current_source_hash": record["current_source_hash"], "source_hashes": record["source_hashes"],
            "resolution": resolution, "annotation": annotation, "annotation_sha256": annotation_hash,
            "mapped": mapped.to_dict() if mapped else None,
            "initial_envelope_sha256": assignment["initial_envelope_sha256"],
            "initial_annotation_sha256": prior[sid]["adjudicator_initial_annotation_sha256"],
            "review_visibility": assignment["visibility"],
        })
    payload = {
        "workflow_version": WORKFLOW_VERSION,
        "role": "C_ADJUDICATION", "reviewer_identity": expected_reviewer,
        "model": MODEL_REQUIRED, "reasoning": REASONING_REQUIRED,
        "packet_sha256": assignment["packet_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "initial_envelope_sha256": assignment["initial_envelope_sha256"],
        "a_envelope_sha256": assignment["a_envelope_sha256"],
        "b_envelope_sha256": assignment["b_envelope_sha256"],
        "visibility": assignment["visibility"],
        "envelope_sha256": sha256_file(envelope_path),
        "records": output,
    }
    stored = directory / "envelopes" / "C_adjudication.json"
    sha = _write_json_new(stored, payload)
    receipt_sha = _write_ingest_receipt(
        directory=directory, role="C_ADJUDICATION", payload_path=stored,
        payload_sha256=sha256_file(stored), envelope_sha256=payload["envelope_sha256"],
        packet_sha256=assignment["packet_sha256"], source_manifest_sha256=manifest["source_manifest_sha256"],
        reviewer_identity=expected_reviewer,
    )
    return {"stored_path": stored.relative_to(directory).as_posix(), "stored_sha256": sha,
            "receipt_sha256": receipt_sha, "record_count": len(output), "visibility": payload["visibility"]}


def adjudicate_row(
    *, purpose: str, a: Mapping[str, Any], b: Mapping[str, Any],
    comparison: Mapping[str, Any], third: Mapping[str, Any] | None,
    root_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compute conservative per-row outcome and list immutable evidence hashes."""
    purpose = purpose.upper()
    third_required = purpose in {"EVAL", "CHALLENGE"} or comparison["primitive_disagreement"]
    flags = comparison.get("risk_flags", [])
    if third_required and third is None:
        return {"status": "review_required", "reason": "third_review_missing", "risk_flags": flags}
    selected: Mapping[str, Any] | None = None
    third_resolution = None
    if third is not None:
        third_resolution = third.get("resolution")
        if third_resolution in {"reject", "unresolved"}:
            return {"status": "rejected" if third_resolution == "reject" else "review_required",
                    "reason": "third_reviewer_" + third_resolution, "risk_flags": flags,
                    "third_annotation_sha256": third.get("annotation_sha256")}
        if third_resolution in {"select_a", "select_b", "amend"}:
            selected = third.get("annotation")
    elif comparison["primitive_disagreement"]:
        return {"status": "review_required", "reason": "primitive_disagreement", "risk_flags": flags}
    else:
        selected = a.get("annotation")
    if selected is None:
        return {"status": "review_required", "reason": "selected_annotation_missing", "risk_flags": flags}
    mapped = selected.get("_mapped_result")
    annotation_hash = digest_json(selected)
    root_rejects_selected = (
        root_decision is not None
        and root_decision.get("decision") == "reject"
        and root_decision.get("annotation_sha256") == annotation_hash
        and bool(root_decision.get("root_identity"))
    )
    # Re-map result may be carried as JSON; eligibility also checks primitive uncertainty.
    if selected.get("needs_review") is True or selected.get("uncertainty_reasons"):
        if root_rejects_selected:
            return {"status": "rejected", "reason": "root_rejected_uncertain_annotation",
                    "risk_flags": flags, "annotation_sha256": annotation_hash}
        return {"status": "review_required", "reason": "selected_annotation_uncertain", "risk_flags": flags,
                "annotation_sha256": annotation_hash}
    scope = selected.get("project_scope", {})
    if scope.get("value") == "UNCERTAIN" or scope.get("confidence") == "uncertain":
        if root_rejects_selected:
            return {"status": "rejected", "reason": "root_rejected_uncertain_annotation",
                    "risk_flags": flags, "annotation_sha256": annotation_hash}
        return {"status": "review_required", "reason": "selected_scope_uncertain", "risk_flags": flags,
                "annotation_sha256": annotation_hash}
    if flags:
        if root_decision is None:
            return {"status": "review_required", "reason": "root_risk_decision_missing", "risk_flags": flags,
                    "annotation_sha256": annotation_hash}
        if root_decision.get("annotation_sha256") != annotation_hash:
            return {"status": "review_required", "reason": "root_decision_hash_mismatch", "risk_flags": flags,
                    "annotation_sha256": annotation_hash}
        if root_decision.get("decision") == "reject":
            return {"status": "rejected", "reason": "root_rejected", "risk_flags": flags,
                    "annotation_sha256": annotation_hash}
        if root_decision.get("decision") != "approve" or not root_decision.get("root_identity"):
            return {"status": "review_required", "reason": "root_approval_missing_or_invalid", "risk_flags": flags,
                    "annotation_sha256": annotation_hash}
    elif root_decision is not None:
        root_outcome = root_decision.get("decision")
        if root_outcome == "reject":
            return {"status": "rejected", "reason": "root_rejected", "risk_flags": flags,
                    "annotation_sha256": annotation_hash}
        if root_outcome != "approve" or not root_decision.get("root_identity"):
            return {"status": "review_required", "reason": "root_decision_review_required_or_invalid",
                    "risk_flags": flags, "annotation_sha256": annotation_hash}
    return {"status": "accepted", "reason": "all_required_reviews_passed", "risk_flags": flags,
            "annotation_sha256": annotation_hash, "annotation": selected,
            "third_resolution": third_resolution}


def add_root_decision(
    *, run_dir: str | Path, source_id: str, annotation_sha256: str,
    decision: str, root_identity: str, reason: str,
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    if decision not in {"approve", "reject", "review_required"}:
        raise ValueError("root decision must be approve, reject, or review_required")
    if not _canonical_identity(root_identity) or not reason.strip() or not re.fullmatch(r"[0-9a-f]{64}", annotation_sha256):
        raise ValueError("root identity, reason, and exact annotation SHA-256 are required")
    root_identity = root_identity.strip()
    comparison, a_artifact, b_artifact, a_packet = _load_verified_pair_comparison(directory=directory, manifest=manifest)
    comparison_by_id = {row["source_id"]: row for row in comparison["records"]}
    if source_id not in comparison_by_id:
        raise ValueError("root decision source ID is absent from the current verified review")
    source = next(row for row in a_packet["records"] if row["source_id"] == source_id)
    a_row = next(row for row in a_artifact["records"] if row["source_id"] == source_id)
    b_row = next(row for row in b_artifact["records"] if row["source_id"] == source_id)
    third_row = None
    if comparison_by_id[source_id]["third_required"]:
        if not _envelope_path(directory, "C_ADJUDICATION").is_file():
            raise ValueError("root decision requires a completed third adjudication selection")
        _verify_adjudication_artifact(directory=directory, manifest=manifest, root=root)
        third_doc = _read_json(_envelope_path(directory, "C_ADJUDICATION"))
        third_row = next((row for row in third_doc.get("records", []) if row.get("source_id") == source_id), None)
        if third_row is None or third_row.get("resolution") not in {"select_a", "select_b", "amend"}:
            raise ValueError("root decision requires a resolved third adjudication")
        selected = third_row.get("annotation")
    else:
        if comparison_by_id[source_id]["primitive_disagreement"]:
            raise ValueError("root decision cannot bypass required third adjudication")
        selected = a_row["annotation"]
    _validated, mapped, selected_sha = _validate_one(source, selected)
    if selected_sha != annotation_sha256:
        raise ValueError("root decision annotation hash must match the current selected annotation")
    if decision == "approve" and _is_uncertain(selected, mapped):
        raise ValueError("uncertain or invalid annotations cannot receive root approval")
    reviewer_ids = {_canonical_identity(item["reviewer_identity"]) for item in manifest["reviewers"].values()}
    c_assignment_path = _third_assignment_path(directory)
    if c_assignment_path.exists():
        reviewer_ids.add(_canonical_identity(_read_json(c_assignment_path).get("reviewer_identity")))
    if _canonical_identity(root_identity) in reviewer_ids:
        raise ValueError("root approval identity must be distinct from all reviewers")
    path = directory / "root_decisions" / (digest_json(source_id) + ".json")
    payload = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": manifest["run_id"], "source_id": source_id,
        "annotation_sha256": annotation_sha256,
        "decision": decision, "root_identity": root_identity,
        "reason": reason,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
    }
    sha = _write_json_new(path, payload)
    return {"stored_path": path.relative_to(directory).as_posix(), "stored_sha256": sha, "source_id": source_id, "decision": decision}


def _final_annotation_and_review(
    *, directory: Path, manifest: Mapping[str, Any], record: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    sid = record["source_id"]
    a = _read_json(_envelope_path(directory, "A"))
    b = _read_json(_envelope_path(directory, "B"))
    a_row = next(row for row in a["records"] if row["source_id"] == sid)
    b_row = next(row for row in b["records"] if row["source_id"] == sid)
    third_row = None
    third_path = _envelope_path(directory, "C_ADJUDICATION")
    if third_path.is_file():
        third_doc = _read_json(third_path)
        third_row = next((row for row in third_doc["records"] if row["source_id"] == sid), None)
    root_path = directory / "root_decisions" / (digest_json(sid) + ".json")
    root_decision = _read_json(root_path) if root_path.is_file() else None
    # Risk flags include any valid primitive proposed by either blind reviewer or adjudicator.
    flags = set(comparison.get("risk_flags", []))
    selected = None
    if third_row and third_row.get("resolution") in {"select_a", "select_b", "amend"}:
        selected = third_row.get("annotation")
    elif not comparison["primitive_disagreement"] and manifest["purpose"] in {"TRAIN", "TRAIN_SCREEN"}:
        selected = a_row["annotation"]
    mapped_by_source = {sid: record}
    sources = record["sources"]
    for answer in (a_row, b_row):
        ann = answer["annotation"]
        mapped = map_labels(ann, current_source_id=sid, sources=sources)
        flags.update(risk_flags(ann, mapped))
    if third_row and third_row.get("annotation") is not None:
        mapped = map_labels(third_row["annotation"], current_source_id=sid, sources=sources)
        flags.update(risk_flags(third_row["annotation"], mapped))
    if third_row:
        effective_third = {**third_row, "annotation": third_row.get("annotation")}
    else:
        effective_third = None
    effective_comparison = {**comparison, "risk_flags": sorted(flags)}
    if root_decision is not None:
        reviewer_ids = {_canonical_identity(item["reviewer_identity"]) for item in manifest["reviewers"].values()}
        c_assignment_path = _third_assignment_path(directory)
        if c_assignment_path.exists():
            reviewer_ids.add(_canonical_identity(_read_json(c_assignment_path).get("reviewer_identity")))
        expected_root = {
            "workflow_version": WORKFLOW_VERSION,
            "run_id": manifest["run_id"], "source_id": sid,
            "source_manifest_sha256": manifest["source_manifest_sha256"],
        }
        if (any(root_decision.get(key) != value for key, value in expected_root.items())
                or _canonical_identity(root_decision.get("root_identity")) in reviewer_ids
                or not _canonical_identity(root_decision.get("root_identity"))
                or root_decision.get("decision") not in {"approve", "reject", "review_required"}
                or not isinstance(root_decision.get("reason"), str) or not root_decision["reason"].strip()
                or not isinstance(root_decision.get("annotation_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", root_decision["annotation_sha256"]) is None):
            return None, {"status": "review_required", "reason": "root_decision_binding_mismatch", "risk_flags": sorted(flags)}, sorted(flags)
        if selected is None or root_decision.get("annotation_sha256") != digest_json(selected):
            return None, {"status": "review_required", "reason": "root_decision_annotation_mismatch", "risk_flags": sorted(flags)}, sorted(flags)
    outcome = adjudicate_row(
        purpose=manifest["purpose"], a=a_row, b=b_row,
        comparison=effective_comparison, third=effective_third,
        root_decision=root_decision,
    )
    if outcome.get("status") == "accepted":
        selected = outcome["annotation"]
        mapped = map_labels(selected, current_source_id=sid, sources=sources)
        if mapped.needs_review:
            return None, None, sorted(flags)
        # Revalidate selected text/evidence against the exact packet sources at finalization.
        valid = validate_annotation(selected, current_source_id=sid, sources=sources)
        if not valid.valid:
            return None, None, sorted(flags)
        outcome["mapped"] = mapped.to_dict()
        outcome["annotation_sha256"] = digest_json(selected)
    return outcome.get("annotation"), outcome, sorted(flags)


def finalize_run(*, run_dir: str | Path, root: Path | None = None) -> dict[str, Any]:
    """Write immutable decisions only for rows satisfying every required gate."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    comparison, _a_artifact, _b_artifact, a_packet = _load_verified_pair_comparison(directory=directory, manifest=manifest)
    if _envelope_path(directory, "C_INITIAL").is_file():
        _verify_third_initial_artifact(directory=directory, manifest=manifest, comparison=comparison, a_packet=a_packet)
    if _envelope_path(directory, "C_ADJUDICATION").is_file():
        _verify_adjudication_artifact(directory=directory, manifest=manifest, root=root)
    elif (directory / "adjudication_assignment.json").is_file():
        _verify_adjudication_packet_context(directory=directory, manifest=manifest, root=root)
    comparison_by_id = {item["source_id"]: item for item in comparison["records"]}
    counts: Counter[str] = Counter()
    pending = []
    for record in a_packet["records"]:
        sid = record["source_id"]
        final_path = directory / "decisions" / (digest_json(sid) + ".json")
        selected, outcome, flags = _final_annotation_and_review(
            directory=directory, manifest=manifest, record=record,
            comparison=comparison_by_id[sid],
        )
        if outcome is None or outcome.get("status") not in {"accepted", "rejected"}:
            if final_path.exists():
                raise ValueError("stored decision exists although its current reviews no longer satisfy acceptance")
            counts["review_required"] += 1
            pending.append({"source_id": sid, "reason": outcome.get("reason") if outcome else "final_validation_failed", "risk_flags": flags})
            continue
        decision = {
            "workflow_version": WORKFLOW_VERSION,
            "run_id": manifest["run_id"], "purpose": manifest["purpose"],
            "source_id": sid, "current_source_hash": record["current_source_hash"],
            "source_hashes": record["source_hashes"],
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "reviewer_A_packet_sha256": manifest["reviewers"]["A"]["packet_sha256"],
            "reviewer_B_packet_sha256": manifest["reviewers"]["B"]["packet_sha256"],
            "reviewer_A_envelope_sha256": sha256_file(_envelope_path(directory, "A")),
            "reviewer_B_envelope_sha256": sha256_file(_envelope_path(directory, "B")),
            "reviewer_A_receipt_sha256": sha256_file(directory / "receipts" / "A.json"),
            "reviewer_B_receipt_sha256": sha256_file(directory / "receipts" / "B.json"),
            "pair_comparison_sha256": sha256_file(directory / "pair_comparison.json"),
            "third_initial_envelope_sha256": sha256_file(_envelope_path(directory, "C_INITIAL")) if _envelope_path(directory, "C_INITIAL").is_file() else None,
            "third_initial_receipt_sha256": sha256_file(directory / "receipts" / "C_INITIAL.json") if (directory / "receipts" / "C_INITIAL.json").is_file() else None,
            "third_adjudication_envelope_sha256": sha256_file(_envelope_path(directory, "C_ADJUDICATION")) if _envelope_path(directory, "C_ADJUDICATION").is_file() else None,
            "third_adjudication_receipt_sha256": sha256_file(directory / "receipts" / "C_ADJUDICATION.json") if (directory / "receipts" / "C_ADJUDICATION.json").is_file() else None,
            "root_decision_sha256": sha256_file(directory / "root_decisions" / (digest_json(sid) + ".json")) if (directory / "root_decisions" / (digest_json(sid) + ".json")).is_file() else None,
            "risk_flags": flags,
            "status": outcome["status"], "reason": outcome["reason"],
            "annotation_sha256": outcome.get("annotation_sha256"),
            "mapped": outcome.get("mapped"),
            # Private run artifacts only. Never copied to reports.
            "annotation": selected,
        }
        if final_path.is_file():
            if _read_json(final_path) != decision:
                raise ValueError("stored decision differs from the current verified review outcome")
        else:
            _write_json_new(final_path, decision)
        counts[decision["status"]] += 1
    total = len(a_packet["records"])
    counts["review_required"] += len(a_packet["records"]) - sum(counts.values()) if sum(counts.values()) < total else 0
    decision_rows = []
    for record in a_packet["records"]:
        sid = record["source_id"]
        path = directory / "decisions" / (digest_json(sid) + ".json")
        if path.is_file():
            decision = _read_json(path)
            decision_rows.append({"source_id": sid, "status": decision["status"], "decision_sha256": sha256_file(path)})
    decision_manifest_sha = None
    if counts["review_required"] == 0 and len(decision_rows) == total:
        decision_manifest = {
            "workflow_version": WORKFLOW_VERSION,
            "run_id": manifest["run_id"], "purpose": manifest["purpose"],
            "run_manifest_sha256": sha256_file(directory / "run_manifest.json"),
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "counts": {"accepted": counts["accepted"], "rejected": counts["rejected"], "review_required": 0},
            "records": decision_rows,
        }
        decision_manifest_path = directory / "decision_manifest.json"
        if decision_manifest_path.exists():
            if _read_json(decision_manifest_path) != decision_manifest:
                raise ValueError("immutable decision manifest differs from current decision files")
        else:
            _write_json_new(decision_manifest_path, decision_manifest)
        decision_manifest_sha = sha256_file(decision_manifest_path)
    elif (directory / "decision_manifest.json").exists():
        raise ValueError("complete decision manifest exists although current review gates are incomplete")
    result = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": manifest["run_id"], "purpose": manifest["purpose"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "counts": {"accepted": counts["accepted"], "rejected": counts["rejected"], "review_required": counts["review_required"]},
        "total": total,
        "decision_manifest_sha256": decision_manifest_sha,
        "pending": pending,
    }
    _write_json_replace(directory / "progress.json", result)
    return result


def summarize_run(*, run_dir: str | Path, root: Path | None = None) -> dict[str, Any]:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    a_path = _envelope_path(directory, "A")
    b_path = _envelope_path(directory, "B")
    if not (a_path.is_file() and b_path.is_file()):
        if (directory / "decision_manifest.json").exists() or any((directory / "decisions").glob("*.json")):
            raise ValueError("stored final decisions exist before both blind reviews are complete")
        source_manifest = _read_json(directory / manifest["source_manifest_path"])
        pending = [
            {"source_id": item["source_id"], "reason": "blind_reviews_incomplete", "risk_flags": []}
            for item in source_manifest["source_hashes"]
        ]
        return {
            "workflow_version": WORKFLOW_VERSION,
            "run_id": manifest["run_id"], "purpose": manifest["purpose"],
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "counts": {"accepted": 0, "rejected": 0, "review_required": len(pending)},
            "total": len(pending), "decision_manifest_sha256": None,
            "pending": pending,
        }
    if not (directory / "pair_comparison.json").is_file():
        compare_run(run_dir=directory, root=root)
    return finalize_run(run_dir=directory, root=root)


def _load_verified_training_boundary(
    *, directory: Path, manifest: Mapping[str, Any], root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
    source_manifest = _read_json(directory / manifest["source_manifest_path"])
    for record_type in ("global_index", "partition_manifest"):
        entry = source_manifest.get(record_type)
        if not isinstance(entry, dict) or not entry.get("path") or not entry.get("sha256"):
            raise ValueError(f"{record_type} is missing from the source manifest")
        if sha256_file(root / entry["path"]) != entry["sha256"]:
            raise ValueError(f"{record_type} changed after review packets were prepared")
    index_path = root / source_manifest["global_index"]["path"]
    assignment_path = root / source_manifest["partition_manifest"]["path"]
    index_payload, assignments, index_sha, assignments_sha = _load_boundary(
        index_path=index_path, assignments_path=assignment_path, dataset_id=manifest["dataset_id"], root=root,
    )
    if index_sha != source_manifest["global_index"]["sha256"] or assignments_sha != source_manifest["partition_manifest"]["sha256"]:
        raise ValueError("verified leakage boundary hash changed")
    _verify_train_isolation(index_payload, assignments)
    if sha256_file(root / source_manifest["source_file"]) != source_manifest["source_file_sha256"]:
        raise ValueError("source JSONL changed after review packets were prepared")
    return source_manifest, index_payload, assignments, index_sha, assignments_sha


def prepare_accepted_handoff(
    *, run_dir: str | Path, output_path: str | Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Write a private accepted-review handoff, explicitly not training permission."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    if manifest.get("purpose") not in {"TRAIN", "TRAIN_SCREEN"}:
        raise ValueError("accepted handoff requires a TRAIN or TRAIN_SCREEN review run")
    summary = summarize_run(run_dir=directory, root=root)
    if summary["counts"]["review_required"]:
        raise ValueError("accepted handoff blocked while any source remains review-required")
    if not summary.get("decision_manifest_sha256"):
        raise ValueError("complete immutable decision manifest is required")
    source_manifest, index_payload, assignments, index_sha, assignments_sha = _load_verified_training_boundary(
        directory=directory, manifest=manifest, root=root,
    )
    output = _ensure_private(output_path or (directory / "accepted_annotations_for_orchestrator_review.jsonl"), root=root)
    if output.exists():
        raise FileExistsError("accepted review handoff is immutable")
    a_packet, _ = _load_packet(directory, manifest, "A")
    records = []
    ids = []
    dataset_id = manifest["dataset_id"]
    for packet_record in a_packet["records"]:
        sid = packet_record["source_id"]
        decision_path = directory / "decisions" / (digest_json(sid) + ".json")
        decision = _read_json(decision_path)
        if decision.get("status") != "accepted":
            continue
        global_id = _qualified_id(dataset_id, sid)
        if global_id not in index_payload["records"]:
            raise ValueError("accepted source is absent from the actual global index")
        if assignments["partitions"].get(global_id) not in {"TRAIN", "TRAIN_SCREEN"}:
            raise ValueError("accepted source is not in a train-screen partition")
        if global_id in set(assignments.get("protected_global_ids", [])) or sid in set(assignments.get("protected_source_ids", [])):
            raise ValueError("accepted source appears in the boundary's protected/reserved IDs")
        index_record = index_payload["records"][global_id]
        if decision.get("risk_flags") and not decision.get("root_decision_sha256"):
            raise ValueError("risk-bearing accepted source lacks a root decision hash")
        row = {
            "source_id": sid,
            "current_source_id": packet_record["current_source_id"],
            "subject": packet_record["sources"][sid].get("subject", ""),
            "current_message": packet_record["sources"][sid].get("current_message", ""),
            "dataset_id": dataset_id,
            "source_partition": assignments["partitions"][global_id],
            "source_index_id": global_id,
            "overlap_family": index_record.get("overlap_family"),
            "leakage_group_id": index_record.get("leakage_group_id"),
            "identity_complete": index_record.get("identity_complete"),
            "partition_conflicts": [],
            "training_exclusions": [],
            "sources": packet_record["sources"],
            "source_hashes": packet_record["source_hashes"],
            "annotation": decision["annotation"],
            "fyp_labels": decision["mapped"]["labels"],
            "review_decision_sha256": sha256_file(decision_path),
        }
        records.append(row)
        ids.append(sid)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    registry_path = root / "ai" / "config" / "dataset_registry.json"
    result_manifest = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": manifest["run_id"],
        "purpose": "TRAIN_SCREEN_REVIEW_HANDOFF",
        "training_permitted": False,
        "count": len(records),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "run_manifest_sha256": sha256_file(directory / "run_manifest.json"),
        "decision_manifest_sha256": summary["decision_manifest_sha256"],
        "source_file_sha256": source_manifest["source_file_sha256"],
        "index_sha256": index_sha,
        "partition_manifest_sha256": assignments_sha,
        # The boundary manifest is the frozen evaluation-source boundary.
        # Its own bytes are hashed externally in this handoff to avoid a
        # self-referential manifest hash.
        "frozen_evaluation_source_boundary_sha256": assignments_sha,
        "dataset_registry_sha256": sha256_file(registry_path),
        "accepted_annotation_file_sha256": sha256_file(output),
        # Canonical definition: SHA-256 of UTF-8 canonical JSON for sorted native source ID strings.
        "accepted_source_ids_sha256": digest_json(sorted(ids)),
        "accepted_source_ids_order": sorted(ids),
        "raw_text_private_under_ai_data": True,
    }
    _write_json_new(output.with_suffix(output.suffix + ".manifest.json"), result_manifest)
    return {"count": len(records), "output_path": output.relative_to(root).as_posix(), "manifest": result_manifest}


def _verify_handoff_provenance(
    *, run_dir: Path, manifest: Mapping[str, Any], handoff_path: Path,
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str, list[dict[str, Any]], dict[str, Any]]:
    if manifest.get("purpose") not in {"TRAIN", "TRAIN_SCREEN"}:
        raise ValueError("accepted training handoff requires a TRAIN/TRAIN_SCREEN run")
    summary = finalize_run(run_dir=run_dir, root=root)
    if summary["counts"]["review_required"] or not summary.get("decision_manifest_sha256"):
        raise ValueError("complete accepted/rejected decisions are required before handoff validation")
    source_manifest, index_payload, assignments, index_sha, assignments_sha = _load_verified_training_boundary(
        directory=run_dir, manifest=manifest, root=root,
    )
    sidecar_path = handoff_path.with_suffix(handoff_path.suffix + ".manifest.json")
    if not handoff_path.is_file() or not sidecar_path.is_file():
        raise ValueError("accepted review handoff and adjacent manifest are required")
    if not handoff_path.stat().st_size:
        raise ValueError("empty accepted training handoff cannot be used")
    rows = _read_jsonl(handoff_path)
    a_packet, _ = _load_packet(run_dir, manifest, "A")
    decision_manifest = _read_json(run_dir / "decision_manifest.json")
    decision_by_id = {row["source_id"]: row for row in decision_manifest["records"]}
    expected_rows: list[dict[str, Any]] = []
    accepted_ids: list[str] = []
    dataset_id = manifest["dataset_id"]
    from src.datasets.global_leakage import LeakageIndex
    leakage = LeakageIndex(
        records=index_payload["records"], links=index_payload.get("links", []),
        policy=index_payload.get("policy", {}),
    )
    train_ids = [rid for rid, part in assignments["partitions"].items() if part in {"TRAIN", "TRAIN_SCREEN"}]
    protected_ids = sorted({
        rid for rid, part in assignments["partitions"].items() if part not in {"TRAIN", "TRAIN_SCREEN"}
    } | set(assignments.get("protected_global_ids", [])))
    exclusions = leakage.training_exclusions(train_ids, protected_ids)
    for source in a_packet["records"]:
        sid = source["source_id"]
        decision_path = run_dir / "decisions" / (digest_json(sid) + ".json")
        decision = _read_json(decision_path)
        if decision_by_id.get(sid) != {
            "source_id": sid, "status": decision.get("status"), "decision_sha256": sha256_file(decision_path),
        }:
            raise ValueError("decision manifest does not bind the actual per-source decision")
        if decision.get("status") != "accepted":
            continue
        global_id = _qualified_id(dataset_id, sid)
        if global_id not in index_payload["records"] or assignments["partitions"].get(global_id) not in {"TRAIN", "TRAIN_SCREEN"}:
            raise ValueError("accepted handoff source is absent or not assigned to TRAIN_SCREEN")
        if global_id in set(assignments.get("protected_global_ids", [])) or sid in set(assignments.get("protected_source_ids", [])):
            raise ValueError("accepted handoff source is protected/reserved")
        if global_id in exclusions:
            raise ValueError("accepted handoff source is excluded by current training isolation")
        index_record = index_payload["records"][global_id]
        _verify_candidate_index_fingerprint(normalized_record=source, index_record=index_record)
        for context_id in source["source_order"][1:]:
            context = source["sources"][context_id]
            context_global = _qualified_id(dataset_id, context_id)
            if context.get("source_id_kind") != "source_id" or context_global not in index_payload["records"]:
                raise ValueError("accepted handoff context is not index-bound")
            if assignments["partitions"].get(context_global) != assignments["partitions"][global_id]:
                raise ValueError("accepted handoff context crosses a source partition")
            _verify_candidate_index_fingerprint(
                normalized_record={"source_id": context_id, "current_source_id": context_id, "sources": {context_id: context}},
                index_record=index_payload["records"][context_global],
            )
        expected_source_hashes = {
            source_id: digest_json({"source_id": source_id, **source_object})
            for source_id, source_object in source["sources"].items()
        }
        if source.get("source_hashes") != expected_source_hashes or decision.get("source_hashes") != expected_source_hashes:
            raise ValueError("accepted handoff source text hash mismatch")
        annotation = decision.get("annotation")
        _, mapped, annotation_sha = _validate_one(source, annotation)
        if annotation_sha != decision.get("annotation_sha256") or mapped.to_dict() != decision.get("mapped"):
            raise ValueError("accepted handoff annotation or mapped labels differ from verified decision")
        root_decision_path = run_dir / "root_decisions" / (digest_json(sid) + ".json")
        if decision.get("risk_flags") and (not root_decision_path.is_file() or decision.get("root_decision_sha256") != sha256_file(root_decision_path)):
            raise ValueError("risk-bearing accepted decision is missing its bound root approval")
        row = {
            "source_id": sid,
            "current_source_id": source["current_source_id"],
            "subject": source["sources"][sid].get("subject", ""),
            "current_message": source["sources"][sid].get("current_message", ""),
            "dataset_id": dataset_id,
            "source_partition": assignments["partitions"][global_id],
            "source_index_id": global_id,
            "overlap_family": index_record.get("overlap_family"),
            "leakage_group_id": index_record.get("leakage_group_id"),
            "identity_complete": index_record.get("identity_complete"),
            "partition_conflicts": [], "training_exclusions": [],
            "sources": source["sources"], "source_hashes": expected_source_hashes,
            "annotation": annotation, "fyp_labels": list(mapped.labels),
            "review_decision_sha256": sha256_file(decision_path),
        }
        expected_rows.append(row)
        accepted_ids.append(sid)
    if rows != expected_rows:
        if len(rows) != len(expected_rows):
            raise ValueError("accepted handoff row count differs from verified source/decision/index records")
        for actual, expected in zip(rows, expected_rows):
            if actual != expected:
                differing_fields = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
                raise ValueError("accepted handoff row differs from verified fields: " + ", ".join(differing_fields))
        raise ValueError("accepted handoff rows differ from verified source/decision/index records")
    registry_path = root / "ai" / "config" / "dataset_registry.json"
    expected_sidecar = {
        "workflow_version": WORKFLOW_VERSION,
        "run_id": manifest["run_id"], "purpose": "TRAIN_SCREEN_REVIEW_HANDOFF",
        "training_permitted": False, "count": len(expected_rows),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "run_manifest_sha256": sha256_file(run_dir / "run_manifest.json"),
        "decision_manifest_sha256": summary["decision_manifest_sha256"],
        "source_file_sha256": source_manifest["source_file_sha256"],
        "index_sha256": index_sha,
        "partition_manifest_sha256": assignments_sha,
        "frozen_evaluation_source_boundary_sha256": assignments_sha,
        "dataset_registry_sha256": sha256_file(registry_path),
        "accepted_annotation_file_sha256": sha256_file(handoff_path),
        "accepted_source_ids_sha256": digest_json(sorted(accepted_ids)),
        "accepted_source_ids_order": sorted(accepted_ids),
        "raw_text_private_under_ai_data": True,
    }
    sidecar = _read_json(sidecar_path)
    if sidecar != expected_sidecar:
        raise ValueError("accepted handoff manifest differs from verified run/decision/source hashes")
    return source_manifest, index_payload, assignments, index_sha, assignments_sha, rows, sidecar


def _verify_training_authorization(
    *, authorization: Mapping[str, Any], manifest: Mapping[str, Any], directory: Path,
    handoff_path: Path, handoff_manifest: Mapping[str, Any], source_manifest: Mapping[str, Any],
    index_sha: str, assignments_sha: str, evaluation_boundary_path: str | Path,
    root: Path,
) -> list[str]:
    bound_boundary = root / source_manifest["partition_manifest"]["path"]
    supplied_boundary = _ensure_private(evaluation_boundary_path, root=root)
    if supplied_boundary != bound_boundary or sha256_file(supplied_boundary) != assignments_sha:
        raise ValueError("evaluation boundary path must be the exact partition manifest bound at packet preparation")
    required = {
        "authorization_version": "2-alpha",
        "issued_by": "orchestrator",
        "training_permitted": True,
        "run_manifest_sha256": sha256_file(directory / "run_manifest.json"),
        "decision_manifest_sha256": sha256_file(directory / "decision_manifest.json"),
        "dataset_registry_sha256": sha256_file(root / "ai" / "config" / "dataset_registry.json"),
        "index_sha256": index_sha,
        "partition_manifest_sha256": assignments_sha,
        "accepted_annotation_file_sha256": sha256_file(handoff_path),
        "accepted_source_ids_sha256": handoff_manifest["accepted_source_ids_sha256"],
        "frozen_evaluation_source_boundary_sha256": assignments_sha,
    }
    for key, expected in required.items():
        if authorization.get(key) != expected:
            raise ValueError(f"training authorization missing or mismatched: {key}")
    components = authorization.get("permitted_components")
    if not isinstance(components, list) or not components or any(not isinstance(value, str) or not value.strip() for value in components):
        raise ValueError("training authorization must enumerate permitted_components")
    registry = _read_json(root / "ai" / "config" / "dataset_registry.json")
    from src.datasets.registry import require_training_source
    handoff_rows = _read_jsonl(handoff_path) if handoff_path.stat().st_size else []
    dataset_ids = sorted({row.get("dataset_id") for row in handoff_rows})
    if not dataset_ids:
        raise ValueError("empty accepted handoff cannot be authorized for model training")
    for dataset_id in dataset_ids:
        if not isinstance(dataset_id, str):
            raise ValueError("accepted handoff has a missing dataset_id")
        require_training_source(registry, dataset_id)
    return components


def export_accepted_train(
    *, run_dir: str | Path, output_path: str | Path, authorization_path: str | Path,
    evaluation_boundary_path: str | Path, handoff_path: str | Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Copy accepted rows to TRAIN only when the post-review root authorization matches."""
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    directory, manifest = _load_run(run_dir, root=root)
    if manifest.get("purpose") not in {"TRAIN", "TRAIN_SCREEN"}:
        raise ValueError("only a train-screen review run may produce a TRAIN export")
    summary = summarize_run(run_dir=directory, root=root)
    if summary["counts"]["review_required"]:
        raise ValueError("TRAIN export blocked while any source remains review-required")
    if not (directory / "decision_manifest.json").is_file():
        raise ValueError("immutable decision manifest is required")
    source_manifest, index_payload, assignments, index_sha, assignments_sha = _load_verified_training_boundary(
        directory=directory, manifest=manifest, root=root,
    )
    handoff = _ensure_private(handoff_path or (directory / "accepted_annotations_for_orchestrator_review.jsonl"), root=root)
    handoff_manifest_path = handoff.with_suffix(handoff.suffix + ".manifest.json")
    if not handoff.is_file() or not handoff_manifest_path.is_file():
        raise ValueError("accepted review handoff and its hash manifest are required before authorization")
    source_manifest, index_payload, assignments, index_sha, assignments_sha, _rows, handoff_manifest = _verify_handoff_provenance(
        run_dir=directory, manifest=manifest, handoff_path=handoff, root=root,
    )
    if handoff_manifest.get("training_permitted") is not False or handoff_manifest.get("accepted_annotation_file_sha256") != sha256_file(handoff):
        raise ValueError("accepted review handoff hash/status mismatch")
    authorization_file = _ensure_private(authorization_path, root=root)
    authorization = _read_json(authorization_file)
    if not isinstance(authorization, dict):
        raise ValueError("training authorization must be a JSON object")
    components = _verify_training_authorization(
        authorization=authorization, manifest=manifest, directory=directory,
        handoff_path=handoff, handoff_manifest=handoff_manifest,
        source_manifest=source_manifest, index_sha=index_sha, assignments_sha=assignments_sha,
        evaluation_boundary_path=evaluation_boundary_path, root=root,
    )
    output = _ensure_private(output_path, root=root)
    if output.exists():
        raise FileExistsError("authorized TRAIN export is immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    with handoff.open("rb") as source, output.open("xb") as target:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            target.write(block)
    train_manifest = {
        "workflow_version": WORKFLOW_VERSION,
        "purpose": "TRAIN", "run_id": manifest["run_id"],
        "count": handoff_manifest["count"],
        "training_permitted": True,
        "permitted_components": components,
        "run_manifest_sha256": sha256_file(directory / "run_manifest.json"),
        "decision_manifest_sha256": sha256_file(directory / "decision_manifest.json"),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "source_file_sha256": source_manifest["source_file_sha256"],
        "global_index_sha256": index_sha,
        "partition_manifest_sha256": assignments_sha,
        "frozen_evaluation_source_boundary_sha256": assignments_sha,
        "dataset_registry_sha256": sha256_file(root / "ai" / "config" / "dataset_registry.json"),
        "authorization_sha256": sha256_file(authorization_file),
        "accepted_annotation_file_sha256": sha256_file(handoff),
        "accepted_source_ids_sha256": handoff_manifest["accepted_source_ids_sha256"],
        "output_sha256": sha256_file(output),
        "private_under_ai_data": True,
    }
    _write_json_new(output.with_suffix(output.suffix + ".manifest.json"), train_manifest)
    return {"count": train_manifest["count"], "output_path": output.relative_to(root).as_posix(), "manifest": train_manifest}


def verify_accepted_train_provenance(
    accepted_train_path: str | Path, authorization_path: str | Path,
    registry_path: str | Path | None = None, *, root: Path | None = None,
) -> dict[str, Any]:
    """Revalidate a TRAIN export before any baseline/model consumes its rows.

    Returns verified source/index/boundary data and accepted rows only after
    the full A/B/C/root-decision and train-isolation chain is recomputed.
    Callers should treat the returned rows as private source-bearing data.
    """
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    train_path = _ensure_private(accepted_train_path, root=root)
    authorization_file = _ensure_private(authorization_path, root=root)
    train_manifest_path = train_path.with_suffix(train_path.suffix + ".manifest.json")
    if not train_path.is_file() or not train_manifest_path.is_file() or not authorization_file.is_file():
        raise ValueError("TRAIN data, manifest and explicit authorization are all required")
    train_manifest = _read_json(train_manifest_path)
    run_id = train_manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("TRAIN manifest lacks a run ID")
    directory = _ensure_private(root / "ai" / "data" / "structured_review" / run_id, root=root)
    directory, manifest = _load_run(directory, root=root)
    if manifest.get("purpose") not in {"TRAIN", "TRAIN_SCREEN"}:
        raise ValueError("TRAIN export references a non-training review run")
    summary = finalize_run(run_dir=directory, root=root)
    if summary["counts"]["review_required"] or not (directory / "decision_manifest.json").is_file():
        raise ValueError("TRAIN export run has unresolved review rows")
    handoff_path = directory / "accepted_annotations_for_orchestrator_review.jsonl"
    source_manifest, index_payload, assignments, index_sha, assignments_sha, rows, handoff_manifest = _verify_handoff_provenance(
        run_dir=directory, manifest=manifest, handoff_path=handoff_path, root=root,
    )
    if sha256_file(train_path) != handoff_manifest["accepted_annotation_file_sha256"]:
        raise ValueError("TRAIN export bytes differ from the independently verified accepted handoff")
    if _read_jsonl(train_path) != rows:
        raise ValueError("TRAIN export rows differ from the verified accepted handoff rows")
    actual_registry = root / "ai" / "config" / "dataset_registry.json"
    if registry_path is not None and Path(registry_path).resolve() != actual_registry.resolve():
        raise ValueError("registry path must be the repository registry bound by the review run")
    authorization = _read_json(authorization_file)
    _verify_training_authorization(
        authorization=authorization, manifest=manifest, directory=directory,
        handoff_path=handoff_path, handoff_manifest=handoff_manifest,
        source_manifest=source_manifest, index_sha=index_sha,
        assignments_sha=assignments_sha,
        evaluation_boundary_path=root / source_manifest["partition_manifest"]["path"],
        root=root,
    )
    expected_train_manifest = {
        "workflow_version": WORKFLOW_VERSION,
        "purpose": "TRAIN", "run_id": manifest["run_id"],
        "count": len(rows), "training_permitted": True,
        "permitted_components": authorization["permitted_components"],
        "run_manifest_sha256": sha256_file(directory / "run_manifest.json"),
        "decision_manifest_sha256": sha256_file(directory / "decision_manifest.json"),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "source_file_sha256": source_manifest["source_file_sha256"],
        "global_index_sha256": index_sha,
        "partition_manifest_sha256": assignments_sha,
        "frozen_evaluation_source_boundary_sha256": assignments_sha,
        "dataset_registry_sha256": sha256_file(actual_registry),
        "authorization_sha256": sha256_file(authorization_file),
        "accepted_annotation_file_sha256": sha256_file(handoff_path),
        "accepted_source_ids_sha256": handoff_manifest["accepted_source_ids_sha256"],
        "output_sha256": sha256_file(train_path),
        "private_under_ai_data": True,
    }
    if train_manifest != expected_train_manifest:
        raise ValueError("TRAIN sidecar differs from independently recomputed provenance hashes")
    return {
        "manifest": train_manifest,
        "source_manifest": source_manifest,
        "index_payload": index_payload,
        "assignments": assignments,
        "rows": rows,
    }
