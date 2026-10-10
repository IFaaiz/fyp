# FYP source inventory — October 2026

Reviewed 10 October 2026 against main `c32f85f505edd9ba0b91b5efe11e28741b83df4c`.
Recommendations concern **email coordination content**, not whether a source
already has annotations. USE below authorizes a bounded local candidate exercise;
it is not a claim of training or redistribution permission.

Detailed primary-source checks are in
[Apache/Debian/Python/PostgreSQL research](source_research_apache_debian_2026-10.md)
and [W3C/EmailSum/RADAR/Avocado/IETF research](source_research_w3c_auxiliary_2026-10.md).
No protected export, account creation, purchase or private mailing list was used.

## Existing system before changes

| Component | Verified starting state |
|---|---|
| Main | Local and GitHub main both `c32f85f`; clean checkout before this work. |
| Annotation | Private Site version 7; current source mirror already contains independent queues, rules, exact evidence, drafts and blind submission. Live metadata: zero v1.1 reviews, one legacy direct-v1 draft. |
| Active schema | `fyp-direct-label-v1.1`; PROJECT/NON_PROJECT/UNCERTAIN, eight direct project labels, 11 optional extraction targets, EVIDENCE auxiliary. No required act layer; no INPUT/APPROVAL_TARGET extraction targets. Historical Structured V1 and direct-v1 records retain their versions. |
| Human round | Frozen 30 real emails, 24 shared and six TRAIN-source examples; 11 sealed holdout sources remain excluded. No new queue or source allocation was written. |
| Existing datasets | Prior reports: MailEx 3,936 reconstructed messages; Enron 517,401 scanned messages and 8,000 candidate pool; Airspace 711 mostly fabricated records; RADAR 744 obfuscated messages; Parakweet 4,649 sentences; CEREC 6,001 thread documents. Their scopes/rights differ; these are historical reported counts, not new acquisitions. |
| Outlook | No product COM import adapter before this change. |
| Archive/Excel/PySide | No canonical product SQLite, Excel export or PySide viewer before this change. `desktop/offline_dashboard.py` is the preserved browser-based Structured V1 single-packet review prototype. |
| Classifier | Existing frozen AI-silver diagnostic ensemble and inference CLI; scores are not calibrated confidence or human-gold performance. |
| Extraction | Historical compact BIO and GLiNER MailEx results preserved; decision D rejected reliable unattended extraction. Closed TEST is unchanged. Later span-link diagnostic expired with zero completed seeds. |
| Tests/obsolete components | Existing direct-v1.1, direct-v1, Structured V1, queue migration/agreement and parser/thread tests. Earlier annotators and schema layers remain historical; they are not the active human contract. |

Annotation is ready for human work on its existing queue. Actual human submissions,
agreement, adjudicated gold and FYP accuracy have not been established.

## Ranked public project-mail sources

Approximate counters below have different units. Index links and displayed
discussions are not interchangeable with parsed messages. All quantities include
their measurement boundary; none implies that the whole corpus was acquired.

| Rank/source | Availability and scale | Label relevance | Thread and metadata quality | Acquisition/noise | Rights/privacy and recommendation |
|---|---|---|---|---|---|
| 1. Apache public dev lists | Documented public Pony Mail mbox/API. Actual fixed Jan 2024 acquisition: Subversion 42 + HTTPD 39 = **81 parsed messages**, about 1.21 MB. | Release votes/outcomes, reviews/tasks, follow-ups, cutoffs and updates; meetings/report requests less frequent, departmental input weak. | Raw RFC822 Message-ID, References, In-Reply-To, sender/recipient/date; explicit-header grouping. | One public list/month per request; exclude private/security/PMC, commit/issue/build feeds. Technical discussions, quote chains, diffs and bot traffic. | [ASF public-forum policy](https://www.apache.org/foundation/public-archives.html) supports public archiving but is not an Apache-2.0 email-corpus license. Addresses/signatures stay local; separate review before training/public excerpts. **USE** bounded local candidates. |
| 2. W3C WCAG working-group mail | Anonymous per-message HTML verified. Live quarter index contained **192 distinct message links** on our acquisition check; older crawled date/thread pages showed 184/150. **12 pages** acquired locally. | Agendas/meeting times, review/document requests, CFC deadlines, consensus/outcomes and updates. Departmental input weak. | Rendered From/To/Date/Message-ID; explicit parent navigation where available. Raw mailbox link redirects to authentication. Reconstructed headers are marked; missing RFC reply headers stay missing. | Curated 12 URLs, not a full crawl. Historical charsets, repeated agendas, specification jargon, long quotes, warning/signature blocks. | [W3C email/archive policy](https://www.w3.org/email/) permits archive publication; no blanket third-party email training grant verified. **AUXILIARY** local inspection only, `NOT_CLEARED` for training; no redistribution or auth bypass. |
| 3. Debian project/development | Public HTML indexes: September 2026 project **21 links**, development **272 links**. Across-list stats approximately 7.7 million messages, not a target acquisition size. | Project decisions, technical work requests, follow-ups, maintenance/release changes; fewer meetings and department/report requests. | Visible reply headers and thread links in sample pages; no anonymous raw month export verified. | Fixed monthly index then selected pages. Tested legacy mbox route returned 404. Development list is technical/high-volume, with notifications and quoted/code-heavy discussion. | [Debian public-list guidance](https://www.debian.org/MailingLists/) warns of public copying, not blanket ML rights. No email-text reuse grant verified. **AUXILIARY**, next bounded HTML adapter only after source review. |
| 4. IETF HTTP Working Group | Public archive pages/search; approximately **40,000 displayed messages** in `httpbisa`, drifting counter. No acquisition this turn. | Adoption calls, comment deadlines, support/opposition, follow-up and outcomes; not a direct university project domain. | Per-message identifiers, From/To/Date/Subject and reply context; full bulk export authentication not verified as anonymous. | Selected public thread URLs; official rsync/IMAP routes also documented but unused. Secretariat/RFC notices and dense standards discussions. | [Trust FAQ](https://trustee.ietf.org/documents/trust-legal-provisions/copyright-policy-and-tlp-faq/) grants certain Contribution publication rights, not a blanket external derivative/training license. Public identities noted in Note Well. **AUXILIARY**, rights review before training. |
| 5. Python core-workflow | Public HyperKitty. Anonymous mbox.gz HEAD returned 200/gzip; no Content-Length. Displayed **169 discussions**, not messages. No raw acquisition. | Review workflow, triage, assignments/process decisions, follow-ups and updates; scheduling/departmental/report categories scarce. | Mbox expected to preserve standard email/reply headers; not independently parsed yet. | Use exact historical month export from archive, byte/message caps; never all-time export. Narrow process domain and occasional spam. | [Official archive](https://mail.python.org/archives/list/core-workflow@python.org/) is public; no authored-email dataset license verified. PSF policy license does not license mail bodies. **AUXILIARY**. |
| 6. PostgreSQL pgsql-hackers | Public monthly/per-message HTML; September 2026 index check found **200 distinct Message-ID links**, not a verified whole-month total. | Release freezes, review/test requests, patch follow-ups, consensus, progress and blockers. | Visible From/To/Date/Subject/Message-ID plus thread navigation. Wiki documents simple-auth mbox access; anonymous bulk not verified. | Bounded selected HTML; no login automation. Very technical code/patch discussions and long quotations. | [Archive policy](https://www.postgresql.org/about/policies/archives/) covers public archiving, not ML licensing. **AUXILIARY**; keep identifying content local. |

The three additional credible project-mail sources are IETF, Python core-workflow
and PostgreSQL. Recommendations are conditional source-selection decisions, not
legal conclusions. Public availability and institutional rights approval are
recorded separately.

## Auxiliary datasets and routes

| Source | Availability/scale | Coordination value; metadata/thread quality | Acquisition/noise | Rights/privacy; recommendation |
|---|---|---|---|---|
| EmailSum W3C tooling | Author repo provides extraction/anonymization code and links a separate Drive raw-data folder; no W3C count/provenance verified. The **2,549** count is Avocado summary threads. | Thread reconstruction ideas useful; summaries are not original project emails or FYP labels. Input metadata quality depends on unverified underlying mail. | Inspect licensed code only. Drive route not opened or downloaded; incomplete raw provenance. | [Repository MIT license](https://github.com/ZhangShiyue/EmailSum) covers repo software, not presumed third-party W3C/LDC email rights. **AUXILIARY** tooling; **SKIP** unverified raw route. |
| RADAR action items | Existing local audited release: **744 messages**, 328 positive/416 negative action-presence judgments; 416 action spans in prior audit. | Narrow action task; randomized tokens weaken lexical transfer. Headers except subject and threading removed. Source positives are not automatically ACTION_REQUEST. | Already acquired; do not duplicate. Obfuscation and task mismatch dominate. | [CMU release](https://www.cs.cmu.edu/~pbennett/action-item-dataset.html) describes research/IRB release, no blanket redistribution license. **AUXILIARY** original task only. |
| Avocado LDC2015T03 | Official Web Download, agreements required; README **614,461 nonduplicate email texts**, 938,035 email items. Institutional entitlement/fee unknown. | Potentially useful real work threads and metadata; approximate dedup and reconstructed Exchange headers; sensitive content/PII remain material. | No account, agreement, purchase or acquisition. Only catalog/README/license review. | [LDC catalog and agreements](https://catalog.ldc.upenn.edu/LDC2015T03) restrict users, redistribution and reproduction, and require organizational approvals/training. **SKIP** until legitimate institutional access is verified. |
| Python python-dev | Public historical archive and export links; retired to Discourse. Nov 2023 page reports four discussions and mainly spam/errors/release posts. | Historical development mail; present sampling value poor. Mbox links useful but no current parser validation. | No download; recent noise and dormant list. | Public access is not a dataset license. **SKIP** new sampling; prefer core-workflow. |
| Consented team/university project email | No actual consented source files or consent terms supplied yet; scale unknown. | Likely strongest transfer for real departmental/report/meeting language; metadata depends on .eml/.msg/Outlook export. | Future explicit bounded import after author/team consent and sensitivity screen; no live mailbox accessed. | **USE when consent is documented**, with revocable local access, separate permission for training and publication. No assumed university entitlement. |

## Implemented acquisition and candidate selection

Config: [`project_mail_sources_2026-10.json`](../config/project_mail_sources_2026-10.json).
CLI: [`acquire_project_mail.py`](../scripts/acquire_project_mail.py).

- Fixed two Apache Jan 2024 months and 12 verified W3C quarter message URLs.
  Network allowlist rejects private/auth routes, credentials, unapproved hosts,
  ports and redirects. 8 MB archive cap / 300 KB HTML cap / 1,500 message cap.
- Original bytes and dated SHA-256 receipts retained under ignored
  `ai/data/project_mail/2026-10-10/raw/`; reuse requires matching URL/hash.
- Normalize subject, sender, recipients, timestamp, raw/current/quoted text,
  filenames, IDs, explicit reply links and acquisition/rights provenance.
  No attachment content fetched. W3C missing raw headers/attachment metadata
  are explicitly marked unavailable; declared HTML charset is respected.
- Empty authored text, bot/housekeeping and patch-dominated messages filtered.
  Operational cues are sampling hints, never label annotations.
- Seeded **naturalistic sample only from full fixed-month Apache frames**.
  Purposive W3C pages enter only ENRICHED_CHALLENGE. Both tracks are biased by
  selected source/month and noise filtering; neither estimates product accuracy
  or general email prevalence.
- Exact-copy deduplication and within-batch thread/template connected groups;
  Jaccard diversity plus rare cues and source balancing for enrichment.
  Future global/thread/template split audit is still required.
- Outputs `normalized.jsonl`, `candidates.jsonl`, `candidate_manifest.jsonl`
  and `summary.json` stay local and ignored. Every new record has labels/spans
  empty, scope null, method UNANNOTATED, tier UNSET and split UNASSIGNED.

### Actual result, including shortfall

| Quantity | Count |
|---|---:|
| Acquired/parsed messages | 93 = 81 Apache + 12 W3C |
| Eligible after noise filters | 77 |
| Excluded | 16: 11 no authored text, four automation/housekeeping, one patch |
| Naturalistic eligible frame | 65 Apache messages |
| Selected candidates | **44**, below requested cap 120 |
| Sampling tracks | 30 NATURALISTIC + 14 ENRICHED_CHALLENGE |
| Source composition | 22 Subversion + 12 HTTPD + 10 W3C |
| Selected threads | 21 |
| Exact duplicates / near-template suppression | 0 / 0 in this small batch |
| Metadata present | Message-ID/sender/recipient/date: 44 each; RFC References and In-Reply-To: 30 each |
| New labels / gold | **0 / 0** |

Weak cue counts (overlapping, **not measured label coverage**): meeting 4,
deadline 2, document/report 9, action 14, follow-up 3, approval 7, update 9,
departmental input 0. Hard-negative hints: seven review-without-approval and
two meeting-without-due cues. A review hint is not a correctness judgment.
There are no selected document-delivery contrast hints in this batch; that
contrast is tested synthetically, not claimed as acquired real coverage.

### What failed or remains uncertain

W3C anonymous mbox access was not available; Debian's guessed legacy mbox route
returned 404. Avocado entitlement is unresolved. Python/PostgreSQL raw acquisition
has not been performed. The sample does not fill 120 useful candidates and is
not representative of Outlook users. Departmental-input examples remain a real
domain gap. Source rights/privacy checks before human selection/training remain
necessary; W3C records explicitly carry `training_rights_status=NOT_CLEARED`.

Next data action: finish the existing blind human round first, screen these
blank candidates and rights separately, then expand a bounded relevant source
window if actual category gaps justify it. Prefer consented real project email
for departmental/report semantics; do not force open-source teams into
department labels or manufacture examples for TEST.
