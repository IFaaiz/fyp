# AI-only annotation pilot: independent review and disagreement audit

## What was run

The fixed, screened 50-email Enron pilot was annotated independently by two GPT-6 Luna subagents at xhigh reasoning effort. Both used the [annotation guidelines](../annotation/annotation_guidelines.md) and the same canonical schema, but neither read the other's annotations. A third GPT-6 Luna xhigh subagent reviewed the **24 classification disagreements** after both outputs were complete. It saw both reviewers' labels, so its recommendations are an AI audit, not an independent accuracy reference.

All source email text and both AI JSONL outputs remain in ignored `ai/data/annotated/ai/project_pilot_50/`; the full-text disagreement queue is in ignored `ai/data/annotated/ai_reviewed/project_pilot_50/`. The tracked [agreement JSON](ai_pilot_agreement.json) contains aggregate counts and hashed email IDs but no email bodies. The original 250-email seed and the existing human `faaiz` decisions were not changed.

Every one of the 50 rows in both reviewer outputs preserves the fixed seed's source fields and order, passes canonical validation, and has `annotation.status=ai_prelabelled` and `annotation.annotation_source=ai`. No record is marked `human_reviewed` or `gold`. Reviewer A produced 168 valid spans and reviewer B 276; these counts describe annotation coverage, not correctness.

## Agreement observed

| Measure | All 50 | Neither reviewer flagged (36) |
| --- | ---: | ---: |
| Exact multi-label set | 26/50 (52%) | 21/36 (58.3%) |
| Exact full span set | 12/50 (24%) | 12/36 (33.3%) |

The ten intentionally clear out-of-scope controls all received `NON_PROJECT` from both reviewers. Among the 40 provisionally project-relevant candidates, exact full-label agreement was 16/40 (40%). Across all 50, 24 emails have a classification difference, 15 have only span differences, and 23 differ in both labels and spans (39 unique disagreement emails). The reviewers marked 14 distinct emails `needs_review`; neither abstained with `unlabelled` status. The clean-subset denominator excludes those 14 flagged emails.

Per-label raw agreement ranges from 78% for `ACTION_REQUEST` to 100% for `APPROVAL`, but a high percentage can reflect agreement that a rare label is absent. In particular, `FOLLOW_UP` was used on 2 emails by reviewer B and none by reviewer A. The reviewer A/B span instance counts are 107 exact matches, 61 A-only, and 169 B-only. These are exact boundary comparisons, not semantic equivalence.

The third AI audit's complete suggested label set matched reviewer A on 11 of the 24 classification disagreements, reviewer B on 9, and neither on 4; it retained ambiguity on 2. This does not make A a more accurate annotator: the audit saw the reviewers' outputs, and all three used the same model family.

## What the disagreements show

1. `REPORT_REQUEST` needs a concrete request or follow-up for a formal project document. A document being attached, reviewed, or mentioned as due does not by itself satisfy that label.
2. `MEETING` requires an actual project meeting being scheduled, confirmed, changed, or substantively discussed. A past meeting reference or a meeting merely used as a date anchor is insufficient.
3. `DEADLINE` requires a project action or deliverable due date. Event dates, regulatory start dates, and tentative launch targets need separate interpretation.
4. `ACTION_REQUEST` should cover a distinct operational task; a sole departmental input, document delivery, or approval transaction uses its specific label.
5. Spans need a stricter shared boundary checklist. The two reviewers often selected different extents for action phrases, named documents, dates, and roles. Exact offsets passed schema validation, but validation cannot decide whether a span is semantically complete.

These points already appear in the annotation guidelines; the pilot shows that an AI prompt needs to enforce them with a short decision checklist and examples before scaling. The third audit recommendations remain local AI suggestions and should not be merged into a gold set.

## Reproduce the comparison

From the repository root, with the project virtual environment:

```powershell
ai\.venv\Scripts\python.exe ai\scripts\compare_ai_pilot.py --reviewer-a ai\data\annotated\ai\project_pilot_50\reviewer_a.jsonl --reviewer-b ai\data\annotated\ai\project_pilot_50\reviewer_b.jsonl --report ai\reports\ai_pilot_agreement.json
```

The comparison validates the fixed seed, exact ID order and source fields, AI provenance, known labels, and exact span offsets before writing metrics. It keeps the full-text disagreement queue under ignored `ai/data/`.

Seed SHA-256: `3595cda452a6bff59274aa7db2cc4d47f02d10877c14a74f473ca2244e43720f`. Reviewer A SHA-256: `3fede5c95a8b0e5c3d1605bf3bd192757e2e1f293ce2db24cf1a60b49ecd0552`. Reviewer B SHA-256: `fdced4db1ac2904f7489fb12ca512fde83a58486a308f1b025cfba4fb00a4277`.

This experiment shows where the AI reviewers are consistent and where the task definition remains hard. It is not a model accuracy or deployment-readiness result. Enron is also outside the intended university/workplace Outlook domain. A human-reviewed, thread-isolated target-domain set remains necessary to measure real performance; that work is deferred for now.
