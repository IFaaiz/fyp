# Native MailEx extraction benchmark

## Scope and preserved checkpoint

This experiment compares native event/argument extraction with direct event
records. It is separate from FYP classification and structured V2 fitting.
Starting repository HEAD: `e3fe3c88476d942b72e85708be0b394b3c8ced4d`.
The closed V1 verification checked 77 files without inference: zero changed
or missing. A private SHA-256 snapshot covers 231 current V2 files, including
the schema, mapper, boundary, review artifacts, accepted export and scope
model. Snapshot digest:
`456fa124d96807ae26351cab07d1a51e60c15b96d5b9bb37bb4e641c91040555`.

## Dataset and protected-source exclusion

The [official MailEx package](https://github.com/salokr/Email-Event-Extraction)
contains 1,200/150/150 TRAIN/DEV/TEST threads and 3,117/414/405 message turns.
It contains 11 non-O types, 25 case-sensitive role names and 8,392 events.
The faithful case-sensitive BIO conversion yields 18,149 argument runs;
the legacy case-folded conversion yielded 18,099. The 50 additional runs
are explicit role-case transitions, not invented annotation.

Model runs use the separately named `mailex_native_fyp_safe_v1` variant.
Metadata comparison against actual protected FYP membership found 31/4/3
direct message matches. Expansion through the existing leakage components
and whole-thread exclusion removes 139/19/15 threads. The unchanged official
conversion remains available privately; variant results must not be cited as
untouched official MailEx results.

| Partition | Usable threads | Messages | Events | JSONL SHA-256 |
|---|---:|---:|---:|---|
| TRAIN | 1,061 | 2,762 | 5,729 | `9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333` |
| DEV | 131 | 361 | 828 | `fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d` |
| TEST | 135 | 363 | 772 | `1d728079223c64892d1925b0d6bee90c8e3f1e95253a9629256be7de6d882f68` |

This exclusion addresses known fingerprint/component associations. Original
Enron identities remain unresolved, so it does not establish complete FYP
identity isolation. Published duplicate leakage is documented in the
[native audit](mailex_native_extraction_audit.md); official partition
membership is retained for every included thread.

## Personal conversion review

The supervisor read 100 randomly sampled original TRAIN turns, their full
converted texts, native triggers, attached arguments, qualifiers and extras.
Every original non-O event array matched, every labeled token was retained,
and each derived span matched its source substring. After the component
exclusion, 86 reviewed rows remained usable; 14 additional random usable
rows were personally inspected to complete 100 usable TRAIN reviews.
Sampling seeds were 20261004 and 20261005. Private samples and identifiers
are excluded from Git.

Orphan I tags remain flagged and start explicit derived argument runs;
their raw BIO arrays are retained. Empty content stays in the dataset.
Zero-width tokens are omitted only from the compact model's token view,
with the exact message text and original token-index mapping retained.
No source labels were adjudicated or relabeled for this benchmark.

## Candidates

- Direct records: `fastino/gliner2.5-small-v1`, revision
  `7132dc4561c3f94563c6147e75ffa8ef34c4964a`, using verified boundary
  implementation in `gliner2==2.0.0`. Actual parameter count: 73,881,879.
- Pipeline: one shared DistilBERT encoder, revision
  `12040accade4e8a0f71eabdb258fecc2e7e948be`, with categorical BIO
  triggers per event type and trigger/type-conditioned argument BIO heads,
  signed distance embeddings and a trigger interaction. Actual
  parameter count: 66,601,862. Repeated predicted triggers create separate
  argument records. Discontinuous trigger grouping is not learned.

The compact encoder uses 512-wordpiece windows with stride 128, averaging
first available wordpiece embeddings across windows. Its argument head
sees the complete current turn and a pooled trigger. The coverage check
represented every nonempty original TRAIN word; 26 official TRAIN messages
needed multiple windows, at most three. Subject enrichment, runtime results,
model selection and TEST results are recorded in the dedicated reports as
measured. TEST inference requires a committed selection lock.

## Finalist selection rule (declared before TEST)

The compact final recipe retains encoder LR 2e-5 and body-only input. Complete
seeds 17, 23 and 41 use the same TRAIN/DEV hashes and four-threshold grid.
Choose the completed seed/threshold pair with the highest native DEV exact
argument-role micro F1; ties prefer the lower threshold, then smaller seed.
Report the three-seed mean and sample standard deviation separately. There
is no seed ensemble.

GLiNER's bounded fit selects its saved checkpoint by minimum trainer-DEV loss;
its native full-gold DEV record threshold is selected by exact argument-role
micro F1. This checkpoint criterion differs from the compact model and is a
limitation of the bounded comparison. The complete native DEV evaluator
includes records omitted from GLiNER's trainer-validation representation.

Base is considered only if Small shows useful learning and competitive native
role/record extraction. Prefer Small unless Base improves role or partial
record F1 by at least two absolute points, with CPU median latency and peak
working set no more than twice Small's on the same cohort. No Base result
will be estimated if that experiment is not justified.

## Historical initial results (DEV only)

The first independent-BCE trial was rejected after actual predictions showed
severe B/I fragmentation. Exclusive decoding helped, but exact role F1 remained
1.999%. Its failed checkpoint is preserved privately and has no TEST result.

The corrected categorical model was fitted for eight epochs on all 2,762 safe
TRAIN messages, seed 17, encoder LR 2e-5 and head LR 1e-3, batch 8. Epoch 6
was selected by DEV argument-role exact F1: 30.490% at threshold 0.5. A declared
four-value DEV grid (0.3, 0.5, 0.7, 0.9) selected 0.7: role F1 33.872%, partial
record F1 48.798%, exact record F1 17.938%. The subsequent learning-rate
comparison, subject ablation, robustness seeds and locked one-time TEST are
complete in [the final report](mailex_extraction_final.md). This section retains
the original seed-17 result as historical evidence.

The selected weights have SHA-256
`ac17ba4dbf09a45d9311ef186487b9c9dbc40ecb3bb69d1b3900588313e2c698`;
the threshold-0.7 DEV predictions have SHA-256
`1ba0824e0e74f1fdc64b649cfc9c464ed4748f7a1ebb146b2a1bc4984fd1382a`.
An independent evaluator reproduced the original threshold-0.5 metrics and
reported no non-source prediction segments. Loading the fine-tuned model from
architecture configuration rather than reading the original pretrained weights
again reproduced the original prediction bytes exactly.

At threshold 0.7, the gold-type-plus-trigger argument oracle reaches 44.304%
role exact F1. Event detection/association remains a bottleneck, and argument
quality is still inadequate for automatic Outlook actions.

Actual preliminary Windows CPU latency is 36.3 ms for the median-length DEV
email (39 source words), and 607.5 ms for the longest (721 words). Four CPU
threads are used. The corresponding RTX 5070 medians are 13.0 and 78.6 ms.
The weight file is 266,443,579 bytes. Peak CPU-process working set was
1,412,337,664 bytes. Measurements use DEV only and filesystem caches are not
flushed; final runtime details are maintained in the runtime report.
