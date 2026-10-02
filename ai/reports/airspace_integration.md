# CMU Airspace integration

## Acquisition and terms

- Official collection page: [CMU Airspace](https://www.cs.cmu.edu/~airspace/)
- Download: [Airspace wargaming v1.0 ZIP](https://www.cs.cmu.edu/~airspace/corpus/Airspace_wargaming_1.0.zip)
- Syntax and usage guide: [Email Syntax v1.0 PDF](https://www.cs.cmu.edu/~airspace/corpus/README_EmailSyntax_1.0.pdf)
- CMU release version: **1.0** (the page advertises 711 wargaming messages)
- Retrieved at (UTC): `2026-10-02T14:08:44.766776+00:00`
- Raw ZIP SHA-256: `04f8c82dc96ca00d565b5598e73424e35dbac4692ffa4d98271fe0c54bcc31a7`
- ZIP size: 1063031 bytes; ZIP CRC check passed.
- Syntax PDF SHA-256: `a7471383aaf08455035b6e25fe48ca83b4c14708020bb4aa0033a092734922f2`

CMU says more than 90% of this content is fabricated and requires that users do
not redistribute it. Record and report version 1.0, cite the RADAR methodology
paper and this official page in proposals/publications, and send resulting
publication references to `steinfeld@cmu.edu`. Raw files and derived email text
remain ignored local data. This synthetic conference-planning corpus is
auxiliary supervision only and must never be represented as real-email
evaluation.

The `Noise` value is retained as an Airspace source annotation about relation to
the fictional conference. It is not converted into the FYP `NON_PROJECT` label.

The syntax guide identifies `X-RADAR-Label`, `X-RADAR-Noise`, `X-RADAR-Messageid`,
and `X-RADAR-Replyto` as supported fields. `X-RADAR-Replyto: 0` means no parent;
a missing value stays unknown. Unsupported fields are retained only when useful
for provenance and are not treated as validated labels/features.

## Observed messages and original labels

CMU advertises 711 messages; the local archive contains **711 `.eml` records**.
The local count matches the advertised count.

| Original source category | Messages |
|---|---:|
| `BRIEFING` | 101 |
| `CHANGE-ROOM` | 112 |
| `CHANGE-SESSION` | 74 |
| `CHANGE-SPEAKER` | 63 |
| `INFO-REQ` | 63 |
| `MISC-ACTION` | 63 |
| `WEB-VIO` | 96 |
| `WEB-WBE` | 36 |

Noise annotation: `{"false": 662, "true": 49}`.
Reply status: `{"no_parent": 711}`;
explicit `Replyto: 0` records: 711; observed reply
edges: 0; derived reply components:
0. This release has no observed actual
reply edges. The source `Thread` field appears in 711
messages across 82 raw grouping values
(`Thread: 0` on 448 messages). Those raw
values are preserved separately and are not treated as verified reply links;
the syntax guide describes this field for the backstory while these records are
the wargaming/injected release. No parent link is invented when the source field
is absent. Unknown source categories:
`[]`.

All eight original categories remain unchanged. `INFO-REQ` and `MISC-ACTION` are
not renamed into project labels. The auxiliary rows contain no FYP `labels`
field and are not validated against the V1 schema.

## Prepared artifacts

- `ai/data/processed/airspace.jsonl` contains 711 parsed
  messages with original subject/body, reconstructed source text, supported
  labels, noise annotation, source message ID, exact source reply field,
  source/thread identity where observed, archive SHA provenance, and Unicode
  character offsets for subject/body in the parser's source-text view.
- `ai/data/processed/airspace_review_candidates.jsonl` contains 100
  actual messages for orchestrator source-and-label inspection. It is ignored
  local data and must not be committed.
- `ai/reports/airspace_statistics.json` contains aggregate counts only.
- `ai/reports/airspace_registry_proposal.json` records version, family,
  provenance and restrictions for the global registry owner.

The source PDF describes Email Syntax v1.0, dated October 2006, and the linked
methodology citation is the 2006 CMU technical report, [*The RADAR Test
Methodology: Evaluating a Multi-Task Machine Learning System with Humans in the
Loop*](https://reports-archive.adm.cs.cmu.edu/anon/2006/abstracts/06-125.html) (CMU-CS-06-125 / CMU-HCII-06-102).

## Orchestrator audit update — 2026-10-03

The user approved brief private excerpts. Personal audits now cover 51 Airspace, 50 Parakweet and 50 CEREC samples. See `auxiliary_source_audits.md` and the canonical registry for current gates; earlier pending-audit statements above describe the initial integration state. Airspace permits private original-task auxiliary use subject to global exclusions. Parakweet remains in original-identity quarantine. CEREC remains inspection-only pending rights, identity/global-index integration and review of suspected entity merges. No new FYP labels or human gold were created.
