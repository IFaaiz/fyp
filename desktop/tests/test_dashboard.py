"""Synthetic API-client and offscreen dashboard tests; no mailbox or DB access."""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
from urllib.request import HTTPRedirectHandler, Request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from desktop.local_product.dashboard import APIClient, QT_AVAILABLE

try:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from desktop.local_product.dashboard import DashboardWindow
except ImportError:
    QApplication = None
    QTest = None
    DashboardWindow = None


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self.payload


class APIClientTests(unittest.TestCase):
    def test_localhost_transport_sends_bearer_and_json_without_logging_body(self):
        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            return _Response(b'{"ok":true}')

        client = APIClient("http://127.0.0.1:8312", "synthetic-secret", opener=opener)
        payload = {"candidate_id": "cand-1", "decision": "APPROVE", "expected_version": 3}

        result = client.request("POST", "/api/decide", payload)

        request, timeout = captured[0]
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-secret")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data.decode("utf-8")), payload)
        self.assertEqual(timeout, 30)

    def test_client_rejects_non_local_api_hosts(self):
        for base_url in (
            "https://example.test",
            "http://localhost:8312",
            "http://127.0.0.1:8312/project",
            "http://127.0.0.1:8312/?redirect=elsewhere",
        ):
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                APIClient(base_url, "token")

    def test_default_opener_is_configured_to_refuse_redirects(self):
        client = APIClient("http://127.0.0.1:8312", "synthetic-secret")
        opener = client._opener.__self__
        redirect_handlers = [
            handler for handler in opener.handlers if isinstance(handler, HTTPRedirectHandler)
        ]
        self.assertTrue(redirect_handlers)
        request = Request("http://127.0.0.1:8312/api/emails")
        self.assertTrue(
            all(
                handler.redirect_request(
                    request, None, 302, "Found", {}, "https://example.test/steal"
                )
                is None
                for handler in redirect_handlers
            )
        )


class _FakeAPI:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str, dict | None, bool]] = []
        self.email = {
            "source_id": "source-1",
            "subject": "Roadmap update",
            "current_message": "Please update the roadmap by Friday.",
            "source_revision": 2,
            "input_fingerprint": "sha256:synthetic",
        }
        self.candidate = {
            "candidate_id": "candidate-1",
            "version": 3,
            "target_item_id": "item-1",
            "target_version": 8,
            "source_id": "source-1",
            "source_revision": 2,
            "input_fingerprint": "sha256:synthetic",
            "status": "PENDING",
            "proposed_fields": {
                "title": "Roadmap update",
                "project_id": "default",
                "kind": "TASK",
                "owner": "",
                "department": "",
                "due": "",
                "due_text": "Friday",
                "status": "OPEN",
                "requested_document": "",
            },
            "review_flags": ["OWNER_UNASSIGNED"],
            "source_conflict": False,
            "source_conflict_reason": None,
            "evidence": {
                "field": "current_message",
                "start": 7,
                "end": 26,
                "text": "update the roadmap",
            },
        }
        self.item = {
            "item_id": "item-1",
            "version": 8,
            "status": "IN_PROGRESS",
            "fields": {
                "project_id": "default", "kind": "TASK", "title": "Roadmap", "owner": "Morgan",
                "department": "", "due": "", "due_text": "", "requested_document": "",
                "status": "IN_PROGRESS",
            },
            "evidence": [{"source_id": "source-1", "text": "Roadmap"}],
            "history": [{"action": "APPROVE", "version": 7, "note": "Seeded test history"}],
        }

    def request(self, method, path, payload=None, *, binary=False):
        with self.lock:
            self.calls.append((method.upper(), path, payload, binary))
        if binary:
            return b"synthetic-xlsx-bytes"
        if method.upper() == "GET" and path == "/api/emails":
            return {"emails": [self.email]}
        if method.upper() == "GET" and path == "/api/candidates":
            return {"candidates": [self.candidate]}
        if method.upper() == "GET" and path.startswith("/api/items?"):
            return {"items": [self.item]}
        if method.upper() == "GET" and path == "/api/items":
            return {"items": [self.item]}
        if method.upper() == "GET" and path == "/api/items/item-1":
            return self.item
        return {"ok": True}

    def snapshot(self):
        with self.lock:
            return list(self.calls)


class _BlockingAPI(_FakeAPI):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def request(self, method, path, payload=None, *, binary=False):
        self.release.wait(timeout=5)
        return super().request(method, path, payload, binary=binary)


@unittest.skipIf(not QT_AVAILABLE or QApplication is None, "PySide6 not installed")
class DashboardUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.api = _FakeAPI()
        self.window = DashboardWindow(
            "http://127.0.0.1:8312", "synthetic-secret", transport=self.api
        )
        self.window.show()
        self.assertTrue(
            self._wait_for(
                lambda: bool(self.window.emails)
                and bool(self.window.candidates)
                and bool(self.window.items)
                and self.window.current_item is not None
            )
        )

    def tearDown(self):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and any(
            worker.isRunning() for worker in self.window._workers.values()
        ):
            self.app.processEvents()
            QTest.qWait(10)
        self.window.close()
        self.app.processEvents()

    def _wait_for(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        self.app.processEvents()
        return bool(predicate())

    def _calls_for(self, method: str, path: str):
        return [
            (verb, route, payload, binary)
            for verb, route, payload, binary in self.api.snapshot()
            if verb == method and route == path
        ]

    def test_candidate_actions_and_target_link_use_versions_and_fields(self):
        self.assertIn("item-1", self.window.candidate_target_button.text())
        self.window.candidate_target_button.click()
        self.assertIn("Owner is unassigned", self.window.candidate_review_flags.text())
        self.assertEqual(self.window.candidate_source_binding.text(), "Source binding: current")
        self.assertTrue(self._wait_for(lambda: self.window.tabs.currentWidget() is self.window.items_tab))
        self.assertTrue(self._wait_for(lambda: "Seeded test history" in self.window.item_detail.toPlainText()))

        self.window.tabs.setCurrentWidget(self.window.candidates_tab)
        self.window.approve_button.click()
        self.assertTrue(self._wait_for(lambda: len(self._calls_for("POST", "/api/decide")) >= 1))
        self.window.candidate_fields["title"].setText("Corrected roadmap title")
        self.window.decision_note.setText("Use the corrected title from the reviewed source.")
        self.window.correct_button.click()
        self.assertTrue(self._wait_for(lambda: len(self._calls_for("POST", "/api/decide")) >= 2))
        self.window.reject_button.click()
        self.assertTrue(self._wait_for(lambda: len(self._calls_for("POST", "/api/decide")) >= 3))

        actions = [call[2] for call in self._calls_for("POST", "/api/decide")]
        self.assertEqual([action["decision"] for action in actions[:3]], ["APPROVE", "CORRECT", "REJECT"])
        self.assertTrue(all(action["expected_version"] == 3 for action in actions[:3]))
        self.assertNotIn("fields", actions[0])
        self.assertEqual(actions[1]["fields"], {"title": "Corrected roadmap title"})
        self.assertEqual(actions[1]["note"], "Use the corrected title from the reviewed source.")
        self.assertNotIn("fields", actions[2])

    def test_inbox_proposal_links_explicit_target_with_exact_current_message(self):
        index = self.window.proposal_target.findData("item-1")
        self.assertGreaterEqual(index, 0)
        self.window.proposal_target.setCurrentIndex(index)
        self.window.proposal_fields["title"].setText("Roadmap action")
        self.window.proposal_fields["owner"].setText("")
        self.window.propose_button.click()
        self.assertTrue(self._wait_for(lambda: bool(self._calls_for("POST", "/api/propose"))))

        payload = self._calls_for("POST", "/api/propose")[-1][2]
        body = self.api.email["current_message"]
        self.assertEqual(payload["source_id"], "source-1")
        self.assertEqual(payload["target_item_id"], "item-1")
        self.assertEqual(payload["fields"], {"title": "Roadmap action", "owner": ""})
        self.assertEqual(
            payload["evidence"],
            {"field": "current_message", "start": 0, "end": len(body), "text": body},
        )

    def test_item_filters_history_and_undo_use_current_version(self):
        self.window.item_search.setText("Roadmap")
        self.window.item_status.setCurrentText("IN_PROGRESS")
        self.assertTrue(
            self._wait_for(
                lambda: any(
                    method == "GET" and path == "/api/items?search=Roadmap&status=IN_PROGRESS"
                    for method, path, _payload, _binary in self.api.snapshot()
                )
            )
        )
        self.assertTrue(self._wait_for(lambda: "Seeded test history" in self.window.item_detail.toPlainText()))

        self.window.undo_note.setText("Undo synthetic decision")
        self.window.undo_button.click()
        self.assertTrue(self._wait_for(lambda: bool(self._calls_for("POST", "/api/undo"))))
        payload = self._calls_for("POST", "/api/undo")[-1][2]
        self.assertEqual(payload["item_id"], "item-1")
        self.assertEqual(payload["expected_version"], 8)
        self.assertEqual(payload["note"], "Undo synthetic decision")

    def test_close_waits_for_inflight_workers_before_dropping_window(self):
        api = _BlockingAPI()
        window = DashboardWindow(
            "http://127.0.0.1:8312", "synthetic-secret", transport=api
        )
        window.show()
        try:
            self.assertTrue(
                self._wait_for(
                    lambda: len(window._workers) == 3
                    and all(worker.isRunning() for worker in window._workers.values())
                )
            )
            self.assertFalse(window.close())
            self.assertTrue(window.isVisible())
            self.assertTrue(window._close_pending)

            api.release.set()
            self.assertTrue(
                self._wait_for(
                    lambda: not window._workers and not window.isVisible(), timeout=3
                )
            )
        finally:
            api.release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and window._workers:
                self.app.processEvents()
                for worker in tuple(window._workers.values()):
                    worker.wait(20)
                QTest.qWait(10)
            if window.isVisible():
                window.close()
                self.app.processEvents()


@unittest.skipIf(
    not QT_AVAILABLE or QApplication is None or os.environ.get("FYP_TEST_LOCALHOST_API") != "1",
    "requires PySide6 and explicit opt-in to the local HTTP integration test",
)
class LocalServiceDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_inbox_suggestion_can_be_approved_through_local_service(self):
        from pathlib import Path

        from desktop.local_product.models import EmailRecord
        from desktop.local_product.service import start_local_service
        from desktop.local_product.store import EmailStore
        from desktop.tests.support import temporary_directory

        token = "synthetic-dashboard-token-12345"
        body = "Please update the project report by Friday."
        with temporary_directory() as scratch:
            store = EmailStore(Path(scratch) / "dashboard-test.sqlite3")
            store.import_records([
                EmailRecord(
                    source_id="dashboard-source",
                    source_name="synthetic-dashboard-test",
                    subject="Update project report",
                    body_raw=body,
                    current_message=body,
                    project_or_list="default",
                )
            ])
            with start_local_service(store, token) as service:
                window = DashboardWindow(service.base_url, token)
                window.show()
                try:
                    self.assertTrue(
                        self._wait_for(
                            lambda: bool(window.emails) and window.current_email is not None
                        )
                    )
                    window.suggest_button.click()
                    self.assertTrue(self._wait_for(lambda: bool(window.candidates)))
                    self.assertEqual(window.current_candidate["status"], "PENDING")
                    window.approve_button.click()
                    self.assertTrue(
                        self._wait_for(
                            lambda: bool(window.items)
                            and window.current_item is not None
                            and bool(window.current_item.get("history"))
                        )
                    )
                    self.assertEqual(window.current_item["history"][-1]["action"], "APPROVE")
                finally:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and any(
                        worker.isRunning() for worker in window._workers.values()
                    ):
                        self.app.processEvents()
                        QTest.qWait(10)
                    window.close()

    def _wait_for(self, predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        self.app.processEvents()
        return bool(predicate())


if __name__ == "__main__":
    unittest.main()
