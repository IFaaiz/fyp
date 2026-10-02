"""Synthetic contract tests for the blind structured review workflow.

All source strings in this module are invented fixtures. Nothing here reads or
annotates a released or canonical email corpus.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.datasets.global_leakage import build_global_index, identity_from_row
from src.structured_annotation import workflow


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _annotation(source_id: str, message: str, *, kind: str = "action", act_span: str | None = None,
                uncertain: bool = False) -> dict:
    evidence = []

    def ev(phrase: str, field: str = "current_message") -> str:
        value = message if field == "current_message" else f"Project Orion {source_id}"
        start = value.index(phrase)
        evidence_id = f"ev{len(evidence) + 1}"
        evidence.append({"id": evidence_id, "source_id": source_id, "field": field,
                         "start": start, "end": start + len(phrase), "text": phrase})
        return evidence_id

    scope_value = "UNCERTAIN" if uncertain else "PROJECT"
    scope_evidence = ev(f"Project Orion {source_id}", field="subject")
    annotation = {
        "schema_version": "2-alpha", "email_id": source_id, "current_source_id": source_id,
        "project_scope": {"value": scope_value, "confidence": "uncertain" if uncertain else "supported",
                           "evidence_ids": [scope_evidence]},
        "evidence": evidence, "actors": [], "actions": [], "documents": [], "departments": [],
        "temporal_entities": [], "meetings": [], "deadlines": [], "approvals": [],
        "status_updates": [], "thread_changes": [], "acts": [],
        "needs_review": bool(uncertain), "uncertainty_reasons": ["synthetic_uncertain_scope"] if uncertain else [],
    }
    if kind == "report":
        document_id = "document-1"
        name_ev = ev("project report")
        annotation["documents"].append({
            "id": document_id, "state": "requested", "document_type": "PROJECT_DELIVERABLE",
            "named": True, "name_evidence_ids": [name_ev], "evidence_ids": [name_ev], "confidence": "supported",
        })
        act_ev = ev(act_span or "prepare the project report")
        annotation["acts"].append({
            "id": "act-1", "speech_act": "REQUEST", "target_type": "DOCUMENT", "target_id": document_id,
            "target_formality": "NOT_APPLICABLE", "evidence_ids": [act_ev], "confidence": "supported",
        })
    else:
        action_id = "action-1"
        action_ev = ev("call the vendor")
        annotation["actions"].append({
            "id": action_id, "state": "requested", "category": "OPERATIONAL",
            "evidence_ids": [action_ev], "actor_id": None, "confidence": "supported",
        })
        act_ev = ev(act_span or "Please call the vendor")
        annotation["acts"].append({
            "id": "act-1", "speech_act": "REQUEST", "target_type": "ACTION", "target_id": action_id,
            "target_formality": "NOT_APPLICABLE", "evidence_ids": [act_ev], "confidence": "supported",
        })
    return annotation


class StructuredReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-structured-review-")
        self.root = Path(self.temp.name)
        ai = Path(__file__).parents[1]
        for relative in (
            "src/structured/__init__.py", "src/structured/validation.py", "src/structured/mapper.py",
            "config/structured_primitive_schema.json",
        ):
            target = self.root / "ai" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ai / relative, target)
        self.data = self.root / "ai" / "data"
        self.source_dir = self.data / "synthetic_sources"
        self.index_path = self.data / "processed" / "synthetic_index.json"
        self.boundary_path = self.data / "experiments" / "synthetic_boundary.json"
        self.train_rows = [
            {"source_id": "train-1", "subject": "Project Orion train-1", "current_message":
             "Project Orion train-1 planning is active. Please call the vendor about equipment setup, confirm the synthetic installation window, and report the result to operations."},
            {"source_id": "train-2", "subject": "Project Orion train-2", "current_message":
             "Project Orion train-2 work is underway. Please call the vendor about storage racks, confirm the separate synthetic delivery window, and report the result to operations."},
        ]
        self.eval_rows = [
            {"source_id": "eval-1", "subject": "Project Orion eval-1", "current_message":
             "Project Orion eval-1 planning is active. Please call the vendor about the synthetic lighting plan, confirm the evaluation setup window, and report the result to operations."},
            {"source_id": "eval-2", "subject": "Project Orion eval-2", "current_message":
             "Project Orion eval-2 work is underway. Please call the vendor about the synthetic wiring plan, confirm the evaluation service window, and report the result to operations."},
        ]
        self.protected_row = {"source_id": "unused-protected", "subject": "Project Orion unused-protected", "current_message":
                              "Project Orion unused-protected planning is separate. Please review the synthetic archive plan, confirm storage policy, and relay a status note to operations."}
        self.train_path = self.source_dir / "train.jsonl"
        self.eval_path = self.source_dir / "eval.jsonl"
        _write_jsonl(self.train_path, self.train_rows)
        _write_jsonl(self.eval_path, self.eval_rows)

        index = build_global_index([
            identity_from_row(row, "fixture", "FIXTURE")
            for row in self.train_rows + self.eval_rows + [self.protected_row]
        ])
        _write_json(self.index_path, index.export())
        self.index_sha = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        self.boundary = {
            "version": "synthetic-v1", "index_path": "ai/data/processed/synthetic_index.json",
            "index_sha256": self.index_sha,
            "partitions": {"fixture:train-1": "TRAIN_SCREEN", "fixture:train-2": "TRAIN_SCREEN",
                           "fixture:eval-1": "EVAL_RESERVED", "fixture:eval-2": "EVAL_RESERVED"},
            "protected_ids": ["fixture:unused-protected"], "protected_source_ids": ["unused-protected"],
            "train_screen_candidates_sha256": hashlib.sha256(self.train_path.read_bytes()).hexdigest(),
            "evaluation_candidates_sha256": hashlib.sha256(self.eval_path.read_bytes()).hexdigest(),
        }
        _write_json(self.boundary_path, self.boundary)
        self._write_training_registry()
        self.submissions = self.data / "synthetic_submissions"
        self.submissions.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    @property
    def registry_path(self):
        return self.root / "ai" / "config" / "dataset_registry.json"

    def _write_training_registry(self):
        gates = {key: True for key in (
            "official_source_verified", "usage_terms_documented", "reproducible_acquisition",
            "deterministic_parser", "counts_documented", "schema_validated",
            "offsets_validated_or_not_applicable", "tests_passed", "orchestrator_source_audit",
        )}
        row = {
            "dataset_name": "Synthetic fixture", "dataset_id": "fixture", "version": "1",
            "official_source": "synthetic fixture", "download_url": None, "origin_corpus": "synthetic",
            "overlap_family": "FIXTURE", "license": {"status": "synthetic"},
            "redistribution_allowed": True, "raw_text_allowed_in_git": False,
            "intended_component": ["synthetic-review-test"], "original_labels": [],
            "mapping_policy": {"fyp_labels_generated": False},
            "checksum": {"algorithm": "sha256", "files": [{"path": "synthetic", "sha256": "a" * 64}]},
            "download_date": "2026-10-03", "local_path": "synthetic", "status": "integrated_auxiliary",
            "training_permitted": True, "quality_gates": gates,
        }
        _write_json(self.registry_path, {"datasets": [row]})

    def _run(self, run_id: str, purpose: str = "TRAIN_SCREEN", *, source_path: Path | None = None,
             offset: int = 0, limit: int | None = None):
        source_path = source_path or (self.train_path if purpose in {"TRAIN", "TRAIN_SCREEN"} else self.eval_path)
        return workflow.prepare_run(
            source_path=source_path, output_dir=self.data / "structured_review" / run_id,
            purpose=purpose, dataset_id="fixture", reviewer_a="reviewer-a", reviewer_b="reviewer-b",
            assignments_path=self.boundary_path,
            partition_name="TRAIN_SCREEN" if purpose in {"TRAIN", "TRAIN_SCREEN"} else None,
            record_offset=offset, record_limit=limit, root=self.root,
        )

    def _packet(self, run_id: str, role: str) -> tuple[Path, dict]:
        path = self.data / "structured_review" / run_id / f"reviewer_{role}" / "packet.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    def _submit_ab(self, run_id: str, annotations_by_role=None):
        run = self.data / "structured_review" / run_id
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        for role in ("A", "B"):
            _packet_path, packet = self._packet(run_id, role)
            rows = []
            for source in packet["records"]:
                annotation = (annotations_by_role or {}).get(role, {}).get(source["source_id"])
                if annotation is None:
                    text = source["sources"][source["current_source_id"]]["current_message"]
                    if "prepare the project report" in text:
                        annotation = _annotation(source["source_id"], text, kind="report")
                    else:
                        annotation = _annotation(source["source_id"], text)
                rows.append({key: source[key] for key in ("source_id", "current_source_id", "current_source_hash", "source_hashes")} | {"annotation": annotation})
            envelope = {
                "workflow_version": workflow.WORKFLOW_VERSION, "run_id": run_id, "packet_role": role,
                "packet_sha256": manifest["reviewers"][role]["packet_sha256"],
                "source_manifest_sha256": manifest["source_manifest_sha256"],
                "reviewer_identity": manifest["reviewers"][role]["reviewer_identity"],
                "model": workflow.MODEL_REQUIRED, "reasoning": workflow.REASONING_REQUIRED,
                "source_read_attestation": {"read_all_sources": True,
                                            "source_ids": [row["source_id"] for row in packet["records"]],
                                            "source_bundle_sha256": packet["source_bundle_sha256"]},
                "records": rows,
            }
            path = self.submissions / f"{run_id}-{role}.json"
            _write_json(path, envelope)
            workflow.ingest_envelope(run_dir=run, role=role, envelope_path=path, root=self.root)
        return workflow.compare_run(run_dir=run, root=self.root)

    def _complete_third(self, run_id: str, *, resolution: str = "select_a"):
        run = self.data / "structured_review" / run_id
        workflow.prepare_third_initial(run_dir=run, reviewer_identity="reviewer-c", root=self.root)
        _packet_path, packet = self._packet(run_id, "C_initial")
        self.assertEqual(packet["review_visibility"], "independent_source_only")
        self.assertNotIn("prior_answers", packet)
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        # Preparing the reveal packet before the independent source-only verdict must fail.
        with self.assertRaises(ValueError):
            workflow.prepare_adjudication(run_dir=run, root=self.root)
        initial = self._reviewer_envelope(run_id, packet, manifest, "C_INITIAL", "reviewer-c")
        initial_path = self.submissions / f"{run_id}-C-initial.json"
        bad_initial = copy.deepcopy(initial)
        bad_initial["source_read_attestation"]["source_bundle_sha256"] = "0" * 64
        bad_initial_path = self.submissions / f"{run_id}-C-initial-bad-attestation.json"
        _write_json(bad_initial_path, bad_initial)
        with self.assertRaises(ValueError):
            workflow.ingest_third_initial(run_dir=run, envelope_path=bad_initial_path, root=self.root)
        _write_json(initial_path, initial)
        workflow.ingest_third_initial(run_dir=run, envelope_path=initial_path, root=self.root)
        workflow.prepare_adjudication(run_dir=run, root=self.root)
        _packet_path, reveal_packet = self._packet(run_id, "C_adjudication")
        self.assertIn("prior_answers", reveal_packet)
        assignment = json.loads((run / "adjudication_assignment.json").read_text(encoding="utf-8"))
        rows = []
        for source in reveal_packet["records"]:
            prior = reveal_packet["prior_answers"][source["source_id"]]
            annotation = prior["review_A_annotation"] if resolution == "select_a" else prior["review_B_annotation"]
            rows.append({key: source[key] for key in ("source_id", "current_source_id", "current_source_hash", "source_hashes")} |
                        {"resolution": resolution, "annotation": annotation})
        envelope = {
            "workflow_version": workflow.WORKFLOW_VERSION, "run_id": run_id,
            "packet_role": "C_ADJUDICATION", "packet_sha256": assignment["packet_sha256"],
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "reviewer_identity": "reviewer-c", "model": workflow.MODEL_REQUIRED,
            "reasoning": workflow.REASONING_REQUIRED,
            "initial_envelope_sha256": assignment["initial_envelope_sha256"],
            "source_read_attestation": {"read_all_sources": True,
                                        "source_ids": assignment["source_ids"],
                                        "source_bundle_sha256": reveal_packet["source_bundle_sha256"]},
            "records": rows,
        }
        path = self.submissions / f"{run_id}-C-adjudication.json"
        bad_envelope = copy.deepcopy(envelope)
        bad_envelope["source_read_attestation"]["read_all_sources"] = False
        bad_path = self.submissions / f"{run_id}-C-adjudication-bad-attestation.json"
        _write_json(bad_path, bad_envelope)
        with self.assertRaises(ValueError):
            workflow.ingest_adjudication(run_dir=run, envelope_path=bad_path, root=self.root)
        _write_json(path, envelope)
        workflow.ingest_adjudication(run_dir=run, envelope_path=path, root=self.root)

    def _reviewer_envelope(self, run_id, packet, manifest, role, reviewer):
        records = []
        for source in packet["records"]:
            text = source["sources"][source["current_source_id"]]["current_message"]
            annotation = _annotation(source["source_id"], text,
                                     kind="report" if "prepare the project report" in text else "action")
            records.append({key: source[key] for key in ("source_id", "current_source_id", "current_source_hash", "source_hashes")} |
                           {"annotation": annotation})
        if role == "C_INITIAL":
            packet_sha = json.loads((self.data / "structured_review" / run_id / "third_reviewer_assignment.json").read_text(encoding="utf-8"))["packet_sha256"]
        else:
            packet_sha = manifest["reviewers"][role]["packet_sha256"]
        return {
            "workflow_version": workflow.WORKFLOW_VERSION, "run_id": run_id, "packet_role": role,
            "packet_sha256": packet_sha,
            "source_manifest_sha256": manifest["source_manifest_sha256"], "reviewer_identity": reviewer,
            "model": workflow.MODEL_REQUIRED, "reasoning": workflow.REASONING_REQUIRED,
            "source_read_attestation": {"read_all_sources": True,
                                        "source_ids": [row["source_id"] for row in packet["records"]],
                                        "source_bundle_sha256": packet["source_bundle_sha256"]},
            "records": records,
        }

    def _complete_initial_third(self, run_id: str):
        run = self.data / "structured_review" / run_id
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        workflow.prepare_third_initial(run_dir=run, reviewer_identity="reviewer-c", root=self.root)
        _packet_path, packet = self._packet(run_id, "C_initial")
        envelope = self._reviewer_envelope(run_id, packet, manifest, "C_INITIAL", "reviewer-c")
        assignment = json.loads((run / "third_reviewer_assignment.json").read_text(encoding="utf-8"))
        envelope["packet_sha256"] = assignment["packet_sha256"]
        path = self.submissions / f"{run_id}-C-initial.json"
        _write_json(path, envelope)
        workflow.ingest_third_initial(run_dir=run, envelope_path=path, root=self.root)

    def _make_handoff_and_export(self, run_id: str):
        run = self.data / "structured_review" / run_id
        workflow.prepare_accepted_handoff(run_dir=run, root=self.root)
        handoff = run / "accepted_annotations_for_orchestrator_review.jsonl"
        handoff_manifest = json.loads(handoff.with_suffix(handoff.suffix + ".manifest.json").read_text(encoding="utf-8"))
        decision_manifest = run / "decision_manifest.json"
        authorization = {
            "authorization_version": "2-alpha", "issued_by": "orchestrator", "training_permitted": True,
            "run_manifest_sha256": hashlib.sha256((run / "run_manifest.json").read_bytes()).hexdigest(),
            "decision_manifest_sha256": hashlib.sha256(decision_manifest.read_bytes()).hexdigest(),
            "dataset_registry_sha256": hashlib.sha256(self.registry_path.read_bytes()).hexdigest(),
            "index_sha256": self.index_sha,
            "partition_manifest_sha256": hashlib.sha256(self.boundary_path.read_bytes()).hexdigest(),
            "accepted_annotation_file_sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
            "accepted_source_ids_sha256": handoff_manifest["accepted_source_ids_sha256"],
            "frozen_evaluation_source_boundary_sha256": hashlib.sha256(self.boundary_path.read_bytes()).hexdigest(),
            "permitted_components": ["speech_act"],
        }
        authorization_path = self.data / "authorization" / f"{run_id}.json"
        _write_json(authorization_path, authorization)
        train_path = self.data / "authorized_train" / f"{run_id}.jsonl"
        workflow.export_accepted_train(run_dir=run, output_path=train_path,
                                       authorization_path=authorization_path,
                                       evaluation_boundary_path=self.boundary_path, root=self.root)
        return train_path, authorization_path, handoff

    def _run_report_review(self, run_id="approved-report", *, disagree=False):
        report_text = "Project Orion report-1 planning is active. Please prepare the project report before the synthetic review checkpoint."
        report_row = {"source_id": "train-1", "subject": "Project Orion train-1", "current_message": report_text}
        source_path = self.source_dir / f"{run_id}.jsonl"
        _write_jsonl(source_path, [report_row])
        report_index = build_global_index([
            identity_from_row(report_row, "fixture", "FIXTURE"),
            identity_from_row(self.train_rows[1], "fixture", "FIXTURE"),
            identity_from_row(self.eval_rows[0], "fixture", "FIXTURE"),
            identity_from_row(self.eval_rows[1], "fixture", "FIXTURE"),
            identity_from_row(self.protected_row, "fixture", "FIXTURE"),
        ])
        _write_json(self.index_path, report_index.export())
        self.index_sha = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        self.boundary["index_sha256"] = self.index_sha
        self.boundary["train_screen_candidates_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        _write_json(self.boundary_path, self.boundary)
        prepared = workflow.prepare_run(source_path=source_path, output_dir=self.data / "structured_review" / run_id,
                                       purpose="TRAIN_SCREEN", dataset_id="fixture", reviewer_a="reviewer-a",
                                       reviewer_b="reviewer-b", assignments_path=self.boundary_path,
                                       root=self.root)
        source = json.loads((self.data / "structured_review" / run_id / "reviewer_A" / "packet.json").read_text(encoding="utf-8"))["records"][0]
        ann = _annotation("train-1", report_text, kind="report")
        annotation_b = _annotation("train-1", report_text, kind="report", act_span="the project report") if disagree else copy.deepcopy(ann)
        self._submit_ab(run_id, {"A": {"train-1": ann}, "B": {"train-1": annotation_b}})
        return prepared, ann

    def test_train_blind_review_root_approval_handoff_authorized_export_and_public_verify(self):
        prepared, annotation = self._run_report_review(disagree=True)
        run = self.data / "structured_review" / "approved-report"
        comparison = json.loads((run / "pair_comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(comparison["records"][0]["reviewer_A_labels"], ["REPORT_REQUEST"])
        self.assertTrue(comparison["records"][0]["root_decision_required"])
        self.assertTrue(comparison["records"][0]["primitive_disagreement"])
        pending = workflow.finalize_run(run_dir=run, root=self.root)
        self.assertEqual(pending["counts"]["review_required"], 1)
        with self.assertRaises(ValueError):
            workflow.prepare_accepted_handoff(run_dir=run, root=self.root)
        with self.assertRaises(ValueError):
            workflow.add_root_decision(run_dir=run, source_id="train-1",
                                       annotation_sha256=workflow.digest_json(annotation), decision="approve",
                                       root_identity="orchestrator-root", reason="Must wait for C.", root=self.root)
        self._complete_third("approved-report")

        result = workflow.add_root_decision(run_dir=run, source_id="train-1",
                                            annotation_sha256=workflow.digest_json(annotation), decision="approve",
                                            root_identity="orchestrator-root", reason="Synthetic evidence and scope reviewed.",
                                            root=self.root)
        self.assertEqual(result["decision"], "approve")
        finalized = workflow.finalize_run(run_dir=run, root=self.root)
        self.assertEqual(finalized["counts"], {"accepted": 1, "rejected": 0, "review_required": 0})
        train_path, authorization_path, handoff = self._make_handoff_and_export("approved-report")
        verified = workflow.verify_accepted_train_provenance(train_path, authorization_path,
                                                              registry_path=self.registry_path, root=self.root)
        self.assertEqual(verified["manifest"]["purpose"], "TRAIN")
        self.assertEqual([row["source_id"] for row in verified["rows"]], ["train-1"])
        self.assertEqual(verified["rows"][0]["fyp_labels"], ["REPORT_REQUEST"])
        self.assertEqual(handoff.read_bytes(), train_path.read_bytes())

        # Every stored artifact in the acceptance chain is re-derived from the
        # blind submissions, decisions, current source, schema, mapper and boundary.
        targets = [
            (run / "reviewer_A" / "packet.json", lambda p: p.read_bytes() + b"\n"),
            (run / "reviewer_C_initial" / "packet.json", lambda p: p.read_bytes() + b"\n"),
            (run / "reviewer_C_adjudication" / "packet.json", lambda p: p.read_bytes() + b"\n"),
            (run / "pair_comparison.json", lambda p: {**json.loads(p.read_text(encoding="utf-8")), "run_id": "forged"}),
            (run / "envelopes" / "A.json", lambda p: {**json.loads(p.read_text(encoding="utf-8")), "reviewer_identity": "forged"}),
            (run / "envelopes" / "C_initial.json", lambda p: {**json.loads(p.read_text(encoding="utf-8")), "visibility": "revealed-too-soon"}),
            (run / "envelopes" / "C_adjudication.json", lambda p: {**json.loads(p.read_text(encoding="utf-8")), "visibility": "forged"}),
            (run / "decisions" / (workflow.digest_json("train-1") + ".json"),
             lambda p: {**json.loads(p.read_text(encoding="utf-8")), "status": "rejected"}),
            (run / "root_decisions" / (workflow.digest_json("train-1") + ".json"),
             lambda p: {**json.loads(p.read_text(encoding="utf-8")), "source_id": "other"}),
            (handoff, lambda p: p.read_bytes() + b"{}\n"),
            (train_path, lambda p: p.read_bytes() + b"{}\n"),
            (authorization_path, lambda p: {**json.loads(p.read_text(encoding="utf-8")), "accepted_source_ids_sha256": "0" * 64}),
            (self.registry_path, lambda p: {"datasets": []}),
        ]
        for path, forge in targets:
            original = path.read_bytes()
            with self.subTest(tampered=path.name):
                try:
                    value = forge(path)
                    if isinstance(value, bytes):
                        path.write_bytes(value)
                    else:
                        _write_json(path, value)
                    with self.assertRaises((ValueError, KeyError)):
                        workflow.verify_accepted_train_provenance(train_path, authorization_path,
                                                                  registry_path=self.registry_path, root=self.root)
                finally:
                    path.write_bytes(original)

        source_path = Path(json.loads((run / "source_manifest.json").read_text(encoding="utf-8"))["source_file"])
        source_path = self.root / source_path
        original_source = source_path.read_bytes()
        try:
            source_path.write_bytes(original_source.replace(b"synthetic review checkpoint", b"forged source checkpoint"))
            with self.assertRaises(ValueError):
                workflow.verify_accepted_train_provenance(train_path, authorization_path, root=self.root)
        finally:
            source_path.write_bytes(original_source)

        for relative in ("config/structured_primitive_schema.json", "src/structured/validation.py", "src/structured/mapper.py"):
            path = self.root / "ai" / relative
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"\n# synthetic drift\n")
                with self.assertRaises(ValueError):
                    workflow.verify_accepted_train_provenance(train_path, authorization_path, root=self.root)
            finally:
                path.write_bytes(original)

    def test_eval_requires_third_source_only_verdict_before_ab_reveal_and_resolution(self):
        run_id = "eval-third"
        self._run(run_id, "EVAL", limit=2)
        manifest = json.loads((self.data / "structured_review" / run_id / "run_manifest.json").read_text(encoding="utf-8"))
        _packet_path, packet = self._packet(run_id, "A")
        forged_attestation = self._reviewer_envelope(run_id, packet, manifest, "A", "reviewer-a")
        forged_attestation["source_read_attestation"]["source_ids"] = []
        forged_path = self.submissions / f"{run_id}-bad-attestation.json"
        _write_json(forged_path, forged_attestation)
        with self.assertRaises(ValueError):
            workflow.ingest_envelope(run_dir=self.data / "structured_review" / run_id, role="A",
                                     envelope_path=forged_path, root=self.root)
        _packet_path, packet_b = self._packet(run_id, "B")
        forged_b = self._reviewer_envelope(run_id, packet_b, manifest, "B", "reviewer-b")
        forged_b["source_read_attestation"]["read_all_sources"] = False
        _write_json(forged_path, forged_b)
        with self.assertRaises(ValueError):
            workflow.ingest_envelope(run_dir=self.data / "structured_review" / run_id, role="B",
                                     envelope_path=forged_path, root=self.root)
        comparison = self._submit_ab(run_id)
        self.assertEqual(len(comparison["records"]), 2)
        self.assertTrue(all(row["third_required"] for row in comparison["records"]))
        self._complete_third(run_id)
        result = workflow.finalize_run(run_dir=self.data / "structured_review" / run_id, root=self.root)
        self.assertEqual(result["counts"], {"accepted": 2, "rejected": 0, "review_required": 0})

    def test_train_primitive_disagreement_triggers_third_even_when_final_labels_match(self):
        run_id = "same-label-primitive-disagreement"
        self._run(run_id, limit=1)
        text = self.train_rows[0]["current_message"]
        annotation_a = _annotation("train-1", text, act_span="Please call the vendor")
        annotation_b = _annotation("train-1", text, act_span="call the vendor")
        comparison = self._submit_ab(run_id, {"A": {"train-1": annotation_a}, "B": {"train-1": annotation_b}})
        row = comparison["records"][0]
        self.assertEqual(row["reviewer_A_labels"], row["reviewer_B_labels"])
        self.assertEqual(row["reviewer_A_labels"], ["ACTION_REQUEST"])
        self.assertTrue(row["primitive_disagreement"])
        self.assertTrue(row["third_required"])
        self.assertEqual(workflow.finalize_run(run_dir=self.data / "structured_review" / run_id, root=self.root)["counts"]["review_required"], 1)
        self._complete_third(run_id)
        result = workflow.finalize_run(run_dir=self.data / "structured_review" / run_id, root=self.root)
        self.assertEqual(result["counts"], {"accepted": 1, "rejected": 0, "review_required": 0})

    def test_uncertain_scope_never_accepts_and_root_cannot_clear_it(self):
        run_id = "uncertain-scope"
        self._run(run_id, limit=1)
        text = self.train_rows[0]["current_message"]
        uncertain = _annotation("train-1", text, uncertain=True)
        comparison = self._submit_ab(run_id, {"A": {"train-1": uncertain}, "B": {"train-1": copy.deepcopy(uncertain)}})
        self.assertTrue(comparison["records"][0]["uncertain"])
        with self.assertRaises(ValueError):
            workflow.add_root_decision(run_dir=self.data / "structured_review" / run_id,
                                       source_id="train-1", annotation_sha256=workflow.digest_json(uncertain),
                                       decision="approve", root_identity="orchestrator-root",
                                       reason="Synthetic uncertainty test.", root=self.root)
        result = workflow.finalize_run(run_dir=self.data / "structured_review" / run_id, root=self.root)
        self.assertEqual(result["counts"], {"accepted": 0, "rejected": 0, "review_required": 1})
        workflow.add_root_decision(run_dir=self.data / "structured_review" / run_id,
                                   source_id="train-1", annotation_sha256=workflow.digest_json(uncertain),
                                   decision="reject", root_identity="orchestrator-root",
                                   reason="Exclude the synthetic record because its scope remains uncertain.",
                                   root=self.root)
        rejected = workflow.finalize_run(run_dir=self.data / "structured_review" / run_id, root=self.root)
        self.assertEqual(rejected["counts"], {"accepted": 0, "rejected": 1, "review_required": 0})

    def test_deterministic_source_bound_slices_invalid_ranges_and_partition_isolation(self):
        first = self._run("slice-one", offset=1, limit=1)
        second = self._run("slice-two", offset=1, limit=1)
        one = json.loads((self.data / "structured_review" / "slice-one" / "source_manifest.json").read_text(encoding="utf-8"))
        two = json.loads((self.data / "structured_review" / "slice-two" / "source_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((one["record_offset"], one["record_count"], one["input_record_count"]), (1, 1, 2))
        self.assertEqual(one["source_bundle_sha256"], two["source_bundle_sha256"])
        self.assertEqual(one["source_hashes"], two["source_hashes"])
        self.assertEqual(one["source_hashes"][0]["source_id"], "train-2")
        self.assertEqual(first["source_bundle_sha256"], second["source_bundle_sha256"])
        for offset, limit in ((2, 1), (1, 2), (True, 1), (0, 0)):
            with self.subTest(offset=offset, limit=limit):
                target = self.data / "structured_review" / f"invalid-{offset}-{limit}"
                with self.assertRaises(ValueError):
                    workflow.prepare_run(source_path=self.train_path, output_dir=target,
                                         purpose="TRAIN_SCREEN", dataset_id="fixture",
                                         reviewer_a="reviewer-a", reviewer_b="reviewer-b",
                                         assignments_path=self.boundary_path, record_offset=offset,
                                         record_limit=limit, root=self.root)
                self.assertFalse(target.exists())
        initial_status = workflow.summarize_run(run_dir=self.data / "structured_review" / "slice-one", root=self.root)
        self.assertEqual(initial_status["counts"], {"accepted": 0, "rejected": 0, "review_required": 1})
        with self.assertRaises(ValueError):
            self._run("wrong-partition", "TRAIN_SCREEN", source_path=self.eval_path, limit=1)

        original_boundary = self.boundary_path.read_bytes()
        mismatched = copy.deepcopy(self.boundary)
        mismatched["protected_source_ids"] = []
        try:
            _write_json(self.boundary_path, mismatched)
            with self.assertRaisesRegex(ValueError, "protected native IDs"):
                self._run("mismatched-protection", limit=1)
        finally:
            self.boundary_path.write_bytes(original_boundary)

        # Even an unused protected reserve remains outside named partitions but
        # participates in isolation checks; an actual cross-partition component
        # is rejected from the real index records and links.
        self.assertNotIn("fixture:unused-protected", self.boundary["partitions"])
        unused_overlap_index = json.loads(self.index_path.read_text(encoding="utf-8"))
        unused_overlap_index["records"]["fixture:unused-protected"]["leakage_group_id"] = unused_overlap_index["records"]["fixture:train-1"]["leakage_group_id"]
        _write_json(self.index_path, unused_overlap_index)
        self.boundary["index_sha256"] = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        _write_json(self.boundary_path, self.boundary)
        with self.assertRaisesRegex(ValueError, "training isolation failed"):
            self._run("unused-protected-component", limit=1)

        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        index["records"]["fixture:eval-1"]["leakage_group_id"] = index["records"]["fixture:train-1"]["leakage_group_id"]
        _write_json(self.index_path, index)
        self.boundary["index_sha256"] = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        _write_json(self.boundary_path, self.boundary)
        with self.assertRaises(ValueError):
            self._run("cross-partition-component", limit=1)

    def test_fresh_status_reports_all_records_pending_without_comparison_or_stale_progress(self):
        run_id = "fresh-status"
        self._run(run_id, limit=1)
        run = self.data / "structured_review" / run_id
        _write_json(run / "progress.json", {"counts": {"accepted": 1, "rejected": 0, "review_required": 0}})
        status = workflow.summarize_run(run_dir=run, root=self.root)
        self.assertEqual(status["counts"], {"accepted": 0, "rejected": 0, "review_required": 1})
        self.assertEqual(status["pending"][0]["reason"], "blind_reviews_incomplete")

    def test_temporal_evidence_and_local_id_renames_do_not_create_primitive_disagreement(self):
        source_id = "temporal-fixture"
        message = "Project Orion schedule fixture. Please call the vendor. The synthetic design review is scheduled for Friday at 3 PM."
        annotation = _annotation(source_id, message)
        # Replace the basic action with an explicitly linked scheduled meeting.
        annotation["actions"] = []
        annotation["acts"] = []
        evidence = annotation["evidence"]
        def add_ev(phrase):
            start = message.index(phrase)
            value = {"id": f"ev{len(evidence) + 1}", "source_id": source_id, "field": "current_message",
                     "start": start, "end": start + len(phrase), "text": phrase}
            evidence.append(value)
            return value["id"]
        meeting_ev = add_ev("design review is scheduled")
        date_ev = add_ev("Friday")
        time_ev = add_ev("3 PM")
        annotation["temporal_entities"] = [
            {"id": "date-1", "kind": "DATE", "evidence_ids": [date_ev], "confidence": "supported"},
            {"id": "time-1", "kind": "TIME", "evidence_ids": [time_ev], "confidence": "supported"},
        ]
        annotation["meetings"] = [{"id": "meeting-1", "state": "scheduled", "evidence_ids": [meeting_ev],
                                   "date_ids": ["date-1"], "time_ids": ["time-1"],
                                   "participant_actor_ids": [], "confidence": "supported"}]
        annotation["acts"] = [{"id": "act-1", "speech_act": "SCHEDULE", "target_type": "MEETING",
                               "target_id": "meeting-1", "target_formality": "NOT_APPLICABLE",
                               "evidence_ids": [meeting_ev], "confidence": "supported"}]
        renamed = copy.deepcopy(annotation)
        evidence_map = {item["id"]: f"evidence-{i}" for i, item in enumerate(renamed["evidence"], 1)}
        for item in renamed["evidence"]:
            item["id"] = evidence_map[item["id"]]
        for item in renamed["project_scope"].get("evidence_ids", []):
            pass
        renamed["project_scope"]["evidence_ids"] = [evidence_map[eid] for eid in renamed["project_scope"]["evidence_ids"]]
        collection_maps = {}
        for collection in workflow.TOP_COLLECTIONS:
            collection_maps[collection] = {item["id"]: f"{collection}-renamed-{i}"
                                           for i, item in enumerate(renamed[collection], 1)}
            for item in renamed[collection]:
                item["id"] = collection_maps[collection][item["id"]]
                for field in ("evidence_ids", "name_evidence_ids", "context_evidence_ids", "due_relation_evidence_ids"):
                    if field in item:
                        item[field] = [evidence_map[value] for value in item[field]]
        for item in renamed["meetings"]:
            item["date_ids"] = [collection_maps["temporal_entities"][value] for value in item["date_ids"]]
            item["time_ids"] = [collection_maps["temporal_entities"][value] for value in item["time_ids"]]
        for item in renamed["acts"]:
            item["target_id"] = collection_maps["meetings"][item["target_id"]]
        for collection in workflow.TOP_COLLECTIONS:
            renamed[collection].reverse()
        renamed["evidence"].reverse()
        comparison = workflow.compare_annotations(annotation, renamed)
        self.assertTrue(comparison["agreement"], comparison["changed_paths"])


if __name__ == "__main__":
    unittest.main()
