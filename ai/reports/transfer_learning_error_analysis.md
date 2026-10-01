# Transfer-learning source-based error analysis — 2 October 2026

**AI-silver diagnostic errors, not errors against human ground truth.**

## Coverage

The primary weighted DistilBERT evaluation with training-only tuned thresholds made **135 exact-set errors among 138 validation records**. The supervisor personally read the actual subject and current authored body of **50** selected errors. The unweighted fixed-threshold prediction was also examined on each same source.

Selection: all rare-reference errors first, followed by deterministic SHA-256 ranking, taking one error per leakage component. This intentionally diagnostic sample is not an unbiased prevalence estimate of all error causes. Categories overlap; counts need not sum to 50.

## Source-based categories

| Category | Records |
|---|---:|
| action_vs_document_request | 27 |
| project_scope | 25 |
| multi_label_partial_miss | 19 |
| approval_scope | 15 |
| general_update_overuse | 13 |
| deadline_date_role | 12 |
| rare_class | 8 |
| action_vs_department_input | 8 |
| missing_context | 9 |
| meeting_scope | 7 |

No selected case established quote cleaning as the direct cause of a prediction error. Earlier header repairs remain in place. The small error sample cannot rule out other cleaning errors.

## Concrete failure patterns

- Weighted predictions repeatedly treated ordinary invoices, HR reviews, training invitations and external vendor/system notices as project requests or progress. This was checked against source context, not inferred from reference labels alone.
- Documents already attached or reviewed often acquired REPORT_REQUEST. Explicit review/comment tasks and current document-production requests were not reliably distinguished.
- Meetings, release dates, historical source dates and completion cutoffs were mixed up. Genuine pre-migration cleanup and notice-to-proceed deadlines were missed.
- The unweighted 0.5 model emitted only GENERAL_UPDATE and NON_PROJECT across final validation. It therefore missed meeting coordination, actions, completion deadlines, approvals, departmental contributions and follow-ups even when those functions were explicit.
- Genuine authorization and substantive unit requirements/testing examples were often reduced to generic updates; weighted inference also invented approval on sources with no authorization function.

One reviewed approval miss also had a concrete input limitation: the source contained 588 tokenizer tokens, and its explicit proceed-decision request fell beyond the 512-token cutoff. Another sampled truncated source lost only vendor footer/contact material. Five of 138 validation messages were truncated overall. These checks used actual tokenizer boundaries and source text.

## Class weighting and tuning

Training-only raw negative/positive weights reached 84.2 for REPORT_REQUEST, 70.0 for FOLLOW_UP and 52.25 for APPROVAL. The weighted tuned model predicted REPORT_REQUEST on **101/138** records although its reference support was **2** (precision about 0.020). It correctly recovered only **1/74** NON_PROJECT references. This is not usable rare-label recognition.

Threshold optimization was isolated to the 110-row tuning partition, but most labels had fewer than 20 tuning positives. Rare thresholds based on two to four positives did not transfer reliably. Independent binary threshold selection followed by exclusive NON_PROJECT resolution also couples outcomes; tomorrow must use training-only calibration to investigate that behavior.

## Reference uncertainty and future exclusions

The source review identified **six additional unresolved project-scope references**. They are quarantined for future fitting in [tonight_post_experiment_quarantine.json](../annotation/tonight_post_experiment_quarantine.json). The frozen 674-record experiment, 138-record validation set and published metrics were preserved. Removing error cases and presenting a better score would be a post-hoc change, so no such accuracy claim is made. Eligible records for the next training iteration are **668** after applying this quarantine.

These six validation records are not in the future human calibration queue. A later independent human evaluation requires a fresh held-out set.

## Error IDs and decisions

[Text-free machine-readable source decisions](transfer_learning_error_analysis.json) contain all 50 IDs, reference labels, model labels, categories, uncertainty flags and paraphrased reasons. Full source queues are local ignored files under `ai/data/experiments/tonight_20261002/`. No source email text is reproduced in this report.

## Tomorrow

Prioritize targeted human calibration and then active learning on ambiguous project scope and rare functions. Keep TF-IDF as the stronger nine-label diagnostic reference. The present result does not justify DAPT, a stronger encoder, or extraction work before label quality and rare coverage improve.
