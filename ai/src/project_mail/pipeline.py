"""Reproducible project-mail normalization, mining and diversity sampling.

Reuses the audited RFC822 parser and header-only thread reconstruction. No
classifier, annotation API, training split, private mailbox or model is invoked.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin
from email.message import EmailMessage
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import mailbox
import re
import urllib.request

from src.datasets.cleaning import clean_email_body
from src.datasets.enron import parse_enron_bytes
from src.datasets.threading import assign_thread_metadata


VERSION = "fyp-project-mail-candidates-v1"
CUES = {
    "MEETING": r"\b(meeting|agenda|minutes|telecon|reschedul\w*|conference call)\b",
    "DEADLINE": r"\b(deadline|overdue|extension|extended|due (?:by|on)|by (?:monday|tuesday|wednesday|thursday|friday)|submit by|by end of day)\b|\b(?:72|48|24) hours\b|\b(?:cfc|call for consensus|vote|review period|comment period)[^.!?\n]{0,60}\b(?:end|ends|close|closes)\b",
    "REPORT_REQUEST": r"\b(report|document|draft|proposal|minutes|deliverable|status report)\b",
    "DEPARTMENTAL_INPUT": r"\b(finance|legal|marketing|department|organizational unit)\b",
    "ACTION_REQUEST": r"\b(please|can you|could you|should|action item|todo|assigned|responsible|review|test|fix)\b",
    "FOLLOW_UP": r"\b(reminder|follow[ -]?up|still waiting|any update|pending|haven.t received|checking on)\b",
    "APPROVAL": r"\b(approve\w*|sign[ -]?off|authoriz\w*|vote|consensus|accepted|rejected)\b|(?:^|\s)[+-]1\b",
    "GENERAL_UPDATE": r"\b(completed|done|fixed|released|progress|blocker|blocked|finished|implemented|changed|resolved|status)\b",
}
PATTERNS = {k: re.compile(v, re.I) for k, v in CUES.items()}
NOISE_SENDER = re.compile(r"(?:noreply|no-reply|jenkins|github-actions|buildbot|jira|bugzilla|gitbox|dependabot|commits@)", re.I)
NOISE_SUBJECT = re.compile(r"^(?:\[jira\]|\[github\]|\[ci\]|\[build\]|svn commit:|git commit:)|\b(?:unsubscribe|subscription confirmation|password reset)\b", re.I)


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def allowed_public_url(url: str) -> bool:
    """Allow only documented anonymous public routes; reject auth/private lists."""
    p = urlparse(url)
    if p.scheme != "https" or p.username or p.password or p.fragment or p.port not in (None, 443):
        return False
    if p.hostname == "lists.apache.org" and p.path == "/api/mbox.lua":
        q = parse_qs(p.query)
        return (q.get("list") == ["dev"] and len(q.get("domain", [])) == 1
                and q["domain"][0] in {"subversion.apache.org", "httpd.apache.org"}
                and len(q.get("d", [])) == 1
                and re.fullmatch(r"20\d\d-\d\d", q["d"][0]) is not None)
    if p.hostname == "lists.w3.org":
        return not p.query and bool(re.fullmatch(r"/Archives/Public/(?:w3c-wai-gl|public-wai-cc)/20\d\d(?:JanMar|AprJun|JulSep|OctDec|[A-Z][a-z]{2})/(?:\d{4}\.html|)", p.path))
    return False


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_public_url(newurl):
            raise ValueError("Redirect left the approved public archive route; no authentication or bypass attempted.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def acquire(spec: dict, target: Path, *, max_bytes: int = 8_000_000) -> dict:
    if not spec.get("terms_reviewed") or not spec.get("terms_url") or not spec.get("terms_note"):
        raise ValueError("Source needs explicit terms review and a retention/redistribution note.")
    url = spec["url"]
    if not allowed_public_url(url):
        raise ValueError("Only approved public archive URLs are allowed.")
    receipt = target.with_suffix(target.suffix + ".acquisition.json")
    if target.exists():
        if target.stat().st_size > max_bytes:
            raise ValueError("Cached source exceeds bounded acquisition size.")
        data = target.read_bytes()
        prior = json.loads(receipt.read_text(encoding="utf-8"))
        if prior["url"] != url or prior["sha256"] != digest(data):
            raise ValueError("Cached source receipt/hash mismatch; preserve bytes and inspect provenance.")
        return {**prior, "cached": True}
    else:
        request = urllib.request.Request(url, headers={"User-Agent": "FYP-ProjectMail/1.0 bounded academic research"})
        with urllib.request.build_opener(PublicRedirects()).open(request, timeout=30) as response:
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Archive exceeds byte cap; select a smaller source window.")
        if spec["format"] == "mbox" and not data.startswith(b"From "):
            raise ValueError("Expected mbox; received login/error/non-email response.")
        if spec["format"] == "w3c_html" and b"<!-- body=" not in data:
            raise ValueError("Expected W3C archived message body markers.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        cached = False
    result = {"name": spec["name"], "url": url, "path": str(target), "bytes": len(data),
            "sha256": digest(data), "cached": cached, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def normalize(raw: bytes, spec: dict, location: str, acquired_at: str) -> dict:
    parsed = parse_enron_bytes(raw, source_path=location)
    body, current = clean_email_body(parsed.raw_body)
    # The old research cleaner deliberately does not cut a quote at line zero.
    # Quote-only archive messages must not become candidate evidence.
    if current.lstrip().startswith(">"):
        current = ""
    cut = body.find(current) if current else 0
    history = body[cut + len(current):] if current else body
    source_id = spec["name"] + "-" + digest(parsed.email_id)[:24]
    return {
        "candidate_schema_version": VERSION, "source_id": source_id,
        "source_name": spec.get("source_name", spec["name"]), "project_or_list": spec["project_or_list"],
        "message_id": parsed.message_id, "in_reply_to": list(parsed.in_reply_to),
        "references": list(parsed.references), "thread_id": source_id,
        "subject": parsed.subject, "sender": parsed.sender,
        "recipients": list(parsed.recipients), "cc": list(parsed.cc),
        "timestamp": parsed.sent_at, "body_raw": parsed.raw_body,
        "current_message": current, "quoted_history": history,
        "attachment_names": list(parsed.attachment_names),
        "acquisition_sampling_frame": spec.get("sampling_frame", "FIXED_PUBLIC_MONTH"),
        "source_url_or_reference": location,
        "source_sha256": digest(parsed.subject + "\0" + current),
        "raw_message_sha256": digest(raw),
        "labels": [], "spans": [], "scope": None, "split": "UNASSIGNED",
        "annotation_method": "UNANNOTATED", "annotation_tier": "UNSET",
        "provenance": {"data_origin": "PUBLIC_CORPUS", "source_name": spec["name"],
            "acquired_at": acquired_at, "terms_url": spec["terms_url"],
            "acquisition_format": spec["format"],
            "training_rights_status": spec.get("training_rights_status", "NOT_CLEARED"),
            "redistribution_allowed": False, "raw_text_allowed_in_git": False},
        "license_or_terms_note": spec["terms_note"],
        "metadata_quality": {"parser_defects": parsed.parser_defect_count,
            "raw_headers_available": spec["format"] == "mbox",
            "attachment_metadata_available": spec["format"] == "mbox",
            "thread_link_method": "explicit_headers_only"},
    }


class ArchiveText(HTMLParser):
    """Read displayed text only; never follow links or download attachments."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div", "li") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def archive_text(fragment: str) -> str:
    parser = ArchiveText()
    parser.feed(fragment)
    return "".join(parser.parts)


def parse_w3c_html(path: Path, spec: dict, acquired_at: str) -> dict:
    raw = path.read_bytes()
    declared = re.search(rb'<meta\s+charset="([a-zA-Z0-9_-]+)"', raw, re.I)
    charset = declared.group(1).decode("ascii") if declared else "utf-8"
    # Historical HTML messages use their original charset (including cp1252).
    # Fail on undecodable bytes instead of silently corrupting evidence offsets.
    document = raw.decode(charset)
    body_match = re.search(r'<pre\b[^>]*class="body"[^>]*>(.*?)</pre>', document, re.S | re.I)
    if not body_match:
        raise ValueError("W3C message body element missing; do not parse navigation as email.")
    def comment(key):
        match = re.search(r'<!--\s*' + re.escape(key) + r'="(.*?)"\s*-->', document, re.S)
        return unescape(match.group(1)) if match else ""
    def header(key):
        match = re.search(r'<li>\s*<span class="' + re.escape(key) + r'">(.*?)</li>', document, re.S)
        value = archive_text(match.group(1)).strip() if match else ""
        return re.sub(r'^' + key + r':\s*', '', value, flags=re.I)
    rendered = EmailMessage()
    for name, value in (("Subject", comment("subject")), ("From", comment("email")),
                        ("To", header("to")), ("Date", comment("sent")), ("Message-ID", comment("id"))):
        if value:
            rendered[name] = value.replace("\r", " ").replace("\n", " ")
    rendered.set_content(archive_text(body_match.group(1)).strip())
    row = normalize(rendered.as_bytes(), spec, spec["url"], acquired_at)
    # This is a rendered archive page, not the original RFC822 payload.
    row["raw_message_sha256"] = digest(raw)
    row["metadata_quality"]["raw_headers_available"] = False
    row["metadata_quality"]["thread_link_method"] = "archive_parent_navigation_if_available"
    row["metadata_quality"]["headers_reconstructed_from_public_html"] = True
    row["metadata_quality"]["html_charset"] = charset
    outside_body = document[:body_match.start()] + document[body_match.end():]
    row["archive_parent_url"] = None
    for item in re.findall(r'<li\b[^>]*>(.*?)</li>', outside_body, re.S | re.I):
        if re.search(r'In reply to:', archive_text(item), re.I):
            match = re.search(r'href="([^"]+)"', item)
            if match:
                parent = urljoin(spec["url"], unescape(match.group(1)))
                if allowed_public_url(parent):
                    row["archive_parent_url"] = parent
    return row


def parse_archive(path: Path, spec: dict, acquired_at: str, *, max_messages: int = 1500) -> list[dict]:
    if spec["format"] == "w3c_html":
        return [parse_w3c_html(path, spec, acquired_at)]
    if spec["format"] != "mbox":
        raise ValueError("This parser requires an RFC822 mbox archive.")
    box = mailbox.mbox(path, create=False)
    try:
        if len(box) > max_messages:
            raise ValueError("Message cap exceeded; choose a smaller archive window.")
        return [normalize(box.get_bytes(key, from_=False), spec, spec["url"] + "#message-" + str(key), acquired_at) for key in box.iterkeys()]
    finally:
        box.close()


def join_threads(rows: list[dict]) -> None:
    by_url = {r["source_url_or_reference"]: r for r in rows}
    def links(row):
        parent = by_url.get(row.get("archive_parent_url"))
        # Relationship is archive navigation, never fabricated as an RFC header.
        if parent and parent["message_id"]:
            row["archive_parent_source_id"] = parent["source_id"]
            return [parent["message_id"]]
        return row["in_reply_to"]
    adapted = [{"email_id": r["source_id"], "message_id": r["message_id"],
                "references": r["references"], "in_reply_to": links(r),
                "sent_at": r["timestamp"], "source_path": r["source_url_or_reference"]} for r in rows]
    linked = assign_thread_metadata(adapted)
    for row in rows:
        thread, turn = linked[row["source_id"]]
        row["thread_id"] = "project-mail-" + thread.removeprefix("enron-thread-")
        row["turn_index"] = turn
        # Retained for future grouped splitting. No TRAIN/DEV/TEST allocation here.
        row["leakage_group"] = row["thread_id"]


def screen(row: dict) -> dict:
    current = row["current_message"]
    subject = row["subject"]
    noise = []
    if not current.strip():
        noise.append("no_current_authored_text")
    if NOISE_SENDER.search(row["sender"]) or NOISE_SUBJECT.search(subject):
        noise.append("automation_or_housekeeping")
    lines = current.splitlines()
    patch_lines = sum(bool(re.match(r"^(?:diff --git|@@ |[+-]{3}|[+-][^+-])", line)) for line in lines)
    if lines and patch_lines / len(lines) > .65:
        noise.append("patch_dominated")
    categories = [k for k, p in PATTERNS.items() if p.search(current)]
    contrasts = []
    if re.search(r"\bmeeting\b", current, re.I) and not PATTERNS["DEADLINE"].search(current):
        contrasts.append("meeting_without_due_cue")
    if re.search(r"\b(report|document)\b.*\b(attached|sent|delivered)\b|\battached\b.*\b(report|document)\b", current, re.I | re.S):
        contrasts.append("document_delivery_or_mention")
    if re.search(r"\breview\b", current, re.I) and not re.search(r"\b(approve|sign[ -]?off|authoriz\w*)\b", current, re.I):
        contrasts.append("review_without_approval_cue")
    return {"weak_cue_categories": categories, "hard_negative_cues": contrasts,
            "noise_reasons": noise, "cues_are_labels": False}


def tokens(row: dict) -> set[str]:
    text = row["current_message"].casefold()
    text = re.sub(r"https?://\S+|\b\S+@\S+\b|\b\d+\b", " SLOT ", text)
    return set(re.findall(r"[a-z]{3,}", text))


def similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.


def group_templates(rows: list[dict]) -> None:
    """Conservative connected groups for future splits; never assign a split."""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a, b):
        parent[find(b)] = find(a)
    by_thread = {}
    bags = [tokens(r) for r in rows]
    for i, row in enumerate(rows):
        if row["thread_id"] in by_thread:
            union(i, by_thread[row["thread_id"]])
        by_thread[row["thread_id"]] = i
        for j in range(i):
            if len(bags[i]) >= 12 and len(bags[j]) >= 12 and similarity(bags[i], bags[j]) >= .92:
                union(i, j)
    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(rows[i]["source_id"])
    for i, row in enumerate(rows):
        row["leakage_group"] = "project-mail-group-" + digest("\n".join(sorted(groups[find(i)])))[:24]


def select(rows: list[dict], *, limit: int = 120, seed: int = 20261010) -> tuple[list[dict], dict]:
    if not 1 <= limit <= 400:
        raise ValueError("Candidate limit must be 1..400; do not ingest a huge annotation queue.")
    # Drop exact cross-post copies from this selection, retain lineage locally.
    unique, seen, duplicates = [], {}, 0
    for row in sorted(rows, key=lambda r: r["source_id"]):
        key = digest(row["subject"].casefold().removeprefix("re: ") + "\0" + row["body_raw"])
        if key in seen:
            duplicates += 1
            seen[key].setdefault("duplicate_source_references", []).append(row["source_url_or_reference"])
            continue
        seen[key] = row
        row["mining"] = screen(row)
        unique.append(row)
    pool = [r for r in unique if not r["mining"]["noise_reasons"]]
    ordered = sorted(pool, key=lambda r: digest(str(seed) + r["source_id"]))
    # Purposively chosen HTML pages cannot enter the naturalistic month sample.
    natural_frame = [r for r in ordered if r["acquisition_sampling_frame"] == "FIXED_PUBLIC_MONTH"]
    natural_n = min(len(natural_frame), max(1, limit // 4))
    selected = natural_frame[:natural_n]
    for r in selected:
        r["sampling_track"] = "NATURALISTIC"
    picked = {r["source_id"] for r in selected}
    rest = [r for r in ordered if r["source_id"] not in picked and (r["mining"]["weak_cue_categories"] or r["mining"]["hard_negative_cues"])]
    bags = {r["source_id"]: tokens(r) for r in pool}
    category_counts = Counter(k for r in selected for k in r["mining"]["weak_cue_categories"])
    source_counts = Counter(r["source_name"] for r in selected)
    suppressed = 0
    while rest and len(selected) < limit:
        ranked = []
        for r in rest:
            closest = max((similarity(bags[r["source_id"]], bags[s["source_id"]]) for s in selected), default=0.)
            score = ((1 - closest) * 3 + sum(1 / (1 + category_counts[k]) for k in r["mining"]["weak_cue_categories"])
                     + .5 * bool(r["mining"]["hard_negative_cues"]) + 1 / (1 + source_counts[r["source_name"]]))
            ranked.append((score, r["source_id"], closest, r))
        _, _, closest, best = max(ranked, key=lambda v: (v[0], v[1]))
        rest.remove(best)
        if closest >= .92:
            suppressed += 1
            continue
        best["sampling_track"] = "ENRICHED_CHALLENGE"
        selected.append(best)
        category_counts.update(best["mining"]["weak_cue_categories"])
        source_counts[best["source_name"]] += 1
    summary = {
        "schema_version": VERSION, "records_parsed": len(rows), "exact_duplicates_removed": duplicates,
        "eligible_after_noise_filter": len(pool), "noise_excluded": len(unique) - len(pool),
        "naturalistic_frame_size": len(natural_frame),
        "noise_reasons": dict(Counter(reason for r in unique for reason in r["mining"]["noise_reasons"])),
        "selected": len(selected), "requested": limit, "near_templates_suppressed": suppressed,
        "sampling_tracks": dict(Counter(r["sampling_track"] for r in selected)),
        "sources": dict(Counter(r["source_name"] for r in selected)),
        "weak_cue_category_counts_not_labels": dict(category_counts),
        "hard_negative_cue_counts_not_labels": dict(Counter(k for r in selected for k in r["mining"]["hard_negative_cues"])),
        "selected_threads": len({r["thread_id"] for r in selected}),
        "metadata_present": {k: sum(bool(r[k]) for r in selected) for k in ("message_id", "references", "in_reply_to", "sender", "recipients", "timestamp")},
        "seed": seed, "diversity_method": "greedy token-set Jaccard plus rare-cue and source balancing",
        "labels_generated": 0, "gold_generated": 0, "split": "UNASSIGNED",
        "interpretation": "human-selection candidates only; cue counts are not measured label coverage or model accuracy",
    }
    return selected, summary


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
