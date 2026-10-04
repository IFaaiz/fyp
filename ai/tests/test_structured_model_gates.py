from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.structured_models import (
    AUTH_HASH_FIELDS,
    PREDECLARED_MINIMUM_PER_CLASS,
    REQUIRED_COMPONENTS,
    SPEECH_ACTS,
    PreparedExamples,
    TrainingGateError,
    canonical_json_sha256,
    canonical_source_ids_sha256,
    count_and_check_classes,
    load_authorized_training_export,
    prepare_training_examples,
)
from src.structured.mapper import map_labels


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _registry() -> dict:
    gates = {
        "official_source_verified": True,
        "usage_terms_documented": True,
        "reproducible_acquisition": True,
        "deterministic_parser": True,
        "counts_documented": True,
        "schema_validated": True,
        "offsets_validated_or_not_applicable": True,
        "tests_passed": True,
        "orchestrator_source_audit": True,
    }
    return {
        "registry_version": "2-alpha",
        "datasets": [{
            "dataset_name": "Synthetic gate-test registry fixture",
            "dataset_id": "enron",
            "version": "test-only",
            "official_source": "https://example.invalid/source",
            "download_url": "https://example.invalid/data",
            "origin_corpus": "Enron",
            "overlap_family": "ENRON",
            "license": "fixture terms",
            "redistribution_allowed": False,
            "raw_text_allowed_in_git": False,
            "intended_component": ["structured baseline gate test"],
            "original_labels": [],
            "mapping_policy": {"fyp_labels_generated": False},
            "checksum": {"algorithm": "sha256", "files": [{"path": "fixture.zip", "sha256": _sha("fixture")} ]},
            "download_date": "2026-10-02",
            "local_path": "ai/data/raw/ignored-fixture",
            "status": "integrated_auxiliary",
            "training_permitted": True,
            "quality_gates": gates,
        }],
    }


def _annotation(source_id: str, text: str, *, scope: str, speech_act: str | None = None,
                authored_ranges: list[dict] | None = None) -> tuple[dict, dict]:
    source = {"subject": "Project note", "current_message": text}
    source["source_id_kind"] = "source_id"
    if authored_ranges is not None:
        source["authored_ranges"] = authored_ranges
        start, end = authored_ranges[0]["start"], authored_ranges[0]["end"]
    else:
        start, end = 0, len(text)
    evidence = {"id": "ev1", "source_id": source_id, "field": "current_message",
                "start": start, "end": end, "text": text[start:end]}
    annotation = {
        "schema_version": "2-alpha",
        "email_id": source_id,
        "current_source_id": source_id,
        "project_scope": {"value": scope, "confidence": "supported", "evidence_ids": ["ev1"]},
        "evidence": [evidence],
        "actors": [], "actions": [], "documents": [], "departments": [],
        "temporal_entities": [], "meetings": [], "deadlines": [], "approvals": [],
        "status_updates": [], "thread_changes": [], "acts": [],
        "needs_review": False,
        "uncertainty_reasons": [],
    }
    if speech_act:
        annotation["acts"].append({
            "id": "act1", "speech_act": speech_act, "target_type": "IMPLICIT",
            "target_id": None, "target_formality": "PROJECT_DELIVERABLE",
            "evidence_ids": ["ev1"], "confidence": "supported",
        })
    return annotation, source


def _row(source_id: str = "native-1", *, scope: str = "PROJECT", speech_act: str | None = "REQUEST",
         text: str = "Please send the plan.", authored_ranges: list[dict] | None = None) -> dict:
    annotation, source = _annotation(source_id, text, scope=scope, speech_act=speech_act,
                                     authored_ranges=authored_ranges)
    sources = {source_id: source}
    mapped = map_labels(annotation, current_source_id=source_id, sources=sources)
    return {
        "source_id": source_id,
        "current_source_id": source_id,
        "dataset_id": "enron",
        "source_partition": "TRAIN_SCREEN",
        "leakage_group_id": "thread-" + source_id,
        "identity_complete": True,
        "partition_conflicts": [],
        "training_exclusions": [],
        "subject": source["subject"],
        "current_message": text,
        "sources": {source_id: source},
        "source_hashes": {
            sid: canonical_json_sha256({"source_id": sid, **item})
            for sid, item in sources.items()
        },
        "source_index_id": f"enron:{source_id}",
        "overlap_family": "ENRON",
        "annotation": annotation,
        "fyp_labels": list(mapped.labels),
        "review_decision_sha256": _sha("review-" + source_id),
    } | {"sources": sources}


def _write_authorized_export(directory: Path, rows: list[dict], registry_path: Path):
    directory.mkdir(parents=True, exist_ok=True)
    export_path = directory / "accepted_train.jsonl"
    content = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    export_path.write_text(content, encoding="utf-8", newline="\n")
    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    hashes = {field: _sha(field) for field in AUTH_HASH_FIELDS}
    hashes["dataset_registry_sha256"] = registry_sha
    hashes["accepted_annotation_file_sha256"] = hashlib.sha256(export_path.read_bytes()).hexdigest()
    hashes["accepted_source_ids_sha256"] = canonical_source_ids_sha256([row["source_id"] for row in rows])
    hashes["frozen_evaluation_source_boundary_sha256"] = hashes["partition_manifest_sha256"]
    components = sorted(REQUIRED_COMPONENTS)
    authorization = {
        "authorization_version": "2-alpha",
        "issued_by": "orchestrator",
        "training_permitted": True,
        "permitted_components": components,
        **hashes,
    }
    authorization_path = directory / "training_authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    manifest = {
        "purpose": "TRAIN",
        "count": len(rows),
        "training_permitted": True,
        "permitted_components": components,
        "run_manifest_sha256": hashes["run_manifest_sha256"],
        "decision_manifest_sha256": hashes["decision_manifest_sha256"],
        "dataset_registry_sha256": hashes["dataset_registry_sha256"],
        "global_index_sha256": hashes["index_sha256"],
        "partition_manifest_sha256": hashes["partition_manifest_sha256"],
        "frozen_evaluation_source_boundary_sha256": hashes["frozen_evaluation_source_boundary_sha256"],
        "accepted_annotation_file_sha256": hashes["accepted_annotation_file_sha256"],
        "accepted_source_ids_sha256": hashes["accepted_source_ids_sha256"],
        "output_sha256": hashes["accepted_annotation_file_sha256"],
        "authorization_sha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
    }
    (directory / "accepted_train.jsonl.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return export_path, authorization_path


def _load_fixture_export(export: Path, authorization: Path, registry: Path):
    """Exercise model-row gates with a deliberately synthetic workflow result."""
    manifest_path = export.with_name(export.name + ".manifest.json")
    if manifest_path.is_file() and export.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in export.read_text(encoding="utf-8").splitlines()]
    else:
        # Name/path rejection must happen before consulting the synthetic verifier.
        manifest, rows = {}, []
    with mock.patch(
        "src.structured_annotation.workflow.verify_accepted_train_provenance",
        return_value={"manifest": manifest, "rows": rows},
    ):
        return load_authorized_training_export(export, authorization, registry)


class StructuredModelGateTests(unittest.TestCase):
    def setUp(self):
        self.review_root = Path(__file__).resolve().parents[1] / "data" / "structured_review"
        self.review_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.review_root)
        self.root = Path(self.temp.name)
        self.workflow_temp_dirs = []
        self.registry_path = self.root / "dataset_registry.json"
        self.registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
        self.run_dir = self.root / "run-1"

    def tearDown(self):
        for temporary in self.workflow_temp_dirs:
            temporary.cleanup()
        self.temp.cleanup()

    def test_authorized_export_with_valid_rows_passes_contract_gates(self):
        rows = [_row(), _row("native-2", scope="NON_PROJECT", speech_act=None, text="Personal lunch.")]
        export, auth = _write_authorized_export(self.run_dir, rows, self.registry_path)
        loaded = _load_fixture_export(export, auth, self.registry_path)
        self.assertEqual(loaded.source_ids, ("native-1", "native-2"))
        self.assertEqual(len(loaded.rows), 2)

    def test_review_handoff_name_is_not_accepted_as_training_export(self):
        handoff = self.run_dir / "accepted_annotations_for_orchestrator_review.jsonl"
        handoff.parent.mkdir(parents=True)
        handoff.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(TrainingGateError, "accepted_train.jsonl"):
            _load_fixture_export(handoff, handoff, self.registry_path)

    def test_closed_v1_or_other_protected_path_is_blocked(self):
        protected = Path(__file__).resolve().parents[1] / "data" / "models" / "closed_v1" / "accepted_train.jsonl"
        auth = protected.with_name("training_authorization.json")
        with self.assertRaisesRegex(TrainingGateError, "must reside below ai/data/structured_review"):
            _load_fixture_export(protected, auth, self.registry_path)

    def test_unapproved_authorization_is_blocked(self):
        export, auth_path = _write_authorized_export(self.run_dir, [_row()], self.registry_path)
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        auth["training_permitted"] = False
        auth_path.write_text(json.dumps(auth), encoding="utf-8")
        with self.assertRaisesRegex(TrainingGateError, "active orchestrator approval"):
            _load_fixture_export(export, auth_path, self.registry_path)

    def test_missing_component_authorization_is_blocked(self):
        export, auth_path = _write_authorized_export(self.run_dir, [_row()], self.registry_path)
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        auth["permitted_components"] = ["structured_scope_baseline"]
        auth_path.write_text(json.dumps(auth), encoding="utf-8")
        with self.assertRaisesRegex(TrainingGateError, "does not permit both"):
            _load_fixture_export(export, auth_path, self.registry_path)

    def test_uncertain_review_annotation_is_blocked_even_when_export_hash_matches(self):
        row = _row()
        row["annotation"]["needs_review"] = True
        export, auth = _write_authorized_export(self.run_dir, [row], self.registry_path)
        with self.assertRaisesRegex(TrainingGateError, "marked for review"):
            _load_fixture_export(export, auth, self.registry_path)

    def test_uncertain_primitive_state_is_blocked(self):
        row = _row()
        row["annotation"]["uncertainty_reasons"] = ["scope unclear"]
        export, auth = _write_authorized_export(self.run_dir, [row], self.registry_path)
        with self.assertRaisesRegex(TrainingGateError, "uncertainty reasons"):
            _load_fixture_export(export, auth, self.registry_path)

    def test_non_train_partition_is_blocked(self):
        row = _row()
        row["source_partition"] = "TEST"
        export, auth = _write_authorized_export(self.run_dir, [row], self.registry_path)
        with self.assertRaisesRegex(TrainingGateError, "not in a train partition"):
            _load_fixture_export(export, auth, self.registry_path)

    def test_incomplete_identity_conflicts_and_exclusions_are_blocked(self):
        for field, value, phrase in (
            ("identity_complete", False, "incomplete identity"),
            ("partition_conflicts", ["overlap"], "conflicts or training exclusions"),
            ("training_exclusions", ["manual exclusion"], "conflicts or training exclusions"),
        ):
            with self.subTest(field=field):
                row = _row()
                row[field] = value
                run = self.root / ("run-" + field)
                export, auth = _write_authorized_export(run, [row], self.registry_path)
                with self.assertRaisesRegex(TrainingGateError, phrase):
                    _load_fixture_export(export, auth, self.registry_path)

    def test_export_byte_modification_is_blocked(self):
        export, auth = _write_authorized_export(self.run_dir, [_row()], self.registry_path)
        export.write_text(export.read_text(encoding="utf-8").replace("Please", "Kindly"), encoding="utf-8")
        with self.assertRaisesRegex(TrainingGateError, "export bytes"):
            _load_fixture_export(export, auth, self.registry_path)

    def test_registry_byte_modification_is_blocked(self):
        export, auth = _write_authorized_export(self.run_dir, [_row()], self.registry_path)
        self.registry_path.write_text(self.registry_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(TrainingGateError, "registry bytes"):
            _load_fixture_export(export, auth, self.registry_path)

    def test_manifest_hash_mismatch_blocks_even_if_authorization_is_active(self):
        export, auth_path = _write_authorized_export(self.run_dir, [_row()], self.registry_path)
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        auth["index_sha256"] = _sha("different index")
        auth_path.write_text(json.dumps(auth), encoding="utf-8")
        with self.assertRaisesRegex(TrainingGateError, "manifest disagree: index_sha256"):
            _load_fixture_export(export, auth_path, self.registry_path)

    def test_unregistered_or_training_disabled_dataset_is_blocked(self):
        registry = _registry()
        registry["datasets"][0]["training_permitted"] = False
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        export, auth = _write_authorized_export(self.run_dir, [_row()], self.registry_path)
        with self.assertRaisesRegex(TrainingGateError, "not authorized for auxiliary training"):
            _load_fixture_export(export, auth, self.registry_path)

    def test_source_id_digest_uses_canonical_sorted_json(self):
        ids = ["z-1", "ä-2", "a-3"]
        expected = hashlib.sha256(
            json.dumps(sorted(ids), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(canonical_source_ids_sha256(ids), expected)

    def test_workflow_generated_synthetic_export_passes_loader_without_fitting(self):
        """Exercise a real review -> handoff -> authorized export chain with synthetic text only."""
        from src.datasets.global_leakage import build_global_index, identity_from_row
        from src.structured_annotation import workflow
        from src.structured_models import preflight_authorized_export

        project_root = Path(__file__).resolve().parents[2]
        workflow_temp = tempfile.TemporaryDirectory(dir=self.review_root)
        run_dir = Path(workflow_temp.name)
        run_dir.rmdir()  # prepare_run owns creation of the run directory
        self.workflow_temp_dirs.append(workflow_temp)
        source_path = self.root / "synthetic_candidates.jsonl"
        index_path = self.root / "synthetic_global_index.json"
        partition_path = self.root / "synthetic_partition_manifest.json"

        train_sources = [
            {"source_id": "synthetic-1", "subject": "Project status one",
             "current_message": "The project reached the first implementation checkpoint after completing the agreed design review."},
            {"source_id": "synthetic-2", "subject": "Project status two",
             "current_message": "The project team completed integration testing and recorded the release readiness decision."},
            {"source_id": "synthetic-3", "subject": "Personal note",
             "current_message": "This personal weekend note discusses a family visit and a local community event."},
        ]
        protected_source = {
            "source_id": "synthetic-eval-reserved", "subject": "Reserved evaluation item",
            "current_message": "The protected synthetic evaluation item is isolated and never provided to the model harness.",
        }
        source_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in train_sources),
            encoding="utf-8",
        )
        identities = [identity_from_row(row, "enron", "ENRON") for row in [*train_sources, protected_source]]
        index_payload = build_global_index(identities).export()
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        protected_id = "enron:synthetic-eval-reserved"
        partitions = {f"enron:{row['source_id']}": "TRAIN_SCREEN" for row in train_sources}
        partitions[protected_id] = "EVAL_RESERVED"
        partition_payload = {
            "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "partitions": partitions,
            "protected_ids": [protected_id],
            "protected_source_ids": ["synthetic-eval-reserved"],
        }
        partition_path.write_text(json.dumps(partition_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")

        workflow.prepare_run(
            source_path=source_path, output_dir=run_dir, purpose="TRAIN_SCREEN", dataset_id="enron",
            reviewer_a="synthetic reviewer A", reviewer_b="synthetic reviewer B",
            index_path=index_path, assignments_path=partition_path, root=project_root,
        )
        run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        source_manifest_sha = run_manifest["source_manifest_sha256"]
        for role in ("A", "B"):
            packet_path = run_dir / run_manifest["reviewers"][role]["packet_path"]
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            answers = []
            for record in packet["records"]:
                sid = record["source_id"]
                current = record["sources"][sid]
                text = current["current_message"]
                is_project = sid != "synthetic-3"
                evidence = {"id": "e1", "source_id": sid, "field": "current_message",
                            "start": 0, "end": len(text), "text": text}
                annotation = {
                    "schema_version": "2-alpha", "email_id": sid, "current_source_id": sid,
                    "project_scope": {
                        "value": "PROJECT" if is_project else "NON_PROJECT",
                        "confidence": "supported", "evidence_ids": ["e1"],
                    },
                    "evidence": [evidence], "actors": [], "actions": [], "documents": [],
                    "departments": [], "temporal_entities": [], "meetings": [], "deadlines": [],
                    "approvals": [], "status_updates": [], "thread_changes": [], "acts": [],
                    "needs_review": False, "uncertainty_reasons": [],
                }
                if is_project:
                    annotation["status_updates"] = [{
                        "id": "status1", "kind": "progress", "evidence_ids": ["e1"], "confidence": "supported",
                    }]
                    annotation["acts"] = [{
                        "id": "act1", "speech_act": "INFORM", "target_type": "STATUS_UPDATE",
                        "target_id": "status1", "target_formality": "NOT_APPLICABLE",
                        "evidence_ids": ["e1"], "confidence": "supported",
                    }]
                answers.append({
                    "source_id": sid, "current_source_id": sid,
                    "current_source_hash": record["current_source_hash"],
                    "source_hashes": record["source_hashes"], "annotation": annotation,
                })
            envelope = {
                "workflow_version": workflow.WORKFLOW_VERSION,
                "run_id": packet["run_id"], "packet_role": role,
                "packet_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                "source_manifest_sha256": source_manifest_sha,
                "reviewer_identity": run_manifest["reviewers"][role]["reviewer_identity"],
                "model": workflow.MODEL_REQUIRED, "reasoning": workflow.REASONING_REQUIRED,
                "source_read_attestation": {
                    "read_all_sources": True,
                    "source_ids": [record["source_id"] for record in packet["records"]],
                    "source_bundle_sha256": packet["source_bundle_sha256"],
                },
                "records": answers,
            }
            envelope_path = self.root / f"envelope_{role}.json"
            envelope_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
            workflow.ingest_envelope(run_dir=run_dir, role=role, envelope_path=envelope_path, root=project_root)

        workflow.compare_run(run_dir=run_dir, root=project_root)
        finalized = workflow.finalize_run(run_dir=run_dir, root=project_root)
        self.assertEqual(finalized["counts"]["accepted"], 3)
        self.assertEqual(finalized["counts"]["review_required"], 0)
        workflow.prepare_accepted_handoff(run_dir=run_dir, root=project_root)
        handoff_path = run_dir / "accepted_annotations_for_orchestrator_review.jsonl"
        handoff_manifest = json.loads(Path(str(handoff_path) + ".manifest.json").read_text(encoding="utf-8"))
        authorization = {
            "authorization_version": "2-alpha", "issued_by": "orchestrator", "training_permitted": True,
            "permitted_components": sorted(REQUIRED_COMPONENTS),
            "run_manifest_sha256": hashlib.sha256((run_dir / "run_manifest.json").read_bytes()).hexdigest(),
            "decision_manifest_sha256": hashlib.sha256((run_dir / "decision_manifest.json").read_bytes()).hexdigest(),
            "dataset_registry_sha256": hashlib.sha256((project_root / "ai/config/dataset_registry.json").read_bytes()).hexdigest(),
            "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "partition_manifest_sha256": hashlib.sha256(partition_path.read_bytes()).hexdigest(),
            "accepted_annotation_file_sha256": hashlib.sha256(handoff_path.read_bytes()).hexdigest(),
            "accepted_source_ids_sha256": handoff_manifest["accepted_source_ids_sha256"],
            "frozen_evaluation_source_boundary_sha256": hashlib.sha256(partition_path.read_bytes()).hexdigest(),
        }
        authorization_path = run_dir / "training_authorization.json"
        authorization_path.write_text(json.dumps(authorization, ensure_ascii=False), encoding="utf-8")
        accepted_path = run_dir / "accepted_train.jsonl"
        with (
            mock.patch("src.datasets.registry.require_training_source", return_value={"dataset_id": "enron"}),
            mock.patch("src.structured_models.require_training_source", return_value={"dataset_id": "enron"}),
        ):
            workflow.export_accepted_train(
                run_dir=run_dir, output_path=accepted_path, authorization_path=authorization_path,
                evaluation_boundary_path=partition_path, root=project_root,
            )
            export, preflight = preflight_authorized_export(
                accepted_path, authorization_path, project_root / "ai/config/dataset_registry.json",
            )
        self.assertEqual(len(export.rows), 3)
        self.assertEqual(len(preflight.prepared.speech_texts), 2)
        self.assertEqual(preflight.prepared.speech_targets, (("INFORM",), ("INFORM",)))
        self.assertFalse(preflight.ready, "the tiny synthetic fixture is never eligible for fitting")

        # Tampering with the immutable decision chain must fail in the public
        # workflow verifier, even when the export and its local sidecar remain.
        decision_manifest_path = run_dir / "decision_manifest.json"
        decision_manifest_path.write_bytes(decision_manifest_path.read_bytes() + b" ")
        with mock.patch("src.datasets.registry.require_training_source", return_value={"dataset_id": "enron"}), \
                mock.patch("src.structured_models.require_training_source", return_value={"dataset_id": "enron"}):
            with self.assertRaisesRegex(TrainingGateError, "workflow provenance verification failed:.*(decision|handoff manifest)"):
                preflight_authorized_export(
                    accepted_path, authorization_path, project_root / "ai/config/dataset_registry.json",
                )

    def test_preparation_uses_authored_ranges_and_project_only_speech_rows(self):
        text = "Please send the plan.\n> Previously: cancel the meeting."
        end = len("Please send the plan.")
        rows = [
            _row("p-1", text=text, authored_ranges=[{"start": 0, "end": end}]),
            _row("n-1", scope="NON_PROJECT", speech_act=None, text="Personal lunch."),
        ]
        prepared = prepare_training_examples(rows)
        self.assertEqual(prepared.scope_targets, ("PROJECT", "NON_PROJECT"))
        self.assertEqual(len(prepared.speech_texts), 1)
        self.assertEqual(prepared.speech_targets, (("REQUEST",),))
        self.assertNotIn("Previously", prepared.speech_texts[0])

    def test_feature_target_preparation_deduplicates_acts_and_uses_known_heads(self):
        row = _row()
        row["annotation"]["acts"].append({
            **row["annotation"]["acts"][0], "id": "act2", "speech_act": "INFORM",
        })
        prepared = prepare_training_examples([row])
        self.assertEqual(prepared.speech_targets, (("REQUEST", "INFORM"),))
        self.assertEqual(len(prepared.speech_texts), 1)
        self.assertEqual(len(SPEECH_ACTS), 11)

    def test_unbounded_quoted_history_cannot_supervise_current_speech_acts(self):
        for history in ("\n> Previously: cancel the meeting.",
                        "\n-----Original Message-----\nPlease approve the old request.",
                        "\n---------------- Forwarded by Someone ----------------\nOld request.",
                        "\nOn Tuesday Someone wrote:\nOld request."):
            with self.subTest(history=history):
                prepared = prepare_training_examples([_row(text="Please send the plan." + history)])
                self.assertEqual(prepared.scope_targets, ("PROJECT",))
                self.assertEqual(prepared.speech_texts, ())
                self.assertEqual(prepared.speech_targets, ())
                self.assertEqual(prepared.speech_history_quarantined_rows, 1)
                report = count_and_check_classes(prepared, PREDECLARED_MINIMUM_PER_CLASS)
                self.assertEqual(report.counts["speech_acts"]["REQUEST"]["positive"], 0)

    def test_explicit_authored_range_recovers_current_act_without_history(self):
        text = "Please send the plan.\n-----Original Message-----\nPlease approve the old request."
        prepared = prepare_training_examples([_row(text=text, authored_ranges=[{"start": 0, "end": 21}])])
        self.assertEqual(prepared.speech_targets, (("REQUEST",),))
        self.assertEqual(prepared.speech_history_quarantined_rows, 0)
        self.assertNotIn("Original Message", prepared.speech_texts[0])

    def test_duplicate_model_inputs_cannot_inflate_support_or_hide_conflicting_targets(self):
        rows = [_row(f"copy-{index}") for index in range(25)]
        prepared = prepare_training_examples(rows)
        self.assertEqual(len(prepared.scope_texts), 1)
        self.assertEqual(prepared.speech_targets, (("REQUEST",),))
        report = count_and_check_classes(prepared, PREDECLARED_MINIMUM_PER_CLASS)
        self.assertFalse(report.ready)
        self.assertEqual(report.counts["scope"]["PROJECT"], 1)
        conflict = _row("conflict", scope="NON_PROJECT", speech_act=None)
        with self.assertRaisesRegex(TrainingGateError, "conflicting primitive targets"):
            prepare_training_examples([rows[0], conflict])
        act_conflict = _row("different-act", speech_act="INFORM")
        with self.assertRaisesRegex(TrainingGateError, "conflicting primitive targets"):
            prepare_training_examples([rows[0], act_conflict])

    def test_preregistered_count_floor_is_enforced_without_fitting(self):
        prepared = PreparedExamples(
            scope_texts=("project",) * 20 + ("outside",) * 20,
            scope_targets=("PROJECT",) * 20 + ("NON_PROJECT",) * 20,
            speech_texts=("mail",) * 40,
            speech_targets=tuple(
                tuple(label for label in SPEECH_ACTS if (i < 20)) for i in range(40)
            ),
        )
        report = count_and_check_classes(prepared, PREDECLARED_MINIMUM_PER_CLASS)
        self.assertTrue(report.ready)
        self.assertEqual(report.counts["speech_acts"]["REQUEST"], {"positive": 20, "negative": 20})
        with self.assertRaisesRegex(TrainingGateError, "cannot relax"):
            count_and_check_classes(prepared, PREDECLARED_MINIMUM_PER_CLASS - 1)

    def test_shortage_report_counts_positive_and_negative_per_act(self):
        prepared = PreparedExamples(
            scope_texts=("project",) * 20 + ("outside",) * 20,
            scope_targets=("PROJECT",) * 20 + ("NON_PROJECT",) * 20,
            speech_texts=("mail",) * 40,
            speech_targets=tuple(() for _ in range(40)),
        )
        report = count_and_check_classes(prepared, 20)
        self.assertTrue(report.ready, "rare speech-act heads must not block a supported scope baseline")
        self.assertEqual(report.supported_speech_acts, ())
        self.assertIn("positive=0<20", report.unsupported_speech_acts["REQUEST"])
        self.assertEqual(report.counts["speech_acts"]["REQUEST"]["negative"], 40)

    def test_supported_heads_are_selected_individually(self):
        targets = []
        for index in range(40):
            positive = []
            if index < 20:
                positive.extend(("REQUEST", "INFORM"))
            if index < 3:
                positive.append("APPROVE")
            targets.append(tuple(positive))
        prepared = PreparedExamples(
            scope_texts=("project",) * 20 + ("outside",) * 20,
            scope_targets=("PROJECT",) * 20 + ("NON_PROJECT",) * 20,
            speech_texts=("mail",) * 40,
            speech_targets=tuple(targets),
        )
        report = count_and_check_classes(prepared, 20)
        self.assertTrue(report.ready)
        self.assertEqual(report.supported_speech_acts, ("REQUEST", "INFORM"))
        self.assertIn("APPROVE", report.unsupported_speech_acts)


if __name__ == "__main__":
    unittest.main()
