"""Small PySide6 read-only archive browser."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .adapters import OutlookAdapter, iter_path_records
from .excel_export import export_excel
from .store import EmailStore


def _ensure_readable_font(app: QApplication) -> None:
    """Load Segoe UI from Windows when Qt reports no installed font families."""
    if QFontDatabase.families():
        return
    windows_dir = os.environ.get("WINDIR")
    if not windows_dir:
        return
    font_path = Path(windows_dir) / "Fonts" / "segoeui.ttf"
    if not font_path.is_file():
        return
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id < 0:
        return
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        app.setFont(QFont(families[0], 10))


class EmailTableModel(QAbstractTableModel):
    HEADERS = ("Date", "Subject", "Sender", "Source", "Thread", "Source labels", "Baseline")
    FIELDS = ("timestamp", "subject", "sender", "source_name", "thread_id", "labels", "rule_status")

    def __init__(self, rows: list[dict[str, Any]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = rows or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        value = self.rows[index.row()].get(self.FIELDS[index.column()])
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return "" if value is None else str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def replace_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def record_at(self, row: int) -> dict[str, Any]:
        return self.rows[row]


class MainWindow(QMainWindow):
    def __init__(self, store: EmailStore) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            _ensure_readable_font(app)
        self.store = store
        self.setWindowTitle("FYP Project Email Archive")
        self.resize(1320, 820)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        actions = QHBoxLayout()
        self.import_button = QPushButton("Import .eml / .msg / JSONL")
        self.outlook_button = QPushButton("Import 200 newest Inbox messages")
        self.export_button = QPushButton("Export Excel")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by subject, sender, source, thread, or label")
        actions.addWidget(self.import_button)
        actions.addWidget(self.outlook_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.search, stretch=1)
        layout.addLayout(actions)

        self.status = QLabel()
        layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setMinimumSectionSize(24)
        self.model = EmailTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table.setModel(self.proxy)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((145, 330, 220, 130, 190, 180, 100)):
            self.table.setColumnWidth(column, width)
        splitter.addWidget(self.table)

        details = QWidget()
        detail_layout = QVBoxLayout(details)
        self.subject_label = QLabel("Select a message to view its authored text.")
        self.subject_label.setTextFormat(Qt.TextFormat.PlainText)
        self.subject_label.setWordWrap(True)
        self.message_text = QPlainTextEdit()
        self.message_text.setReadOnly(True)
        self.message_text.setPlaceholderText("Current authored text appears here.")
        self.quote_text = QPlainTextEdit()
        self.quote_text.setReadOnly(True)
        self.quote_text.setPlaceholderText("Quoted history, when found, appears separately.")
        self.extraction_text = QPlainTextEdit()
        self.extraction_text.setReadOnly(True)
        self.extraction_text.setPlaceholderText("No rule extraction suggestions; targets remain unknown.")
        detail_layout.addWidget(self.subject_label)
        detail_layout.addWidget(QLabel("Current authored text"))
        detail_layout.addWidget(self.message_text, stretch=3)
        detail_layout.addWidget(QLabel("Rule extraction suggestions (unvalidated; not gold)"))
        detail_layout.addWidget(self.extraction_text, stretch=1)
        detail_layout.addWidget(QLabel("Quoted history"))
        detail_layout.addWidget(self.quote_text, stretch=1)
        splitter.addWidget(details)
        splitter.setSizes([340, 420])
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

        self.import_button.clicked.connect(self.choose_import)
        self.outlook_button.clicked.connect(self.import_outlook)
        self.export_button.clicked.connect(self.choose_export)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table.selectionModel().currentRowChanged.connect(self.show_selected)
        self.table.doubleClicked.connect(self.show_selected_index)
        self.reload()

    def reload(self) -> None:
        self.model.replace_rows(self.store.list_emails())
        count = self.store.count()
        self.status.setText(
            f"{count} messages · {len(self.store.list_threads())} threads · rule cues stay in REVIEW or ABSTAIN"
        )

    def _import(self, records: Any) -> None:
        result = self.store.import_records(records)
        self.reload()
        QMessageBox.information(
            self,
            "Import complete",
            f"Added {result['inserted']} messages and updated {result['updated']} existing messages.",
        )

    def choose_import(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import local messages or normalized corpus",
            "",
            "Email sources (*.eml *.msg *.jsonl);;All files (*.*)",
        )
        if not paths:
            return
        try:
            self._import(iter_path_records(paths))
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def import_outlook(self) -> None:
        try:
            self._import(OutlookAdapter(limit=200).iter_records())
        except Exception as exc:
            QMessageBox.critical(self, "Outlook import failed", str(exc))

    def choose_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export local archive", "ProjectEmailArchive.xlsx", "Excel workbook (*.xlsx)"
        )
        if not path:
            return
        try:
            written = export_excel(self.store, path)
            QMessageBox.information(self, "Excel export complete", f"Saved local archive to:\n{written}")
        except Exception as exc:
            QMessageBox.critical(self, "Excel export failed", str(exc))

    def show_selected(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            return
        source_index = self.proxy.mapToSource(current)
        row = self.model.record_at(source_index.row())
        self._show_record(row)

    def show_selected_index(self, index: QModelIndex) -> None:
        if index.isValid():
            row = self.model.record_at(self.proxy.mapToSource(index).row())
            self._show_record(row)

    def _show_record(self, row: dict[str, Any]) -> None:
        self.subject_label.setText(
            f"{row.get('subject') or '(no subject)'} · {row.get('sender') or '(unknown sender)'} · "
            f"{row.get('rule_status')} / {', '.join(row.get('rule_labels', [])) or 'no cue'}"
        )
        self.message_text.setPlainText(row.get("current_message") or "")
        self.quote_text.setPlainText(row.get("quoted_history") or "")
        suggestions = row.get("extraction_suggestions", {})
        spans = suggestions.get("spans", [])
        lines = [
            f"{suggestions.get('method', 'RULE_EXTRACTION_V1')} · {suggestions.get('status', 'ABSTAIN')} · human_gold=false",
        ]
        for target, values in suggestions.get("targets", {}).items():
            text_values = [item.get("text", "") for item in values]
            lines.append(f"{target}: " + ("; ".join(text_values) if text_values else "unknown"))
        if not spans:
            lines.append("No exact-text cue found; empty targets remain unknown.")
        self.extraction_text.setPlainText("\n".join(lines))


def run_gui(database_path: str | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    _ensure_readable_font(app)
    window = MainWindow(EmailStore(database_path))
    window.show()
    return app.exec()
