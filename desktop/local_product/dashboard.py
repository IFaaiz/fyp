"""Authenticated PySide6 client for the localhost project review API.

This module is intentionally independent from the local archive database. All
reading and writing happens through the bearer-authenticated HTTP API.
"""
from __future__ import annotations

import json
import os
import tempfile
from itertools import count
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .view_text import FIELD_LABELS, FLAG_LABELS, candidate_text, item_text


_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class APIError(RuntimeError):
    """Safe-to-display API failure; response bodies and credentials are omitted."""


class APIClient:
    """Small injectable transport for the authenticated localhost API."""

    def __init__(self, base_url: str, token: str, *, opener: Callable[..., Any] | None = None) -> None:
        parsed = urlsplit(base_url.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("The project API must use a localhost URL.")
        if not token or not token.strip():
            raise ValueError("A project API bearer token is required.")
        self.base_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        self.token = token.strip()
        self._opener = opener or build_opener(_NoRedirectHandler()).open

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        binary: bool = False,
    ) -> Any:
        url = self.base_url + "/" + path.lstrip("/")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with self._opener(request, timeout=30) as response:
                data = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise APIError("The local API response exceeded the dashboard size limit.")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise APIError("Authentication failed. Check the local API token.") from None
            if exc.code == 409:
                raise APIError("The record changed on the server. Refresh it and review the latest state.") from None
            raise APIError(f"The local API returned HTTP {exc.code}.") from None
        except (URLError, TimeoutError, OSError):
            raise APIError("Could not reach the local project API. Check that the server is running.") from None

        if binary:
            return data
        if not data:
            return {}
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise APIError("The local API returned an invalid response.") from None
        if not isinstance(decoded, (dict, list)):
            raise APIError("The local API returned an unexpected response.")
        return decoded


try:
    from PySide6.QtCore import QThread, QTimer, Qt, Signal
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    QT_AVAILABLE = True
except ImportError:  # APIClient remains importable for headless transport checks.
    QT_AVAILABLE = False


def _record_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields")
    return fields if isinstance(fields, dict) else record


def _identifier(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


_EDITABLE_FIELDS = (
    "title", "kind", "owner", "department", "due", "due_text", "status",
    "project_id", "requested_document",
)


if QT_AVAILABLE:
    class _APIWorker(QThread):
        succeeded = Signal(int, object)
        failed = Signal(int, str)

        def __init__(
            self,
            request_id: int,
            transport: APIClient,
            method: str,
            path: str,
            payload: dict[str, Any] | None,
            binary: bool,
        ) -> None:
            super().__init__()
            self.request_id = request_id
            self.transport = transport
            self.method = method
            self.path = path
            self.payload = payload
            self.binary = binary

        def run(self) -> None:
            try:
                result = self.transport.request(
                    self.method, self.path, self.payload, binary=self.binary
                )
            except APIError as exc:
                self.failed.emit(self.request_id, str(exc))
            except Exception:
                self.failed.emit(self.request_id, "The local API request failed.")
            else:
                self.succeeded.emit(self.request_id, result)


    class DashboardWindow(QMainWindow):
        """Review inbox, candidates, linked items and decision history."""

        def __init__(
            self,
            base_url: str,
            token: str,
            *,
            transport: APIClient | None = None,
        ) -> None:
            super().__init__()
            # The Windows offscreen plugin may have no system font database.
            # Read the installed OS font for reproducible, legible visual QA.
            if not QFontDatabase.families() and os.name == "nt":
                font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
                if font.is_file():
                    QFontDatabase.addApplicationFont(str(font))
            if "Segoe UI" in QFontDatabase.families():
                self.setFont(QFont("Segoe UI", 11))
            self.transport = transport or APIClient(base_url, token)
            self._ids = count(1)
            self._workers: dict[int, _APIWorker] = {}
            self._callbacks: dict[int, Callable[[Any], None]] = {}
            self._request_error_titles: dict[int, str] = {}
            self._close_pending = False
            self.emails: list[dict[str, Any]] = []
            self.candidates: list[dict[str, Any]] = []
            self.items: list[dict[str, Any]] = []
            self.current_email: dict[str, Any] | None = None
            self.current_candidate: dict[str, Any] | None = None
            self.current_item: dict[str, Any] | None = None
            self._proposal_target_baseline: dict[str, str] | None = None
            self._selected_detail_id: str | None = None
            self._latest_items_request = 0

            self.setWindowTitle("Project Review Dashboard")
            self.resize(1440, 920)
            self._build_ui()
            self.refresh_all()

        def _build_ui(self) -> None:
            central = QWidget(self)
            root = QVBoxLayout(central)
            toolbar = QHBoxLayout()
            self.refresh_button = QPushButton("Refresh")
            self.export_button = QPushButton("Export Excel…")
            toolbar.addWidget(self.refresh_button)
            toolbar.addWidget(self.export_button)
            toolbar.addStretch(1)
            self.connection_label = QLabel("Connected to localhost project API")
            toolbar.addWidget(self.connection_label)
            root.addLayout(toolbar)
            self.data_notice = QLabel("Review suggestions before approval. Confirm the owner, date and target item.")
            self.data_notice.setWordWrap(True)
            root.addWidget(self.data_notice)

            self.tabs = QTabWidget()
            self.inbox_tab = self._build_inbox_tab()
            self.candidates_tab = self._build_candidates_tab()
            self.items_tab = self._build_items_tab()
            self.tabs.addTab(self.inbox_tab, "Inbox & Propose")
            self.tabs.addTab(self.candidates_tab, "Candidate Review")
            self.tabs.addTab(self.items_tab, "Items & History")
            root.addWidget(self.tabs, stretch=1)
            self.setCentralWidget(central)
            self.statusBar().showMessage("Loading inbox, candidates, and items…")
            self.refresh_button.clicked.connect(self.refresh_all)
            self.export_button.clicked.connect(self.choose_export)

        def _build_inbox_tab(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            splitter = QSplitter(Qt.Orientation.Horizontal)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.addWidget(QLabel("Inbox sources"))
            self.email_list = QListWidget()
            self.email_list.setWordWrap(True)
            self.email_list.currentRowChanged.connect(self._select_email)
            left_layout.addWidget(self.email_list, stretch=1)
            splitter.addWidget(left)

            right = QWidget()
            right_layout = QVBoxLayout(right)
            self.email_heading = QLabel("Select a source message")
            self.email_heading.setWordWrap(True)
            self.email_metadata = QLabel("")
            self.email_metadata.setWordWrap(True)
            self.source_evidence = QPlainTextEdit()
            self.source_evidence.setReadOnly(True)
            self.source_evidence.setPlaceholderText("The selected source's current message appears here.")
            self.raw_evidence = QPlainTextEdit()
            self.raw_evidence.setReadOnly(True)
            self.quoted_evidence = QPlainTextEdit()
            self.quoted_evidence.setReadOnly(True)
            source_tabs = QTabWidget()
            source_tabs.addTab(self.source_evidence, "Current authored text")
            source_tabs.addTab(self.raw_evidence, "Original message")
            source_tabs.addTab(self.quoted_evidence, "Quoted / uncertain history")
            right_layout.addWidget(self.email_heading)
            right_layout.addWidget(self.email_metadata)
            right_layout.addWidget(QLabel("Exact current-message evidence"))
            right_layout.addWidget(source_tabs, stretch=2)

            proposal = QGroupBox("Proposal fields (unknown values may stay blank)")
            proposal_layout = QFormLayout(proposal)
            self.proposal_fields = self._make_fields(proposal_layout)
            self.proposal_target = QComboBox()
            self.proposal_target.addItem("Create a new item", None)
            self.proposal_target.currentIndexChanged.connect(self._proposal_target_changed)
            proposal_layout.addRow("Target item (optional)", self.proposal_target)
            right_layout.addWidget(proposal, stretch=1)

            actions = QHBoxLayout()
            self.suggest_button = QPushButton("Create review suggestion")
            self.propose_button = QPushButton("Propose from this message")
            self.suggest_button.setEnabled(False)
            self.propose_button.setEnabled(False)
            actions.addWidget(self.suggest_button)
            actions.addWidget(self.propose_button)
            right_layout.addLayout(actions)
            self.suggest_button.clicked.connect(self._suggest_from_email)
            self.propose_button.clicked.connect(self._propose_from_email)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 3)
            outer.addWidget(splitter)
            return page

        def _build_candidates_tab(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            splitter = QSplitter(Qt.Orientation.Horizontal)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.addWidget(QLabel("Review candidates"))
            self.candidate_list = QListWidget()
            self.candidate_list.setWordWrap(True)
            self.candidate_list.currentRowChanged.connect(self._select_candidate)
            left_layout.addWidget(self.candidate_list, stretch=1)
            splitter.addWidget(left)

            right = QWidget()
            right_layout = QVBoxLayout(right)
            self.candidate_heading = QLabel("Select a candidate")
            self.candidate_heading.setWordWrap(True)
            right_layout.addWidget(self.candidate_heading)
            self.candidate_target_button = QPushButton("No linked target item")
            self.candidate_target_button.setEnabled(False)
            self.candidate_target_button.clicked.connect(self._open_candidate_target)
            right_layout.addWidget(self.candidate_target_button)
            self.candidate_target_hint = QLabel("")
            self.candidate_target_hint.setWordWrap(True)
            right_layout.addWidget(self.candidate_target_hint)
            self.candidate_review_flags = QLabel("")
            self.candidate_review_flags.setWordWrap(True)
            self.candidate_source_binding = QLabel("")
            self.candidate_source_binding.setWordWrap(True)
            right_layout.addWidget(self.candidate_review_flags)
            right_layout.addWidget(self.candidate_source_binding)

            detail_split = QSplitter(Qt.Orientation.Vertical)
            evidence_box = QWidget()
            evidence_layout = QVBoxLayout(evidence_box)
            evidence_layout.setContentsMargins(0, 0, 0, 0)
            evidence_layout.addWidget(QLabel("Exact evidence and source/version metadata"))
            self.candidate_evidence = QPlainTextEdit()
            self.candidate_evidence.setReadOnly(True)
            evidence_layout.addWidget(self.candidate_evidence)
            detail_split.addWidget(evidence_box)

            fields_box = QGroupBox("Proposed or corrected fields")
            fields_layout = QFormLayout(fields_box)
            self.candidate_fields = self._make_fields(fields_layout)
            detail_split.addWidget(fields_box)
            detail_split.setSizes([300, 310])
            right_layout.addWidget(detail_split, stretch=1)

            note_row = QHBoxLayout()
            self.decision_note = QLineEdit()
            self.decision_note.setPlaceholderText("Explain a correction; optional for approval or rejection")
            note_row.addWidget(QLabel("Note"))
            note_row.addWidget(self.decision_note, stretch=1)
            right_layout.addLayout(note_row)
            buttons = QHBoxLayout()
            self.approve_button = QPushButton("Approve")
            self.correct_button = QPushButton("Correct")
            self.reject_button = QPushButton("Reject")
            for button in (self.approve_button, self.correct_button, self.reject_button):
                button.setEnabled(False)
                buttons.addWidget(button)
            right_layout.addLayout(buttons)
            self.approve_button.clicked.connect(lambda: self._decide("APPROVE"))
            self.correct_button.clicked.connect(lambda: self._decide("CORRECT"))
            self.reject_button.clicked.connect(lambda: self._decide("REJECT"))
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 3)
            outer.addWidget(splitter)
            return page

        def _build_items_tab(self) -> QWidget:
            page = QWidget()
            outer = QVBoxLayout(page)
            filters = QHBoxLayout()
            self.item_search = QLineEdit()
            self.item_search.setPlaceholderText("Search items")
            self.item_status = QComboBox()
            self.item_status.setEditable(False)
            self.item_status.addItems([
                "All statuses", "OPEN", "IN_PROGRESS", "DELIVERED", "COMPLETED", "CANCELLED"
            ])
            self.item_status.setCurrentIndex(0)
            self.apply_filter_button = QPushButton("Apply filters")
            filters.addWidget(QLabel("Search"))
            filters.addWidget(self.item_search, stretch=1)
            filters.addWidget(QLabel("Status"))
            filters.addWidget(self.item_status)
            filters.addWidget(self.apply_filter_button)
            outer.addLayout(filters)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.addWidget(QLabel("Project items"))
            self.item_list = QListWidget()
            self.item_list.setWordWrap(True)
            self.item_list.currentRowChanged.connect(self._select_item)
            left_layout.addWidget(self.item_list, stretch=1)
            splitter.addWidget(left)

            right = QWidget()
            right_layout = QVBoxLayout(right)
            self.item_heading = QLabel("Select an item to inspect its evidence and history")
            self.item_heading.setWordWrap(True)
            self.item_metadata = QLabel("")
            self.item_metadata.setWordWrap(True)
            self.item_detail = QPlainTextEdit()
            self.item_detail.setReadOnly(True)
            self.item_detail.setPlaceholderText("Exact evidence, item fields, and decision history appear here.")
            right_layout.addWidget(self.item_heading)
            right_layout.addWidget(self.item_metadata)
            right_layout.addWidget(self.item_detail, stretch=1)
            undo_row = QHBoxLayout()
            self.undo_note = QLineEdit()
            self.undo_note.setPlaceholderText("Optional undo note")
            self.undo_button = QPushButton("Undo latest decision")
            self.undo_button.setEnabled(False)
            undo_row.addWidget(self.undo_note, stretch=1)
            undo_row.addWidget(self.undo_button)
            right_layout.addLayout(undo_row)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 3)
            outer.addWidget(splitter, stretch=1)

            self._filter_timer = QTimer(self)
            self._filter_timer.setSingleShot(True)
            self._filter_timer.setInterval(250)
            self._filter_timer.timeout.connect(self.load_items)
            self.item_search.textChanged.connect(lambda _text: self._filter_timer.start())
            self.item_status.currentTextChanged.connect(lambda _text: self._filter_timer.start())
            self.apply_filter_button.clicked.connect(self.load_items)
            self.undo_button.clicked.connect(self._undo_item)
            return page

        @staticmethod
        def _make_fields(layout: QFormLayout) -> dict[str, QLineEdit]:
            result: dict[str, QLineEdit] = {}
            for field in _EDITABLE_FIELDS:
                edit = QLineEdit()
                edit.setClearButtonEnabled(True)
                edit.setAccessibleName(FIELD_LABELS.get(field, field))
                if field == "due":
                    edit.setPlaceholderText("YYYY-MM-DD or timestamp with timezone; leave unresolved dates blank")
                elif field == "kind":
                    edit.setPlaceholderText("TASK (default), MEETING, DOCUMENT_REQUEST, DEPARTMENTAL_INPUT, APPROVAL, FOLLOW_UP")
                elif field == "status":
                    edit.setPlaceholderText("OPEN (default), IN_PROGRESS, DELIVERED, COMPLETED, CANCELLED")
                elif field == "project_id":
                    edit.setPlaceholderText("default if not specified")
                result[field] = edit
                layout.addRow(FIELD_LABELS.get(field, field) + (" *" if field == "title" else ""), edit)
            return result

        @staticmethod
        def _read_fields(controls: dict[str, QLineEdit]) -> dict[str, str]:
            return {name: control.text().strip() for name, control in controls.items()}

        @staticmethod
        def _field_patch(
            controls: dict[str, QLineEdit], baseline: dict[str, Any]
        ) -> dict[str, str]:
            current = DashboardWindow._read_fields(controls)
            return {
                name: value
                for name, value in current.items()
                if value != ("" if baseline.get(name) is None else str(baseline.get(name, "")))
            }

        @staticmethod
        def _fill_fields(controls: dict[str, QLineEdit], values: Any) -> None:
            values = values if isinstance(values, dict) else {}
            for name, control in controls.items():
                value = values.get(name)
                control.setText("" if value is None else str(value))

        def _request(
            self,
            method: str,
            path: str,
            payload: dict[str, Any] | None = None,
            *,
            callback: Callable[[Any], None] | None = None,
            binary: bool = False,
            error_title: str = "Project API request failed",
        ) -> int:
            request_id = next(self._ids)
            worker = _APIWorker(request_id, self.transport, method, path, payload, binary)
            worker.succeeded.connect(self._request_succeeded)
            worker.failed.connect(self._request_failed)
            worker.finished.connect(self._worker_finished, Qt.QueuedConnection)
            self._workers[request_id] = worker
            if callback is not None:
                self._callbacks[request_id] = callback
            self._request_error_titles[request_id] = error_title
            worker.start()
            return request_id

        def _worker_finished(self) -> None:
            """Retire workers on the GUI thread, then honor a deferred close."""
            worker = self.sender()
            request_id = getattr(worker, "request_id", None)
            if request_id is not None:
                self._workers.pop(request_id, None)
                self._callbacks.pop(request_id, None)
                self._request_error_titles.pop(request_id, None)
            if self._close_pending and not self._workers:
                QTimer.singleShot(0, self.close)

        def closeEvent(self, event: Any) -> None:
            # urllib requests have a 30-second timeout. Keep the window alive
            # until those workers finish so Qt never destroys a running QThread.
            if self._workers:
                self._close_pending = True
                self.statusBar().showMessage(
                    "Finishing local API requests before closing…"
                )
                event.ignore()
                return
            self._close_pending = False
            event.accept()

        def refresh_all(self) -> None:
            self.load_emails()
            self.load_candidates()
            self.load_items()

        def load_emails(self) -> None:
            self.statusBar().showMessage("Loading source inbox…")
            self._request("GET", "/api/emails", callback=self._set_emails, error_title="Inbox unavailable")

        def load_candidates(self) -> None:
            self.statusBar().showMessage("Loading review candidates…")
            self._request(
                "GET", "/api/candidates", callback=self._set_candidates,
                error_title="Candidates unavailable",
            )

        def load_items(self) -> None:
            search = self.item_search.text().strip()
            status = self.item_status.currentText().strip()
            if status.lower() == "all statuses":
                status = ""
            params = {key: value for key, value in (("search", search), ("status", status)) if value}
            path = "/api/items" + ("?" + urlencode(params) if params else "")
            request_id_box: dict[str, int] = {}

            def apply_items(result: Any) -> None:
                if request_id_box.get("id") == self._latest_items_request:
                    self._set_items(result)

            request_id = self._request(
                "GET", path, callback=apply_items, error_title="Items unavailable"
            )
            request_id_box["id"] = request_id
            self._latest_items_request = request_id

        def _request_succeeded(self, request_id: int, result: Any) -> None:
            callback = self._callbacks.pop(request_id, None)
            self._request_error_titles.pop(request_id, None)
            if callback is None:
                return
            try:
                callback(result)
            except Exception:
                self._show_error("Project API response error", "The local API returned data the dashboard could not display.")

        def _request_failed(self, request_id: int, message: str) -> None:
            self._callbacks.pop(request_id, None)
            title = self._request_error_titles.pop(request_id, "Project API request failed")
            self._show_error(title, message)

        def _show_error(self, title: str, message: str) -> None:
            QMessageBox.warning(self, title, message)
            self.statusBar().showMessage(message, 8000)

        @staticmethod
        def _list_response(result: Any, key: str) -> list[dict[str, Any]]:
            values = result.get(key, []) if isinstance(result, dict) else []
            return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []

        def _set_emails(self, result: Any) -> None:
            selected_id = _identifier(self.current_email or {}, "source_id", "id")
            self.emails = self._list_response(result, "emails")
            if any((row.get("provenance") or {}).get("synthetic") or "SYNTHETIC" in str(row.get("source_name", "")).upper() for row in self.emails):
                self.data_notice.setText("Synthetic demonstration sources are present. These examples provide functional checks, not accuracy evidence.")
            self.email_list.blockSignals(True)
            self.email_list.clear()
            selected_row = 0 if self.emails else -1
            for row, email in enumerate(self.emails):
                source_id = _identifier(email, "source_id", "id")
                subject = email.get("subject") or "(no subject)"
                item = QListWidgetItem(f"{subject}  ·  {source_id or 'unknown source'}")
                item.setData(Qt.ItemDataRole.UserRole, email)
                self.email_list.addItem(item)
                if source_id == selected_id:
                    selected_row = row
            self.email_list.blockSignals(False)
            self.email_list.setCurrentRow(selected_row)
            self._select_email(selected_row)
            self.statusBar().showMessage(f"Loaded {len(self.emails)} source messages", 4000)

        def _select_email(self, row: int) -> None:
            email = self.emails[row] if 0 <= row < len(self.emails) else None
            self.current_email = email
            if email is None:
                self.email_heading.setText("Select a source message")
                self.email_metadata.clear()
                self.source_evidence.clear()
                self.raw_evidence.clear()
                self.quoted_evidence.clear()
                self.suggest_button.setEnabled(False)
                self.propose_button.setEnabled(False)
                return
            source_id = _identifier(email, "source_id", "id")
            body = email.get("current_message") or ""
            self.email_heading.setText(f"{email.get('subject') or '(no subject)'} · {source_id or 'unknown source'}")
            self.email_metadata.setText(
                f"Source: {email.get('source_name') or 'unknown'} · "
                f"Source revision: {email.get('source_revision', 'unknown')} · "
                f"Input fingerprint: {email.get('input_fingerprint', 'unknown')}"
            )
            self.source_evidence.setPlainText(str(body))
            self.raw_evidence.setPlainText(str(email.get("body_raw") or ""))
            self.quoted_evidence.setPlainText(str(email.get("quoted_history") or ""))
            self._fill_fields(self.proposal_fields, {})
            self._proposal_target_baseline = None
            self.proposal_target.setCurrentIndex(0)
            self.suggest_button.setEnabled(bool(source_id))
            self.propose_button.setEnabled(bool(source_id) and isinstance(body, str) and bool(body))

        def _suggest_from_email(self) -> None:
            if not self.current_email:
                return
            source_id = _identifier(self.current_email, "source_id", "id")
            if not source_id:
                return
            self._request(
                "POST", "/api/suggest", {"source_id": source_id},
                callback=lambda _result: self._after_mutation("Suggestion created"),
                error_title="Could not create suggestion",
            )

        def _propose_from_email(self) -> None:
            if not self.current_email:
                return
            source_id = _identifier(self.current_email, "source_id", "id")
            body = self.current_email.get("current_message") or ""
            if not source_id or not isinstance(body, str) or not body:
                return
            target_item_id = self.proposal_target.currentData()
            if target_item_id is None:
                fields = {
                    name: value for name, value in self._read_fields(self.proposal_fields).items()
                    if value
                }
                if not fields.get("title"):
                    self.statusBar().showMessage("Enter a title before proposing a new item.", 6000)
                    return
            else:
                fields = self._field_patch(
                    self.proposal_fields, self._proposal_target_baseline or {}
                )
                if not fields:
                    self.statusBar().showMessage("Change at least one item field before proposing an update.", 6000)
                    return
                if any(not fields[name] for name in ("title", "kind", "project_id", "status") if name in fields):
                    self._show_error(
                        "Required field cannot be blank",
                        "Title, kind, project ID, and status must have values.",
                    )
                    return
            payload: dict[str, Any] = {
                "source_id": source_id,
                "fields": fields,
                "evidence": {
                    "field": "current_message",
                    "start": 0,
                    "end": len(body),
                    "text": body,
                },
            }
            if target_item_id is not None:
                payload["target_item_id"] = target_item_id
            self._request(
                "POST", "/api/propose", payload,
                callback=lambda _result: self._after_mutation("Proposal submitted"),
                error_title="Could not submit proposal",
            )

        def _set_candidates(self, result: Any) -> None:
            selected_id = _identifier(self.current_candidate or {}, "candidate_id", "id")
            self.candidates = self._list_response(result, "candidates")
            self.candidate_list.blockSignals(True)
            self.candidate_list.clear()
            selected_row = 0 if self.candidates else -1
            for row, candidate in enumerate(self.candidates):
                candidate_id = _identifier(candidate, "candidate_id", "id")
                fields = candidate.get("proposed_fields") or candidate.get("fields") or {}
                fields = fields if isinstance(fields, dict) else {}
                title = fields.get("title") or "untitled proposal"
                source_id = candidate.get("source_id") or "unknown source"
                target_id = _identifier(candidate, "target_item_id", "item_id")
                target = f" → item {target_id}" if target_id is not None else " → new item"
                item = QListWidgetItem(
                    f"{candidate.get('status', 'REVIEW')} · {title} · {source_id}{target}"
                )
                item.setData(Qt.ItemDataRole.UserRole, candidate)
                self.candidate_list.addItem(item)
                if candidate_id == selected_id:
                    selected_row = row
            self.candidate_list.blockSignals(False)
            self.candidate_list.setCurrentRow(selected_row)
            self._select_candidate(selected_row)
            self.statusBar().showMessage(f"Loaded {len(self.candidates)} review candidates", 4000)

        def _select_candidate(self, row: int) -> None:
            candidate = self.candidates[row] if 0 <= row < len(self.candidates) else None
            self.current_candidate = candidate
            enabled = bool(
                candidate
                and candidate.get("status") == "PENDING"
                and not candidate.get("source_conflict")
            )
            for button in (self.approve_button, self.correct_button, self.reject_button):
                button.setEnabled(enabled)
            self.reject_button.setEnabled(bool(candidate and candidate.get("status") == "PENDING"))
            if candidate is None:
                self.candidate_heading.setText("Select a candidate")
                self.candidate_target_button.setText("No linked target item")
                self.candidate_target_button.setEnabled(False)
                self.candidate_target_hint.clear()
                self.candidate_review_flags.clear()
                self.candidate_source_binding.clear()
                self.candidate_evidence.clear()
                self._fill_fields(self.candidate_fields, {})
                return
            candidate_id = _identifier(candidate, "candidate_id", "id")
            target_id = _identifier(candidate, "target_item_id", "item_id")
            source_id = candidate.get("source_id") or "unknown source"
            target_item = self._find_item(target_id)
            target_label = self._item_label(target_item) if target_item else f"Item {target_id}"
            proposed = candidate.get("proposed_fields") or candidate.get("fields") or {}
            recorded = candidate.get("status") != "PENDING"
            if recorded and isinstance(candidate.get("decision_fields"), dict):
                proposed = {**proposed, **candidate["decision_fields"]}
            self.candidate_heading.setText(
                f"Candidate {candidate_id or 'unknown'} · {candidate.get('status', 'REVIEW')} · source {source_id}"
            )
            self.candidate_target_button.setText(
                f"Open linked target: {target_label}" if target_id is not None else "No linked target item"
            )
            self.candidate_target_button.setEnabled(target_id is not None)
            self.candidate_target_hint.setText(
                "Decision recorded. Current approved facts and history appear in Items & History."
                if recorded else "Target is fixed for this candidate. Reject and propose again if it should link elsewhere."
                if target_id is not None else "Approval creates a new item from this proposal."
            )
            flags = candidate.get("review_flags", [])
            flags = [str(flag) for flag in flags] if isinstance(flags, list) else []
            self.candidate_review_flags.setText(
                ("Original suggestion warnings: " if recorded else "Needs review: ") + ("; ".join(FLAG_LABELS.get(flag, flag) for flag in flags) if flags else "No unresolved suggestion fields")
            )
            conflict = bool(candidate.get("source_conflict"))
            conflict_reason = candidate.get("source_conflict_reason") or "source revision or fingerprint changed"
            self.candidate_source_binding.setText(
                f"Source binding: CONFLICT — {conflict_reason}"
                if conflict else "Source binding: current"
            )
            self.candidate_source_binding.setStyleSheet(
                "color: #a32020; font-weight: bold;" if conflict else "color: #276749;"
            )
            self.candidate_evidence.setPlainText(candidate_text(candidate))
            self._fill_fields(self.candidate_fields, proposed)
            for control in self.candidate_fields.values():
                control.setReadOnly(recorded)
            self.decision_note.setText(candidate.get("note") or "")
            self.decision_note.setReadOnly(recorded)

        def _decide(self, decision: str) -> None:
            candidate = self.current_candidate
            if candidate is None or decision not in {"APPROVE", "CORRECT", "REJECT"}:
                return
            candidate_id = _identifier(candidate, "candidate_id", "id")
            version = _identifier(candidate, "version", "expected_version")
            if candidate_id is None or version is None:
                self._show_error("Candidate cannot be reviewed", "The candidate is missing its ID or version. Refresh the review list.")
                return
            payload: dict[str, Any] = {
                "candidate_id": candidate_id,
                "decision": decision,
                "expected_version": version,
                "note": self.decision_note.text().strip(),
            }
            proposed = candidate.get("proposed_fields") or candidate.get("fields") or {}
            proposed = proposed if isinstance(proposed, dict) else {}
            patch = self._field_patch(self.candidate_fields, proposed)
            if decision == "APPROVE" and patch:
                self._show_error(
                    "Fields were changed",
                    "Approve accepts the exact proposal. Use Correct and add a note to save field changes.",
                )
                return
            if decision == "CORRECT":
                if not patch:
                    self.statusBar().showMessage("Change at least one proposed field before correcting.", 6000)
                    return
                if not payload["note"]:
                    self._show_error("Correction note required", "Add a short note explaining the field correction.")
                    return
                if any(not patch[name] for name in ("title", "kind", "project_id", "status") if name in patch):
                    self._show_error(
                        "Required field cannot be blank",
                        "Title, kind, project ID, and status must have values.",
                    )
                    return
                payload["fields"] = patch
            self._request(
                "POST", "/api/decide", payload,
                callback=lambda _result: self._after_mutation(f"Candidate {decision.lower()}d"),
                error_title=f"Could not {decision.lower()} candidate",
            )

        def _open_candidate_target(self) -> None:
            target_id = _identifier(self.current_candidate or {}, "target_item_id", "item_id")
            if target_id is None:
                return
            self.tabs.setCurrentWidget(self.items_tab)
            row = next(
                (index for index, item in enumerate(self.items) if str(_identifier(item, "item_id", "id")) == str(target_id)),
                -1,
            )
            if row >= 0:
                self.item_list.setCurrentRow(row)
            else:
                self._load_item_detail(target_id)

        def _set_items(self, result: Any) -> None:
            selected_id = _identifier(self.current_item or {}, "item_id", "id")
            self.items = self._list_response(result, "items")
            self.item_list.blockSignals(True)
            self.item_list.clear()
            selected_row = 0 if self.items else -1
            for row, item_record in enumerate(self.items):
                item_id = _identifier(item_record, "item_id", "id")
                item = QListWidgetItem(self._item_label(item_record))
                item.setData(Qt.ItemDataRole.UserRole, item_record)
                self.item_list.addItem(item)
                if str(item_id) == str(selected_id):
                    selected_row = row
            self.item_list.blockSignals(False)
            self._refresh_target_choices()
            self.item_list.setCurrentRow(selected_row)
            self._select_item(selected_row)
            self.statusBar().showMessage(f"Loaded {len(self.items)} items", 4000)

        @staticmethod
        def _item_label(item: dict[str, Any]) -> str:
            fields = _record_fields(item)
            item_id = _identifier(item, "item_id", "id") or "unknown"
            title = fields.get("title") or "untitled item"
            status = item.get("status") or fields.get("status") or "unknown status"
            return f"{title} · {status} · {str(item_id)[:8]}"

        def _find_item(self, item_id: Any) -> dict[str, Any] | None:
            if item_id is None:
                return None
            return next(
                (item for item in self.items if str(_identifier(item, "item_id", "id")) == str(item_id)),
                None,
            )

        def _refresh_target_choices(self) -> None:
            selected = self.proposal_target.currentData()
            self.proposal_target.blockSignals(True)
            self.proposal_target.clear()
            self.proposal_target.addItem("Create a new item", None)
            for item in self.items:
                item_id = _identifier(item, "item_id", "id")
                if item_id is not None:
                    self.proposal_target.addItem(self._item_label(item), item_id)
            if selected is not None and self.proposal_target.findData(selected) < 0:
                selected_item = self._find_item(selected)
                if selected_item is None and str(_identifier(self.current_item or {}, "item_id", "id")) == str(selected):
                    selected_item = self.current_item
                if selected_item is not None:
                    self.proposal_target.addItem(self._item_label(selected_item), selected)
                else:
                    self.proposal_target.addItem(f"Existing item · {selected}", selected)
            match = self.proposal_target.findData(selected)
            self.proposal_target.setCurrentIndex(match if match >= 0 else 0)
            self.proposal_target.blockSignals(False)

        def _proposal_target_changed(self, _index: int) -> None:
            target_id = self.proposal_target.currentData()
            if target_id is None:
                self._proposal_target_baseline = None
                self._fill_fields(self.proposal_fields, {})
                return
            target = self._find_item(target_id)
            if target is None and str(_identifier(self.current_item or {}, "item_id", "id")) == str(target_id):
                target = self.current_item
            if target is None:
                self._proposal_target_baseline = {}
                self._fill_fields(self.proposal_fields, {})
                return
            values = dict(_record_fields(target))
            values.setdefault("status", target.get("status", ""))
            self._proposal_target_baseline = {
                name: "" if values.get(name) is None else str(values.get(name, ""))
                for name in _EDITABLE_FIELDS
            }
            self._fill_fields(self.proposal_fields, self._proposal_target_baseline)

        def _select_item(self, row: int) -> None:
            item_record = self.items[row] if 0 <= row < len(self.items) else None
            item_id = _identifier(item_record or {}, "item_id", "id")
            self.current_item = item_record
            if item_id is None:
                self._selected_detail_id = None
                self.item_heading.setText("Select an item to inspect its evidence and history")
                self.item_metadata.clear()
                self.item_detail.clear()
                self.undo_button.setEnabled(False)
                return
            self._load_item_detail(item_id)

        def _load_item_detail(self, item_id: Any) -> None:
            safe_id = quote(str(item_id), safe="")
            expected = str(item_id)
            self._selected_detail_id = expected
            self._request(
                "GET", f"/api/items/{safe_id}",
                callback=lambda result: self._set_item_detail_if_current(expected, result),
                error_title="Item details unavailable",
            )

        def _set_item_detail_if_current(self, expected_id: str, result: Any) -> None:
            if self._selected_detail_id == expected_id:
                self._set_item_detail(expected_id, result)

        def _set_item_detail(self, expected_id: str, result: Any) -> None:
            if not isinstance(result, dict):
                raise ValueError("item detail is not an object")
            item = result.get("item") if isinstance(result.get("item"), dict) else result
            if item is not result:
                item = dict(item)
                for key in ("history", "evidence"):
                    if key in result and key not in item:
                        item[key] = result[key]
            item_id = str(_identifier(item, "item_id", "id") or expected_id)
            self.current_item = item
            fields = _record_fields(item)
            self.item_heading.setText(f"{fields.get('title') or 'Project item'} · {item_id}")
            self.item_metadata.setText(
                f"Status: {item.get('status') or fields.get('status') or 'unknown'} · "
                f"Version: {item.get('version', 'unknown')}"
            )
            self.item_detail.setPlainText(item_text(item))
            self.undo_button.setEnabled(item.get("version") is not None)

        def _undo_item(self) -> None:
            item = self.current_item
            if item is None:
                return
            item_id = _identifier(item, "item_id", "id")
            version = item.get("version")
            if item_id is None or version is None:
                self._show_error("Item cannot be undone", "The item is missing its ID or version. Refresh the item list.")
                return
            payload = {
                "item_id": item_id,
                "expected_version": version,
                "note": self.undo_note.text().strip(),
            }
            self._request(
                "POST", "/api/undo", payload,
                callback=lambda _result: self._after_mutation("Latest decision undone"),
                error_title="Could not undo item decision",
            )

        def _after_mutation(self, message: str) -> None:
            self.statusBar().showMessage(message, 6000)
            self.refresh_all()

        def choose_export(self) -> None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export project items", "ProjectItems.xlsx", "Excel workbook (*.xlsx)"
            )
            if not path:
                return
            output_path = Path(path)
            self._request(
                "POST", "/api/export", {}, binary=True,
                callback=lambda data: self._save_export(output_path, data),
                error_title="Could not export project items",
            )

        def _save_export(self, path: Path, data: Any) -> None:
            if not isinstance(data, bytes) or not data:
                raise ValueError("export is empty")
            if not path.suffix:
                path = path.with_suffix(".xlsx")
            if path.suffix.lower() != ".xlsx":
                self._show_error("Choose an Excel filename", "The export filename must end in .xlsx.")
                return
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp.xlsx", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(data)
                temporary.replace(path)
            except OSError:
                self._show_error("Could not save export", "Choose a writable location and try again.")
                return
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.statusBar().showMessage(f"Excel export saved to {path}", 8000)
            QMessageBox.information(self, "Export complete", f"Saved workbook to:\n{path}")

else:
    class DashboardWindow:  # pragma: no cover - used only when desktop extras are absent.
        def __init__(self, base_url: str, token: str, **_: Any) -> None:
            raise RuntimeError("PySide6 is required to open the project dashboard.")


def run_dashboard(base_url: str, token: str) -> int:
    """Open the authenticated dashboard and return the Qt event-loop result."""
    if not QT_AVAILABLE:
        raise RuntimeError("PySide6 is required to open the project dashboard.")
    app = QApplication.instance() or QApplication([])
    window = DashboardWindow(base_url, token)
    window.show()
    result = app.exec()
    # Normal window closes are deferred by closeEvent. Also cover external
    # QApplication.quit() calls while retaining the window and thread objects
    # until every bounded (30-second) request has stopped.
    while window._workers:
        for worker in tuple(window._workers.values()):
            worker.wait(31_000)
        app.processEvents()
    return result
