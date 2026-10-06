# Guided annotation app usability update

Date: 6 October 2026, Asia/Karachi.

## Delivered changes

The existing review app now uses three stages: Relevance, Label message, Check & submit. The email remains beside the form on desktop. A phone stacks the reading and editing areas; moving to a later stage scrolls to its controls and opening a new email returns to the top.

Five choices have ordinary names and examples: Meeting, Task, Document, Approval and Project update. Required evidence has a completion checklist; optional names, dates and places stay in a disclosure. Tasks and updates let the reviewer explicitly reuse the same phrase for both required typed evidence roles. No label, state, argument or evidence is inferred from the assigned email.

A help dialog explains relevance, current-message-only evidence, exact words, document-transfer duplication, meeting dates, responsible people, departmental input, follow-ups, uncertainty and independent submission. These are general hand-authored examples. Missing information is left blank, and an email can have no acts to label.

Saved evidence is visibly highlighted. Internal excluded ranges are faded; tail text is collapsed as reference. Exact-word lookup excludes occurrences outside authored ranges and offers an occurrence choice for repeated valid phrases. The UI maintains the original source text and Unicode code-point offsets.

Draft autosave, revision checks, server provenance, frozen submissions, private account access and original assignments are preserved. Submit & next opens the next unfinished email. Owner progress is shown in human-readable counts instead of raw JSON.

## Design guidance

Read the user-requested gpt-taste skill in the separate Padelverse project. Applied its contrast, spacing, restrained card and typography guidance to this task workspace. Cinematic hero, marketing sections and scroll pinning would obstruct labeling and were not added. No new UI dependency or remote asset is required. Text uses rem sizes, visible keyboard focus and reduced-motion support. Help uses a native modal dialog with Escape/focus handling.

## Verification

- Existing TypeScript check passed.
- Existing validator: 16 synthetic fixtures / 29 checks passed.
- Synthetic browser workflow passed using bundled Playwright and a separate headless Chrome process: rendered content; DOM range selection across highlighted text; excluded-line rejection; task/update typed phrase reuse; draft save; modal Escape; 390px phone overflow check; 200% text overflow check; submit-next; new-email scroll reset; submitted review locked; and non-project zero-event review with pasted evidence.
- Browser API responses used synthetic intercepted records. Zero production reviews were created by verification, and no human calibration submission is claimed.
- In-app browser automation still failed to initialize because of its Windows ACL setup; browser verification used the separate local headless process. The user-facing browser handoff remains subject to the desktop app opening its queued tab.
- Guidance helper checks passed for Unicode offsets, excluded occurrences and required-role coverage.
- Production-compatible build and native publication succeeded. Site source `6185d80a407478005e0d8ceab688f4282f6a9157`, deployment `appgdep_6ac503ca09688191b3eabba13ed62f2b`, runtime revision 3. The existing custom private allowlist is preserved.

## Research limits

This is an interface change, not a schema freeze, agreement result or training-quality claim. General examples and UI defaults are aids to manual work; reviewers must choose the state and meaning themselves. No source queue or corpus text is in this report. Heldout evidence-range verification, the third account, blind completion and human adjudication remain pending.
