"""Authorization-gated word-level baselines for structured annotations.

This module accepts only the orchestrator-created ``accepted_train.jsonl``.
It never discovers candidates, reads a review handoff, or loads evaluation data.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from src.datasets.registry import require_training_source
from src.structured.mapper import map_labels
from src.structured.validation import validate_annotation


AUTHORIZATION_VERSION = "2-alpha"
REQUIRED_COMPONENTS = frozenset({
    "structured_scope_baseline",
    "structured_speech_act_baseline",
})
AUTH_HASH_FIELDS = (
    "run_manifest_sha256",
    "decision_manifest_sha256",
    "dataset_registry_sha256",
    "index_sha256",
    "partition_manifest_sha256",
    "accepted_annotation_file_sha256",
    "accepted_source_ids_sha256",
    "frozen_evaluation_source_boundary_sha256",
)
SPEECH_ACTS = (
    "REQUEST", "INFORM", "COMMIT", "APPROVE", "REJECT", "DELIVER",
    "PROPOSE", "REMIND", "SCHEDULE", "CANCEL", "RESCHEDULE",
)
PREDECLARED_MINIMUM_PER_CLASS = 20
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TrainingGateError(ValueError):
    """Raised when provenance, review, annotation, or count gates fail."""


class InsufficientTrainingExamples(TrainingGateError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("one or more classes are below the preregistered minimum")


@dataclass(frozen=True)
class AuthorizedExport:
    rows: tuple[dict[str, Any], ...]
    source_ids: tuple[str, ...]
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class PreparedExamples:
    scope_texts: tuple[str, ...]
    scope_targets: tuple[str, ...]
    speech_texts: tuple[str, ...]
    speech_targets: tuple[tuple[str, ...], ...]
    speech_history_quarantined_rows: int = 0


@dataclass(frozen=True)
class Preflight:
    prepared: PreparedExamples
    minimum_per_class: int
    counts: Mapping[str, Any]
    shortages: tuple[str, ...]
    supported_speech_acts: tuple[str, ...]
    unsupported_speech_acts: Mapping[str, str]

    @property
    def ready(self) -> bool:
        return not self.shortages

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_per_class": self.minimum_per_class,
            "scope_rows": len(self.prepared.scope_texts),
            "project_rows_for_speech_acts": len(self.prepared.speech_texts),
            "counts": dict(self.counts),
            "shortages": list(self.shortages),
            "supported_speech_acts": list(self.supported_speech_acts),
            "unsupported_speech_acts": dict(self.unsupported_speech_acts),
            "ready": self.ready,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def canonical_source_ids_sha256(source_ids: Sequence[str]) -> str:
    """Hash sorted native IDs using the review-export canonical JSON encoding."""
    canonical = json.dumps(
        sorted(source_ids), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(canonical)


def _read_json(path: Path, description: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingGateError(f"cannot read {description}: {path}") from exc


def _validate_hash(value: Any, field: str) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise TrainingGateError(f"cannot read accepted training export: {path}") from exc
    if text.startswith("\ufeff"):
        raise TrainingGateError("accepted training export must be UTF-8 without a BOM")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise TrainingGateError(f"accepted training export has a blank line at {line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TrainingGateError(f"invalid JSON at accepted export line {line_number}") from exc
        if not isinstance(row, dict):
            raise TrainingGateError(f"accepted export line {line_number} must be an object")
        rows.append(row)
    if not rows:
        raise TrainingGateError("accepted training export is empty")
    return tuple(rows)


def _check_authorization(auth: Any, manifest: Any) -> None:
    if not isinstance(auth, dict):
        raise TrainingGateError("training authorization must be an object")
    expected_keys = {
        "authorization_version", "issued_by", "training_permitted", "permitted_components",
        *AUTH_HASH_FIELDS,
    }
    if set(auth) != expected_keys:
        raise TrainingGateError("training authorization has missing or unknown keys")
    if auth.get("authorization_version") != AUTHORIZATION_VERSION:
        raise TrainingGateError("authorization_version is not 2-alpha")
    if auth.get("issued_by") != "orchestrator" or auth.get("training_permitted") is not True:
        raise TrainingGateError("training authorization is not an active orchestrator approval")
    components = auth.get("permitted_components")
    if not isinstance(components, list) or any(not isinstance(item, str) for item in components):
        raise TrainingGateError("permitted_components must be a string array")
    if not REQUIRED_COMPONENTS.issubset(components):
        raise TrainingGateError("authorization does not permit both preregistered baselines")
    if len(components) != len(set(components)):
        raise TrainingGateError("permitted_components contains duplicates")
    if not isinstance(manifest, dict):
        raise TrainingGateError("accepted training manifest must be an object")
    manifest_hash_field = {
        "index_sha256": "global_index_sha256",
        "accepted_source_ids_sha256": "accepted_source_ids_sha256",
        "accepted_annotation_file_sha256": "accepted_annotation_file_sha256",
    }
    for field in AUTH_HASH_FIELDS:
        if not _validate_hash(auth.get(field), field):
            raise TrainingGateError(f"authorization has an invalid SHA-256 field: {field}")
        if manifest.get(manifest_hash_field.get(field, field)) != auth[field]:
            raise TrainingGateError(f"authorization and accepted export manifest disagree: {field}")
    manifest_components = manifest.get("permitted_components")
    if (not isinstance(manifest_components, list)
            or any(not isinstance(item, str) for item in manifest_components)
            or set(manifest_components) != set(components)):
        raise TrainingGateError("authorization and accepted export manifest component lists disagree")
    if manifest.get("training_permitted") is not True or manifest.get("purpose") != "TRAIN":
        raise TrainingGateError("accepted export manifest does not authorize training")
    if manifest.get("frozen_evaluation_source_boundary_sha256") != manifest.get("partition_manifest_sha256"):
        raise TrainingGateError("frozen evaluation boundary is not the same bytes as the partition manifest")


def _source_message_text(row: Mapping[str, Any], *, include_subject: bool = True) -> str:
    sources = row.get("sources")
    source_id = row.get("current_source_id")
    current = sources.get(source_id) if isinstance(sources, Mapping) and isinstance(source_id, str) else None
    if not isinstance(current, Mapping):
        raise TrainingGateError("current source is missing from the row's sources map")
    subject = current.get("subject")
    message = current.get("current_message")
    if not isinstance(subject, str) or not isinstance(message, str):
        raise TrainingGateError("current source subject/current_message must be strings")
    if "subject" in row and row.get("subject") != subject:
        raise TrainingGateError("row subject differs from its current sources-map source")
    if "current_message" in row and row.get("current_message") != message:
        raise TrainingGateError("row current_message differs from its current sources-map source")
    authored_ranges = current.get("authored_ranges")
    if authored_ranges is None:
        authored = message
    else:
        if not isinstance(authored_ranges, list) or not authored_ranges:
            raise TrainingGateError("authored_ranges must be a non-empty list when present")
        parts: list[str] = []
        previous_end = 0
        for index, bounds in enumerate(authored_ranges):
            if not isinstance(bounds, Mapping) or set(bounds) != {"start", "end"}:
                raise TrainingGateError(f"authored_ranges[{index}] must contain only start/end")
            start, end = bounds.get("start"), bounds.get("end")
            if (not isinstance(start, int) or isinstance(start, bool)
                    or not isinstance(end, int) or isinstance(end, bool)
                    or start < previous_end or end <= start or end > len(message)):
                raise TrainingGateError(f"authored_ranges[{index}] has invalid offsets")
            parts.append(message[start:end])
            previous_end = end
        authored = " ".join(parts)
    return (f"{subject}\n{authored}" if include_subject else authored).strip()


def _unbounded_speech_history(row: Mapping[str, Any]) -> bool:
    """Known retained-history markers require explicit authored boundaries.

    This conservative screen is not a complete quoted-text parser. Scope may
    use contextual text; current-act targets must not supervise old requests.
    """
    current = row["sources"][row["current_source_id"]]
    if current.get("authored_ranges") is not None:
        return False  # offsets were validated by _source_message_text
    message = current["current_message"]
    return bool(re.search(
        r"(?im)^\s*(?:>\s*\S|[-_]{2,}\s*(?:original message|forwarded by|forwarded message)|"
        r"begin forwarded message:|on .+wrote:\s*$|from:\s*\S)", message))


def _has_uncertain_primitive_state(annotation: Mapping[str, Any]) -> bool:
    if annotation.get("project_scope", {}).get("value") == "UNCERTAIN":
        return True
    if any(item.get("category") == "UNCERTAIN" for item in annotation.get("actions", [])):
        return True
    if any(item.get("document_type") == "UNCERTAIN" or item.get("state") == "unknown"
           for item in annotation.get("documents", [])):
        return True
    if any(item.get("formality") == "UNCERTAIN" for item in annotation.get("approvals", [])):
        return True
    if any(item.get("prior_expectation") == "unknown" for item in annotation.get("thread_changes", [])):
        return True
    return any(item.get("target_formality") == "UNCERTAIN" for item in annotation.get("acts", []))


def _validate_reviewed_row(row: Any, index: int, registry: Mapping[str, Any]) -> dict[str, Any]:
    prefix = f"accepted row {index}"
    if not isinstance(row, dict):
        raise TrainingGateError(f"{prefix} must be an object")
    required = {
        "source_id", "current_source_id", "dataset_id", "source_partition", "leakage_group_id",
        "identity_complete", "partition_conflicts", "training_exclusions",
        "sources", "source_hashes", "source_index_id", "overlap_family", "annotation", "fyp_labels",
        "review_decision_sha256",
    }
    missing = required - row.keys()
    if missing:
        raise TrainingGateError(f"{prefix} missing fields: {sorted(missing)}")
    source_id = row.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip() or row.get("current_source_id") != source_id:
        raise TrainingGateError(f"{prefix} source_id/current_source_id mismatch")
    if row.get("source_partition") not in {"TRAIN", "TRAIN_SCREEN"}:
        raise TrainingGateError(f"{prefix} is not in a train partition")
    if row.get("identity_complete") is not True:
        raise TrainingGateError(f"{prefix} has incomplete identity")
    if row.get("partition_conflicts") != [] or row.get("training_exclusions") != []:
        raise TrainingGateError(f"{prefix} has partition conflicts or training exclusions")
    group = row.get("leakage_group_id")
    if not isinstance(group, str) or not group.strip():
        raise TrainingGateError(f"{prefix} lacks a leakage_group_id")
    if not _validate_hash(row.get("review_decision_sha256"), "review_decision_sha256"):
        raise TrainingGateError(f"{prefix} has invalid review_decision_sha256")
    dataset_id = row.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise TrainingGateError(f"{prefix} has invalid dataset_id")
    try:
        require_training_source(registry, dataset_id)
    except (ValueError, TypeError, KeyError) as exc:
        raise TrainingGateError(f"{prefix} dataset is not authorized for auxiliary training") from exc

    source_hashes = row.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise TrainingGateError(f"{prefix} source_hashes must be an object")
    sources = row.get("sources")
    if not isinstance(sources, Mapping) or not isinstance(sources.get(source_id), Mapping):
        raise TrainingGateError(f"{prefix} has no current source in sources")
    for sid, source in sources.items():
        if not isinstance(sid, str) or not isinstance(source, Mapping):
            raise TrainingGateError(f"{prefix} sources map is malformed")
        if not isinstance(source.get("subject"), str) or not isinstance(source.get("current_message"), str):
            raise TrainingGateError(f"{prefix} source {sid!r} lacks exact text fields")
    expected_source_hashes = {
        sid: canonical_json_sha256({"source_id": sid, **source})
        for sid, source in sources.items()
    }
    if dict(source_hashes) != expected_source_hashes:
        raise TrainingGateError(f"{prefix} source_hashes do not match the exact supplied source text/metadata")
    expected_index_id = source_id if source_id.startswith(dataset_id + ":") else f"{dataset_id}:{source_id}"
    if row.get("source_index_id") != expected_index_id:
        raise TrainingGateError(f"{prefix} source_index_id does not match dataset_id/source_id")
    if not isinstance(row.get("overlap_family"), str) or not row["overlap_family"]:
        raise TrainingGateError(f"{prefix} lacks an overlap_family")
    _source_message_text(row)
    annotation = row.get("annotation")
    validation = validate_annotation(
        annotation,
        current_source_id=source_id,
        sources=sources,
    )
    if not validation.valid:
        raise TrainingGateError(f"{prefix} structured annotation invalid: {'; '.join(validation.errors)}")
    if annotation.get("needs_review") is not False or annotation.get("uncertainty_reasons") != []:
        raise TrainingGateError(f"{prefix} is marked for review or has uncertainty reasons")
    if annotation.get("project_scope", {}).get("confidence") != "supported":
        raise TrainingGateError(f"{prefix} has unsupported scope confidence")
    if annotation.get("project_scope", {}).get("value") not in {"PROJECT", "NON_PROJECT"}:
        raise TrainingGateError(f"{prefix} has uncertain scope")
    if _has_uncertain_primitive_state(annotation):
        raise TrainingGateError(f"{prefix} contains uncertain/unknown primitive states")
    for collection in (
        "actors", "actions", "documents", "departments", "temporal_entities", "meetings",
        "deadlines", "approvals", "status_updates", "thread_changes", "acts",
    ):
        if any(item.get("confidence") != "supported" for item in annotation[collection]):
            raise TrainingGateError(f"{prefix} collection {collection} contains unsupported confidence")
    mapped = map_labels(annotation, current_source_id=source_id, sources=sources)
    if mapped.needs_review:
        raise TrainingGateError(f"{prefix} maps to a review-required result")
    if row.get("fyp_labels") != list(mapped.labels):
        raise TrainingGateError(f"{prefix} fyp_labels do not equal the deterministic mapper output")
    return row


def load_authorized_training_export(
    accepted_train_path: str | Path,
    authorization_path: str | Path,
    registry_path: str | Path,
) -> AuthorizedExport:
    """Load and validate only the orchestrator-authorized training export."""
    export_path = Path(accepted_train_path)
    auth_path = Path(authorization_path)
    manifest_path = export_path.with_name(export_path.name + ".manifest.json")
    if export_path.name != "accepted_train.jsonl":
        raise TrainingGateError("input must be named accepted_train.jsonl; review handoffs are not training data")
    review_root = (Path(__file__).resolve().parents[1] / "data" / "structured_review").resolve()
    if not export_path.resolve().is_relative_to(review_root):
        raise TrainingGateError("accepted training export must reside below ai/data/structured_review/")
    if not export_path.is_file() or not auth_path.is_file() or not manifest_path.is_file():
        raise TrainingGateError("accepted export, explicit authorization, or colocated manifest is missing")
    if auth_path.parent.resolve() != export_path.parent.resolve():
        raise TrainingGateError("training authorization must be colocated with accepted_train.jsonl")

    # Rebuild the complete review-to-export trust chain before trusting any
    # authorization or sidecar fields. This checks the run, independent A/B/C
    # review artifacts, immutable decision record, source and identity hashes,
    # partition/index isolation, protected membership, frozen boundary bytes,
    # canonical registry, and the bytes copied into the TRAIN export.
    from src.structured_annotation import workflow

    repo_root = Path(__file__).resolve().parents[2]
    try:
        provenance = workflow.verify_accepted_train_provenance(
            export_path,
            auth_path,
            registry_path,
            root=repo_root,
        )
    except Exception as exc:
        raise TrainingGateError(f"workflow provenance verification failed: {exc}") from exc
    if not isinstance(provenance, Mapping):
        raise TrainingGateError("workflow provenance verifier returned an invalid result")
    verified_rows = provenance.get("rows")
    verified_manifest = provenance.get("manifest")
    if not isinstance(verified_rows, list) or not isinstance(verified_manifest, Mapping):
        raise TrainingGateError("workflow provenance verifier omitted verified rows or manifest")

    auth = _read_json(auth_path, "training authorization")
    manifest = _read_json(manifest_path, "accepted training export manifest")
    if dict(manifest) != dict(verified_manifest):
        raise TrainingGateError("accepted export manifest differs from workflow-reverified provenance")
    _check_authorization(auth, manifest)
    if manifest.get("authorization_sha256") != sha256_bytes(auth_path.read_bytes()):
        raise TrainingGateError("accepted export manifest is not bound to the explicit authorization bytes")

    try:
        registry_bytes = Path(registry_path).read_bytes()
    except OSError as exc:
        raise TrainingGateError("cannot read the canonical dataset registry") from exc
    if sha256_bytes(registry_bytes) != auth["dataset_registry_sha256"]:
        raise TrainingGateError("dataset registry bytes do not match the orchestrator authorization")
    try:
        registry = json.loads(registry_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingGateError("canonical dataset registry is invalid JSON") from exc
    if not isinstance(registry, Mapping):
        raise TrainingGateError("canonical dataset registry must be a JSON object")

    rows = _read_jsonl(export_path)
    if list(rows) != verified_rows:
        raise TrainingGateError("accepted export rows differ from workflow-reverified source/decision/index records")
    export_sha256 = sha256_bytes(export_path.read_bytes())
    if export_sha256 != auth["accepted_annotation_file_sha256"] or export_sha256 != manifest.get("output_sha256"):
        raise TrainingGateError("accepted training export bytes do not match the orchestrator authorization")
    source_ids: list[str] = []
    validated_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        validated = _validate_reviewed_row(row, index, registry)
        source_ids.append(validated["source_id"])
        validated_rows.append(validated)
    if len(source_ids) != len(set(source_ids)):
        raise TrainingGateError("accepted export repeats a source_id")
    if canonical_source_ids_sha256(source_ids) != auth["accepted_source_ids_sha256"]:
        raise TrainingGateError("accepted native source IDs do not match the authorized sorted-ID digest")
    if manifest.get("count") != len(validated_rows):
        raise TrainingGateError("accepted export row count disagrees with its manifest")
    return AuthorizedExport(tuple(validated_rows), tuple(sorted(source_ids)), manifest)


def prepare_training_examples(rows: Sequence[Mapping[str, Any]]) -> PreparedExamples:
    """Prepare targets; repeated normalized inputs cannot inflate support."""
    scope_texts: list[str] = []
    scope_targets: list[str] = []
    speech_texts: list[str] = []
    speech_targets: list[tuple[str, ...]] = []
    speech_history_quarantined_rows = 0
    seen_inputs: dict[str, tuple[str, tuple[str, ...]]] = {}
    seen_speech_inputs: dict[str, tuple[str, ...]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TrainingGateError(f"row {index} must be an object")
        annotation = row.get("annotation")
        if not isinstance(annotation, Mapping) or not isinstance(annotation.get("project_scope"), Mapping):
            raise TrainingGateError(f"row {index} lacks a project_scope annotation")
        scope = annotation["project_scope"].get("value")
        if scope not in {"PROJECT", "NON_PROJECT"}:
            raise TrainingGateError(f"row {index} has unsupported project scope")
        text = _source_message_text(row)
        labels: set[str] = set()
        if scope == "PROJECT":
            acts = annotation.get("acts")
            if not isinstance(acts, list):
                raise TrainingGateError(f"row {index} acts must be an array")
            for act in acts:
                if not isinstance(act, Mapping) or act.get("speech_act") not in SPEECH_ACTS:
                    raise TrainingGateError(f"row {index} has malformed speech-act target")
                labels.add(act["speech_act"])
        target = (scope, tuple(label for label in SPEECH_ACTS if label in labels))
        input_key = " ".join(text.split())
        if input_key in seen_inputs:
            if seen_inputs[input_key] != target:
                raise TrainingGateError("identical normalized training inputs have conflicting primitive targets")
            continue
        seen_inputs[input_key] = target
        scope_texts.append(text)
        scope_targets.append(scope)
        if scope == "PROJECT":
            if _unbounded_speech_history(row):
                speech_history_quarantined_rows += 1
            else:
                # Thread subjects can retain an earlier request. Current-act
                # features use authored body text only, counted independently
                # of subjects so subject variants cannot inflate head support.
                speech_text = _source_message_text(row, include_subject=False)
                speech_key = " ".join(speech_text.split())
                if speech_key in seen_speech_inputs:
                    if seen_speech_inputs[speech_key] != target[1]:
                        raise TrainingGateError("identical normalized speech inputs have conflicting primitive targets")
                    continue
                seen_speech_inputs[speech_key] = target[1]
                speech_texts.append(speech_text)
                speech_targets.append(target[1])
    return PreparedExamples(tuple(scope_texts), tuple(scope_targets), tuple(speech_texts), tuple(speech_targets),
                            speech_history_quarantined_rows)


def count_and_check_classes(prepared: PreparedExamples, minimum_per_class: int) -> Preflight:
    if not isinstance(minimum_per_class, int) or isinstance(minimum_per_class, bool):
        raise TrainingGateError("minimum_per_class must be an integer")
    if minimum_per_class < PREDECLARED_MINIMUM_PER_CLASS:
        raise TrainingGateError(
            f"minimum_per_class cannot relax the preregistered floor of {PREDECLARED_MINIMUM_PER_CLASS}"
        )
    scope_counts = {
        label: prepared.scope_targets.count(label) for label in ("PROJECT", "NON_PROJECT")
    }
    act_counts: dict[str, dict[str, int]] = {}
    for label in SPEECH_ACTS:
        positive = sum(label in row for row in prepared.speech_targets)
        act_counts[label] = {"positive": positive, "negative": len(prepared.speech_targets) - positive}
    shortages = [
        f"scope:{label}={count}<{minimum_per_class}"
        for label, count in scope_counts.items() if count < minimum_per_class
    ]
    supported_speech_acts: list[str] = []
    unsupported_speech_acts: dict[str, str] = {}
    for label, counts in act_counts.items():
        lacking = [
            f"{polarity}={counts[polarity]}<{minimum_per_class}"
            for polarity in ("positive", "negative")
            if counts[polarity] < minimum_per_class
        ]
        if lacking:
            unsupported_speech_acts[label] = "; ".join(lacking)
        else:
            supported_speech_acts.append(label)
    return Preflight(
        prepared=prepared,
        minimum_per_class=minimum_per_class,
        counts={
            "scope": scope_counts,
            "speech_act_project_rows": len(prepared.speech_texts),
            "speech_history_quarantined_rows": prepared.speech_history_quarantined_rows,
            "speech_acts": act_counts,
        },
        shortages=tuple(shortages),
        supported_speech_acts=tuple(supported_speech_acts),
        unsupported_speech_acts=unsupported_speech_acts,
    )


def fit_and_save_baselines(
    authorized_export: AuthorizedExport,
    preflight: Preflight,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Fit the preregistered models and save artifacts only under ai/data/."""
    if not isinstance(authorized_export, AuthorizedExport):
        raise TrainingGateError("fit requires a provenance-validated AuthorizedExport")
    if not isinstance(authorized_export.manifest, Mapping) or authorized_export.manifest.get("training_permitted") is not True:
        raise TrainingGateError("fit requires the accepted export's active training manifest")
    if preflight.prepared != prepare_training_examples(authorized_export.rows):
        raise TrainingGateError("preflight features/targets do not match the authorized export")
    if not preflight.ready:
        raise InsufficientTrainingExamples(preflight.to_dict())
    out = Path(output_dir).resolve()
    ai_root = Path(__file__).resolve().parents[1]
    data_root = (ai_root / "data").resolve()
    if data_root not in out.parents:
        raise TrainingGateError("model artifacts must be written below ai/data/")

    from joblib import dump
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier

    out.mkdir(parents=True, exist_ok=False)
    vectorizer = TfidfVectorizer(
        analyzer="word", lowercase=True, ngram_range=(1, 1), token_pattern=r"(?u)\b\w\w+\b"
    )
    scope_matrix = vectorizer.fit_transform(preflight.prepared.scope_texts)
    scope_model = LogisticRegression(max_iter=1000, random_state=0)
    scope_model.fit(scope_matrix, preflight.prepared.scope_targets)
    dump({"vectorizer": vectorizer, "classifier": scope_model}, out / "scope_baseline.joblib")

    if preflight.supported_speech_acts:
        speech_vectorizer = TfidfVectorizer(
            analyzer="word", lowercase=True, ngram_range=(1, 1), token_pattern=r"(?u)\b\w\w+\b"
        )
        speech_matrix = speech_vectorizer.fit_transform(preflight.prepared.speech_texts)
        try:
            import numpy as np
            target_matrix = np.asarray([
                [int(label in labels) for label in preflight.supported_speech_acts]
                for labels in preflight.prepared.speech_targets
            ], dtype=int)
        except ImportError as exc:  # sklearn depends on numpy; keep the failure explicit.
            raise TrainingGateError("numpy is required by the installed scikit-learn runtime") from exc
        speech_model = OneVsRestClassifier(LogisticRegression(max_iter=1000, random_state=0))
        speech_model.fit(speech_matrix, target_matrix)
        dump({
            "vectorizer": speech_vectorizer,
            "classifier": speech_model,
            "classes": list(preflight.supported_speech_acts),
        }, out / "speech_act_baseline.joblib")
    model_paths = [out / "scope_baseline.joblib"]
    if preflight.supported_speech_acts:
        model_paths.append(out / "speech_act_baseline.joblib")
    provenance_fields = (
        "run_manifest_sha256", "decision_manifest_sha256", "source_manifest_sha256",
        "global_index_sha256", "partition_manifest_sha256",
        "frozen_evaluation_source_boundary_sha256", "dataset_registry_sha256",
        "authorization_sha256", "accepted_annotation_file_sha256",
        "accepted_source_ids_sha256", "output_sha256",
    )
    provenance_hashes = {
        field: authorized_export.manifest[field]
        for field in provenance_fields
        if isinstance(authorized_export.manifest.get(field), str)
    }
    metadata = {
        "model_version": "structured-baselines-2-alpha",
        "training_code_sha256": sha256_file(Path(__file__)),
        "features": "word-level TF-IDF unigram",
        "classifier": "LogisticRegression; OneVsRest for speech acts",
        "training_source_partition": "TRAIN_SCREEN only",
        "evaluation_performed": False,
        "minimum_per_class": preflight.minimum_per_class,
        "training_rows": len(preflight.prepared.scope_texts),
        "authorized_export_rows": len(authorized_export.rows),
        "duplicate_input_policy": "scope: unique normalized subject/body; speech: unique normalized authored body; conflicting targets fail closed",
        "speech_act_rows": len(preflight.prepared.speech_texts),
        "speech_history_policy": "body-only features; exclude known retained-history markers without explicit authored_ranges; heuristic is not exhaustive",
        "trained_speech_acts": list(preflight.supported_speech_acts),
        "untrained_speech_acts": dict(preflight.unsupported_speech_acts),
        "class_counts": dict(preflight.counts),
        "models_trained": 1 + int(bool(preflight.supported_speech_acts)),
        "provenance_hashes": provenance_hashes,
        "model_artifact_sha256": {
            path.name: sha256_file(path) for path in model_paths
        },
    }
    (out / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def preflight_authorized_export(
    accepted_train_path: str | Path,
    authorization_path: str | Path,
    registry_path: str | Path,
    *,
    minimum_per_class: int = PREDECLARED_MINIMUM_PER_CLASS,
) -> tuple[AuthorizedExport, Preflight]:
    export = load_authorized_training_export(accepted_train_path, authorization_path, registry_path)
    prepared = prepare_training_examples(export.rows)
    return export, count_and_check_classes(prepared, minimum_per_class)
