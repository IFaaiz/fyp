# Second blind AI annotation pilot

## Design and provenance

A fresh 50-email Enron batch was screened from the existing candidate pool: 40 provisional project-work candidates plus 10 clear out-of-scope controls. It shares no email IDs with the original 250-email seed or first 50-email pilot, and no threads or normalized message bodies with the first pilot. The deterministic selection is in [project_pilot_50_v2_ids.json](../annotation/project_pilot_50_v2_ids.json); the seed builder rejects overlaps and split candidate-pool threads. The seed remains unlabelled and is stored under ignored `ai/data/annotated/ai/project_pilot_50_v2/`.

Two independent GPT-6 Luna xhigh subagents read the [v2 AI review protocol](../annotation/ai_review_protocol_v2.md), the canonical guideline and schema, and the new seed. They did not read one another's outputs or the first pilot's labels while annotating. The two canonical outputs are local ignored JSONL files under `ai/data/annotated/ai/project_pilot_50_v2/reviewers/`. They are AI prelabels or explicit AI abstentions, never `human_reviewed` or `gold`. One duplicate span instance in reviewer A's output was mechanically removed after the comparison validator detected it; no label, source text, or unique span was changed. Both corrected outputs then passed canonical validation and exact source-field/order checks.

The second batch is somewhat longer than the first (median current-message length 1,728 vs 1,474 characters; 16 vs 13 messages over 2,500 characters). The content and difficulty distribution also differ. Results below compare consistency across batches; they cannot isolate the protocol's causal effect or measure annotation accuracy.

## Observed inter-AI agreement

| Measure | First pilot | Second pilot |
| --- | ---: | ---: |
| Exact full label set, all 50 | 26/50 (52%) | 33/50 (66%) |
| Exact full span set, all 50 | 12/50 (24%) | 23/50 (46%) |
| Exact full label set, neither flagged | 21/36 (58.3%) | 25/31 (80.6%) |
| Exact full span set, neither flagged | 12/36 (33.3%) | 17/31 (54.8%) |
| Distinct emails flagged `needs_review` | 14 | 19 |
| Explicit classification abstentions | 0 | 1 |

Both reviewers assigned `NON_PROJECT` to all ten clear controls. For the 40 provisionally project-relevant candidates, exact full-label agreement was 23/40 (57.5%), compared with 16/40 (40%) in the first pilot. However, both reviewers also marked eight additional screened candidates `NON_PROJECT`, showing that the screening is an imperfect proxy for in-scope project mail. Of 33 second-pilot queue entries, 17 have a classification difference, 11 have only a span difference, and 5 are flagged even though their labels and spans match.

Reviewer A has 143 unique exact spans after mechanical deduplication; reviewer B has 134. The first pilot had 168 and 276 respectively. Part of the count difference follows the higher number of `NON_PROJECT` decisions in pilot 2, but reviewer B's span count per in-scope email also fell (6.9 to 4.47). A higher exact-set match can therefore reflect more consistent **omission** as well as better boundary selection. The second pilot shows higher observed consistency under the v2 protocol, while extraction coverage needs separate audit before using spans for model training.

The tracked [v2 agreement JSON](ai_pilot_v2_agreement.json) contains aggregate metrics and source-qualified IDs without email text. The full-text disagreement queue remains under ignored `ai/data/annotated/ai_reviewed/project_pilot_50_v2/`. Agreement is not precision, recall, F1 against truth, or evidence that one reviewer is more accurate. No human annotation was requested or overwritten.

## Remaining issues

The second pilot still shows disagreements on whether general business and administrative work is within the FYP's **project-management** scope; whether `ACTION_REQUEST` should accompany a specialized request; and whether a short meeting-related message describes a project meeting or an unrelated business appointment. The single abstention concerns `Woodside Petroleum Meeting`, where the current message is insufficient for one reviewer to decide the defined scope. Reviewer flags rose from 14 to 19 distinct emails, which is appropriate to keep visible instead of forcing labels.

A third GPT-6 Luna xhigh auditor then examined the 17 classification disagreements with access to both reviewers' labels. Its ignored local suggestions (`ai/data/annotated/ai/project_pilot_50_v2/disagreement_audit.jsonl`) match reviewer A's full label set on 5 cases, reviewer B's on 4, and neither on 8. It flagged 12/17 as ambiguous and left 3 `unlabelled` because the current message did not establish project scope. This is an AI analysis of the disputed cases, not an independent reference or gold adjudication. Its dominant concerns are project scope for ordinary business/operations mail, standalone tasks versus specialized document or department requests, and project meetings versus commercial or public events.

The next useful AI-only experiment is to hold the batch fixed when comparing prompt variants, or to use another blind batch for a replication check. Neither can establish correctness without a trusted reference, and the historical Enron domain still differs from the intended Outlook project mail. Keep all these records marked as AI prelabels while human review is deferred.

## Reproduce

From the repository root:

```powershell
ai\.venv\Scripts\python.exe ai\scripts\build_project_pilot_v2.py
ai\.venv\Scripts\python.exe ai\scripts\compare_ai_pilot.py --pilot-seed ai\data\annotated\ai\project_pilot_50_v2\annotation_seed_50.jsonl --reviewer-a ai\data\annotated\ai\project_pilot_50_v2\reviewers\reviewer_a.jsonl --reviewer-b ai\data\annotated\ai\project_pilot_50_v2\reviewers\reviewer_b.jsonl --report ai\reports\ai_pilot_v2_agreement.json --disagreements ai\data\annotated\ai_reviewed\project_pilot_50_v2\disagreements.jsonl
```

Protocol SHA-256: `358bf2be522f799ea81e2e61a09d0897e260ba224bb76dd423e9d1b31f09b871`. Seed SHA-256: `91d89d89923c28464dfdacc8cba1317da2cee18498db07b21fbd49f41bbbb835`. Reviewer A SHA-256 after deduplication: `dd7396a634810b1a6bd94abd7d73f735c13b0dd5cc524db99d8678b036703d1c`. Reviewer B SHA-256: `2375200aa03d4e1a45d43ad119065e9111905421e94a93295e8e21aad0325975`.
