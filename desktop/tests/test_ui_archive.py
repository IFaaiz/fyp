"""Synthetic checks at the desktop display boundary, without Outlook access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

try:
    from PySide6.QtCore import QSortFilterProxyModel, Qt
    from PySide6.QtWidgets import QApplication
    from desktop.local_product.ui import EmailTableModel
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class ArchiveDisplayTests(unittest.TestCase):
    def test_desktop_date_sort_matches_known_utc_instead_of_display_offset(self):
        app = QApplication.instance() or QApplication([])
        rows = [
            {"source_id": "earlier", "timestamp": "2026-10-11T10:00:00+05:00", "timestamp_utc": "2026-10-11T05:00:00.000000Z"},
            {"source_id": "later", "timestamp": "2026-10-11T06:00:00Z", "timestamp_utc": "2026-10-11T06:00:00.000000Z"},
        ]
        model = EmailTableModel(rows)
        proxy = QSortFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.setSortRole(Qt.ItemDataRole.UserRole)
        proxy.sort(0, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        first = proxy.mapToSource(proxy.index(0, 0))
        self.assertEqual(model.record_at(first.row())["source_id"], "later")
        self.assertEqual(proxy.data(proxy.index(0, 0)), "2026-10-11T06:00:00Z")
