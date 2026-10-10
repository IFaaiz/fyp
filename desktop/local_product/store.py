"""Canonical local SQLite archive for imported messages and review-only cues."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .classification import DiagnosticClassifier, ReviewSuggestion, rule_baseline
from .extraction import extract_rule_suggestions
from .models import EmailRecord


SCHEMA_VERSION = 2


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
        with closing(self._connect()) as connection, connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than this app supports ({SCHEMA_VERSION})."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    first_timestamp TEXT,
                    latest_timestamp TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    source_names_json TEXT NOT NULL DEFAULT '[]',
                    project_or_lists_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS emails (
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
                    body_sha256 TEXT NOT NULL,
                    rule_status TEXT NOT NULL,
                    rule_labels_json TEXT NOT NULL DEFAULT '[]',
                    rule_evidence_json TEXT NOT NULL DEFAULT '[]',
                    extraction_suggestions_json TEXT NOT NULL DEFAULT '{}',
                    classifier_status TEXT,
                    classifier_method TEXT,
                    classifier_run_id TEXT,
                    classifier_labels_json TEXT NOT NULL DEFAULT '[]',
                    classifier_scores_json TEXT NOT NULL DEFAULT '{}',
                    classifier_scope_uncertainty_available INTEGER,
                    imported_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id);
                CREATE INDEX IF NOT EXISTS idx_emails_timestamp ON emails(timestamp);
                CREATE INDEX IF NOT EXISTS idx_emails_source_name ON emails(source_name);
                """
            )
            existing_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(emails)")
            }
            if "extraction_suggestions_json" not in existing_columns:
                connection.execute(
                    "ALTER TABLE emails ADD COLUMN extraction_suggestions_json TEXT NOT NULL DEFAULT '{}'"
                )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def import_records(
        self,
        records: Iterable[EmailRecord],
        *,
        classifier: DiagnosticClassifier | None = None,
    ) -> dict[str, int]:
        inserted = updated = 0
        imported_at = _now()
        with closing(self._connect()) as connection, connection:
            for record in records:
                if not isinstance(record, EmailRecord):
                    raise TypeError("EmailStore accepts normalized EmailRecord instances only")
                existing = connection.execute(
                    "SELECT annotation_method, subject, current_message FROM emails WHERE source_id = ?",
                    (record.source_id,),
                ).fetchone()
                if existing and existing["annotation_method"] != "UNANNOTATED":
                    if (
                        existing["subject"] != record.subject
                        or existing["current_message"] != record.current_message
                    ):
                        raise AnnotationConflictError(
                            "This source has annotations tied to its subject or authored text; "
                            "the changed source was not imported. Use a new source ID or review the change manually."
                        )
                baseline = rule_baseline(record)
                extraction = extract_rule_suggestions(record)
                diagnostic = classifier.predict(record) if classifier is not None else None
                self._upsert_thread(connection, record, imported_at)
                self._upsert_email(connection, record, baseline, extraction, diagnostic, imported_at)
                if existing is None:
                    inserted += 1
                else:
                    updated += 1
            self._refresh_threads(connection)
        return {"inserted": inserted, "updated": updated, "total": inserted + updated}

    @staticmethod
    def _upsert_thread(connection: sqlite3.Connection, record: EmailRecord, now: str) -> None:
        thread_id = record.canonical_thread_id
        connection.execute(
            """
            INSERT INTO threads(thread_id, first_timestamp, latest_timestamp, message_count)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(thread_id) DO NOTHING
            """,
            (thread_id, record.timestamp, record.timestamp),
        )

    @staticmethod
    def _upsert_email(
        connection: sqlite3.Connection,
        record: EmailRecord,
        baseline: ReviewSuggestion,
        extraction: dict[str, Any],
        diagnostic: dict[str, Any] | None,
        now: str,
    ) -> None:
        classifier_method = diagnostic.get("method") if diagnostic else None
        classifier_status = diagnostic.get("status") if diagnostic else None
        classifier_run_id = diagnostic.get("run_id") if diagnostic else None
        classifier_labels = diagnostic.get("labels", []) if diagnostic else []
        classifier_scores = diagnostic.get("scores", {}) if diagnostic else {}
        scope_uncertainty = diagnostic.get("scope_uncertainty_available") if diagnostic else None
        evidence = [
            {"label": item.label, "field": item.field, "text": item.text, "rule_id": item.rule_id}
            for item in baseline.evidence
        ]
        connection.execute(
            """
            INSERT INTO emails(
                source_id, source_name, project_or_list, message_id, in_reply_to,
                references_json, thread_id, subject, sender, recipients_json,
                timestamp, body_raw, current_message, quoted_history,
                attachment_names_json, provenance_json, license_or_terms_note,
                scope, labels_json, spans_json, annotation_method, body_sha256,
                rule_status, rule_labels_json, rule_evidence_json,
                extraction_suggestions_json,
                classifier_status, classifier_method, classifier_run_id,
                classifier_labels_json, classifier_scores_json,
                classifier_scope_uncertainty_available, imported_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(source_id) DO UPDATE SET
                source_name=excluded.source_name,
                project_or_list=excluded.project_or_list,
                message_id=excluded.message_id,
                in_reply_to=excluded.in_reply_to,
                references_json=excluded.references_json,
                thread_id=excluded.thread_id,
                subject=excluded.subject,
                sender=excluded.sender,
                recipients_json=excluded.recipients_json,
                timestamp=excluded.timestamp,
                body_raw=excluded.body_raw,
                current_message=excluded.current_message,
                quoted_history=excluded.quoted_history,
                attachment_names_json=excluded.attachment_names_json,
                provenance_json=excluded.provenance_json,
                license_or_terms_note=excluded.license_or_terms_note,
                scope=CASE WHEN emails.annotation_method='UNANNOTATED' THEN excluded.scope ELSE emails.scope END,
                labels_json=CASE WHEN emails.annotation_method='UNANNOTATED' THEN excluded.labels_json ELSE emails.labels_json END,
                spans_json=CASE WHEN emails.annotation_method='UNANNOTATED' THEN excluded.spans_json ELSE emails.spans_json END,
                annotation_method=CASE WHEN emails.annotation_method='UNANNOTATED' THEN excluded.annotation_method ELSE emails.annotation_method END,
                body_sha256=excluded.body_sha256,
                rule_status=excluded.rule_status,
                rule_labels_json=excluded.rule_labels_json,
                rule_evidence_json=excluded.rule_evidence_json,
                extraction_suggestions_json=excluded.extraction_suggestions_json,
                classifier_status=CASE WHEN excluded.classifier_method IS NULL THEN emails.classifier_status ELSE excluded.classifier_status END,
                classifier_method=CASE WHEN excluded.classifier_method IS NULL THEN emails.classifier_method ELSE excluded.classifier_method END,
                classifier_run_id=CASE WHEN excluded.classifier_method IS NULL THEN emails.classifier_run_id ELSE excluded.classifier_run_id END,
                classifier_labels_json=CASE WHEN excluded.classifier_method IS NULL THEN emails.classifier_labels_json ELSE excluded.classifier_labels_json END,
                classifier_scores_json=CASE WHEN excluded.classifier_method IS NULL THEN emails.classifier_scores_json ELSE excluded.classifier_scores_json END,
                classifier_scope_uncertainty_available=CASE WHEN excluded.classifier_method IS NULL THEN emails.classifier_scope_uncertainty_available ELSE excluded.classifier_scope_uncertainty_available END,
                updated_at=excluded.updated_at
            """,
            (
                record.source_id,
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
                classifier_status,
                classifier_method,
                classifier_run_id,
                _json(classifier_labels),
                _json(classifier_scores),
                None if scope_uncertainty is None else int(bool(scope_uncertainty)),
                now,
                now,
            ),
        )

    @staticmethod
    def _refresh_threads(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM threads WHERE NOT EXISTS (SELECT 1 FROM emails WHERE emails.thread_id=threads.thread_id)")
        connection.execute(
            """
            UPDATE threads SET
                first_timestamp=(SELECT MIN(timestamp) FROM emails WHERE emails.thread_id=threads.thread_id),
                latest_timestamp=(SELECT MAX(timestamp) FROM emails WHERE emails.thread_id=threads.thread_id),
                message_count=(SELECT COUNT(*) FROM emails WHERE emails.thread_id=threads.thread_id),
                source_names_json=(SELECT json_group_array(source_name) FROM (SELECT DISTINCT source_name FROM emails WHERE emails.thread_id=threads.thread_id ORDER BY source_name)),
                project_or_lists_json=(SELECT json_group_array(project_or_list) FROM (SELECT DISTINCT project_or_list FROM emails WHERE emails.thread_id=threads.thread_id AND project_or_list<>'' ORDER BY project_or_list))
            """
        )

    def list_emails(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM emails ORDER BY timestamp IS NULL, timestamp DESC, source_id"
            ).fetchall()
        return [self._decode_email(row) for row in rows]

    def get_email(self, source_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM emails WHERE source_id = ?", (source_id,)).fetchone()
        return self._decode_email(row) if row else None

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
            ("classifier_labels_json", "classifier_labels", []),
            ("classifier_scores_json", "classifier_scores", {}),
        ):
            value[target] = _load_json(value.pop(column), default)
        value["classifier_scope_uncertainty_available"] = (
            None
            if value["classifier_scope_uncertainty_available"] is None
            else bool(value["classifier_scope_uncertainty_available"])
        )
        return value
