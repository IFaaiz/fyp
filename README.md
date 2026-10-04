# Outlook Integrated Smart Project Management — FYP

## Current AI/NLP workstream

**5 October 2026:** Native MailEx extraction benchmark completed, including
real fitting, DEV selection, CPU/GPU measurements and one-time locked TEST.
Read the [final measured comparison and decision](ai/reports/mailex_extraction_final.md)
and [reviewer handoff](ai/reports/mailex_extraction_reviewer_status.md).

Compact TEST argument-role / exact-record F1: **0.339138 / 0.199578**;
GLiNER Small FT: **0.231894 / 0.035132**. Decision **D**: neither is reliable
enough yet. The specific next candidate is a shared compact encoder with
explicit span candidates and event-conditioned role/link scoring.

[AI directory documentation](ai/README.md) retains historical experiments.
Email text, private predictions, reviews and model weights stay local under
ignored `ai/data/`; GitHub contains code, aggregate reports, configurations,
tests and checkpoint hashes.
