# Outlook Integrated Smart Project Management — FYP

## Current AI/NLP workstream

**6 October 2026:** The data-first V1 calibration pilot has root approval as a
47-source unlabelled historical public-corpus fallback, imported into the
private three-person review app. See the [iteration 3 aggregate curation report](ai/reports/fyp_calibration_v1_curation.md)
for the allocations and limits. See the [calibration reviewer handoff](ai/reports/fyp_calibration_v1_reviewer_handoff.md)
for the research review workflow and next gates.

- [Review app source](apps/annotation-review/README.md): independent account-based
  queues, exact evidence, autosaved drafts, blind submissions and labeling rules.
- [Offline desktop prototype](desktop/README.md): local single-packet review using
  the V1 validator and mapper.
- [V1 annotation guide](ai/annotation/fyp_structured_v1_annotation_guide.md) and
  [schema](ai/config/fyp_structured_v1_schema.json): current authored events and
  exact evidence; uncertainty requires review.
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
