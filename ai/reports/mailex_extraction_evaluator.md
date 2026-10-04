# MailEx event extraction evaluator

This document defines the native message-level evaluator implemented in
`src/mailex_extraction/metrics.py`. It contains scoring rules only; it includes
no message bodies, annotations, model outputs, or benchmark results.

## Input contract

The gold and prediction files are UTF-8 JSONL. Each row represents one message
and has `message_id`, `split`, `text`, and `events`. Gold rows also normally
include `thread_id`, tokens, token offsets, and source provenance. These extra
fields are ignored by the scorer.

Each event is a distinct object with `event_type`, an optional `event_id`, a
`trigger` span group, and its own `arguments` list. An argument has `role`, an
optional `qualifier`, and a `segments` list. A segment has half-open `start` and
`end` Python character offsets plus the exact source `text`. This is the native
MailEx event contract: argument records remain attached to their event. The
scorer never flattens arguments across events or recovers a mention by searching
for text.

## Matching and scores

All source offsets use `[start, end)` character intervals into that message's
`text`. Discontinuous groups are represented as multiple segments. IoU merges
overlapping or nested intervals inside each group before measuring character
intersection over union. Partial span matches require IoU of at least 0.50.
Exact extents compare sorted segment boundaries, independent of segment order.
A split group and one merged segment can overlap fully while still failing exact
match. Every assignment is deterministic and one-to-one.

Primary event-record assignment only pairs the same event type. It maximizes
role-agnostic overlap between attached argument spans. For triggerless direct
records with no argument geometry, same-type records pair by attached role and
qualifier overlap, then stable input order. This preserves event-to-argument
association and prevents a wrong-type record with stronger mention overlap
from displacing a valid same-type record.

After primary pairs are fixed, residual events may be aligned by trigger and
argument overlap for event-type diagnostics, missed/spurious event counts, and
wrong-role/qualifier error counts. These diagnostic pairs do not earn primary
argument or exact-record credit. Trigger identification uses a separate
one-to-one assignment based on trigger span IoU.

The report includes:

- Event-type micro and per-type precision, recall, F1, macro F1 over gold
  supported types, and type-confusion counts.
- Event-record exact F1: exact event type and exact multiset of attached
  `(role, qualifier, span)` records. The primary record score does not require
  a trigger. A separate trigger-inclusive exact score adds the trigger when
  gold has one.
- Event-record partial F1: event type must be exact; argument records receive
  credit for matching role and qualifier with IoU at least 0.50. A separate
  trigger-inclusive exact and partial score adds the trigger when gold has an
  annotated trigger.
- Argument-record exact and partial F1, plus role-agnostic span exact and
  overlap F1. Role exact requires exact source extent and role, while role
  partial requires role and IoU at least 0.50. Role-plus-qualifier exact and
  qualifier scores are reported separately. Per-role and per-type/role support
  is included.
- Trigger exact and partial F1, plus trigger-conditioned event-type scores.
  Trigger scores are explicitly `not_applicable` when the selected gold split
  contains no trigger annotations. Gold event types with no annotated triggers
  are listed as N/A.
- Message counts and empty prediction rate, unaligned events, error-category
  counts, and source-offset validation counts.

Argument metric credit is scoped to its primary event pair. Thus an entity
mention reused in two event records can receive credit in each record, while an
argument moved from one event to another cannot borrow credit from the correct
event. Residual diagnostic pairs are used only to count event-type, role, and
qualifier errors.

## Source validation and malformed gold

Every provided span offset is checked against the row text. Gold segments with
invalid offsets, missing source text, or a text value that differs from
`text[start:end]` stop evaluation with an error. Gold event and argument flags
are counted and left in the source rows; they are not silently repaired or
excluded. Prediction segments with invalid offsets or text/offset disagreement
are counted as non-source segments and cannot earn overlap or exact-span credit.
Predicted segment text is required; a missing surface string cannot earn credit
from offsets alone. For shared message IDs, the prediction row's full `text`
must exactly equal the gold row's `text` before any metrics are computed.

Reports contain aggregate metrics and counts only. They do not copy text,
argument values, or source snippets.

## TEST authorization gate

The scorer accepts `split=test` only with a schema-versioned selection-lock
object. The CLI imposes additional checks before opening either TEST JSONL:
the lock must be a tracked, clean JSON file identical to committed `HEAD`; its
gold SHA-256 must match the specified gold file; and every finalist's schema,
weights, code, preprocessing, and evaluator path-to-digest map must match the
workspace files. Each finalist freezes its run ID, architecture, config,
thresholds, and expected private prediction path. The manifest contains no
prediction hash because inference has not run at lock time.

Before inference, call `reserve_test_run(selection_lock_path, run_id)`. It
creates an exclusive private reservation marker under
`ai/data/experiments/mailex_extraction_v1/private_test`; a second reservation
for that finalist fails. The CLI requires this marker, hashes the resulting
prediction file, and writes a private one-time result receipt without changing
the committed selection lock. The evaluator does not run TEST as part of its
tests or automatically discover TEST files.

## Running

From the `ai` directory:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_mailex_extraction.py `
  --gold <native-dev.jsonl> `
  --predictions <dev-predictions.jsonl> `
  --split dev `
  --output <dev-metrics.json>
```

The evaluator reads only the two explicit input paths. The CLI supports `train`
and `dev` directly. `test` requires `--selection-lock <committed-lock.json>` and
`--finalist-id <locked-run-id>`, plus the prior reservation marker. Synthetic coverage is in
`tests/test_mailex_extraction_metrics.py` and exercises event association,
wrong type and role errors, shared mentions, duplicates, invalid offsets,
overlapping/nested and discontinuous spans, empty predictions, and assignment
threshold behavior.
