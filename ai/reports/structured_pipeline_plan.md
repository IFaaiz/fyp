# Structured project-information pipeline — execution plan

Started: 2026-10-02. Starting checkpoint: `5533f3940fbb4a55024cf7efd0b68fb213e54df2`.

## Decision and scope

Closed Experiment V1 established diminishing returns from extensive flat-label search on 668 AI-silver records. Preserve its manifests, source hashes, registry, models, CLI, metrics and source error audit. Its inspected TEST is closed. The new architecture keeps the existing FYP outputs and desktop/offline deployment scope; public canonical email records are unchanged.

The internal path is **scope → evidence-grounded acts/entities/events/relations → deterministic FYP label mapper**. A request, an action item, a due relation and a document mention are separate assertions. They do not become final labels merely because a source corpus uses a related name.

## Team and ownership

All delegated work uses GPT-6 Luna with xhigh reasoning. The orchestrator owns architecture, source/rights approval, global leakage, source inspections, mapper semantics, high-risk adjudication, final metric verification and commits. Three available worker slots rotate through acquisition/licensing; Airspace; RADAR actions; Parakweet/intent; BC3/CEREC threads; schema/mapper; structured annotation. Agents write separate modules/reports. They do not commit or redefine source/public labels.

## Source strategy and current evidence

- **Airspace:** CMU conference-planning v1.0 release. Over 90% fabricated; no redistribution. Preserve original task/change/noise fields as potential auxiliary supervision. All released reply fields are zero, so this release supplies no observed reply edges. Never treat it as representative real-email evaluation. [Official source and terms](https://www.cs.cmu.edu/~airspace/).
- **RADAR Action Item:** 744 source-claimed emails; exact offset/length judgments and NLP annotations. Tokens are replaced by random same-length strings; lexical semantic transfer to real English is severely limited. Assess structural/sequence supervision separately. Reply/header metadata was removed. Research distribution is documented; no blanket open-source content license is inferred. [Official source](https://www.cs.cmu.edu/~pbennett/action-item-dataset.html).
- **Parakweet:** source sentence-level request/speech-act annotations. ENRON overlap family; preserve original labels and split inventory. Do not inherit the source split as an independent FYP boundary. [Author repository](https://github.com/ParakweetLabs/EmailIntentDataSet).
- **MailEx:** existing 1,500 threads / 3,936 mapped messages, 2,922 unique provisional canonical spans. ENRON origin; reconstructed token text makes exact body hashing alone insufficient. Use source events/arguments, not automatic FYP labels. [Existing provenance](mailex_source.md).
- **CEREC:** author release is Enron-derived; coreference supervision does not establish FYP scope or function. Review data rights separately from repository code license. [Author repository](https://github.com/paragdakle/emailcoref).
- **BC3:** UBC public research corpus with registration and CC BY-SA 3.0 terms. No invented form identity or unverified direct asset URL. Pending valid acquisition details where necessary. [Official download page](https://www.cs.ubc.ca/labs/lci/bc3/download.html).
- **CSpace:** useful management-course speech acts, but an authorized current download is not established. Acquisition pending; do not delay available sources.
- **Avocado:** restricted LDC2015T03. Two agreements/institutional workflow; applicable fee requires account access. Bahria institutional access is unknown until documented. Prepare an unsent access request. [Official catalog](https://catalog.ldc.upenn.edu/LDC2015T03).

## Implementation sequence and acceptance gates

| Stage | Work | Gate before the next stage |
| --- | --- | --- |
| 1 | Closed V1 preservation and dataset registry | Original evidence intact; origin/license/access status explicit |
| 2 | Available source acquisition and deterministic parsers | Official asset, byte hash, actual counts, source label inventory, verified offsets, meaningful tests, no source text in Git |
| 3 | Global corpus identity index | Source aliases/Message-ID/thread identities plus exact/near/fragment fingerprints; training excludes protected components and unresolved same-family fragments |
| 4 | Internal structured schema and mapper | Exact evidence slices, target references, uncertainty, taxonomy boundary tests; public canonical schema unchanged |
| 5 | Independent annotation tooling | Reviewer A/B blind separation; third adjudication; high-risk orchestrator audit; immutable source and review hashes |
| 6 | Semantic/diverse retrieval and source-read annotation | 3,000–5,000 screened candidates, actual accept/reject counts; natural primitive-support shortages reported |
| 7 | Fresh evaluation boundary | Reserve independent candidate sources before training/prompt/DEV selection; double review/third adjudication; freeze 400–600 real emails if feasible, no label quota fabrication |
| 8 | Primitive baselines and transfer | TRAIN-only fitting; source-overlap exclusion across every component, including NER/coreference/intent |
| 9 | Temporal and thread components | Date-to-target relation labels; true thread evidence, not subject-derived reply truth |
| 10 | Locked pipeline evaluation | Primitive P/R/F1, action exact/overlap spans, relation and thread metrics, then derived FYP metrics; challenge set reported separately |

Independent evaluation sources must be reserved **before** new model development; the user phase list puts fresh evaluation late, but waiting until after training would create a leakage risk. Annotation/schema policy can develop on separate training sources. Never use the 668 V1 records as new independent TEST sources.

## Internal schema review requirements

Version the internal schema separately. Every assertion has current-message evidence IDs; contextual evidence must identify the actual earlier source message and may resolve identity/previous expectation, not manufacture current acts. Preserve scope PROJECT/NON_PROJECT/UNCERTAIN. Include REQUEST/INFORM/COMMIT/APPROVE/REJECT/DELIVER/PROPOSE/REMIND/SCHEDULE/CANCEL/RESCHEDULE acts, actions with responsible parties and states, formal deliverables and states, department contribution roles, meeting events, due-date targets, formal authorization, substantive status and thread changes.

A date alone is not a deadline. A request to approve a report is not a report request. A document submission alone is not a separate operational action. A future instruction to follow up is not a present FOLLOW_UP act. A department mention alone is not departmental contribution. Completed tasks are status rather than new requests. Bare schedule changes are meeting transactions rather than automatic GENERAL_UPDATE. An uncertain scope or unresolved relation remains needs_review and cannot be silently accepted as NON_PROJECT.

## Evaluation and deployment constraints

All new AI-adjudicated evaluations remain **AI-SILVER DIAGNOSTIC PERFORMANCE**, zero human gold claims. Source corpus annotations supervise their original auxiliary tasks; they are not human-reviewed FYP classifications. Need 30+ major primitive positives, ideally 20–30+ rare positives naturally available; report uncertainty and shortages. Reviewers/adjudicators are AI, so agreement does not remove shared annotation bias.

Keep a prevalence-oriented evaluation sample separate from a deliberately enriched challenge set. A compact trained local pipeline may later be exported; acquisition/research and AI annotation can use development tools, but the final desktop product receives no new web/cloud dependency or chatbot flow.

## Realistic milestone boundary

The first session targets verified source integrations, overlap controls, a reviewed schema/mapper and the annotation workflow foundations. The 3,000–5,000 screened candidates, many source-read reviews, independent evaluation and training of temporal/thread components require sustained subsequent work. No model metric is claimed until those gates are met. No DAPT, large architecture search, attachment OCR or dashboard expansion is authorized in this milestone.

## Observed checkpoint

Local parsing is complete for 711 Airspace messages, 744 RADAR action messages, 4,649 Parakweet sentences and the five pinned CEREC files. Independent raw-source checks cover every Airspace/RADAR/Parakweet prepared record. CEREC's main file contains 6,001 threads and 60,383 distinct per-document numeric coreference IDs; its rights remain unresolved. RADAR received a personal 50-record format/span audit. After the user approved brief private excerpts, the orchestrator audited 51 Airspace, 50 Parakweet and 50 CEREC examples on 2026-10-03. Airspace is approved for private original-task auxiliary use subject to global exclusions; Parakweet remains in identity quarantine and CEREC has unresolved rights/identity plus suspected annotation merges. See `auxiliary_source_audits.md`.

The full Enron reservoir pass recovered 11,889 historically exposed identities. The reviewed global source index covers 28,129 records. After exclusions, 600 evaluation source candidates and 4,285 training-screen source candidates remain, with zero cross-partition component conflicts. These are source candidates: accepted structured annotations and new model fits remain zero. MailEx and Parakweet remain quarantined from training against the Enron evaluation while their original identities are unresolved. See `structured_pipeline_evaluation.md` for scope, limitations and the remaining acceptance gates.
