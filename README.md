# Outlook Integrated Smart Project Management — FYP

## Current AI/NLP workstream

**10 October 2026:** The active human annotation contract is
**fyp-direct-label-v1.1**: direct relevance, eight FYP labels, exactly 11 optional
extraction targets, and auxiliary EVIDENCE. Each selected project label requires
current-message evidence. Missing extraction details alone do not require review.
See the [final pre-labeling audit](ai/reports/fyp_prelabeling_final_audit_2026-10-10.md)
and [current annotation guide](ai/annotation/fyp_direct_label_v1_1_annotation_guide.md).

The first human calibration round contains **30 existing real public-corpus
emails** (24 shared sources and six TRAIN sources), shown independently to the
first two reviewers before personal assignments. These are actual calibration
data, not a disposable pilot or final TEST. The 11 sealed holdout sources remain
excluded. The private app contains 47 sources in total; source hashes and
historical allocations are preserved.

- [Review app source](apps/annotation-review/README.md): independent account-based
  queues, four annotation steps, exact evidence, autosaved drafts, blind frozen
  submissions and labeling rules.
- [Offline desktop prototype](desktop/README.md): local single-packet review using
  the V1 validator and mapper.
- [Historical Structured V1 guide](ai/annotation/fyp_structured_v1_annotation_guide.md)
  and [schema](ai/config/fyp_structured_v1_schema.json) remain available for
  unchanged legacy records. Earlier direct v1 records also retain their version.
- [Bounded span-link diagnostic](ai/reports/mailex_span_link_diagnostic.md):
  interrupted, zero completed seeds, no checkpoint; its one-hour deadline expired.
- [Product/calibration schedule](ai/reports/fyp_calibration_v1_schedule.md): relative
  milestones pending the team's actual academic deadline and measured throughput.

Individual human submissions remain **UNSET** until adjudication. Human agreement,
human gold and FYP-domain model accuracy have not yet been measured. The research
website does not change the final Windows/Outlook product's offline inference scope.

### Preserved historical benchmark

The [final native MailEx comparison](ai/reports/mailex_extraction_final.md) and
[historical reviewer handoff](ai/reports/mailex_extraction_reviewer_status.md)
remain frozen. Compact TEST argument-role / exact-record F1 was
**0.339138 / 0.199578**, versus GLiNER Small FT **0.231894 / 0.035132**.
Decision **D** rejected both for reliable unattended extraction; TEST is closed.

[AI directory documentation](ai/README.md) retains historical experiments.
Raw emails, private reviews, predictions and weights stay in ignored local
storage; the private annotation Site holds only its authorized runtime queue
and human drafts. GitHub contains source, synthetic contract fixtures, aggregate
reports, configurations and hashes.
