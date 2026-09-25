"""Seed loading, validation, and durable canonical annotation storage."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.annotation.label_studio import (
    python_to_utf16_offset,
    utf16_to_python_offset,
)
from src.datasets.schemas import LABELS, SPAN_LABELS
from src.datasets.validation import validate_record


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEED_PATH = (
    PROJECT_ROOT
    / "ai"
    / "data"
    / "annotated"
    / "human"
    / "label_studio_seed"
    / "reviewer_a_tasks.json"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "ai" / "data" / "annotated" / "human" / "simple_annotator"
)
LABEL_SCHEMA_PATH = PROJECT_ROOT / "ai" / "annotation" / "label_schema.json"
SPAN_FIELDS = frozenset({"subject", "current_message"})
REVIEWER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FRIENDLY_NAMES = {
    "MEETING": "Meeting",
    "DEADLINE": "Deadline",
    "REPORT_REQUEST": "Report / Document Request",
    "DEPARTMENTAL_INPUT": "Departmental Input",
    "ACTION_REQUEST": "Task / Action Request",
    "FOLLOW_UP": "Follow-up",
    "APPROVAL": "Approval",
    "GENERAL_UPDATE": "Project Update",
    "NON_PROJECT": "Not Project Related",
    "MEETING_DATE": "Meeting Date",
    "MEETING_TIME": "Meeting Time",
    "DEADLINE_DATE": "Deadline Date",
    "DEADLINE_TIME": "Deadline Time",
    "PARTICIPANT": "Meeting Participant",
    "RESPONSIBLE_PARTY": "Person Responsible",
    "DEPARTMENT": "Department",
    "AGENDA": "Meeting Agenda",
    "ACTION_ITEM": "Action / Task",
    "REQUESTED_DOCUMENT": "Requested Document",
    "PROJECT": "Project Name",
}


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except OSError as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _labels_from_schema() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    schema = _read_json(LABEL_SCHEMA_PATH)
    try:
        groups = (
            (schema["classification"]["labels"], LABELS),
            (schema["extraction"]["span_labels"], SPAN_LABELS),
        )
        inventories: list[list[dict[str, str]]] = []
        for rows, allowed in groups:
            if not isinstance(rows, list):
                raise ValueError("label schema inventories must be lists")
            inventory = []
            for row in rows:
                key, definition = row.get("name"), row.get("definition")
                if key not in allowed or not isinstance(definition, str):
                    raise ValueError("label schema does not match the canonical label inventory")
                inventory.append({
                    "key": key,
                    "name": FRIENDLY_NAMES.get(key, key.replace("_", " ").title()),
                    "definition": definition,
                })
            if {item["key"] for item in inventory} != set(allowed):
                raise ValueError("label schema is missing canonical labels")
            inventories.append(inventory)
        return inventories[0], inventories[1]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"label schema is malformed: {exc}") from exc


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Lock across app instances/processes while a reviewer file is updated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class AnnotationStore:
    """Own one reviewer's immutable seed and mutable canonical annotations."""

    def __init__(
        self,
        reviewer: str,
        *,
        limit: int | None = None,
        seed_path: str | Path = DEFAULT_SEED_PATH,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    ) -> None:
        if not isinstance(reviewer, str) or not REVIEWER_PATTERN.fullmatch(reviewer):
            raise ValueError(
                "reviewer must be 1-64 safe filename characters "
                "(letters, digits, dot, underscore, or hyphen)"
            )
        if reviewer in {".", ".."}:
            raise ValueError("reviewer is not a safe filename")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("limit must be a positive integer")

        self.reviewer = reviewer
        self.seed_path = Path(seed_path).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.manifest_path = self.seed_path.parent / "manifest.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.output_path = self.output_dir / f"{reviewer}.jsonl"
        self.draft_path = self.output_dir / f"{reviewer}.drafts.json"
        self.lock_path = self.output_dir / f".{reviewer}.lock"
        self._thread_lock = threading.RLock()
        self._seed_records, self.seed_ids = self._load_seed()
        self.seed_count = len(self.seed_ids)
        self.active_limit = min(limit or self.seed_count, self.seed_count)
        self.classification_labels, self.span_labels = _labels_from_schema()
        self.records = [self._reviewer_baseline(row) for row in self._seed_records]
        self.draft_spans: list[list[dict[str, Any]]] = [[] for _ in range(self.seed_count)]
        self._reload_existing_output()
        self._reload_drafts()

    def _load_seed(self) -> tuple[list[dict[str, Any]], list[str]]:
        manifest = _read_json(self.manifest_path)
        if self.seed_path.suffix.lower() == ".jsonl":
            try:
                with self.seed_path.open("r", encoding="utf-8") as stream:
                    tasks = [json.loads(line) for line in stream if line.strip()]
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"could not read canonical seed JSONL: {exc}") from exc
            direct_canonical_records = True
        else:
            tasks = _read_json(self.seed_path)
            direct_canonical_records = False
        if not isinstance(manifest, dict):
            raise ValueError("seed manifest must be a JSON object")
        self.batch_name = str(manifest.get("display_name") or "Email review batch")[:80]
        expected_count = manifest.get("selected_email_count", manifest.get("requested_count"))
        if type(expected_count) is not int or expected_count < 1:
            raise ValueError("seed manifest must declare a positive selected_email_count")
        if not isinstance(tasks, list) or len(tasks) != expected_count:
            raise ValueError(f"seed must contain exactly {expected_count} rows")
        selected_ids = manifest.get("selected_email_ids")
        if (not isinstance(selected_ids, list) or len(selected_ids) != expected_count
                or any(not isinstance(value, str) or not value for value in selected_ids)
                or len(set(selected_ids)) != expected_count):
            raise ValueError(f"seed manifest must list {expected_count} unique selected_email_ids")
        expected_source = manifest.get("source_dataset")
        if expected_source not in {"enron", "manual"}:
            raise ValueError("seed manifest source_dataset must be enron or manual")

        records: list[dict[str, Any]] = []
        task_ids: list[str] = []
        for number, task in enumerate(tasks, 1):
            if direct_canonical_records:
                record = task
                data = task
            else:
                if not isinstance(task, dict) or not isinstance(task.get("data"), dict):
                    raise ValueError(f"seed task {number} must contain a data object")
                data = task["data"]
                encoded = data.get("canonical_record_json")
                if not isinstance(encoded, str):
                    raise ValueError(f"seed task {number} is missing canonical_record_json")
                try:
                    record = json.loads(encoded)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"seed task {number} has invalid canonical_record_json"
                    ) from exc
            if not isinstance(record, dict):
                raise ValueError(f"seed task {number} canonical record must be an object")
            email_id = record.get("email_id")
            if not isinstance(email_id, str) or data.get("email_id") != email_id:
                raise ValueError(f"seed task {number} email_id does not match its canonical record")
            if record.get("source_dataset") != expected_source:
                raise ValueError(f"seed task {number} source_dataset does not match manifest")
            if record.get("labels") != [] or record.get("spans") != []:
                raise ValueError(f"seed task {number} must start with blank labels and spans")
            annotation = record.get("annotation")
            if not isinstance(annotation, dict) or annotation.get("status") != "unlabelled":
                raise ValueError(f"seed task {number} must start unlabelled")
            errors = validate_record(record)
            if errors:
                raise ValueError(
                    f"seed task {number} is not canonical: {'; '.join(errors)}"
                )
            records.append(record)
            task_ids.append(email_id)

        if task_ids != selected_ids:
            raise ValueError("seed task ID order does not match manifest selected_email_ids")
        return records, task_ids

    def _reviewer_baseline(self, record: dict[str, Any]) -> dict[str, Any]:
        copy_record = copy.deepcopy(record)
        copy_record["labels"] = []
        copy_record["spans"] = []
        copy_record["annotation"] = {
            "status": "unlabelled",
            "annotator": self.reviewer,
            "annotation_source": "human",
            "confidence": None,
            "needs_review": False,
        }
        return copy_record

    def _read_existing_output(self) -> list[dict[str, Any]] | None:
        if not self.output_path.exists():
            return None
        rows: list[dict[str, Any]] = []
        try:
            with self.output_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError(f"output line {line_number} must be a JSON object")
                    rows.append(row)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read existing reviewer output: {exc}") from exc
        if len(rows) != self.seed_count:
            raise ValueError(f"existing output must contain exactly {self.seed_count} rows")
        ids = [row.get("email_id") for row in rows]
        if ids != self.seed_ids:
            raise ValueError("existing output ID order does not match the seed")

        for index, (row, baseline) in enumerate(zip(rows, self._seed_records)):
            if set(row) != set(baseline):
                raise ValueError(f"existing output row {index} changes canonical record fields")
            immutable_fields = set(baseline) - {"labels", "spans", "annotation"}
            for field in immutable_fields:
                if row.get(field) != baseline.get(field):
                    raise ValueError(
                        f"existing output row {index} modified source field {field}"
                    )
            annotation = row.get("annotation")
            if not isinstance(annotation, dict):
                raise ValueError(f"existing output row {index} has invalid annotation")
            if (annotation.get("annotator") != self.reviewer
                    or annotation.get("annotation_source") != "human"):
                raise ValueError(
                    f"existing output row {index} does not belong to reviewer {self.reviewer}"
                )
            if row.get("source_dataset") != baseline.get("source_dataset") or annotation.get("status") == "gold":
                raise ValueError(f"existing output row {index} violates the seed source contract")
            errors = validate_record(row)
            if errors:
                raise ValueError(
                    f"existing output row {index} is not canonical: {'; '.join(errors)}"
                )
        return rows

    def _reload_existing_output(self) -> None:
        existing = self._read_existing_output()
        if existing is not None:
            self.records = existing

    @staticmethod
    def _is_completed(record: dict[str, Any]) -> bool:
        annotation = record.get("annotation", {})
        return (
            annotation.get("status") == "human_reviewed"
            or annotation.get("needs_review") is True
        )

    def _progress(self) -> dict[str, int | None]:
        active = self.records[: self.active_limit]
        completed = sum(self._is_completed(row) for row in active)
        first_unfinished = next(
            (index for index, row in enumerate(active) if not self._is_completed(row)),
            None,
        )
        return {"completed": completed, "first_unfinished": first_unfinished}

    def state(self) -> dict[str, Any]:
        progress = self._progress()
        return {
            "reviewer": self.reviewer,
            "batch_name": self.batch_name,
            "total": self.active_limit,
            "completed": progress["completed"],
            "first_unfinished": progress["first_unfinished"],
            "limit": self.active_limit,
            "labels": copy.deepcopy(self.classification_labels),
            "span_labels": copy.deepcopy(self.span_labels),
        }

    def get_email(self, index: int) -> dict[str, Any]:
        if type(index) is not int or not 0 <= index < self.active_limit:
            raise IndexError("email index is outside the active review limit")
        record = self.records[index]
        annotation = record["annotation"]
        source_fields = (
            "subject", "current_message", "clean_body", "thread_context", "sender",
            "recipients", "cc", "sent_at", "attachment_names", "thread_id", "turn_index",
        )
        source = {key: copy.deepcopy(record.get(key)) for key in source_fields}
        spans = []
        visible_spans = record["spans"]
        if (not self._is_completed(record)
                and annotation.get("needs_review") is not True):
            visible_spans = self.draft_spans[index]
        for span in visible_spans:
            field = span.get("field", "current_message")
            text = record[field]
            spans.append({
                "field": field,
                "start": python_to_utf16_offset(text, span["start"]),
                "end": python_to_utf16_offset(text, span["end"]),
                "text": span["text"],
                "label": span["label"],
            })
        return {
            "index": index,
            "email_id": record["email_id"],
            "source": source,
            "metadata": {
                key: copy.deepcopy(record.get(key))
                for key in ("sender", "recipients", "cc", "sent_at", "attachment_names")
            },
            "labels": list(record["labels"]),
            "spans": spans,
            "needs_review": annotation.get("needs_review") is True,
            "note": annotation.get("ambiguity_note", ""),
            "completed": self._is_completed(record),
        }

    def _validate_labels(self, labels: Any) -> list[str]:
        if not isinstance(labels, list):
            raise ValueError("labels must be a list")
        if any(not isinstance(label, str) or label not in LABELS for label in labels):
            raise ValueError("labels contains an unknown classification label")
        if len(labels) != len(set(labels)):
            raise ValueError("labels contains duplicates")
        if "NON_PROJECT" in labels and len(labels) > 1:
            raise ValueError("NON_PROJECT cannot be combined with project labels")
        return list(labels)

    def _validate_spans(self, index: int, spans: Any) -> list[dict[str, Any]]:
        if not isinstance(spans, list):
            raise ValueError("spans must be a list")
        record = self.records[index]
        canonical: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int, str]] = set()
        for position, span in enumerate(spans):
            if not isinstance(span, dict):
                raise ValueError(f"span {position} must be an object")
            field = span.get("field")
            if not isinstance(field, str) or field not in SPAN_FIELDS:
                raise ValueError(f"span {position} has an invalid field")
            label = span.get("label")
            if not isinstance(label, str) or label not in SPAN_LABELS:
                raise ValueError(f"span {position} has an invalid label")
            start16, end16 = span.get("start"), span.get("end")
            if type(start16) is not int or type(end16) is not int:
                raise ValueError(f"span {position} offsets must be integers")
            text = span.get("text")
            if not isinstance(text, str):
                raise ValueError(f"span {position} text must be a string")
            source_text = record[field]
            try:
                start = utf16_to_python_offset(source_text, start16)
                end = utf16_to_python_offset(source_text, end16)
            except ValueError as exc:
                raise ValueError(f"span {position} has invalid UTF-16 offsets: {exc}") from exc
            if end <= start:
                raise ValueError(f"span {position} must have a nonempty range")
            if source_text[start:end] != text:
                raise ValueError(f"span {position} text does not match its source range")
            key = (field, start, end, label)
            if key in seen:
                raise ValueError(f"span {position} duplicates another canonical span")
            seen.add(key)
            canonical.append({
                "field": field,
                "start": start,
                "end": end,
                "text": text,
                "label": label,
            })
        return canonical

    def save(self, index: int, payload: Any) -> dict[str, Any]:
        if type(index) is not int or not 0 <= index < self.active_limit:
            raise IndexError("email index is outside the active review limit")
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        required = {"labels", "spans", "needs_review", "note"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"request is missing fields: {', '.join(sorted(missing))}")
        needs_review = payload["needs_review"]
        if type(needs_review) is not bool:
            raise ValueError("needs_review must be a boolean")
        note = payload["note"]
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        if len(note) > 5000:
            raise ValueError("note must be 5000 characters or fewer")
        labels = self._validate_labels(payload["labels"])
        spans = self._validate_spans(index, payload["spans"])

        if needs_review:
            labels = []
            spans = []
            status = "unlabelled"
            draft_spans: list[dict[str, Any]] = []
        elif labels:
            status = "human_reviewed"
            draft_spans = []
        else:
            status = "unlabelled"
            draft_spans = spans

        with self._thread_lock, _exclusive_file_lock(self.lock_path):
            self._reload_existing_output()
            self._reload_drafts()
            updated = copy.deepcopy(self.records[index])
            updated["labels"] = labels
            updated["spans"] = spans if labels else []
            self.draft_spans[index] = copy.deepcopy(draft_spans)
            annotation = {
                "status": status,
                "annotator": self.reviewer,
                "annotation_source": "human",
                "confidence": None,
                "needs_review": needs_review,
            }
            if note:
                annotation["ambiguity_note"] = note
            updated["annotation"] = annotation
            errors = validate_record(updated)
            if errors:
                raise ValueError(f"annotation is invalid: {'; '.join(errors)}")
            self.records[index] = updated

            # Every reviewer file is full length and ordered like the seed, including
            # unresolved records, so compare_annotations.py can consume it directly.
            for row in self.records:
                row_errors = validate_record(row)
                if row_errors:
                    raise ValueError(
                        f"output row {row['email_id']} is invalid: {'; '.join(row_errors)}"
                    )
            self._atomic_write()
            self._atomic_write_drafts()

        result = self._progress()
        return {
            "ok": True,
            "record_completed": self._is_completed(self.records[index]),
            **result,
        }

    def _reload_drafts(self) -> None:
        self.draft_spans = [[] for _ in range(self.seed_count)]
        if not self.draft_path.exists():
            return
        draft_data = _read_json(self.draft_path)
        if not isinstance(draft_data, dict):
            raise ValueError("reviewer draft file must contain a JSON object")
        if draft_data.get("reviewer") != self.reviewer:
            raise ValueError("reviewer draft file belongs to a different reviewer")
        if draft_data.get("email_ids") != self.seed_ids:
            raise ValueError("reviewer draft IDs do not match the seed")
        rows = draft_data.get("spans")
        if not isinstance(rows, list) or len(rows) != self.seed_count:
            raise ValueError(f"reviewer draft file must contain {self.seed_count} span lists")
        for index, spans in enumerate(rows):
            if not isinstance(spans, list):
                raise ValueError(f"reviewer draft row {index} must contain a span list")
            canonical: list[dict[str, Any]] = []
            seen: set[tuple[str, int, int, str]] = set()
            for position, span in enumerate(spans):
                if not isinstance(span, dict):
                    raise ValueError(f"reviewer draft span {index}:{position} must be an object")
                field, label = span.get("field"), span.get("label")
                start, end, text = span.get("start"), span.get("end"), span.get("text")
                if not isinstance(field, str) or field not in SPAN_FIELDS:
                    raise ValueError(f"reviewer draft span {index}:{position} has invalid field")
                if not isinstance(label, str) or label not in SPAN_LABELS:
                    raise ValueError(f"reviewer draft span {index}:{position} has invalid label")
                if (type(start) is not int or type(end) is not int or end <= start
                        or not isinstance(text, str)):
                    raise ValueError(f"reviewer draft span {index}:{position} has invalid range")
                source_text = self._seed_records[index][field]
                if end > len(source_text) or source_text[start:end] != text:
                    raise ValueError(f"reviewer draft span {index}:{position} text mismatch")
                key = (field, start, end, label)
                if key in seen:
                    raise ValueError(f"reviewer draft span {index}:{position} is duplicated")
                seen.add(key)
                canonical.append({
                    "field": field, "start": start, "end": end,
                    "text": text, "label": label,
                })
            record = self.records[index]
            if (not self._is_completed(record)
                    and record["annotation"].get("needs_review") is not True):
                self.draft_spans[index] = canonical

    def _atomic_write_drafts(self) -> None:
        payload = {
            "version": 1,
            "reviewer": self.reviewer,
            "email_ids": self.seed_ids,
            "spans": self.draft_spans,
        }
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        self._atomic_replace_text(self.draft_path, serialized)

    def _atomic_write(self) -> None:
        serialized = "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in self.records
        )
        self._atomic_replace_text(self.output_path, serialized)

    def _atomic_replace_text(self, target: Path, contents: str) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{self.reviewer}.",
                suffix=".tmp",
                dir=self.output_dir,
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target)
            temp_path = None
            if os.name != "nt":
                directory_fd = os.open(self.output_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
