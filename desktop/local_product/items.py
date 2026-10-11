"""Reviewed, source-bound project item ledger stored beside the email archive."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any

from .item_contracts import validate_fields


PRODUCT_SCHEMA_VERSION = 1
_CANDIDATE_NAMESPACE = uuid.UUID("3baf0dfc-8619-4c0a-a1af-83e12c6bb2fd")
_TERMINAL = {"APPROVED", "CORRECTED", "REJECTED", "STALE"}


class ConflictError(RuntimeError):
    """A candidate, source, or item changed since the caller reviewed it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load(value: str | None, fallback: Any) -> Any:
    return fallback if value is None else json.loads(value)


def _proposal_key(value: dict[str, Any]) -> str:
    encoded = _json(value).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


def _version(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _note(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("note must be a string of at most 2000 characters")
    return value


def _evidence(value: Any, current_message: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"field", "start", "end", "text"}:
        raise ValueError("evidence must contain field, start, end, and text only")
    start, end, text = value["start"], value["end"], value["text"]
    if value["field"] != "current_message":
        raise ValueError("evidence field must be current_message")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end <= start
        or end > len(current_message)
    ):
        raise ValueError("evidence offsets are outside current_message")
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError("evidence text must be nonempty and bounded")
    if current_message[start:end] != text:
        raise ValueError("evidence text must exactly match current_message at the supplied offsets")
    return {"field": "current_message", "start": start, "end": end, "text": text}


def _source_binding(source: dict[str, Any]) -> dict[str, Any]:
    source_id = source.get("source_id")
    fingerprint = source.get("input_fingerprint")
    revision = source.get("source_revision")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("Canonical source record has no source_id")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("Canonical source record has no input_fingerprint")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("Canonical source record has no valid source_revision")
    return {"source_id": source_id, "input_fingerprint": fingerprint, "source_revision": revision}


class ItemLedger:
    """Persist reviewed product items without changing the archive's schema version."""

    def __init__(self, store: Any) -> None:
        if not callable(getattr(store, "get_email", None)) or not callable(getattr(store, "_connect", None)):
            raise TypeError("ItemLedger requires an EmailStore-compatible instance")
        self.store = store
        self._initialize()

    def _initialize(self) -> None:
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS product_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT NOT NULL)"
                )
                version_row = connection.execute(
                    "SELECT meta_value FROM product_meta WHERE meta_key='schema_version'"
                ).fetchone()
                version = int(version_row[0]) if version_row else 0
                if version > PRODUCT_SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Product schema version {version} is newer than this app supports "
                        f"({PRODUCT_SCHEMA_VERSION})."
                    )
                self._create_schema(connection)
                connection.execute(
                    "INSERT INTO product_meta(meta_key, meta_value) VALUES ('schema_version', ?) "
                    "ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value",
                    (str(PRODUCT_SCHEMA_VERSION),),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                fields_json TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                source_revision INTEGER NOT NULL,
                created_from_candidate_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS item_candidates (
                candidate_id TEXT PRIMARY KEY,
                proposal_key TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                source_revision INTEGER NOT NULL,
                evidence_json TEXT NOT NULL,
                proposed_fields_json TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                target_item_id TEXT,
                target_version INTEGER,
            review_flags_json TEXT NOT NULL DEFAULT '[]',
                decision TEXT,
                decision_fields_json TEXT,
                note TEXT NOT NULL DEFAULT '',
                stale_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS item_history (
                event_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES items(item_id),
                version INTEGER NOT NULL,
                action TEXT NOT NULL,
                before_state_json TEXT NOT NULL,
                after_state_json TEXT NOT NULL,
                diff_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT 'null',
                note TEXT NOT NULL,
                candidate_id TEXT,
                source_id TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                source_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(item_id, version)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_item_candidates_status ON item_candidates(status, created_at)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_item_candidates_source ON item_candidates(source_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_item_history_item ON item_history(item_id, version)")
        connection.execute(
            """CREATE TRIGGER IF NOT EXISTS item_history_immutable_update
               BEFORE UPDATE ON item_history BEGIN
                   SELECT RAISE(ABORT, 'item history is immutable');
               END"""
        )
        connection.execute(
            """CREATE TRIGGER IF NOT EXISTS item_history_immutable_delete
               BEFORE DELETE ON item_history BEGIN
                   SELECT RAISE(ABORT, 'item history is immutable');
               END"""
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(item_candidates)")}
        if "review_flags_json" not in columns:
            connection.execute("ALTER TABLE item_candidates ADD COLUMN review_flags_json TEXT NOT NULL DEFAULT '[]'")
        history_columns = {row[1] for row in connection.execute("PRAGMA table_info(item_history)")}
        if "evidence_json" not in history_columns:
            connection.execute("ALTER TABLE item_history ADD COLUMN evidence_json TEXT NOT NULL DEFAULT 'null'")

    @staticmethod
    def _source_review_flags(source: dict[str, Any]) -> list[str]:
        provenance = source.get("provenance")
        segmentation = provenance.get("segmentation", {}) if isinstance(provenance, dict) else {}
        if not isinstance(segmentation, dict):
            return []
        flags: list[str] = []
        if segmentation.get("uncertain"):
            flags.append("SEGMENTATION_UNCERTAIN")
        if segmentation.get("current_projection_matches") is False:
            flags.append("PROJECTION_MISMATCH")
        return flags

    def _get_source(self, source_id: str) -> dict[str, Any]:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a nonempty string")
        canonical_getter = getattr(self.store, "get_canonical_email", None)
        source = canonical_getter(source_id) if callable(canonical_getter) else self.store.get_email(source_id)
        if source is None or source.get("source_id") != source_id:
            raise ConflictError("Canonical source is missing or ambiguous")
        _source_binding(source)
        if not isinstance(source.get("current_message"), str):
            raise ValueError("Canonical source has no current_message text")
        return source

    def _source_is_current(self, source_id: str, fingerprint: str, revision: int) -> tuple[bool, str | None]:
        canonical_getter = getattr(self.store, "get_canonical_email", None)
        source = canonical_getter(source_id) if callable(canonical_getter) else self.store.get_email(source_id)
        if source is None or source.get("source_id") != source_id:
            return False, "SOURCE_MISSING_OR_AMBIGUOUS"
        if source.get("input_fingerprint") != fingerprint:
            return False, "INPUT_FINGERPRINT_CHANGED"
        if source.get("source_revision") != revision:
            return False, "SOURCE_REVISION_CHANGED"
        return True, None

    def propose(
        self,
        source_id: str,
        fields: dict[str, Any],
        evidence: dict[str, Any],
        target_item_id: str | None = None,
        *,
        review_flags: list[str] | None = None,
    ) -> dict[str, Any]:
        initial = self._get_source(source_id)
        if target_item_id is not None and (not isinstance(target_item_id, str) or not target_item_id):
            raise ValueError("target_item_id must be a nonempty string when provided")
        if target_item_id is None:
            normalized_fields = validate_fields(fields)
        else:
            normalized_fields = validate_fields(fields, partial=True)
        if review_flags is None:
            review_flags = []
        if (
            not isinstance(review_flags, list)
            or any(not isinstance(flag, str) or not flag or len(flag) > 80 for flag in review_flags)
            or len(set(review_flags)) != len(review_flags)
        ):
            raise ValueError("review_flags must be a list of unique bounded strings")
        normalized_evidence = _evidence(evidence, initial["current_message"])

        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._get_source(initial["source_id"])
                binding = _source_binding(current)
                if binding != _source_binding(initial):
                    raise ConflictError("Source changed while the candidate was being proposed")
                review_flags = list(dict.fromkeys([*review_flags, *self._source_review_flags(current)]))
                normalized_evidence = _evidence(evidence, current["current_message"])
                if target_item_id is None:
                    stored_fields = normalized_fields
                    target_version = None
                else:
                    target = connection.execute("SELECT * FROM items WHERE item_id=?", (target_item_id,)).fetchone()
                    if target is None:
                        raise ValueError("target_item_id does not identify an existing item")
                    target_fields = validate_fields(_load(target["fields_json"], {}))
                    validate_fields({**target_fields, **normalized_fields})
                    stored_fields = normalized_fields
                    target_version = int(target["version"])
                identity = {
                    **binding,
                    "evidence": normalized_evidence,
                    "fields": stored_fields,
                    "target_item_id": target_item_id,
                    "target_version": target_version,
                    "review_flags": review_flags,
                }
                key = _proposal_key(identity)
                row = connection.execute(
                    "SELECT * FROM item_candidates WHERE proposal_key=?", (key,)
                ).fetchone()
                if row is None:
                    candidate_id = str(uuid.uuid5(_CANDIDATE_NAMESPACE, key))
                    now = _now()
                    connection.execute(
                        """INSERT INTO item_candidates(
                            candidate_id, proposal_key, source_id, input_fingerprint, source_revision,
                            evidence_json, proposed_fields_json, status, version, target_item_id,
                            target_version, review_flags_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 1, ?, ?, ?, ?, ?)""",
                        (
                            candidate_id,
                            key,
                            binding["source_id"],
                            binding["input_fingerprint"],
                            binding["source_revision"],
                            _json(normalized_evidence),
                            _json(stored_fields),
                            target_item_id,
                            target_version,
                            _json(review_flags),
                            now,
                            now,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM item_candidates WHERE candidate_id=?", (candidate_id,)
                    ).fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self._decode_candidate(row)

    def suggest(self, source_id: str) -> list[dict[str, Any]]:
        source = self._get_source(source_id)
        text = source["current_message"]
        results: list[dict[str, Any]] = []
        for start, end in _sentence_spans(text):
            sentence = text[start:end]
            kind = _suggested_kind(sentence)
            if kind is None:
                continue
            due_match = re.search(
                r"\b(?:by|before|after|on|until)\s+(?:end of day|eod|[A-Za-z]+\s+\d{1,2}|[A-Za-z]+|\d{1,4}(?:[-/]\d{1,2}){1,2})\b",
                sentence,
                re.IGNORECASE,
            )
            fields = {
                "project_id": str(source.get("project_or_list") or "default"),
                "kind": kind,
                "title": sentence.strip()[:2000],
                "owner": "",
                "department": "",
                "due": "",
                "due_text": due_match.group(0) if due_match else "",
                "requested_document": "",
                "status": "OPEN",
            }
            flags = ["OWNER_UNASSIGNED"]
            flags.append("DUE_NOT_NORMALIZED" if due_match else "DUE_UNRESOLVED")
            evidence = {"field": "current_message", "start": start, "end": end, "text": sentence}
            candidate = self.propose(source["source_id"], fields, evidence, review_flags=flags)
            results.append(candidate)
        return results

    def list_candidates(self) -> list[dict[str, Any]]:
        with closing(self.store._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM item_candidates ORDER BY created_at, candidate_id"
            ).fetchall()
        result = []
        for row in rows:
            value = self._decode_candidate(row)
            value.update(self._conflict_fields(value["source_id"], value["input_fingerprint"], value["source_revision"]))
            result.append(value)
        return result

    def list_items(self) -> list[dict[str, Any]]:
        with closing(self.store._connect()) as connection:
            rows = connection.execute("SELECT * FROM items ORDER BY created_at, item_id").fetchall()
        result = []
        for row in rows:
            value = self._decode_item(row)
            history = self._item_history(value["item_id"])
            value.update(self._history_conflict_fields(history, value))
            result.append(value)
        return result

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("item_id must be a nonempty string")
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
            if row is None:
                return None
            history = connection.execute(
                "SELECT * FROM item_history WHERE item_id=? ORDER BY version", (item_id,)
            ).fetchall()
            connection.commit()
        result = self._decode_item(row)
        result["history"] = [self._decode_history(event) for event in history]
        result.update(self._history_conflict_fields(result["history"], result))
        return result

    def _item_history(self, item_id: str) -> list[dict[str, Any]]:
        with closing(self.store._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM item_history WHERE item_id=? ORDER BY version", (item_id,)
            ).fetchall()
        return [self._decode_history(row) for row in rows]

    def _history_conflict_fields(
        self, history: list[dict[str, Any]], item: dict[str, Any]
    ) -> dict[str, Any]:
        bindings = {
            (item["source_id"], item["input_fingerprint"], item["source_revision"]),
            *(
                (event["source_id"], event["input_fingerprint"], event["source_revision"])
                for event in history
            ),
        }
        reasons = []
        for source_id, fingerprint, revision in sorted(bindings):
            _current, reason = self._source_is_current(source_id, fingerprint, revision)
            if reason:
                reasons.append(reason)
        reason = reasons[0] if reasons else None
        return {"source_conflict": reason is not None, "source_conflict_reason": reason}

    def export_snapshot(self) -> list[dict[str, Any]]:
        """Return items and their immutable history from one consistent read snapshot."""
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            try:
                items = connection.execute("SELECT * FROM items ORDER BY created_at, item_id").fetchall()
                result = []
                for row in items:
                    value = self._decode_item(row)
                    history = connection.execute(
                        "SELECT * FROM item_history WHERE item_id=? ORDER BY version", (row["item_id"],)
                    ).fetchall()
                    value["history"] = [self._decode_history(event) for event in history]
                    reason = self._snapshot_conflict_reason(connection, [value, *value["history"]])
                    value.update(source_conflict=reason is not None, source_conflict_reason=reason)
                    result.append(value)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def decide(
        self,
        candidate_id: str,
        decision: str,
        expected_version: int,
        fields: dict[str, Any] | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("candidate_id must be a nonempty string")
        version = _version(expected_version, "expected_version")
        if not isinstance(decision, str):
            raise ValueError("decision must be APPROVE, CORRECT, or REJECT")
        decision = decision.upper()
        if decision not in {"APPROVE", "CORRECT", "REJECT"}:
            raise ValueError("decision must be APPROVE, CORRECT, or REJECT")
        note = _note(note)
        if fields is not None:
            fields = validate_fields(fields, partial=True)
        requested_fields_json = None if fields is None else _json(fields)

        stale_after_commit: str | None = None
        result: dict[str, Any] | None = None
        result_kind = "candidate"
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                candidate = connection.execute(
                    "SELECT * FROM item_candidates WHERE candidate_id=?", (candidate_id,)
                ).fetchone()
                if candidate is None:
                    raise ValueError("Unknown candidate_id")
                if candidate["status"] == "STALE":
                    raise ConflictError("Candidate source is stale; propose again from the current source")
                if candidate["status"] in _TERMINAL:
                    if (
                        candidate["decision"] == decision
                        and version == int(candidate["version"]) - 1
                        and candidate["decision_fields_json"] == requested_fields_json
                        and candidate["note"] == note
                    ):
                        result = self._current_decision_result(connection, candidate)
                        result_kind = "item" if candidate["status"] in {"APPROVED", "CORRECTED"} else "candidate"
                        connection.commit()
                    else:
                        raise ConflictError("Candidate already has a different terminal decision")
                else:
                    if candidate["version"] != version:
                        raise ConflictError("Candidate version changed; reload it before deciding")
                    proposed_fields = _load(candidate["proposed_fields_json"], {})
                    if decision == "APPROVE" and fields is not None and fields != proposed_fields:
                        raise ValueError("APPROVE cannot change proposed fields; use CORRECT with a note")
                    if decision == "REJECT" and fields is not None:
                        raise ValueError("REJECT cannot include item fields")
                    if decision == "CORRECT" and fields is not None:
                        if any(proposed_fields.get(key) != value for key, value in fields.items()) and not note.strip():
                            raise ValueError("CORRECT requires a nonempty note when overriding proposed fields")
                    if decision != "REJECT":
                        source_current, reason = self._source_is_current(
                            candidate["source_id"], candidate["input_fingerprint"], candidate["source_revision"]
                        )
                        if source_current:
                            current_source = self._get_source(candidate["source_id"])
                            try:
                                _evidence(_load(candidate["evidence_json"], {}), current_source["current_message"])
                            except ValueError:
                                source_current, reason = False, "EVIDENCE_NO_LONGER_MATCHES_SOURCE"
                        if not source_current:
                            now = _now()
                            connection.execute(
                                """UPDATE item_candidates SET status='STALE', version=version+1,
                                   decision=?, decision_fields_json=?, note=?, stale_reason=?, updated_at=?
                                   WHERE candidate_id=?""",
                                (decision, requested_fields_json, note, reason, now, candidate_id),
                            )
                            stale_after_commit = reason or "SOURCE_CHANGED"
                            result = self._decode_candidate(
                                connection.execute(
                                    "SELECT * FROM item_candidates WHERE candidate_id=?", (candidate_id,)
                                ).fetchone()
                            )
                            result_kind = "candidate"
                            connection.commit()
                    if stale_after_commit is None and result is None:
                        if decision == "REJECT":
                            now = _now()
                            connection.execute(
                                """UPDATE item_candidates SET status='REJECTED', version=version+1,
                                   decision=?, decision_fields_json=?, note=?, updated_at=? WHERE candidate_id=?""",
                                (decision, requested_fields_json, note, now, candidate_id),
                            )
                            result = self._decode_candidate(
                                connection.execute(
                                    "SELECT * FROM item_candidates WHERE candidate_id=?", (candidate_id,)
                                ).fetchone()
                            )
                            connection.commit()
                        else:
                            result = self._apply_decision(
                                connection,
                                candidate,
                                decision,
                                version,
                                fields,
                                requested_fields_json,
                                note,
                            )
                            result_kind = "item"
                            connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        if stale_after_commit is not None:
            raise ConflictError(f"Candidate source changed; it is now marked STALE ({stale_after_commit})")
        if result is None:
            raise RuntimeError("Decision did not produce a result")
        if result_kind == "item":
            result.update(self._history_conflict_fields(self._item_history(result["item_id"]), result))
            return result
        result.update(
            self._conflict_fields(result["source_id"], result["input_fingerprint"], result["source_revision"])
        )
        return result

    def _apply_decision(
        self,
        connection: sqlite3.Connection,
        candidate: sqlite3.Row,
        decision: str,
        expected_version: int,
        correction_fields: dict[str, Any] | None,
        requested_fields_json: str | None,
        note: str,
    ) -> dict[str, Any]:
        candidate_id = candidate["candidate_id"]
        patch = _load(candidate["proposed_fields_json"], {})
        if correction_fields is not None:
            patch = {**patch, **correction_fields}
        target_id = candidate["target_item_id"]
        now = _now()
        if target_id is None:
            final_fields = validate_fields(patch)
            item_id = str(uuid.uuid4())
            source_state = {
                "source_id": candidate["source_id"],
                "input_fingerprint": candidate["input_fingerprint"],
                "source_revision": candidate["source_revision"],
            }
            after = {"fields": final_fields, **source_state}
            connection.execute(
                """INSERT INTO items(
                    item_id, fields_json, status, version, source_id, input_fingerprint,
                    source_revision, created_from_candidate_id, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    _json(final_fields),
                    final_fields["status"],
                    candidate["source_id"],
                    candidate["input_fingerprint"],
                    candidate["source_revision"],
                    candidate_id,
                    now,
                    now,
                ),
            )
            self._insert_history(
                connection,
                item_id=item_id,
                version=1,
                action=decision,
                before={},
                after=after,
                note=note,
                candidate_id=candidate_id,
                evidence=_load(candidate["evidence_json"], None),
                source_state=source_state,
                created_at=now,
            )
        else:
            item = connection.execute("SELECT * FROM items WHERE item_id=?", (target_id,)).fetchone()
            if item is None:
                raise ConflictError("Target item was removed; reload and propose again")
            if int(item["version"]) != int(candidate["target_version"]):
                raise ConflictError("Target item changed after this update was proposed")
            before = self._item_state(item)
            current_fields = validate_fields(before["fields"])
            final_fields = validate_fields({**current_fields, **patch})
            next_version = int(item["version"]) + 1
            source_state = {
                "source_id": candidate["source_id"],
                "input_fingerprint": candidate["input_fingerprint"],
                "source_revision": candidate["source_revision"],
            }
            after = {"fields": final_fields, **source_state}
            connection.execute(
                """UPDATE items SET fields_json=?, status=?, version=?, source_id=?, input_fingerprint=?,
                   source_revision=?, updated_at=? WHERE item_id=?""",
                (
                    _json(final_fields),
                    final_fields["status"],
                    next_version,
                    source_state["source_id"],
                    source_state["input_fingerprint"],
                    source_state["source_revision"],
                    now,
                    target_id,
                ),
            )
            self._insert_history(
                connection,
                item_id=target_id,
                version=next_version,
                action=decision,
                before=before,
                after=after,
                note=note,
                candidate_id=candidate_id,
                evidence=_load(candidate["evidence_json"], None),
                source_state=source_state,
                created_at=now,
            )
            item_id = target_id

        connection.execute(
            """UPDATE item_candidates SET status=?, version=version+1, decision=?,
               decision_fields_json=?, note=?, updated_at=? WHERE candidate_id=? AND version=?""",
            (
                "APPROVED" if decision == "APPROVE" else "CORRECTED",
                decision,
                requested_fields_json,
                note,
                now,
                candidate_id,
                expected_version,
            ),
        )
        return self._decode_item(connection.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone())

    def undo(self, item_id: str, expected_version: int, note: str = "") -> dict[str, Any]:
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("item_id must be a nonempty string")
        version = _version(expected_version, "expected_version")
        note = _note(note)
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                item = connection.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
                if item is None:
                    raise ConflictError("Item no longer exists")
                if int(item["version"]) != version:
                    raise ConflictError("Item version changed; reload it before undoing")
                last = connection.execute(
                    "SELECT * FROM item_history WHERE item_id=? ORDER BY version DESC LIMIT 1", (item_id,)
                ).fetchone()
                if last is None:
                    raise ConflictError("Item has no reversible history")
                before = self._item_state(item)
                prior_state = _load(last["before_state_json"], {})
                if prior_state:
                    after = {
                        "fields": validate_fields(prior_state.get("fields", {})),
                        "source_id": prior_state.get("source_id", before["source_id"]),
                        "input_fingerprint": prior_state.get("input_fingerprint", before["input_fingerprint"]),
                        "source_revision": prior_state.get("source_revision", before["source_revision"]),
                    }
                else:
                    cancelled_fields = dict(before["fields"])
                    cancelled_fields["status"] = "CANCELLED"
                    after = {**before, "fields": validate_fields(cancelled_fields)}
                next_version = version + 1
                now = _now()
                connection.execute(
                    """UPDATE items SET fields_json=?, status=?, version=?, source_id=?, input_fingerprint=?,
                       source_revision=?, updated_at=? WHERE item_id=?""",
                    (
                        _json(after["fields"]),
                        after["fields"]["status"],
                        next_version,
                        after["source_id"],
                        after["input_fingerprint"],
                        after["source_revision"],
                        now,
                        item_id,
                    ),
                )
                source_state = {
                    "source_id": before["source_id"],
                    "input_fingerprint": before["input_fingerprint"],
                    "source_revision": before["source_revision"],
                }
                self._insert_history(
                    connection,
                    item_id=item_id,
                    version=next_version,
                    action="UNDO",
                    before=before,
                    after=after,
                    note=note,
                    candidate_id=None,
                    evidence=_load(last["evidence_json"], None),
                    source_state=source_state,
                    created_at=now,
                )
                result = self._decode_item(connection.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone())
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        result.update(self._conflict_fields(result["source_id"], result["input_fingerprint"], result["source_revision"]))
        return result

    @staticmethod
    def _item_state(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "fields": _load(row["fields_json"], {}),
            "source_id": row["source_id"],
            "input_fingerprint": row["input_fingerprint"],
            "source_revision": row["source_revision"],
        }

    @staticmethod
    def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_fields = before.get("fields", {}) if before else {}
        after_fields = after.get("fields", {}) if after else {}
        return {
            key: {"before": before_fields.get(key), "after": after_fields.get(key)}
            for key in sorted(set(before_fields) | set(after_fields))
            if before_fields.get(key) != after_fields.get(key)
        }

    def _insert_history(
        self,
        connection: sqlite3.Connection,
        *,
        item_id: str,
        version: int,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        note: str,
        candidate_id: str | None,
        evidence: dict[str, Any] | None,
        source_state: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """INSERT INTO item_history(
                event_id, item_id, version, action, before_state_json, after_state_json,
                diff_json, evidence_json, note, candidate_id, source_id, input_fingerprint, source_revision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                item_id,
                version,
                action,
                _json(before),
                _json(after),
                _json(self._diff(before, after)),
                _json(evidence),
                note,
                candidate_id,
                source_state["source_id"],
                source_state["input_fingerprint"],
                source_state["source_revision"],
                created_at,
            ),
        )

    @staticmethod
    def _decode_item(row: sqlite3.Row) -> dict[str, Any]:
        fields = validate_fields(_load(row["fields_json"], {}))
        return {
            "item_id": row["item_id"],
            "fields": fields,
            "status": row["status"],
            "version": row["version"],
            "source_id": row["source_id"],
            "input_fingerprint": row["input_fingerprint"],
            "source_revision": row["source_revision"],
            "created_from_candidate_id": row["created_from_candidate_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _decode_candidate(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "candidate_id": row["candidate_id"],
            "source_id": row["source_id"],
            "input_fingerprint": row["input_fingerprint"],
            "source_revision": row["source_revision"],
            "evidence": _load(row["evidence_json"], {}),
            "proposed_fields": _load(row["proposed_fields_json"], {}),
            "status": row["status"],
            "version": row["version"],
            "target_item_id": row["target_item_id"],
            "target_version": row["target_version"],
            "review_flags": _load(row["review_flags_json"], []),
            "decision": row["decision"],
            "decision_fields": _load(row["decision_fields_json"], None),
            "note": row["note"],
            "stale_reason": row["stale_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _decode_history(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "item_id": row["item_id"],
            "version": row["version"],
            "action": row["action"],
            "before": _load(row["before_state_json"], {}),
            "after": _load(row["after_state_json"], {}),
            "diff": _load(row["diff_json"], {}),
            "evidence": _load(row["evidence_json"], None),
            "note": row["note"],
            "candidate_id": row["candidate_id"],
            "source_id": row["source_id"],
            "input_fingerprint": row["input_fingerprint"],
            "source_revision": row["source_revision"],
            "created_at": row["created_at"],
            "timestamp": row["created_at"],
        }

    def _current_decision_result(self, connection: sqlite3.Connection, candidate: sqlite3.Row) -> dict[str, Any]:
        if candidate["status"] in {"APPROVED", "CORRECTED"}:
            item = connection.execute(
                "SELECT * FROM items WHERE created_from_candidate_id=?", (candidate["candidate_id"],)
            ).fetchone()
            if item is None and candidate["target_item_id"]:
                item = connection.execute(
                    "SELECT * FROM items WHERE item_id=?", (candidate["target_item_id"],)
                ).fetchone()
            if item is None:
                raise RuntimeError("Terminal item candidate has no committed item")
            return self._decode_item(item)
        return self._decode_candidate(candidate)

    def _conflict_fields(self, source_id: str, fingerprint: str, revision: int) -> dict[str, Any]:
        _current, reason = self._source_is_current(source_id, fingerprint, revision)
        return {"source_conflict": reason is not None, "source_conflict_reason": reason}

    @staticmethod
    def _snapshot_conflict_reason(
        connection: sqlite3.Connection, bindings: list[dict[str, Any]]
    ) -> str | None:
        seen = set()
        for binding in bindings:
            key = (
                binding["source_id"],
                binding["input_fingerprint"],
                binding["source_revision"],
            )
            if key in seen:
                continue
            seen.add(key)
            current = connection.execute(
                "SELECT input_fingerprint, source_revision FROM emails WHERE source_id=?",
                (key[0],),
            ).fetchone()
            if current is None:
                return "SOURCE_MISSING_OR_AMBIGUOUS"
            if current["input_fingerprint"] != key[1]:
                return "INPUT_FINGERPRINT_CHANGED"
            if current["source_revision"] != key[2]:
                return "SOURCE_REVISION_CHANGED"
        return None


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Find stable sentence/line spans while retaining exact source offsets."""
    spans: list[tuple[int, int]] = []
    for line_start, line in _line_spans(text):
        for match in re.finditer(r".+?(?:[.!?]+(?=\s|$)|$)", line):
            start, end = line_start + match.start(), line_start + match.end()
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            if start < end:
                spans.append((start, end))
    return spans


def _line_spans(text: str) -> list[tuple[int, str]]:
    result = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        result.append((offset, content))
        offset += len(line)
    if not text or (text and text[-1] in "\r\n"):
        return result
    if not result:
        result.append((0, text))
    return result


def _suggested_kind(sentence: str) -> str | None:
    action = re.search(
        r"\b(?:please|kindly|could you|can you|would you|need to|needs to|must|should|submit|send|share|prepare|provide|schedule|arrange|review|complete|deliver|finish|follow[ -]?up|action required|let['’]?s)\b",
        sentence,
        re.IGNORECASE,
    )
    if not action:
        return None
    folded = sentence.casefold()
    if re.search(r"\b(?:meeting|meet|call|conference)\b", folded):
        return "MEETING"
    if re.search(r"\b(?:approve|approval|sign off)\b", folded):
        return "APPROVAL"
    if re.search(r"\b(?:provide input|give feedback|send feedback|review comments)\b", folded):
        return "DEPARTMENTAL_INPUT"
    if re.search(r"\b(?:report|document|file|attachment|minutes|slides|presentation|summary|brief)\b", folded):
        return "DOCUMENT_REQUEST"
    if re.search(r"\b(?:follow[ -]?up|check back|remind)\b", folded):
        return "FOLLOW_UP"
    return "TASK"
