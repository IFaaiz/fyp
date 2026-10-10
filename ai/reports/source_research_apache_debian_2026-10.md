# Apache, Debian, Python, and PostgreSQL public-mail research

Reviewed 2026-10-10. This is a source/access review, not a legal opinion. I inspected existing corpus/source reports first; there was no prior report for these public project mailing lists. I used official project/archive documentation and bounded read-only endpoint checks. I did not access private lists, submit forms, create accounts, or save or reproduce message bodies. The Apache Subversion mbox probe below was independently performed by the orchestrator; no message text was printed or committed.

## Recommendation summary

| Source | Verified availability and scale | Disposition |
|---|---|---|
| Apache `dev@subversion.apache.org`; optional `dev@httpd.apache.org` vote search | Public Pony Mail API. Subversion Jan 2024 mbox: HTTP 200, `application/mbox`, 421,403 bytes; SHA-256 recorded below. An HTTPD October 2026 subject-filtered stats query returned 3 `VOTE` matches, not a full-month total. | **USE** for a small, fixed, locally controlled candidate sample after rights/privacy review. Strongest tested bulk route. This is not training or republication approval. |
| Debian `debian-project` and `debian-devel` | Public per-message HTML. September 2026 indexes exposed 21 `debian-project` message links and 272 `debian-devel` links. Debian’s site reports about 7.7 million messages across all lists. | **AUXILIARY** — useful real project/development coordination, but no current anonymous mbox route was verified and no email-text reuse license was found. |
| Python `core-workflow` | Public HyperKitty archive and `.mbox.gz` export. Anonymous `HEAD` returned HTTP 200 and `application/gzip`; export size and a selected historical month’s message count are unknown. | **AUXILIARY** — unusually task/workflow-oriented, but narrower and lower-volume than general project mail. |
| Python `python-dev` | Public historical archive and mbox links, but the list is closed to new posts and discussion moved to Core Development Discourse. The November 2023 archive reports 4 discussions and describes recent list traffic as mostly spam, mailer errors, and occasional release posts. | **SKIP** for new email sampling; use `core-workflow` if Python email is wanted. |
| PostgreSQL `pgsql-hackers` | Public HTML archive; September 2026 index contained 200 distinct Message-ID links. Official wiki documents mbox access behind simple authentication; anonymous bulk access was not verified. | **AUXILIARY** — strong review/release coordination, but very technical, with an access gate for mbox and no email-corpus license found. |

Public archive access does not itself establish permission for model training, redistribution, or long-term corpus retention. Keep any approved candidate sample outside Git, avoid copying full messages into reports, and have the university determine reuse terms before training. None of these sources carries FYP labels; retain source labels only when the archive itself provides them, such as explicit votes or release states.

## Apache Pony Mail archives

### Verified route and bounded evidence

Apache’s official [Pony Mail API documentation](https://github.com/apache/ponymail-foal/blob/master/docs/API.md) documents JSON endpoints for statistics and mbox results. The older [Pony Mail API guide](https://ponymail.apache.org/docs/api.html) documents the month form of the mbox route. Apache’s [mailing-list guidance](https://www.apache.org/foundation/mailinglists) explains that project lists are the public discussion venue and that some lists are private; only explicitly public project lists should be queried.

The orchestrator verified this bounded historical route for the public Subversion development list:

```text
https://lists.apache.org/api/mbox.lua?list=dev&domain=subversion.apache.org&d=2024-01
```

It returned HTTP 200, `Content-Type: application/mbox`, 421,403 bytes; the response began as a valid mbox (`From `). The recorded response SHA-256 is `ed35d36cfae8239f45a79c57d994a4c73fd51c0fe1e50270e69522ec7d781aa7`. This gives a reproducible, one-list/one-month acquisition boundary. No message body was retained in this report or committed. The hash identifies the tested response and should be checked again if the archive revises historical material.

The current API was also tested with a narrow HTTPD vote query. A POST to `https://lists.apache.org/api/stats.json` with `{"list":"dev","domain":"httpd.apache.org","d":"2026-10","header_subject":"VOTE","emailsOnly":true}` returned HTTP 200 and 3 matches. This is a count for that subject filter, not the total number of October messages. The matching list can be requested through the documented `mbox.json` endpoint using the same query. Do not use broad domains or all-list exports when a single public list/month suffices.

The [archive home page](https://lists.apache.org/) advertises roughly 403 projects, 1,758 lists, and 987,000 emails in the last 90 days; these are changing site counters, not parsed corpus totals. The API probes above establish endpoint readability and bounded response shape, not an exact count of all messages for the month. Public examples include an [HTTPD release vote](https://lists.apache.org/thread/bx0lyb7qbhxpgy119ldqfxt12s8dwmdz) and a [release checklist/voting discussion](https://lists.apache.org/thread/116n5fmzffxk40zwf0k461kjg6fp2vo9). These show actual release and decision threads without requiring a broad scrape.

### Relevance, headers, noise, and rights

Human project mail includes explicit release votes, requests to review or test, plans and cutoff dates, approval/outcome messages, and follow-up on unresolved issues. Those behaviors can support FYP `DEADLINE`, `ACTION_REQUEST`, `FOLLOW_UP`, `APPROVAL`, and `GENERAL_UPDATE`; meeting notices and requests for written release artifacts may support `MEETING` or `REPORT_REQUEST`. `DEPARTMENTAL_INPUT` is a poor fit because Apache teams do not generally coordinate by university department. A calendar date alone is not a deadline, a vote is not automatically an approval label, and quoted history must not be labeled as the current sender’s action.

Pony Mail exposes message identifiers and conversation/thread navigation; the bounded HTTPD response probe included standard `Message-ID`, `In-Reply-To`, `References`, `Date`, `From`, `To`, and `Subject` headers. Mbox is the best tested format here for preserving the original header and reply graph. Public `dev` lists should be mostly human discussion, but expected noise is moderate: patch/bot notices, commits, issue updates, CI/build mail, release automation, and long quoted/code-heavy threads. Select `dev` only; exclude `commits`, `issues`, `builds`, notification, and private lists unless independently justified.

The [ASF public-archive policy](https://www.apache.org/foundation/public-archives.html) says messages sent to public forums are treated as published and archived publicly; it also notes that contact details are not treated as confidential and that copied mirrors may persist. The policy does not grant this project a separate dataset license for email bodies. An Apache project’s source-code license must not be assumed to license all list mail. Messages can contain personal addresses, signatures, private references, or accidentally disclosed information. Use only reviewed public-list samples, minimize personal data in derived artifacts, and do not publish raw mbox files or message quotations without a separate rights review.

## Debian public project and development lists

### Verified sample pages and scale

Debian’s official [mailing-list guide](https://www.debian.org/MailingLists/) describes the lists as open to public participation and warns that email addresses and messages are publicly archived/copied. The [Developer’s Reference](https://www.debian.org/doc/manuals/developers-reference/resources) identifies `debian-devel` for technical development, `debian-project` for project matters, `debian-policy` for policy discussion, and `debian-devel-announce` for developer announcements. The official [`debian-devel` list index](https://lists.debian.org/debian-devel/) labels it high-volume and unmoderated and shows archive coverage from 1994 through 2026.

Verified September 2026 monthly indexes:

- [`debian-project/2026/09/`](https://lists.debian.org/debian-project/2026/09/) returned HTTP 200 and linked 21 distinct messages. A sampled [project/infrastructure thread](https://lists.debian.org/debian-project/2026/09/msg00000.html) was readable and exposed `Message-ID`, `In-Reply-To`, `References`, `Date`, `From`, `To`, and `Subject`.
- [`debian-devel/2026/09/`](https://lists.debian.org/debian-devel/2026/09/) returned HTTP 200 and linked 272 distinct messages. This is an index-link count, not a complete parsed or deduplicated mail count.

The official [archive statistics page](https://lists.debian.org/stats/) reported 7,697,678 messages across Debian lists and 2,277 `debian-devel` subscribers when checked; it updates weekly. A tested legacy-looking `cgi-bin/mbox/<list>-YYYYMM` route returned 404, so do not assume Debian currently provides anonymous month mbox files. The verified practical route is bounded monthly HTML indexes plus selected individual pages. Thread links and reference headers are available, but no complete RFC822 or bulk export was verified.

### Relevance and constraints

`debian-project` can provide project decisions, infrastructure changes, and follow-up; `debian-devel` contains technical proposals, maintenance work, release changes, and requests. Those support auxiliary examples of `GENERAL_UPDATE`, `ACTION_REQUEST`, `FOLLOW_UP`, explicit `APPROVAL`/decision, and occasional `DEADLINE`. Meetings and requested reports occur but are not the dominant shape. `DEPARTMENTAL_INPUT` has little direct transfer. `debian-devel` is likely noisier than `debian-project`: the former is explicitly high-volume, and archive traffic includes automated package, bug, security, and upload notices. This is a qualitative expectation; no source-level bot fraction was measured.

Debian’s public-list instructions ask senders not to post confidential or unlicensed material and explicitly warn that addresses/messages are publicly copied. That is a publication warning, not a blanket ML-training or redistribution grant. Preserve only what is needed for a local, reviewed sample; strip direct contact details from derived outputs; and do not commit or redistribute message bodies. The 404 result for the historical mbox pattern is a current access check and can change; retest before planning acquisition.

## Python: `core-workflow` and retired `python-dev`

### `core-workflow`: relevant task mail with a verified export

The official [Core Workflow archive](https://mail.python.org/archives/list/core-workflow@python.org/) is publicly readable and exposes HyperKitty export links. The archive generates month/range-specific export links; select a closed historical month from that page and use its exact link. The verified full-archive route (HEAD only; do not fetch it) is:

```text
https://mail.python.org/archives/list/core-workflow@python.org/export/core-workflow@python.org.mbox.gz
```

The archive page also rendered bounded month/range links, including an October 2026 range. A direct anonymous `HEAD` request to the full-archive `.mbox.gz` route returned HTTP 200 and `application/gzip`; the server did not provide `Content-Length`. Do not fetch the full archive. The website’s archive view reports 169 discussions, but this is a displayed discussion count, not a message count or export size. No reliable month-level count was verified.

The list discusses core development workflow: review requirements, pull request process, issue triage, newcomer-friendly work, and project process changes. This is useful for current task requests, review/follow-up, assignment, decision, and workflow updates. It is narrow and process-heavy compared with general project mail; `MEETING`, `DEPARTMENTAL_INPUT`, requested reports, and explicit deadlines may be sparse. The archive includes an occasional spam thread, so a human screen is still needed. The mbox export should preserve ordinary email headers and thread identifiers; no raw mail body was downloaded during this review.

The [PSF Code of Conduct](https://www.python.org/psf/conduct/) applies to python.org community spaces, including mailing lists, and cautions against publishing others’ private information. The pages reviewed provide public access but no email-text dataset license. The PSF policy’s own license is not a license for user-authored email. Avoid public redistribution and keep any permitted research copy controlled until reuse terms are determined.

### `python-dev`: historical archive, weak sampling value

The official [`python-dev` list page](https://mail.python.org/mailman3/lists/python-dev.python.org/) says the list is archived and that new discussion has moved to Core Development on Discourse. The [archive](https://mail.python.org/archives/list/python-dev@python.org/) exposes monthly/entire-archive mbox links. The [November 2023 archive month](https://mail.python.org/archives/list/python-dev@python.org/2023/11/) reports four discussions and describes list traffic as mostly spam, mailer-error reports, and occasional release postings. The list had no recent activity when checked. For that reason, **skip `python-dev` as a sample source**; if Python email is useful, `core-workflow` has clearer task semantics and a verified public export.

## PostgreSQL `pgsql-hackers`

### Archive availability and a human sample

The official [pgsql-hackers archive](https://www.postgresql.org/list/pgsql-hackers/) and [`2026-09` monthly index](https://www.postgresql.org/list/pgsql-hackers/2026-09/) returned HTTP 200. The monthly index contained 200 distinct Message-ID links; this is a verified index count, not an independently parsed corpus count. Individual pages expose From, To, Date, Subject, and Message-ID, and the archive presents whole-thread navigation plus raw-message and mbox controls.

A useful actual coordination example is [“PostgreSQL 19 Beta 4 release date”](https://www.postgresql.org/message-id/f515cc05-67ee-4295-bc79-41c48ce2589d%40postgresql.org) (September 3, 2026), which sets a beta date, calls out a freeze cutoff, identifies open items, and asks for press-release preparation/review. A second [two-message patch thread](https://www.postgresql.org/message-id/CAJTYsWVtPZuuehX%2BvaYecgbuuL%2BY9rCsASyUyHUSq7ZHvx9LVw%40mail.gmail.com) demonstrates code-review follow-up. These are high-signal examples but technically specialized.

The [PostgreSQL mailing-list wiki](https://wiki.postgresql.org/wiki/Mailing_Lists) says the raw mbox download requires simple authentication to deter bots. I verified public HTML readability, but did not verify an anonymous raw mbox response. Treat the current workable route as individual archive pages unless the project later establishes authorized access. Do not automate a login or scrape a protected bulk route.

### Relevance, noise, and rights

The list is for PostgreSQL developers, patches, bugs, and unreleased-version discussion. It can support `ACTION_REQUEST` (review/test/patch requests), `FOLLOW_UP`, `APPROVAL` (explicit review/consensus), `DEADLINE` (freeze/release cutoffs), and `GENERAL_UPDATE` (release status/outcome). It offers little `DEPARTMENTAL_INPUT`; ordinary meetings and report requests are secondary. Human participation is expected, while code blocks, patch diffs, issue references, technical debate, and quoted history make noise in the FYP sense high even if bot traffic is low. This is qualitative, not a measured bot rate.

The [PostgreSQL archive policy](https://www.postgresql.org/about/policies/archives/) says the archive is public and searchable and describes sender permission to archive messages. It does not establish a general third-party ML dataset license. Any project-specific rights for code submitted to the project should not be extended to the email corpus. Messages disclose identities and may quote prior mail; retain only after privacy/rights review and do not distribute raw messages.

## Practical next steps and guardrails

1. If selecting one source for a first fixed sample, use only `dev@subversion.apache.org`, January 2024, through the exact tested endpoint above. Record the request URL, response metadata, hash, and date; keep the mbox outside Git; and review a small header/body sample for personal or sensitive disclosures before any annotation.
2. If a vote/release slice is needed, query one public Apache `dev` list with an explicit month and a subject filter. The HTTPD October 2026 test returned only 3 `VOTE` matches; it does not establish the month’s full volume.
3. Prefer Python `core-workflow` over retired `python-dev` if a second email format is needed. Use a closed, explicitly bounded month export and measure the count after authorized retrieval; do not request its all-time mbox.
4. Keep Debian and PostgreSQL as HTML-accessible auxiliary candidates until rights review and their bulk-access needs are resolved. Do not equate public archives with permission to train or republish.
5. For any source, keep current-message text separate from quoted history; preserve Message-ID and reply headers where available; exclude private lists, full-history crawls, automated-only feeds, and any closed evaluation/holdout material. This review makes no label mapping and adds no FYP annotations.

## Primary sources checked

- Apache: [Pony Mail Foal API](https://github.com/apache/ponymail-foal/blob/master/docs/API.md), [legacy Pony Mail API guide](https://ponymail.apache.org/docs/api.html), [ASF mailing lists](https://www.apache.org/foundation/mailinglists), [ASF public-archive policy](https://www.apache.org/foundation/public-archives.html), [HTTPD release vote](https://lists.apache.org/thread/bx0lyb7qbhxpgy119ldqfxt12s8dwmdz).
- Debian: [mailing-list guide](https://www.debian.org/MailingLists/), [Developer’s Reference: resources and lists](https://www.debian.org/doc/manuals/developers-reference/resources), [`debian-devel` index](https://lists.debian.org/debian-devel/), [archive statistics](https://lists.debian.org/stats/).
- Python: [`core-workflow` archive](https://mail.python.org/archives/list/core-workflow@python.org/), [`python-dev` list page](https://mail.python.org/mailman3/lists/python-dev.python.org/), [`python-dev` archive](https://mail.python.org/archives/list/python-dev@python.org/), [PSF Code of Conduct](https://www.python.org/psf/conduct/).
- PostgreSQL: [`pgsql-hackers` archive](https://www.postgresql.org/list/pgsql-hackers/), [mailing-list wiki](https://wiki.postgresql.org/wiki/Mailing_Lists), [archive policy](https://www.postgresql.org/about/policies/archives/), [release coordination message](https://www.postgresql.org/message-id/f515cc05-67ee-4295-bc79-41c48ce2589d%40postgresql.org).
- Related research already in the repository: [`source_research_w3c_auxiliary_2026-10.md`](source_research_w3c_auxiliary_2026-10.md), which reviews W3C and IETF public archives and avoids duplicating that work here.
