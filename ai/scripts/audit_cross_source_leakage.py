"""Build a privacy-preserving duplicate/leakage sidecar for Enron and MailEx."""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Iterable

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from src.datasets.leakage import (  # noqa: E402
    MAX_NEAR_SUBJECT_GROUP,
    NEAR_MAX_TOKENS,
    NEAR_MIN_CHARS,
    NEAR_MIN_TOKENS,
    fingerprint_content,
    is_near_duplicate,
)

DEFAULT_ENRON = AI_DIR / "data/interim/enron_full.jsonl"
DEFAULT_MAILEX = AI_DIR / "data/processed/mailex.jsonl"
DEFAULT_CANDIDATES = AI_DIR / "data/interim/enron_candidates.jsonl"
DEFAULT_SIDECAR = AI_DIR / "data/interim/leakage_groups.jsonl"
DEFAULT_REPORT = AI_DIR / "reports/cross_source_leakage_audit.md"

THREAD = 1
CONTENT_BITS = {
    "exact_body": 2,
    "strong_token_body": 4,
    "subject_body": 8,
    "raw_exact_body": 16,
    "raw_strong_token_body": 32,
    "raw_subject_body": 64,
    "near_subject_body": 128,
}
KIND_ORDER = (
    (THREAD, "thread"),
    (CONTENT_BITS["exact_body"], "exact_body"),
    (CONTENT_BITS["strong_token_body"], "strong_token_body"),
    (CONTENT_BITS["subject_body"], "subject_body"),
    (CONTENT_BITS["raw_exact_body"], "raw_exact_body"),
    (CONTENT_BITS["raw_strong_token_body"], "raw_strong_token_body"),
    (CONTENT_BITS["raw_subject_body"], "raw_subject_body"),
    (CONTENT_BITS["near_subject_body"], "near_subject_body"),
)


class DisjointSet:
    def __init__(self) -> None:
        self.parent = array("I")
        self.rank = array("B")

    def add(self) -> None:
        index = len(self.parent)
        self.parent.append(index)
        self.rank.append(0)

    def find(self, item: int) -> int:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, left: int, right: int) -> int:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return left_root
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1
        return left_root


def _json_records(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if line.strip():
                yield offset, json.loads(line)


def _get_fingerprint_fields(subject: str, body: str, raw: bool = False) -> tuple[Any, ...]:
    fp = fingerprint_content(subject, body)
    if raw:
        return (
            fp.body_exact,
            fp.body_tokens,
            fp.body_compact,
            fp.subject_body,
            fp.short_body_exact,
            fp.short_body_tokens,
            fp.body_char_count,
            fp.token_count,
            int(fp.eligible),
        )
    return (
        fp.body_exact,
        fp.body_tokens,
        fp.body_compact,
        fp.subject_body,
        fp.short_body_exact,
        fp.short_body_tokens,
        fp.normalized_subject,
        fp.body_char_count,
        fp.token_count,
        int(fp.eligible),
    )


def _insert_source(db: sqlite3.Connection, dsu: DisjointSet, path: Path) -> int:
    batch: list[tuple[Any, ...]] = []
    count = 0
    base_id = len(dsu.parent)
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record["source_dataset"])
            email_id = str(record["email_id"])
            thread_id = str(record.get("thread_id") or "")
            subject = str(record.get("subject") or "")
            current = str(record.get("current_message") or "")
            raw_body = str(record.get("raw_body") or "")
            cur = _get_fingerprint_fields(subject, current)
            raw = _get_fingerprint_fields(subject, raw_body, raw=True)
            row_id = base_id + count
            dsu.add()
            batch.append((
                row_id, source, email_id, thread_id, *cur[:6], *raw[:6],
                cur[6], cur[7], cur[8], cur[9], raw[6], raw[7], raw[8], offset,
            ))
            count += 1
            if len(batch) >= 2000:
                db.executemany(
                    "INSERT INTO records VALUES (" + ",".join("?" for _ in batch[0]) + ")",
                    batch,
                )
                batch.clear()
        if batch:
            db.executemany(
                "INSERT INTO records VALUES (" + ",".join("?" for _ in batch[0]) + ")",
                batch,
            )
    db.commit()
    return count


def _union_groups(
    db: sqlite3.Connection,
    dsu: DisjointSet,
    evidence: bytearray,
    columns: tuple[tuple[str, int], ...],
) -> None:
    for column, bit in columns:
        cursor = db.execute(
            f"SELECT {column}, MIN(row_id), COUNT(*) FROM records "
            f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING COUNT(*) > 1"
        )
        for key, first_id, _ in cursor:
            members = [row[0] for row in db.execute(
                f"SELECT row_id FROM records WHERE {column}=?", (key,)
            )]
            if len(members) < 2:
                continue
            anchor = members[0]
            for member in members:
                evidence[member] |= bit
                dsu.union(anchor, member)


def _compact_compatible(left_chars: int, left_tokens: int, right_chars: int, right_tokens: int) -> bool:
    if min(left_chars, right_chars) < 80 or min(left_tokens, right_tokens) < 12:
        return False
    return (
        min(left_chars, right_chars) / max(left_chars, right_chars) >= 0.80
        and min(left_tokens, right_tokens) / max(left_tokens, right_tokens) >= 0.75
    )


def _union_compact_groups(
    db: sqlite3.Connection,
    dsu: DisjointSet,
    evidence: bytearray,
    key_col: str,
    chars_col: str,
    tokens_col: str,
    bit: int,
) -> None:
    cursor = db.execute(
        f"SELECT {key_col} FROM records WHERE {key_col} IS NOT NULL "
        f"GROUP BY {key_col} HAVING COUNT(*)>1"
    )
    for (key,) in cursor:
        rows = list(db.execute(
            f"SELECT row_id, {chars_col}, {tokens_col} FROM records WHERE {key_col}=? ORDER BY row_id",
            (key,),
        ))
        clusters: list[list[tuple[int, int, int]]] = []
        for row in rows:
            for cluster in clusters:
                if _compact_compatible(row[1], row[2], cluster[0][1], cluster[0][2]):
                    cluster.append(row)
                    break
            else:
                clusters.append([row])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            anchor = cluster[0][0]
            for row_id, _chars, _tokens in cluster:
                evidence[row_id] |= bit
                dsu.union(anchor, row_id)


def _near_unions(
    db: sqlite3.Connection,
    dsu: DisjointSet,
    evidence: bytearray,
    source_paths: dict[str, Path],
) -> tuple[int, int, int]:
    bucket_rows = db.execute(
        "SELECT subject_norm, COUNT(*) FROM records "
        "WHERE source='enron' AND eligible=1 AND subject_norm<>'' "
        "AND current_chars>=? AND token_count BETWEEN ? AND ? "
        "GROUP BY subject_norm HAVING COUNT(*)>1",
        (NEAR_MIN_CHARS, NEAR_MIN_TOKENS, NEAR_MAX_TOKENS),
    )
    accepted = skipped_large = tested = 0
    enron_path = source_paths["enron"]
    cache: dict[int, tuple[str, str]] = {}

    def read_body(row_id: int, offset: int) -> tuple[str, str]:
        if row_id in cache:
            return cache[row_id]
        with enron_path.open("rb") as stream:
            stream.seek(offset)
            record = json.loads(stream.readline())
        pair = (str(record.get("subject") or ""), str(record.get("current_message") or ""))
        cache[row_id] = pair
        return pair

    for subject_norm, bucket_size in bucket_rows:
        if bucket_size > MAX_NEAR_SUBJECT_GROUP:
            skipped_large += 1
            continue
        rows = list(db.execute(
            "SELECT row_id, byte_offset FROM records WHERE source='enron' AND subject_norm=? "
            "AND eligible=1 AND current_chars>=? AND token_count BETWEEN ? AND ? ORDER BY row_id",
            (subject_norm, NEAR_MIN_CHARS, NEAR_MIN_TOKENS, NEAR_MAX_TOKENS),
        ))
        cache.clear()
        for left_index in range(len(rows)):
            left_id, left_offset = rows[left_index]
            subject_left, body_left = read_body(left_id, left_offset)
            for right_id, right_offset in rows[left_index + 1:]:
                if dsu.find(left_id) == dsu.find(right_id):
                    continue
                subject_right, body_right = read_body(right_id, right_offset)
                tested += 1
                match, _score = is_near_duplicate(
                    subject_left, body_left, subject_right, body_right
                )
                if match:
                    evidence[left_id] |= CONTENT_BITS["near_subject_body"]
                    evidence[right_id] |= CONTENT_BITS["near_subject_body"]
                    dsu.union(left_id, right_id)
                    accepted += 1
    return accepted, skipped_large, tested


def _source_counts(db: sqlite3.Connection, column: str) -> dict[str, int]:
    groups: dict[str, int] = {}
    cursor = db.execute(
        f"SELECT {column}, SUM(source='enron'), SUM(source='mailex') FROM records "
        f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING SUM(source='enron')>0 AND SUM(source='mailex')>0"
    )
    for _key, n_enron, n_mailex in cursor:
        groups[str(_key)] = int(n_enron or 0) + int(n_mailex or 0)
    return groups


def _cross_stats(db: sqlite3.Connection, fields: tuple[str, ...]) -> dict[str, int]:
    records_enron = records_mailex = groups = pair_count = 0
    mail_ids: set[int] = set()
    enron_ids: set[int] = set()
    for field in fields:
        query = (
            f"SELECT {field}, SUM(source='enron'), SUM(source='mailex') FROM records "
            f"WHERE {field} IS NOT NULL GROUP BY {field} "
            f"HAVING SUM(source='enron')>0 AND SUM(source='mailex')>0"
        )
        for key, n_enron, n_mailex in db.execute(query):
            groups += 1
            records_enron += int(n_enron)
            records_mailex += int(n_mailex)
            pair_count += int(n_enron) * int(n_mailex)
            mail_ids.update(row[0] for row in db.execute(
                f"SELECT row_id FROM records WHERE source='mailex' AND {field}=?", (key,)
            ))
            enron_ids.update(row[0] for row in db.execute(
                f"SELECT row_id FROM records WHERE source='enron' AND {field}=?", (key,)
            ))
    return {
        "signature_groups": groups,
        "enron_record_hits_by_signature": records_enron,
        "mailex_record_hits_by_signature": records_mailex,
        "potential_pairs_by_signature": pair_count,
        "unique_enron_records": len(enron_ids),
        "unique_mailex_records": len(mail_ids),
    }


def _cross_enron_row_ids(db: sqlite3.Connection, fields: tuple[str, ...]) -> set[int]:
    result: set[int] = set()
    for field in fields:
        query = (
            f"SELECT {field} FROM records WHERE {field} IS NOT NULL GROUP BY {field} "
            f"HAVING SUM(source='enron')>0 AND SUM(source='mailex')>0"
        )
        for (key,) in db.execute(query):
            result.update(row[0] for row in db.execute(
                f"SELECT row_id FROM records WHERE source='enron' AND {field}=?", (key,)
            ))
    return result


def _short_stats(db: sqlite3.Connection, fields: tuple[str, ...]) -> dict[str, int]:
    matched_members: set[frozenset[int]] = set()
    for field in fields:
        query = (
            f"SELECT {field} FROM records WHERE {field} IS NOT NULL GROUP BY {field} "
            f"HAVING SUM(source='enron')>0 AND SUM(source='mailex')>0"
        )
        for (key,) in db.execute(query):
            members = frozenset(row[0] for row in db.execute(
                f"SELECT row_id FROM records WHERE {field}=?", (key,)
            ))
            if len(members) > 1:
                matched_members.add(members)
    rows = set().union(*matched_members) if matched_members else set()
    max_group = max((len(group) for group in matched_members), default=0)
    return {
        "signature_groups": len(matched_members),
        "record_hits_by_signature": len(rows),
        "largest_signature_group": max_group,
    }


def _run_audit(
    enron_path: Path,
    mailex_path: Path,
    candidates_path: Path | None,
    sidecar_path: Path,
    report_path: Path,
    temp_parent: Path | None = None,
) -> dict[str, Any]:
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if temp_parent:
        temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_parent) as work_dir:
        db = sqlite3.connect(str(Path(work_dir) / "audit.sqlite"))
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-65536")
        db.execute("""CREATE TABLE records (
            row_id INTEGER PRIMARY KEY, source TEXT, email_id TEXT, thread_id TEXT,
            body_exact TEXT, body_tokens TEXT, body_compact TEXT, subject_body TEXT,
            short_exact TEXT, short_tokens TEXT,
            raw_exact TEXT, raw_tokens TEXT, raw_compact TEXT, raw_subject_body TEXT,
            raw_short_exact TEXT, raw_short_tokens TEXT,
            subject_norm TEXT, current_chars INTEGER, token_count INTEGER, eligible INTEGER,
            raw_chars INTEGER, raw_token_count INTEGER, raw_eligible INTEGER, byte_offset INTEGER
        )""")
        dsu = DisjointSet()
        evidence = bytearray()
        source_paths: dict[str, Path] = {}
        total = 0
        for path in (enron_path, mailex_path):
            # Source values are read from each record; the path map is used only for Enron near-match reads.
            source_key = "enron" if "enron" in path.name.lower() else "mailex"
            source_paths[source_key] = path
            before = len(dsu.parent)
            count = _insert_source(db, dsu, path)
            evidence.extend(b"\0" * count)
            total += count
            if len(dsu.parent) - before != count:
                raise RuntimeError("record indexing mismatch")
        db.execute("CREATE INDEX idx_thread ON records(source, thread_id)")
        db.execute("CREATE INDEX idx_subject ON records(source, subject_norm)")
        for col in (
            "body_exact", "body_tokens", "body_compact", "subject_body",
            "raw_exact", "raw_tokens", "raw_compact", "raw_subject_body",
            "short_exact", "short_tokens", "raw_short_exact", "raw_short_tokens",
        ):
            db.execute(f"CREATE INDEX idx_{col} ON records({col})")
        db.commit()

        # Source threads are connected only within their original source.
        for source, thread_id, first_id, n in db.execute(
            "SELECT source, thread_id, MIN(row_id), COUNT(*) FROM records "
            "WHERE thread_id<>'' GROUP BY source, thread_id HAVING COUNT(*)>1"
        ):
            members = [r[0] for r in db.execute(
                "SELECT row_id FROM records WHERE source=? AND thread_id=?", (source, thread_id)
            )]
            for member in members:
                evidence[member] |= THREAD
                dsu.union(first_id, member)

        _union_groups(db, dsu, evidence, (
            ("body_exact", CONTENT_BITS["exact_body"]),
            ("body_tokens", CONTENT_BITS["strong_token_body"]),
            ("subject_body", CONTENT_BITS["subject_body"]),
            ("raw_exact", CONTENT_BITS["raw_exact_body"]),
            ("raw_tokens", CONTENT_BITS["raw_strong_token_body"]),
            ("raw_subject_body", CONTENT_BITS["raw_subject_body"]),
        ))
        _union_compact_groups(
            db, dsu, evidence, "body_compact", "current_chars", "token_count",
            CONTENT_BITS["strong_token_body"],
        )
        _union_compact_groups(
            db, dsu, evidence, "raw_compact", "raw_chars", "raw_token_count",
            CONTENT_BITS["raw_strong_token_body"],
        )
        near_count, skipped_large, near_pairs_tested = _near_unions(db, dsu, evidence, source_paths)

        flags = bytearray(len(dsu.parent))
        min_identity: dict[int, str] = {}
        comp_enron = Counter()
        comp_mailex = Counter()
        comp_size = Counter()
        roots_by_email: dict[tuple[str, str], int] = {}
        for row_id, source, email_id in db.execute("SELECT row_id, source, email_id FROM records"):
            root = dsu.find(row_id)
            comp_size[root] += 1
            if source == "enron":
                comp_enron[root] += 1
            elif source == "mailex":
                comp_mailex[root] += 1
            flags[root] |= evidence[row_id]
            identity = f"{source}\0{email_id}"
            if root not in min_identity or identity < min_identity[root]:
                min_identity[root] = identity
            roots_by_email[(source, email_id)] = root

        root_group_id = {
            root: "lg-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            for root, identity in min_identity.items()
        }
        cross_roots = {root for root in comp_enron if comp_enron[root] and comp_mailex[root]}
        enron_dup_roots = {
            root for root, n in comp_enron.items()
            if n > 1 and flags[root] & sum(CONTENT_BITS.values())
        }
        enron_dup_records = sum(comp_enron[root] for root in enron_dup_roots)
        largest_enron_dup = max((comp_enron[root] for root in enron_dup_roots), default=0)

        exact_stats = _cross_stats(db, ("body_exact", "raw_exact"))
        compact_stats = _cross_stats(db, ("body_compact", "raw_compact"))
        spaced_stats = _cross_stats(db, ("body_tokens", "raw_tokens"))
        subject_stats = _cross_stats(db, ("subject_body", "raw_subject_body"))
        short_stats = _short_stats(db, ("short_exact", "short_tokens", "raw_short_exact", "raw_short_tokens"))

        candidate_ids: set[str] = set()
        if candidates_path and candidates_path.exists():
            candidate_ids = {
                str(record["email_id"])
                for _, record in _json_records(candidates_path)
                if record.get("email_id")
            }
        enron_id_to_row = {
            email_id: row_id for row_id, source, email_id in db.execute(
                "SELECT row_id, source, email_id FROM records WHERE source='enron'"
            )
        }
        candidate_rows = {enron_id_to_row[email_id] for email_id in candidate_ids if email_id in enron_id_to_row}
        candidate_roots = {dsu.find(row_id) for row_id in candidate_rows}
        exact_candidate_rows = _cross_enron_row_ids(db, ("body_exact", "raw_exact"))
        compact_candidate_rows = _cross_enron_row_ids(db, ("body_compact", "raw_compact"))
        subject_candidate_rows = _cross_enron_row_ids(db, ("subject_body", "raw_subject_body"))
        candidate_stats = {
            "candidate_ids_in_pool": len(candidate_ids),
            "candidate_ids_found_in_full_enron": len(candidate_rows),
            "candidate_records_in_cross_source_groups": sum(1 for row in candidate_rows if dsu.find(row) in cross_roots),
            "candidate_records_with_exact_cross_source_match": len(candidate_rows & exact_candidate_rows),
            "candidate_records_with_compact_token_cross_source_match": len(candidate_rows & compact_candidate_rows),
            "candidate_records_with_subject_body_cross_source_match": len(candidate_rows & subject_candidate_rows),
            "candidate_records_in_duplicate_enron_groups": sum(1 for row in candidate_rows if dsu.find(row) in enron_dup_roots),
            "candidate_groups_overlapping_mailEx": sum(1 for root in candidate_roots if root in cross_roots),
            "candidate_groups_with_duplicate_enron_records": sum(1 for root in candidate_roots if root in enron_dup_roots),
        }

        with sidecar_path.open("w", encoding="utf-8", newline="\n") as out:
            for row_id, source, email_id, thread_id in db.execute(
                "SELECT row_id, source, email_id, thread_id FROM records ORDER BY row_id"
            ):
                root = dsu.find(row_id)
                bits = flags[root]
                kinds = [name for bit, name in KIND_ORDER if bits & bit]
                row = {
                    "source_dataset": source,
                    "email_id": email_id,
                    "thread_id": thread_id,
                    "leakage_group_id": root_group_id[root],
                    "match_kind": "+".join(kinds) if kinds else "singleton",
                }
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

        source_record_counts = Counter()
        for source, n in db.execute("SELECT source, COUNT(*) FROM records GROUP BY source"):
            source_record_counts[source] = n
        thread_groups = db.execute(
            "SELECT COUNT(*) FROM (SELECT source, thread_id FROM records "
            "WHERE thread_id<>'' GROUP BY source, thread_id HAVING COUNT(*)>1)"
        ).fetchone()[0]
        component_count = len(comp_size)
        report = _make_report(
            source_record_counts=source_record_counts,
            total=total,
            component_count=component_count,
            cross_group_count=len(cross_roots),
            exact_stats=exact_stats,
            compact_stats=compact_stats,
            spaced_stats=spaced_stats,
            subject_stats=subject_stats,
            short_stats=short_stats,
            enron_dup_groups=len(enron_dup_roots),
            enron_dup_records=enron_dup_records,
            largest_enron_dup=largest_enron_dup,
            near_count=near_count,
            skipped_large=skipped_large,
            near_pairs_tested=near_pairs_tested,
            thread_groups=thread_groups,
            candidate_stats=candidate_stats,
        )
        report_path.write_text(report, encoding="utf-8")
        db.close()
        return {
            "records": total,
            "components": component_count,
            "cross_source_groups": len(cross_roots),
            "exact_mailEx_records": exact_stats["unique_mailex_records"],
            "compact_mailEx_records": compact_stats["unique_mailex_records"],
            "near_pairs": near_count,
            "enron_duplicate_groups": len(enron_dup_roots),
            "enron_duplicate_records": enron_dup_records,
            "largest_enron_duplicate_group": largest_enron_dup,
            "short_ambiguous_groups_excluded": short_stats["signature_groups"],
            "candidate_stats": candidate_stats,
        }


def _make_report(**values: Any) -> str:
    s = values["source_record_counts"]
    exact = values["exact_stats"]
    compact = values["compact_stats"]
    spaced = values["spaced_stats"]
    subject = values["subject_stats"]
    short = values["short_stats"]
    cand = values["candidate_stats"]
    return f"""# Cross-source leakage and duplicate audit

## Scope and method

Scanned the full canonical Enron and MailEx JSONL inputs: {s.get('enron', 0):,} Enron records and {s.get('mailex', 0):,} MailEx records ({values['total']:,} total). The audit reads `current_message` as the primary authored-body field and `raw_body` as a separate whole-body signature. It never uses quote containment or partial-body matching. Reports and the sidecar contain identifiers and aggregate counts only; no email text is emitted.

Exact matching uses NFKC Unicode normalization, case folding, and whitespace collapse while preserving punctuation. Strong matching hashes the ordered alphanumeric token stream with punctuation and spacing removed; spaced-token hashes are also retained as a diagnostic. Subject-plus-body matching combines a reply-prefix-normalized subject with the compact token signature. Only bodies with at least 80 normalized characters and 12 alphanumeric tokens are linkable. Short-message signatures are measured but excluded from grouping. Same-source Enron near matches require the same normalized subject, at least {NEAR_MIN_CHARS} characters and {NEAR_MIN_TOKENS} tokens, 0.90 token-length ratio, and at least 0.92 Jaccard overlap of five-token shingles. Subject buckets larger than {MAX_NEAR_SUBJECT_GROUP} are skipped to avoid ambiguous mass merges.

`raw_body` is compared only as a complete independent signature. Because the canonical Enron schema does not expose original Message-ID as a separate field, exact duplicate content with different Message-IDs is detected by matching content signatures; distinct Enron `email_id` values provide the available identity distinction. This cannot verify Message-ID differences directly.

## Results

| Measure | Result |
|---|---:|
| Leakage components across all records | {values['component_count']:,} |
| Cross-source components with Enron and MailEx members | {values['cross_group_count']:,} |
| Exact current/raw signature groups with cross-source matches | {exact['signature_groups']:,} |
| Unique MailEx records with an exact current/raw match | {exact['unique_mailex_records']:,} |
| Unique Enron records with an exact current/raw match | {exact['unique_enron_records']:,} |
| Potential exact record pairs, summed by signature | {exact['potential_pairs_by_signature']:,} |
| Compact-token current/raw signature groups (includes exact) | {compact['signature_groups']:,} |
| Unique MailEx records with compact-token match | {compact['unique_mailex_records']:,} |
| Unique Enron records with compact-token match | {compact['unique_enron_records']:,} |
| Spaced-token current/raw signature groups | {spaced['signature_groups']:,} |
| Subject + compact-token signature groups | {subject['signature_groups']:,} |
| Unique MailEx records with subject + body match | {subject['unique_mailex_records']:,} |
| Short/under-threshold cross-source signature groups excluded | {short['signature_groups']:,} |
| Unique records in excluded short/under-threshold match groups | {short['record_hits_by_signature']:,} |
| Largest excluded short signature group | {short['largest_signature_group']:,} |
| Enron same-subject near-match links added | {values['near_count']:,} |
| Enron subject buckets skipped as too large | {values['skipped_large']:,} |
| Enron near-match pairs tested | {values['near_pairs_tested']:,} |
| Enron content-duplicate components with at least two Enron records | {values['enron_dup_groups']:,} |
| Enron records in those duplicate components | {values['enron_dup_records']:,} |
| Largest Enron duplicate component (Enron records) | {values['largest_enron_dup']:,} |
| Source thread groups joined | {values['thread_groups']:,} |

Exact and compact-token unique-record counts are independently deduplicated within their signature families. A MailEx record may match multiple Enron records. Potential pair count is summed per signature and can count one record pair more than once when it matches both `current_message` and `raw_body` signatures; it is not a count of unique record pairs.

## Candidate-pool overlap

| Measure | Result |
|---|---:|
| Candidate IDs in candidate file | {cand['candidate_ids_in_pool']:,} |
| Candidate IDs found in full Enron | {cand['candidate_ids_found_in_full_enron']:,} |
| Candidate records in a cross-source leakage component | {cand['candidate_records_in_cross_source_groups']:,} |
| Candidate records with an exact current/raw cross-source signature | {cand['candidate_records_with_exact_cross_source_match']:,} |
| Candidate records with a compact-token cross-source signature | {cand['candidate_records_with_compact_token_cross_source_match']:,} |
| Candidate records with a subject + body cross-source signature | {cand['candidate_records_with_subject_body_cross_source_match']:,} |
| Candidate records in an Enron duplicate component | {cand['candidate_records_in_duplicate_enron_groups']:,} |
| Candidate groups overlapping MailEx | {cand['candidate_groups_overlapping_mailEx']:,} |
| Candidate groups with duplicate Enron records | {cand['candidate_groups_with_duplicate_enron_records']:,} |

## Sidecar and limitations

The ignored sidecar `ai/data/interim/leakage_groups.jsonl` has one row per source record with `source_dataset`, `email_id`, `thread_id`, stable `leakage_group_id`, and component-level `match_kind`. Component IDs are deterministic hashes of the lexicographically smallest source-qualified email identity. Downstream splitting must union both source-qualified thread IDs and these leakage IDs.

Near-duplicate matching is a conservative token-shingle heuristic, not semantic identity detection. It misses paraphrases, body edits outside the thresholds, records with changed subjects, and subject buckets over the size cap. Compact-token matching can collapse token-boundary differences; the minimum length/token thresholds and subject-body diagnostic reduce short generic collisions. No metric here is a human-reviewed correctness estimate.

Large same-body, multi-subject components can be boilerplate or extraction artifacts rather than distinct underlying messages. They remain together because identical complete body signatures are a conservative leakage boundary; downstream curation should inspect these groups before interpreting group identity semantically.
"""


def run_audit(
    enron_path: str | Path,
    mailex_path: str | Path,
    candidates_path: str | Path | None,
    sidecar_path: str | Path,
    report_path: str | Path,
    temp_parent: str | Path | None = None,
) -> dict[str, Any]:
    return _run_audit(
        Path(enron_path), Path(mailex_path),
        Path(candidates_path) if candidates_path else None,
        Path(sidecar_path), Path(report_path), Path(temp_parent) if temp_parent else None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enron", type=Path, default=DEFAULT_ENRON)
    parser.add_argument("--mailex", type=Path, default=DEFAULT_MAILEX)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--temp-dir", type=Path, default=AI_DIR / "data/interim")
    args = parser.parse_args()
    result = run_audit(
        args.enron, args.mailex, args.candidates, args.sidecar, args.report, args.temp_dir
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
