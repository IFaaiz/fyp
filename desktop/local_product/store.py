"""Canonical local SQLite archive for imported messages and review-only cues."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from email.utils import getaddresses
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from .classification import DiagnosticClassifier, ReviewSuggestion, rule_baseline
from .extraction import extract_rule_suggestions
from .models import EmailRecord


SCHEMA_VERSION = 3
_UNSPECIFIED_SCOPE = "UNSPECIFIED"


class AnnotationConflictError(ValueError):
    """A source reimport changed text that existing annotation offsets rely on."""


def default_database_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "BahriaFYP" / "email_archive.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    return json.loads(value)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8", errors="replace")).hexdigest()


def _timestamp_info(record: EmailRecord) -> dict[str, Any]:
    """Read the model's richer timestamp contract, with a legacy fallback."""
    value = getattr(record, "timestamp_info", None)
    if callable(value):
        value = value()
    if isinstance(value, dict):
        original = value.get("original", record.timestamp)
        kind = value.get("kind")
        utc = value.get("utc")
        if kind not in {"aware", "naive", "date_only", "malformed", "missing"}:
            kind = "missing" if record.timestamp is None else "malformed"
        from .temporal import timestamp_info as parse_timestamp_info

        normalized = parse_timestamp_info(utc).get("utc") if isinstance(utc, str) and utc else None
        return {"original": original, "kind": kind, "utc": normalized}
    from .temporal import timestamp_info as parse_timestamp_info

    original = record.timestamp
    return parse_timestamp_info(original)


def _sent_timestamp(record: EmailRecord, info: dict[str, Any]) -> str | None:
    """Return a sent instant, never treating a received-only time as sent time."""
    from .temporal import timestamp_info as parse_timestamp_info

    sent_at = getattr(record, "sent_at", None)
    if sent_at is not None:
        return parse_timestamp_info(str(sent_at)).get("utc")
    received_at = getattr(record, "received_at", None)
    timestamp_kind = getattr(record, "timestamp_kind", "unspecified")
    provenance = record.provenance if isinstance(record.provenance, dict) else {}
    adapter = str(provenance.get("adapter", "")).casefold()
    if received_at is not None or timestamp_kind == "received" or adapter in {"outlook_com", "outlook", "exchange"}:
        return None
    # Legacy normalized records and RFC822 dates represent the sent date.
    if timestamp_kind == "sent":
        return info.get("utc")
    if timestamp_kind == "unspecified" and adapter in {"eml", "extract-msg", "msg"}:
        return info.get("utc")
    return None


def _input_fingerprint(record: EmailRecord, info: dict[str, Any]) -> str:
    value = getattr(record, "input_fingerprint", None)
    if callable(value):
        value = value()
    if isinstance(value, str) and value:
        return value
    # Compatibility with older EmailRecord implementations.
    return _sha256(
        {
            "subject": record.subject,
            "current_message": record.current_message,
            "body_raw": record.body_raw,
            "attachment_names": list(record.attachment_names),
            "timestamp_info": info,
            "version": "legacy-store-fallback-v1",
        }
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\r\n", "\n").replace("\r", "\n")).strip().casefold()


def _normalize_raw(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _addresses(values: Iterable[str]) -> tuple[str, ...]:
    addresses: list[str] = []
    for _name, address in getaddresses(list(values)):
        normalized = address.strip().casefold()
        if normalized and normalized not in addresses:
            addresses.append(normalized)
    return tuple(sorted(addresses))


def _identity_parts(record: EmailRecord, info: dict[str, Any]) -> dict[str, Any]:
    provenance = record.provenance if isinstance(record.provenance, dict) else {}
    sent = _sent_timestamp(record, info)
    return {
        "subject": _normalize_text(record.subject),
        "sender": _addresses((record.sender,)),
        "recipients": _addresses(record.recipients),
        # Transport adapters can add/remove outer MIME boundary newlines. Keep
        # interior body bytes meaningful while ignoring only that boundary.
        "body_raw": _normalize_raw(record.body_raw).strip(),
        "attachment_names": tuple(sorted(_normalize_text(name) for name in record.attachment_names)),
        "sent_utc": sent,
        "sent_time_known": sent is not None,
        "adapter": str(provenance.get("adapter", "")).casefold(),
    }


def _identity_fingerprint(parts: dict[str, Any]) -> str:
    return _sha256({key: value for key, value in parts.items() if key not in {"sent_utc", "sent_time_known", "adapter"}})


def _source_access_scope(record: EmailRecord) -> str:
    provenance = record.provenance if isinstance(record.provenance, dict) else {}
    return _source_access_scope_from_provenance(provenance)


def _source_access_scope_from_provenance(provenance: Any) -> str:
    if not isinstance(provenance, dict):
        return _UNSPECIFIED_SCOPE
    value = provenance.get("source_access_scope", provenance.get("access_scope", _UNSPECIFIED_SCOPE))
    if not isinstance(value, str) or not value.strip():
        return _UNSPECIFIED_SCOPE
    return value.strip()


def _source_location(record: EmailRecord) -> str:
    provenance = record.provenance if isinstance(record.provenance, dict) else {}
    # File names distinguish repeated Message-IDs from different imported files.
    # Mailbox adapters generally have a stable source_id and no file_name.
    value = provenance.get("source_location", provenance.get("file_name"))
    return value.strip() if isinstance(value, str) else ""


def _observation_key(record: EmailRecord) -> str:
    return _sha256(
        {
            "source_name": record.source_name,
            "source_id": record.source_id,
            "location": _source_location(record),
        }
    )


def _observation_metadata(record: EmailRecord, info: dict[str, Any], sent_utc: str | None) -> dict[str, Any]:
    """Keep source-specific headers and provenance separate from canonical data."""
    return {
        "record": record.to_dict(),
        "source_id": record.source_id,
        "source_name": record.source_name,
        "project_or_list": record.project_or_list,
        "message_id": record.message_id,
        "in_reply_to": record.in_reply_to,
        "references": list(record.references),
        "thread_hint": _explicit_thread_hint(record),
        "canonical_thread_id": record.canonical_thread_id,
        "subject": record.subject,
        "sender": record.sender,
        "recipients": list(record.recipients),
        "timestamp": record.timestamp,
        "timestamp_info": info,
        "sent_at": getattr(record, "sent_at", None),
        "received_at": getattr(record, "received_at", None),
        "timestamp_kind": getattr(record, "timestamp_kind", "unspecified"),
        "sent_timestamp_utc": sent_utc,
        "attachment_names": list(record.attachment_names),
        "license_or_terms_note": record.license_or_terms_note,
        "source_access_scope": _source_access_scope(record),
    }


def _explicit_thread_hint(record: EmailRecord) -> str:
    if not record.thread_id:
        return ""
    value = record.canonical_thread_id
    if value.startswith(("message-thread:", "message:")):
        return ""
    return value


def _message_reference_ids(row: sqlite3.Row) -> list[str]:
    values = [row["in_reply_to"]] if row["in_reply_to"] else []
    values.extend(_load_json(row["references_json"], []))
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _timestamp_info_from_saved(timestamp: str | None, existing: Any) -> dict[str, Any]:
    from .temporal import timestamp_info as parse_timestamp_info

    return parse_timestamp_info(timestamp)


def _saved_sent_timestamp(row: sqlite3.Row, info: dict[str, Any]) -> str | None:
    from .temporal import timestamp_info as parse_timestamp_info

    if row["sent_at"]:
        return parse_timestamp_info(row["sent_at"]).get("utc")
    provenance = _load_json(row["provenance_json"], {})
    adapter = str(provenance.get("adapter", "")).casefold() if isinstance(provenance, dict) else ""
    if row["received_at"] or row["timestamp_kind"] == "received" or adapter in {"outlook_com", "outlook", "exchange"}:
        return None
    if row["timestamp_kind"] == "sent" or adapter in {"eml", "extract-msg", "msg"}:
        return info.get("utc")
    return None


def _saved_identity_fingerprint(row: sqlite3.Row) -> str:
    return _sha256(
        {
            "subject": _normalize_text(row["subject"]),
            "sender": _addresses((row["sender"],)),
            "recipients": _addresses(_load_json(row["recipients_json"], [])),
            "body_raw": _normalize_raw(row["body_raw"]).strip(),
            "attachment_names": tuple(
                sorted(_normalize_text(name) for name in _load_json(row["attachment_names_json"], []))
            ),
        }
    )


class EmailStore:
    """Transactional SQLite storage; source text stays local and out of logs."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.path = self.path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than this app supports ({SCHEMA_VERSION})."
                )
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._create_base_schema(connection)
                self._ensure_email_columns(connection)
                self._create_observation_schema(connection)
                self._migrate_observations(connection)
                self._recompute_conversations(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _create_base_schema(connection: sqlite3.Connection) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                first_timestamp TEXT,
                latest_timestamp TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                source_names_json TEXT NOT NULL DEFAULT '[]',
                project_or_lists_json TEXT NOT NULL DEFAULT '[]'
            )""",
            """CREATE TABLE IF NOT EXISTS emails (
                source_id TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                project_or_list TEXT NOT NULL DEFAULT '',
                message_id TEXT,
                in_reply_to TEXT,
                references_json TEXT NOT NULL DEFAULT '[]',
                thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON UPDATE CASCADE,
                subject TEXT NOT NULL DEFAULT '',
                sender TEXT NOT NULL DEFAULT '',
                recipients_json TEXT NOT NULL DEFAULT '[]',
                timestamp TEXT,
                body_raw TEXT NOT NULL DEFAULT '',
                current_message TEXT NOT NULL DEFAULT '',
                quoted_history TEXT NOT NULL DEFAULT '',
                attachment_names_json TEXT NOT NULL DEFAULT '[]',
                provenance_json TEXT NOT NULL DEFAULT '{}',
                license_or_terms_note TEXT NOT NULL DEFAULT '',
                scope TEXT,
                labels_json TEXT NOT NULL DEFAULT '[]',
                spans_json TEXT NOT NULL DEFAULT '[]',
                annotation_method TEXT NOT NULL DEFAULT 'UNANNOTATED',
                body_sha256 TEXT NOT NULL DEFAULT '',
                rule_status TEXT NOT NULL DEFAULT 'ABSTAIN',
                rule_labels_json TEXT NOT NULL DEFAULT '[]',
                rule_evidence_json TEXT NOT NULL DEFAULT '[]',
                extraction_suggestions_json TEXT NOT NULL DEFAULT '{}',
                classifier_status TEXT,
                classifier_method TEXT,
                classifier_run_id TEXT,
                classifier_labels_json TEXT NOT NULL DEFAULT '[]',
                classifier_scores_json TEXT NOT NULL DEFAULT '{}',
                classifier_scope_uncertainty_available INTEGER,
                imported_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )""",
        )
        for statement in statements:
            connection.execute(statement)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_emails_timestamp ON emails(timestamp)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_emails_source_name ON emails(source_name)")

    @staticmethod
    def _ensure_email_columns(connection: sqlite3.Connection) -> None:
        additions = {
            "extraction_suggestions_json": "TEXT NOT NULL DEFAULT '{}'",
            "input_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "identity_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "identity_sent_timestamp_utc": "TEXT",
            "identity_sent_time_known": "INTEGER NOT NULL DEFAULT 0",
            "source_revision": "INTEGER NOT NULL DEFAULT 1",
            "timestamp_utc": "TEXT",
            "timestamp_info_json": "TEXT NOT NULL DEFAULT '{}'",
            "sent_at": "TEXT",
            "received_at": "TEXT",
            "timestamp_kind": "TEXT NOT NULL DEFAULT 'unspecified'",
            "source_thread_hint": "TEXT NOT NULL DEFAULT ''",
            "rule_derivation_json": "TEXT NOT NULL DEFAULT '{}'",
            "extraction_derivation_json": "TEXT NOT NULL DEFAULT '{}'",
            "classifier_derivation_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(emails)")}
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE emails ADD COLUMN {name} {definition}")

    @staticmethod
    def _create_observation_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS source_observations (
                observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_key TEXT NOT NULL UNIQUE,
                canonical_source_id TEXT NOT NULL REFERENCES emails(source_id) ON DELETE CASCADE,
                source_name TEXT NOT NULL,
                adapter_source_id TEXT NOT NULL,
                observation_metadata_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL DEFAULT '{}',
                source_access_scope TEXT NOT NULL DEFAULT 'UNSPECIFIED',
                input_fingerprint TEXT NOT NULL,
                identity_fingerprint TEXT NOT NULL,
                source_revision INTEGER NOT NULL DEFAULT 1,
                timestamp_info_json TEXT NOT NULL DEFAULT '{}',
                sent_timestamp_utc TEXT,
                sent_time_known INTEGER NOT NULL DEFAULT 0,
                observed_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS source_aliases (
                source_name TEXT NOT NULL,
                source_alias TEXT NOT NULL,
                observation_key TEXT NOT NULL REFERENCES source_observations(observation_key) ON DELETE CASCADE,
                canonical_source_id TEXT NOT NULL REFERENCES emails(source_id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY(source_name, source_alias, observation_key)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_source_observations_canonical ON source_observations(canonical_source_id)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_source_aliases_alias ON source_aliases(source_alias)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS message_revisions (
                source_id TEXT NOT NULL REFERENCES emails(source_id) ON DELETE CASCADE,
                source_revision INTEGER NOT NULL,
                input_fingerprint TEXT NOT NULL,
                identity_fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY(source_id, source_revision)
            )"""
        )

    @staticmethod
    def _migrate_observations(connection: sqlite3.Connection) -> None:
        """Backfill additive v3 columns/tables without rebuilding or dropping archive rows."""
        rows = connection.execute("SELECT * FROM emails").fetchall()
        for row in rows:
            info = _timestamp_info_from_saved(row["timestamp"], _load_json(row["timestamp_info_json"], {}))
            timestamp_utc = info.get("utc")
            sent_timestamp_utc = _saved_sent_timestamp(row, info)
            provenance = _load_json(row["provenance_json"], {})
            record_fields = {
                "subject": row["subject"],
                "current_message": row["current_message"],
                "body_raw": row["body_raw"],
                "attachment_names": _load_json(row["attachment_names_json"], []),
                "timestamp_info": info,
                "version": "legacy-store-fallback-v1",
            }
            fingerprint = row["input_fingerprint"] or _sha256(record_fields)
            identity = row["identity_fingerprint"] or _saved_identity_fingerprint(row)
            connection.execute(
                """UPDATE emails SET input_fingerprint=?, identity_fingerprint=?,
                   timestamp_utc=?, timestamp_info_json=?,
                   source_thread_hint=CASE WHEN source_thread_hint<>'' THEN source_thread_hint
                       WHEN thread_id LIKE 'message-thread:%' OR thread_id LIKE 'message:%' THEN ''
                       ELSE thread_id END
                   WHERE source_id=?""",
                (fingerprint, identity, timestamp_utc, _json(info), row["source_id"]),
            )
            revision = max(1, int(row["source_revision"] or 1))
            if connection.execute(
                "SELECT 1 FROM message_revisions WHERE source_id=? AND source_revision=?",
                (row["source_id"], revision),
            ).fetchone() is None:
                connection.execute(
                    """INSERT INTO message_revisions(
                        source_id, source_revision, input_fingerprint, identity_fingerprint,
                        payload_json, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (row["source_id"], revision, fingerprint, identity, _json(dict(row)), row["updated_at"] or _now()),
                )
            observation_key = _sha256({"source_name": row["source_name"], "source_id": row["source_id"], "location": ""})
            if connection.execute(
                "SELECT 1 FROM source_observations WHERE canonical_source_id=?", (row["source_id"],)
            ).fetchone():
                continue
            metadata = {
                "source_id": row["source_id"],
                "source_name": row["source_name"],
                "project_or_list": row["project_or_list"],
                "message_id": row["message_id"],
                "in_reply_to": row["in_reply_to"],
                "references": _load_json(row["references_json"], []),
                "thread_hint": row["thread_id"],
                "subject": row["subject"],
                "sender": row["sender"],
                "recipients": _load_json(row["recipients_json"], []),
                "timestamp": row["timestamp"],
                "timestamp_info": info,
                "sent_at": row["sent_at"],
                "received_at": row["received_at"],
                "timestamp_kind": row["timestamp_kind"],
                "sent_timestamp_utc": sent_timestamp_utc,
                "body_raw": row["body_raw"],
                "current_message": row["current_message"],
                "quoted_history": row["quoted_history"],
                "attachment_names": _load_json(row["attachment_names_json"], []),
                "license_or_terms_note": row["license_or_terms_note"],
                "scope": row["scope"],
                "labels": _load_json(row["labels_json"], []),
                "spans": _load_json(row["spans_json"], []),
                "annotation_method": row["annotation_method"],
                "source_access_scope": _source_access_scope_from_provenance(provenance),
            }
            connection.execute(
                """INSERT INTO source_observations(
                    observation_key, canonical_source_id, source_name, adapter_source_id,
                    observation_metadata_json, provenance_json, source_access_scope,
                    input_fingerprint, identity_fingerprint, source_revision,
                    timestamp_info_json, sent_timestamp_utc, sent_time_known, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation_key,
                    row["source_id"],
                    row["source_name"],
                    row["source_id"],
                    _json(metadata),
                    row["provenance_json"],
                    _source_access_scope_from_provenance(provenance),
                    fingerprint,
                    identity,
                    max(1, int(row["source_revision"] or 1)),
                    _json(info),
                    sent_timestamp_utc,
                    int(sent_timestamp_utc is not None),
                    row["updated_at"] or _now(),
                ),
            )
            if row["classifier_derivation_json"] in {None, "", "{}"} and (
                row["classifier_method"]
                or row["classifier_status"]
                or _load_json(row["classifier_labels_json"], [])
                or _load_json(row["classifier_scores_json"], {})
            ):
                connection.execute(
                    """UPDATE emails SET classifier_status='STALE', classifier_labels_json='[]',
                       classifier_scores_json='{}', classifier_derivation_json=? WHERE source_id=?""",
                    (
                        _json({"status": "STALE", "input_fingerprint": "unknown", "model": "unknown",
                               "schema_version": "unknown", "settings_hash": "unknown",
                               "reason": "legacy classifier result has no persisted derivation binding"}),
                        row["source_id"],
                    ),
                )
            if row["rule_derivation_json"] in {None, "", "{}"}:
                connection.execute(
                    """UPDATE emails SET rule_status='STALE', rule_labels_json='[]', rule_evidence_json='[]',
                       rule_derivation_json=? WHERE source_id=?""",
                    (
                        _json({"status": "STALE", "input_fingerprint": "unknown", "method": "unknown",
                               "schema_version": "unknown", "settings_hash": "unknown",
                               "reason": "legacy rule output has no persisted derivation binding"}),
                        row["source_id"],
                    ),
                )
            if row["extraction_derivation_json"] in {None, "", "{}"}:
                connection.execute(
                    """UPDATE emails SET extraction_suggestions_json=?, extraction_derivation_json=?
                       WHERE source_id=?""",
                    (
                        _json({"method": "unknown", "status": "STALE", "spans": [], "targets": {},
                               "human_gold": False, "review_required": True,
                               "limitations": "Legacy extraction output is unbound; reimport to regenerate."}),
                        _json({"status": "STALE", "input_fingerprint": "unknown", "method": "unknown",
                               "schema_version": "unknown", "settings_hash": "unknown",
                               "reason": "legacy extraction output has no persisted derivation binding"}),
                        row["source_id"],
                    ),
                )
            connection.execute(
                """INSERT OR IGNORE INTO source_aliases(
                    source_name, source_alias, observation_key, canonical_source_id, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (row["source_name"], row["source_id"], observation_key, row["source_id"], row["imported_at"] or _now()),
            )



    def import_records(
        self,
        records: Iterable[EmailRecord],
        *,
        classifier: DiagnosticClassifier | None = None,
    ) -> dict[str, int]:
        inserted = updated = 0
        imported_at = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                if not isinstance(record, EmailRecord):
                    raise TypeError("EmailStore accepts normalized EmailRecord instances only")
                info = _timestamp_info(record)
                sent_utc = _sent_timestamp(record, info)
                fingerprint = _input_fingerprint(record, info)
                identity_parts = _identity_parts(record, info)
                identity = _identity_fingerprint(identity_parts)
                observation_key = _observation_key(record)
                existing_observation = connection.execute(
                    "SELECT * FROM source_observations WHERE observation_key=?", (observation_key,)
                ).fetchone()
                diagnostic = classifier.predict(record) if classifier is not None else None
                baseline = rule_baseline(record)
                extraction = extract_rule_suggestions(record)

                if existing_observation is not None:
                    canonical_id = existing_observation["canonical_source_id"]
                    existing_email = connection.execute(
                        "SELECT * FROM emails WHERE source_id=?", (canonical_id,)
                    ).fetchone()
                    changed = existing_observation["input_fingerprint"] != fingerprint
                    if changed and existing_email is not None and existing_email["annotation_method"] != "UNANNOTATED":
                        if existing_email["input_fingerprint"] != fingerprint:
                            raise AnnotationConflictError(
                                "This source has annotations tied to its imported text; the changed source was not imported. "
                                "Use a new source ID or review the change manually."
                            )
                    revision = int(existing_observation["source_revision"] or 1)
                    if changed:
                        revision = int(existing_email["source_revision"] or 1) + 1
                        self._upsert_thread(connection, record, imported_at)
                        self._upsert_email(
                            connection,
                            record,
                            canonical_id,
                            baseline,
                            extraction,
                            diagnostic,
                            imported_at,
                            fingerprint,
                            identity,
                            identity_parts,
                            info,
                            source_revision=revision,
                            force_input_update=True,
                        )
                        self._record_message_revision(connection, canonical_id, imported_at)
                    elif existing_email is not None and existing_email["input_fingerprint"] == fingerprint:
                        self._upsert_thread(connection, record, imported_at)
                        self._upsert_email(
                            connection,
                            record,
                            canonical_id,
                            baseline,
                            extraction,
                            diagnostic,
                            imported_at,
                            fingerprint,
                            identity,
                            identity_parts,
                            info,
                            source_revision=int(existing_email["source_revision"] or 1),
                            force_input_update=False,
                        )
                    self._upsert_observation(
                        connection,
                        observation_key,
                        canonical_id,
                        record,
                        fingerprint,
                        identity,
                        info,
                        sent_utc,
                        imported_at,
                        revision,
                    )
                    self._upsert_alias(connection, record, observation_key, canonical_id, imported_at)
                    updated += 1
                    continue

                duplicate = self._find_cross_adapter_duplicate(connection, record, identity, identity_parts, sent_utc)
                if duplicate is not None:
                    canonical_id = duplicate["source_id"]
                    if diagnostic is not None and duplicate["input_fingerprint"] == fingerprint:
                        self._update_classifier(connection, canonical_id, diagnostic, fingerprint)
                    self._upsert_thread(connection, record, imported_at)
                    self._upsert_observation(
                        connection,
                        observation_key,
                        canonical_id,
                        record,
                        fingerprint,
                        identity,
                        info,
                        sent_utc,
                        imported_at,
                        1,
                    )
                    self._upsert_alias(connection, record, observation_key, canonical_id, imported_at)
                    self._refresh_threads(connection)
                    updated += 1
                    continue

                canonical_id = record.source_id
                if connection.execute("SELECT 1 FROM emails WHERE source_id=?", (canonical_id,)).fetchone():
                    # Reused adapter IDs with incompatible message content must remain distinct.
                    canonical_id = f"{record.source_id}#collision:{identity[:20]}"
                    suffix = 1
                    while connection.execute("SELECT 1 FROM emails WHERE source_id=?", (canonical_id,)).fetchone():
                        suffix += 1
                        canonical_id = f"{record.source_id}#collision:{identity[:20]}:{suffix}"
                self._upsert_thread(connection, record, imported_at)
                self._upsert_email(
                    connection,
                    record,
                    canonical_id,
                    baseline,
                    extraction,
                    diagnostic,
                    imported_at,
                    fingerprint,
                    identity,
                    identity_parts,
                    info,
                    source_revision=1,
                    force_input_update=False,
                )
                self._upsert_observation(
                    connection,
                    observation_key,
                    canonical_id,
                    record,
                    fingerprint,
                    identity,
                    info,
                    sent_utc,
                    imported_at,
                    1,
                )
                self._upsert_alias(connection, record, observation_key, canonical_id, imported_at)
                self._record_message_revision(connection, canonical_id, imported_at)
                if canonical_id == record.source_id:
                    inserted += 1
                else:
                    updated += 1
            self._recompute_conversations(connection)
        return {"inserted": inserted, "updated": updated, "total": inserted + updated}

    @staticmethod
    def _find_cross_adapter_duplicate(
        connection: sqlite3.Connection,
        record: EmailRecord,
        identity: str,
        parts: dict[str, Any],
        sent_utc: str | None,
    ) -> sqlite3.Row | None:
        if record.message_id:
            candidates = connection.execute(
                "SELECT * FROM emails WHERE message_id=? ORDER BY source_id", (record.message_id,)
            ).fetchall()
            for candidate in candidates:
                if candidate["identity_fingerprint"] != identity:
                    continue
                prior_sent = candidate["identity_sent_timestamp_utc"]
                prior_known = bool(candidate["identity_sent_time_known"])
                if prior_known and sent_utc and prior_sent != sent_utc:
                    continue
                return candidate
            return None

        # Missing IDs can only alias when the envelope and sent time are strong enough.
        if not sent_utc or not parts["sender"] or not parts["recipients"] or not parts["subject"] or not parts["body_raw"].strip():
            return None
        candidates = connection.execute(
            "SELECT * FROM emails WHERE message_id IS NULL OR message_id='' ORDER BY source_id"
        ).fetchall()
        for candidate in candidates:
            if candidate["identity_fingerprint"] != identity:
                continue
            if not candidate["identity_sent_time_known"] or candidate["identity_sent_timestamp_utc"] != sent_utc:
                continue
            return candidate
        return None

    @staticmethod
    def _upsert_thread(connection: sqlite3.Connection, record: EmailRecord, now: str) -> None:
        thread_id = record.canonical_thread_id
        connection.execute(
            """INSERT INTO threads(thread_id, first_timestamp, latest_timestamp, message_count)
               VALUES (?, ?, ?, 0) ON CONFLICT(thread_id) DO NOTHING""",
            (thread_id, None, None),
        )

    @staticmethod
    def _diagnostic_derivation(diagnostic: dict[str, Any], fingerprint: str) -> dict[str, Any]:
        method = diagnostic.get("method")
        settings = diagnostic.get("settings", diagnostic.get("configuration"))
        settings_hash = diagnostic.get("settings_hash")
        if not isinstance(settings_hash, str) or not settings_hash:
            settings_hash = _sha256(settings) if settings is not None else "unknown"
        return {
            "input_fingerprint": fingerprint,
            "model": diagnostic.get("model_id", diagnostic.get("model", "unknown")),
            "method": method if isinstance(method, str) else "unknown",
            "run_id": diagnostic.get("run_id", "unknown"),
            "schema_version": diagnostic.get("schema_version", diagnostic.get("label_schema_version", "unknown")),
            "settings_hash": settings_hash,
        }

    @staticmethod
    def _record_message_revision(
        connection: sqlite3.Connection, canonical_id: str, recorded_at: str
    ) -> None:
        row = connection.execute("SELECT * FROM emails WHERE source_id=?", (canonical_id,)).fetchone()
        if row is None:
            return
        connection.execute(
            """INSERT OR IGNORE INTO message_revisions(
                source_id, source_revision, input_fingerprint, identity_fingerprint,
                payload_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                canonical_id,
                max(1, int(row["source_revision"] or 1)),
                row["input_fingerprint"],
                row["identity_fingerprint"],
                _json(dict(row)),
                recorded_at,
            ),
        )

    @classmethod
    def _update_classifier(
        cls,
        connection: sqlite3.Connection,
        canonical_id: str,
        diagnostic: dict[str, Any],
        fingerprint: str,
    ) -> None:
        connection.execute(
            """UPDATE emails SET classifier_status=?, classifier_method=?, classifier_run_id=?,
               classifier_labels_json=?, classifier_scores_json=?,
               classifier_scope_uncertainty_available=?, classifier_derivation_json=?, updated_at=?
               WHERE source_id=?""",
            (
                diagnostic.get("status"),
                diagnostic.get("method"),
                diagnostic.get("run_id"),
                _json(diagnostic.get("labels", [])),
                _json(diagnostic.get("scores", {})),
                None
                if diagnostic.get("scope_uncertainty_available") is None
                else int(bool(diagnostic.get("scope_uncertainty_available"))),
                _json(cls._diagnostic_derivation(diagnostic, fingerprint)),
                _now(),
                canonical_id,
            ),
        )

    @classmethod
    def _upsert_email(
        cls,
        connection: sqlite3.Connection,
        record: EmailRecord,
        canonical_id: str,
        baseline: ReviewSuggestion,
        extraction: dict[str, Any],
        diagnostic: dict[str, Any] | None,
        now: str,
        fingerprint: str,
        identity: str,
        identity_parts: dict[str, Any],
        info: dict[str, Any],
        *,
        source_revision: int,
        force_input_update: bool,
    ) -> None:
        evidence = [
            {"label": item.label, "field": item.field, "text": item.text, "rule_id": item.rule_id}
            for item in baseline.evidence
        ]
        existing = connection.execute("SELECT * FROM emails WHERE source_id=?", (canonical_id,)).fetchone()
        rule_derivation = {
            "input_fingerprint": fingerprint,
            "method": baseline.method,
            "schema_version": "rule-baseline-v1",
            "settings_hash": "default",
        }
        extraction_derivation = {
            "input_fingerprint": fingerprint,
            "method": extraction.get("method", "unknown"),
            "schema_version": "rule-extraction-v1",
            "settings_hash": "default",
        }
        diagnostic_values = (
            diagnostic.get("status") if diagnostic else None,
            diagnostic.get("method") if diagnostic else None,
            diagnostic.get("run_id") if diagnostic else None,
            _json(diagnostic.get("labels", [])) if diagnostic else "[]",
            _json(diagnostic.get("scores", {})) if diagnostic else "{}",
            None
            if not diagnostic or diagnostic.get("scope_uncertainty_available") is None
            else int(bool(diagnostic.get("scope_uncertainty_available"))),
            _json(cls._diagnostic_derivation(diagnostic, fingerprint)) if diagnostic else "{}",
        )
        thread_hint = _explicit_thread_hint(record)
        values = (
            canonical_id,
            record.source_name,
            record.project_or_list,
            record.message_id,
            record.in_reply_to,
            _json(list(record.references)),
            record.canonical_thread_id,
            record.subject,
            record.sender,
            _json(list(record.recipients)),
            record.timestamp,
            info.get("utc"),
            _json(info),
            getattr(record, "sent_at", None),
            getattr(record, "received_at", None),
            getattr(record, "timestamp_kind", "unspecified"),
            record.body_raw,
            record.current_message,
            record.quoted_history,
            _json(list(record.attachment_names)),
            _json(record.provenance),
            record.license_or_terms_note,
            record.scope,
            _json(list(record.labels)),
            _json([dict(span) for span in record.spans]),
            record.annotation_method,
            record.body_sha256,
            baseline.status,
            _json(list(baseline.labels)),
            _json(evidence),
            _json(extraction),
            _json(rule_derivation),
            _json(extraction_derivation),
            *diagnostic_values,
            fingerprint,
            identity,
            identity_parts.get("sent_utc"),
            int(bool(identity_parts.get("sent_time_known"))),
            source_revision,
            thread_hint,
            now,
            now,
        )
        if existing is None:
            connection.execute(
                """INSERT INTO emails(
                    source_id, source_name, project_or_list, message_id, in_reply_to,
                    references_json, thread_id, subject, sender, recipients_json,
                    timestamp, timestamp_utc, timestamp_info_json, sent_at, received_at, timestamp_kind,
                    body_raw, current_message,
                    quoted_history, attachment_names_json, provenance_json, license_or_terms_note,
                    scope, labels_json, spans_json, annotation_method, body_sha256,
                    rule_status, rule_labels_json, rule_evidence_json, extraction_suggestions_json,
                    rule_derivation_json, extraction_derivation_json,
                    classifier_status, classifier_method, classifier_run_id, classifier_labels_json,
                    classifier_scores_json, classifier_scope_uncertainty_available, classifier_derivation_json,
                    input_fingerprint, identity_fingerprint, identity_sent_timestamp_utc,
                    identity_sent_time_known, source_revision, source_thread_hint, imported_at, updated_at
                ) VALUES (""" + ",".join("?" for _ in values) + ")",
                values,
            )
            return

        annotation_method = existing["annotation_method"]
        if annotation_method != "UNANNOTATED" and existing["input_fingerprint"] != fingerprint:
            raise AnnotationConflictError(
                "This source has annotations tied to its imported text; the changed source was not imported. "
                "Use a new source ID or review the change manually."
            )
        annotation_update_allowed = annotation_method == "UNANNOTATED"
        if force_input_update:
            # A changed input invalidates all diagnostics unless this import rescored it.
            classifier_fields = diagnostic_values if diagnostic is not None else (None, None, None, "[]", "{}", None, "{}")
        else:
            classifier_fields = diagnostic_values
        if diagnostic is None and not force_input_update:
            classifier_fields = (
                existing["classifier_status"],
                existing["classifier_method"],
                existing["classifier_run_id"],
                existing["classifier_labels_json"],
                existing["classifier_scores_json"],
                existing["classifier_scope_uncertainty_available"],
                existing["classifier_derivation_json"],
            )
        connection.execute(
            """UPDATE emails SET
                source_name=?, project_or_list=?, message_id=?, in_reply_to=?, references_json=?,
                thread_id=?, subject=?, sender=?, recipients_json=?, timestamp=?, timestamp_utc=?,
                timestamp_info_json=?, sent_at=?, received_at=?, timestamp_kind=?, body_raw=?, current_message=?, quoted_history=?,
                attachment_names_json=?, provenance_json=?, license_or_terms_note=?,
                scope=CASE WHEN ? THEN ? ELSE scope END,
                labels_json=CASE WHEN ? THEN ? ELSE labels_json END,
                spans_json=CASE WHEN ? THEN ? ELSE spans_json END,
                annotation_method=CASE WHEN ? THEN ? ELSE annotation_method END,
                body_sha256=?, rule_status=?, rule_labels_json=?, rule_evidence_json=?,
                extraction_suggestions_json=?, rule_derivation_json=?, extraction_derivation_json=?,
                classifier_status=?, classifier_method=?,
                classifier_run_id=?, classifier_labels_json=?, classifier_scores_json=?,
                classifier_scope_uncertainty_available=?, classifier_derivation_json=?,
                input_fingerprint=?, identity_fingerprint=?, identity_sent_timestamp_utc=?,
                identity_sent_time_known=?, source_revision=?, source_thread_hint=?, updated_at=?
                WHERE source_id=?""",
            (
                record.source_name,
                record.project_or_list,
                record.message_id,
                record.in_reply_to,
                _json(list(record.references)),
                record.canonical_thread_id,
                record.subject,
                record.sender,
                _json(list(record.recipients)),
                record.timestamp,
                info.get("utc"),
                _json(info),
                getattr(record, "sent_at", None),
                getattr(record, "received_at", None),
                getattr(record, "timestamp_kind", "unspecified"),
                record.body_raw,
                record.current_message,
                record.quoted_history,
                _json(list(record.attachment_names)),
                _json(record.provenance),
                record.license_or_terms_note,
                int(annotation_update_allowed),
                record.scope,
                int(annotation_update_allowed),
                _json(list(record.labels)),
                int(annotation_update_allowed),
                _json([dict(span) for span in record.spans]),
                int(annotation_update_allowed),
                record.annotation_method,
                record.body_sha256,
                baseline.status,
                _json(list(baseline.labels)),
                _json(evidence),
                _json(extraction),
                _json(rule_derivation),
                _json(extraction_derivation),
                *classifier_fields,
                fingerprint,
                identity,
                identity_parts.get("sent_utc"),
                int(bool(identity_parts.get("sent_time_known"))),
                source_revision,
                thread_hint,
                now,
                canonical_id,
            ),
        )

    @staticmethod
    def _upsert_observation(
        connection: sqlite3.Connection,
        observation_key: str,
        canonical_id: str,
        record: EmailRecord,
        fingerprint: str,
        identity: str,
        info: dict[str, Any],
        sent_utc: str | None,
        now: str,
        revision: int,
    ) -> None:
        metadata = _observation_metadata(record, info, sent_utc)
        connection.execute(
            """INSERT INTO source_observations(
                observation_key, canonical_source_id, source_name, adapter_source_id,
                observation_metadata_json, provenance_json, source_access_scope,
                input_fingerprint, identity_fingerprint, source_revision,
                timestamp_info_json, sent_timestamp_utc, sent_time_known, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(observation_key) DO UPDATE SET
                canonical_source_id=excluded.canonical_source_id,
                source_name=excluded.source_name,
                adapter_source_id=excluded.adapter_source_id,
                observation_metadata_json=excluded.observation_metadata_json,
                provenance_json=excluded.provenance_json,
                source_access_scope=excluded.source_access_scope,
                input_fingerprint=excluded.input_fingerprint,
                identity_fingerprint=excluded.identity_fingerprint,
                source_revision=excluded.source_revision,
                timestamp_info_json=excluded.timestamp_info_json,
                sent_timestamp_utc=excluded.sent_timestamp_utc,
                sent_time_known=excluded.sent_time_known,
                observed_at=excluded.observed_at""",
            (
                observation_key,
                canonical_id,
                record.source_name,
                record.source_id,
                _json(metadata),
                _json(record.provenance),
                _source_access_scope(record),
                fingerprint,
                identity,
                revision,
                _json(info),
                sent_utc,
                int(sent_utc is not None),
                now,
            ),
        )

    @staticmethod
    def _upsert_alias(
        connection: sqlite3.Connection,
        record: EmailRecord,
        observation_key: str,
        canonical_id: str,
        now: str,
    ) -> None:
        connection.execute(
            """INSERT INTO source_aliases(source_name, source_alias, observation_key, canonical_source_id, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source_name, source_alias, observation_key) DO UPDATE SET
                   canonical_source_id=excluded.canonical_source_id""",
            (record.source_name, record.source_id, observation_key, canonical_id, now),
        )

    @staticmethod
    def _recompute_conversations(connection: sqlite3.Connection) -> None:
        """Rebuild conversation components so late parents can join transitive replies."""
        rows = connection.execute(
            """SELECT source_id, message_id, in_reply_to, references_json, source_thread_hint,
                      timestamp_utc, timestamp_info_json
               FROM emails ORDER BY source_id"""
        ).fetchall()
        if not rows:
            connection.execute("DELETE FROM threads")
            return
        # Keep the foreign key valid while old components are replaced. A single
        # temporary parent lets this operation remain atomic without cascading or
        # rebuilding the user's email rows.
        sentinel = "__conversation_rebuild__"
        connection.execute(
            "INSERT OR IGNORE INTO threads(thread_id, message_count) VALUES (?, 0)", (sentinel,)
        )
        connection.execute("UPDATE emails SET thread_id=?", (sentinel,))
        connection.execute("DELETE FROM threads WHERE thread_id<>?", (sentinel,))
        by_source = {row["source_id"]: row for row in rows}
        parent = {source_id: source_id for source_id in by_source}

        def find(source_id: str) -> str:
            while parent[source_id] != source_id:
                parent[source_id] = parent[parent[source_id]]
                source_id = parent[source_id]
            return source_id

        def union(left: str, right: str) -> None:
            a, b = find(left), find(right)
            if a != b:
                parent[max(a, b)] = min(a, b)

        links = {source_id: {"message_ids": set(), "references": set(), "hints": set()} for source_id in by_source}
        for row in rows:
            source_id = row["source_id"]
            if row["message_id"]:
                links[source_id]["message_ids"].add(row["message_id"])
            links[source_id]["references"].update(_message_reference_ids(row))
            if row["source_thread_hint"]:
                links[source_id]["hints"].add(row["source_thread_hint"])
        observations = connection.execute(
            "SELECT canonical_source_id, observation_metadata_json FROM source_observations"
        ).fetchall()
        for observation in observations:
            source_id = observation["canonical_source_id"]
            if source_id not in links:
                continue
            metadata = _load_json(observation["observation_metadata_json"], {})
            message_id = metadata.get("message_id")
            if isinstance(message_id, str) and message_id:
                links[source_id]["message_ids"].add(message_id)
            in_reply_to = metadata.get("in_reply_to")
            if isinstance(in_reply_to, str) and in_reply_to:
                links[source_id]["references"].add(in_reply_to)
            references = metadata.get("references", [])
            if isinstance(references, list):
                links[source_id]["references"].update(value for value in references if isinstance(value, str) and value)
            hint = metadata.get("thread_hint")
            if isinstance(hint, str) and hint and not hint.startswith(("message-thread:", "message:")):
                links[source_id]["hints"].add(hint)

        by_message_id: dict[str, set[str]] = {}
        for source_id, values in links.items():
            for message_id in values["message_ids"]:
                by_message_id.setdefault(message_id, set()).add(source_id)

        # Explicit Thread-Index/conversation hints are strong evidence. Aliased
        # observations can contribute additional hints to the same canonical node.
        by_hint: dict[str, list[str]] = {}
        for source_id, values in links.items():
            for hint in values["hints"]:
                by_hint.setdefault(hint, []).append(source_id)
        for members in by_hint.values():
            unique_members = sorted(set(members))
            for source_id in unique_members[1:]:
                union(unique_members[0], source_id)

        unresolved: dict[str, list[str]] = {}
        for source_id, values in links.items():
            for reference in values["references"]:
                candidates = by_message_id.get(reference, set())
                if len(candidates) == 1:
                    union(source_id, next(iter(candidates)))
                elif not candidates:
                    unresolved.setdefault(reference, []).append(source_id)
                # Reused parent IDs are ambiguous; do not join their children.
        for reference, members in unresolved.items():
            if not by_message_id.get(reference) and members:
                for source_id in sorted(set(members))[1:]:
                    union(sorted(set(members))[0], source_id)

        components: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            components.setdefault(find(row["source_id"]), []).append(row)

        desired: dict[str, str] = {}
        component_candidates: dict[str, str] = {}
        for root_id, members in components.items():
            member_ids = {row["source_id"] for row in members}
            hint_sets = [links[row["source_id"]]["hints"] for row in members]
            shared_hints = set.intersection(*hint_sets) if hint_sets and all(hint_sets) else set()
            root_messages = [
                row
                for row in members
                if links[row["source_id"]]["message_ids"] and not links[row["source_id"]]["references"]
            ]
            if len(shared_hints) == 1:
                preferred = next(iter(shared_hints))
            elif root_messages:
                root_messages.sort(key=lambda row: (row["timestamp_utc"] is None, row["timestamp_utc"] or "", row["source_id"]))
                root_message_ids = sorted(links[root_messages[0]["source_id"]]["message_ids"])
                preferred = f"message-thread:{root_message_ids[0]}"
            else:
                referenced = sorted(
                    {
                        reference
                        for row in members
                        for reference in links[row["source_id"]]["references"]
                        if reference not in by_message_id or not (by_message_id[reference] & member_ids)
                    }
                )
                hints = sorted({hint for row in members for hint in links[row["source_id"]]["hints"]})
                preferred = (
                    f"message-thread:{referenced[0]}"
                    if referenced
                    else hints[0]
                    if hints
                    else f"message:{min(member_ids)}"
                )
            component_candidates[root_id] = preferred

        # Duplicate reused root Message-IDs can produce separate components. Give each
        # a stable distinct thread key rather than accidentally joining them by key.
        by_preferred: dict[str, list[str]] = {}
        for root_id, preferred in component_candidates.items():
            by_preferred.setdefault(preferred, []).append(root_id)
        for preferred, roots in by_preferred.items():
            if len(roots) == 1:
                desired[roots[0]] = preferred
                continue
            for root_id in sorted(roots):
                stable = min(row["source_id"] for row in components[root_id])
                desired[root_id] = f"{preferred}#variant:{hashlib.sha256(stable.encode()).hexdigest()[:12]}"

        for root_id, members in components.items():
            thread_id = desired[root_id]
            timestamps = [row["timestamp_utc"] for row in members if row["timestamp_utc"]]
            source_names = connection.execute(
                "SELECT DISTINCT source_name FROM emails WHERE source_id IN ("
                + ",".join("?" for _ in members)
                + ") ORDER BY source_name",
                tuple(row["source_id"] for row in members),
            ).fetchall()
            projects = connection.execute(
                "SELECT DISTINCT project_or_list FROM emails WHERE project_or_list<>'' AND source_id IN ("
                + ",".join("?" for _ in members)
                + ") ORDER BY project_or_list",
                tuple(row["source_id"] for row in members),
            ).fetchall()
            connection.execute(
                """INSERT INTO threads(
                    thread_id, first_timestamp, latest_timestamp, message_count,
                    source_names_json, project_or_lists_json
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    thread_id,
                    min(timestamps) if timestamps else None,
                    max(timestamps) if timestamps else None,
                    len(members),
                    _json([row[0] for row in source_names]),
                    _json([row[0] for row in projects]),
                ),
            )
            connection.executemany(
                "UPDATE emails SET thread_id=? WHERE source_id=?",
                ((thread_id, row["source_id"]) for row in members),
            )
        connection.execute("DELETE FROM threads WHERE thread_id=?", (sentinel,))

    @staticmethod
    def _refresh_threads(connection: sqlite3.Connection) -> None:
        """Compatibility alias retained for earlier local-product callers."""
        EmailStore._recompute_conversations(connection)

    def _observations_for(self, canonical_source_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM source_observations WHERE canonical_source_id=?
                   ORDER BY source_name, adapter_source_id, observation_key""",
                (canonical_source_id,),
            ).fetchall()
        observations = []
        for row in rows:
            observations.append(
                {
                    "source_name": row["source_name"],
                    "source_id": row["adapter_source_id"],
                    "metadata": _load_json(row["observation_metadata_json"], {}),
                    "provenance": _load_json(row["provenance_json"], {}),
                    "source_access_scope": row["source_access_scope"],
                    "input_fingerprint": row["input_fingerprint"],
                    "source_revision": row["source_revision"],
                    "timestamp_info": _load_json(row["timestamp_info_json"], {}),
                    "sent_timestamp_utc": row["sent_timestamp_utc"],
                    "sent_time_known": bool(row["sent_time_known"]),
                    "observed_at": row["observed_at"],
                }
            )
        return observations

    def list_emails(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM emails ORDER BY timestamp_utc IS NULL, timestamp_utc DESC, source_id"
            ).fetchall()
        result = [self._decode_email(row) for row in rows]
        for email in result:
            email["source_observations"] = self._observations_for(email["source_id"])
        return result

    def get_email(self, source_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            aliases = connection.execute(
                "SELECT DISTINCT canonical_source_id FROM source_aliases WHERE source_alias=? ORDER BY canonical_source_id",
                (source_id,),
            ).fetchall()
            if len(aliases) > 1:
                return None
            if len(aliases) == 1:
                row = connection.execute(
                    "SELECT * FROM emails WHERE source_id=?", (aliases[0]["canonical_source_id"],)
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM emails WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            return None
        result = self._decode_email(row)
        result["source_observations"] = self._observations_for(result["source_id"])
        return result

    def get_canonical_email(self, canonical_source_id: str) -> dict[str, Any] | None:
        """Lookup an explicit canonical ID from list_emails, never an adapter alias.

        get_email remains fail-closed for ambiguous adapter aliases. Product
        records bind to this separate canonical namespace.
        """
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM emails WHERE source_id=?", (canonical_source_id,)).fetchone()
        if row is None:
            return None
        result = self._decode_email(row)
        result["source_observations"] = self._observations_for(canonical_source_id)
        return result

    def list_threads(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM threads ORDER BY latest_timestamp DESC, thread_id").fetchall()
        return [
            {
                "thread_id": row["thread_id"],
                "first_timestamp": row["first_timestamp"],
                "latest_timestamp": row["latest_timestamp"],
                "message_count": row["message_count"],
                "source_names": _load_json(row["source_names_json"], []),
                "project_or_lists": _load_json(row["project_or_lists_json"], []),
            }
            for row in rows
        ]

    def count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0])

    @staticmethod
    def _decode_email(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for column, target, default in (
            ("references_json", "references", []),
            ("recipients_json", "recipients", []),
            ("attachment_names_json", "attachment_names", []),
            ("provenance_json", "provenance", {}),
            ("labels_json", "labels", []),
            ("spans_json", "spans", []),
            ("rule_labels_json", "rule_labels", []),
            ("rule_evidence_json", "rule_evidence", []),
            ("extraction_suggestions_json", "extraction_suggestions", {}),
            ("rule_derivation_json", "rule_derivation", {}),
            ("extraction_derivation_json", "extraction_derivation", {}),
            ("classifier_labels_json", "classifier_labels", []),
            ("classifier_scores_json", "classifier_scores", {}),
            ("classifier_derivation_json", "classifier_derivation", {}),
            ("timestamp_info_json", "timestamp_info", {}),
        ):
            value[target] = _load_json(value.pop(column), default)
        value["classifier_scope_uncertainty_available"] = (
            None
            if value["classifier_scope_uncertainty_available"] is None
            else bool(value["classifier_scope_uncertainty_available"])
        )
        value["identity_sent_time_known"] = bool(value["identity_sent_time_known"])
        return value
