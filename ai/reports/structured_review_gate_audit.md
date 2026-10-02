# Structured review and baseline gate audit

Date: 2026-10-03
Scope: read-only review of the structured pipeline plan, schema, runbook, evaluation report, current review workflow, baseline gate, synthetic test source, and metadata for the frozen V2 boundary. No annotation, fitting, TEST access, commits, or test execution was performed. Candidate JSONL bytes were hashed and only record IDs were extracted for membership checks; no source text or excerpts were emitted or inspected.

## Result

The frozen candidate boundary and current code path have the intended core gates in place. The metadata-only membership/isolation checks passed. The follow-up audit confirmed the protected-ID consistency check and added synthetic workflow coverage described below. This is a workflow and provenance audit, not a validation of source-content labels, an independent-process audit, or an evaluation of model performance.

## Boundary and membership checks

The actual index at `ai/data/processed/structured_v2_expanded_leakage_index_v2.json` hashes to `d864f94d4bc68bcca2d3f017fe7b5b7ef69bad5bcd41fde80f8b0905cfe2a0f1`, matching the V2 `boundary_manifest.json` binding.

| Check | Result |
|---|---:|
| Indexed records | 28,129 |
| `TRAIN_SCREEN` records | 4,285 |
| `EVAL_RESERVED` records | 600 |
| `HISTORICAL_EXPOSED` records | 11,889 |
| Train candidate file SHA and ID set match its frozen partition | Pass; 4,285 unique IDs |
| Evaluation candidate file SHA and ID set match its frozen partition | Pass; 600 unique IDs |
| Global protected IDs / native protected IDs | 13,089 / 13,089 |
| Protected selected evaluation IDs | 600 of 600 |
| Protected historical IDs | 11,889 of 11,889 |
| Protected but unassigned reserve IDs | 600 |
| Other unassigned index records | 10,755; remain auxiliary inventory, not held-out partitions |
| Train/protected ID overlap | 0 |
| Cross-partition leakage component conflicts | 0 |
| Current train-component exclusions | 0 |

Protection is correctly separate from partition assignment: the 600 unused reserve sources are protected without being promoted into a held-out partition. The code's component-level TRAIN exclusion includes protected global IDs, so reserves may share components with selected evaluation or historical records without requiring a fabricated partition for each reserve. The current boundary's native/global protected-ID namespace mapping also matches.

The current reports say there are zero accepted structured annotations, zero human-gold labels, and no training authorization. The 4,285 rows are screening sources; they are not 4,285 project examples or usable training labels.

## Workflow gates present in code

- Preparation checks the candidate file hash, exact requested partition membership, unique IDs, current-source fingerprints against the index, and train-component isolation. It produces distinct A/B source-only packets and binds each packet to the source bundle, annotation-schema bytes, validator source, and mapper source.
- Boundary intake now validates both protected-ID lists for valid unique strings and checks that protected native IDs, qualified for the run dataset, exactly match that dataset's protected global IDs. It keeps protected-but-unassigned reserves outside named partitions while including their global IDs in component-level train exclusions.
- Ingest checks the envelope's assigned role, packet/source-manifest hashes, exact ordered source IDs, exact source hashes, and a `read_all_sources` attestation. Reviewers must report distinct identity strings and the configured model/reasoning values.
- Comparison alpha-normalizes local primitive IDs and array order, then compares typed primitives, relations, uncertainty, and exact evidence. Derived FYP labels are recorded but do not stand in for primitive/evidence agreement.
- Every EVAL and CHALLENGE record requires C review even when A/B agree; training rows require C when A/B primitives disagree. C's initial packet contains source material only. The post-blind packet is created only after the initial C verdict and receipt are stored and revalidated, then binds the frozen C verdict and the A/B artifacts.
- Root review flags high-risk mapped labels and deadline, thread-change/follow-up, approval, department, scope-uncertainty, and mapper-review cases. Root approval is bound to the selected annotation hash and is rejected when that annotation remains uncertain. Finalization revalidates A/B, comparison, C, root decisions, and selected annotations before writing decisions.
- Handoff and export rebuild the decision/source/index/boundary chain. The baseline loader accepts only `accepted_train.jsonl`, validates current registry bytes and the actual authorization file bytes, and invokes workflow provenance verification before preparing examples. The baseline CLI defaults to preflight; fitting requires explicit `--fit` and a new private output directory.
- The previously reported `registry_path` containment issue appears fixed in the current source: the canonical `ai/config/dataset_registry.json` path is compared directly and its bytes are hashed; it is not passed through the `ai/data` private-path helper.

## Findings and actions

### Closed — validate both protected-ID representations at boundary intake

The follow-up code validates string values and duplicate IDs, then compares the qualified native IDs with the global protected IDs for the active dataset before checking their index presence and partition safety. The synthetic `test_deterministic_source_bound_slices_invalid_ranges_and_partition_isolation` now checks both a mismatched native/global list and an unassigned protected reserve that shares a component with TRAIN; both must be rejected. The metadata-only V2 boundary check continues to pass.

### Closed — add synthetic coverage for the C/EVAL and root decision path

The new `ai/tests/test_structured_review_workflow.py` covers the requested high-risk branches with invented source strings:

1. A/B primitive disagreement still requiring C when final labels match.
2. Every EVAL record requiring C despite A/B agreement; the C initial packet remains source-only, and the reveal is blocked until the bound initial verdict is ingested.
3. Invalid A/B, C-initial, and C-adjudication source-read attestations being rejected.
4. High-risk assertions requiring root approval after adjudication, with uncertainty unable to be cleared by root approval.
5. Changed reviewer/comparison/C/decision/root-decision/handoff/export/authorization/registry artifacts and stale schema/validator/mapper files being rejected during provenance verification.
6. An unassigned protected reserve sharing a synthetic component with TRAIN, plus native/global protection-list mismatch, being rejected.

The existing model-gate suite still supplies targeted invalid-export, uncertainty, registry, index/hash, count-floor, and no-fit preflight coverage. The root-run focused suite passed 119 tests in total, including the new seven workflow tests and 20 model-gate tests; this sub-audit inspected the test source but did not rerun tests.

### Residual — not every stored sidecar/receipt mutation has a direct test

The workflow rederives its manifests and compares stored receipts/artifacts during ingestion and final verification. Synthetic tamper coverage mutates representative A, C-initial, and C-adjudication envelopes; pair comparison, decision, root decision, handoff bytes, TRAIN bytes, authorization contents, registry bytes, source bytes, and current schema/validator/mapper files. The tests do not directly mutate every receipt or every packet/assignment and sidecar file. Add a compact table-driven test for at least one A/B ingest receipt, C receipt, A/B/C packet or assignment, handoff manifest, TRAIN export sidecar, and the frozen index/boundary after run creation. This is residual coverage work; the current code paths are already designed to revalidate these bindings.

## Assurance limits

The workflow binds reviewer and root identity strings, packet hashes, attestations, receipts, and downstream artifacts. It can detect stale or inconsistent artifacts under the expected filesystem workflow, but a self-reported identity/read attestation is not proof that a person or independent process read the sources. With reviewers and artifacts on a shared writable filesystem, the code cannot prove process isolation or prevent a reviewer from reading another role's files. Likewise, SHA-256 hashes and fields such as `issued_by: orchestrator` and `training_permitted: true` are integrity bindings, not a cryptographic authorization authority: anyone able to rewrite the whole mutable chain can recompute them. Keep the explicit external review/authorization step and describe results as AI-silver diagnostics.

No tests were executed by this audit; the 119-test result above was reported by the root task, while this follow-up independently inspected the current synthetic test source and gates. No conclusion about source-content correctness, rights, or model accuracy follows from these metadata/workflow checks; the source-content audit was completed separately.
