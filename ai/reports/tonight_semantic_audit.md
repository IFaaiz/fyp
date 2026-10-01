# Semantic audit and frozen AI silver — 2 October 2026

**AI-silver diagnostics only. No human or gold labels were used.**

The starting Git HEAD was `7c6096700582ef8db9da5780fee3bc28149c6e9b` (617 accepted at that committed checkpoint). The verified local accepted working state contained **718** rows, including the previously completed third replacement tranche and supervisor exclusions. That complete local state was frozen before this audit. Dataset expansion stopped for this experiment.

## Review coverage

- All 353 project-positive rows were reviewed, including all 93 rows carrying at least one priority label.
- The supervisor personally read all 44 original rare-label cases, every auditor correction/exclusion proposal, all auditor disagreements, and identified scope/date ambiguities. New rare-label additions were also checked against their sources.
- A deterministic SHA-256-ranked sample of 50 NON_PROJECT rows and 12 targeted calendar examples were reviewed; two calendar examples overlapped the sample.
- Total unique audited: **413**. Final decisions: **346 confirmed, 23 corrected, 44 excluded uncertain**.
- Corrected silver v2: **674**. The other 305 retained negative examples did not receive a new semantic review tonight.

## Label changes

| Label | Before | Removed | Added | After |
|---|---:|---:|---:|---:|
| MEETING | 98 | 7 | 2 | 93 |
| DEADLINE | 62 | 6 | 1 | 57 |
| REPORT_REQUEST | 11 | 3 | 1 | 9 |
| DEPARTMENTAL_INPUT | 8 | 1 | 10 | 17 |
| ACTION_REQUEST | 121 | 15 | 1 | 107 |
| FOLLOW_UP | 13 | 3 | 0 | 10 |
| APPROVAL | 17 | 5 | 1 | 13 |
| GENERAL_UPDATE | 237 | 27 | 2 | 212 |
| NON_PROJECT | 365 | 8 | 0 | 357 |

Counts overlap because project labels are multi-label. Excluded rows count as removals for every label they held. Ambiguity was excluded, never converted into NON_PROJECT.

## Recurring mistakes

- Ordinary billing, legal deal work, staffing notices, external regulations and commercial transactions sometimes acquired project labels without clear managed-project scope.
- Launches, callbacks, meeting times and loose report availability estimates were sometimes mislabeled as completion deadlines. Explicit expected project completion dates remain valid deadlines.
- Completed unit testing and other substantive departmental contributions were overlooked; mentioning a company or department alone remains insufficient.
- A past task, contingent future follow-up, courtesy contact or recognition request sometimes acquired an action/follow-up label.
- Approval alone did not automatically acquire an additional GENERAL_UPDATE label.
- Two Lotus quoted-header patterns needed cleaner fixes; 24 original snapshot prefixes changed under the repaired extractor. Sources remained unchanged and the corrected authored view has its own hash.

## Freeze and split safeguards

- Corrected text-free manifest SHA-256: `0e022f93fcdaff59f21ca2c4406ce1f07e1b60a0f22f609ab9fcbca3d3e015fc`.
- Ignored full-text snapshot SHA-256: `3bd621f18e2118f06b8e1734198f1d01936ea817d081e4e2f6f420c29c9a9988`.
- Shared split SHA-256: `ebcdf58b3ffdaf9be854a3bad4ab5bfa79cffc52cb2d0899a07a742db049a1d5`.
- Identity, unique IDs, known nonempty labels, exclusive NON_PROJECT, AI-only provenance, canonical source hashes and exact derived authored-prefix hashes validate.
- Canonical leakage groups and source-qualified threads are unioned with 42 reviewed near-copy/template links before splitting. Template grouping is conservative and reduces effective independent sample size.
- Outer development pool: 536; final validation: 138. Development is further divided into 426 fitting and 110 threshold-tuning records. Both models reuse these exact partitions.
- No threshold, class weight or fitting update uses final validation. Human calibration queue excludes every validation ID, source-qualified thread and leakage group.
- Frozen manifest bytes are preserved by Git attributes so recorded hashes survive checkout across platforms.

## Limits

- AI agreement and supervisor adjudication are not human ground truth.
- Only deterministic 50 NON_PROJECT plus targeted calendar negatives reviewed; other negatives retain earlier AI labels.
- All records come from historical Enron mail, not modern Outlook project workflows.
- All rare labels have low support; diagnostic metrics cannot establish production quality.
- Conservative template grouping reduces effective independent sample size.
- The historical 1,000-row readiness gate remains unmet. The user explicitly authorized this smaller diagnostic run.

## Artifacts

- [Text-free decisions](../annotation/tonight_semantic_audit_decisions.jsonl)
- [Corrected manifest](../annotation/training_silver_v2_manifest.jsonl)
- [Shared split](../annotation/tonight_silver_v2_shared_split.json)
- [Machine-readable audit](tonight_semantic_audit.json)
- Full messages and full-text audit: ignored `ai/data/experiments/tonight_20261002/`.
