"""Cross-corpus identity components, including sentence-derived email copies.

This is separate from closed V1 helpers. Text never appears in the exported
index. Matching is conservative; unmatched records are not proof of absence
of overlap, especially when a release suppresses original identities/text.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .leakage import fingerprint_content, normalize_tokens
from .threading import normalize_message_id


ENRON_DERIVED = {'enron', 'mailex', 'parakweet', 'cerec', 'enron_meetings'}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class IdentityRecord:
    record_id: str
    dataset: str
    overlap_family: str
    subject: str = ''
    body: str = ''
    message_id: str | None = None
    thread_id: str | None = None
    # Namespaces must identify the underlying source, not a derived dataset ID.
    origin_ids: tuple[tuple[str, str], ...] = ()
    source_id: str | None = None
    fragment: bool = False
    identity_complete: bool = True
    additional_texts: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.record_id or not self.dataset or not self.overlap_family:
            raise ValueError('record ID, dataset and known overlap family required')
        if self.dataset.casefold() in ENRON_DERIVED and self.overlap_family != 'ENRON':
            raise ValueError('Known Enron derivatives must register family ENRON')
        if any(not namespace or not value for namespace, value in self.origin_ids):
            raise ValueError('Origin identities need both namespace and value')


def identity_from_row(row: Mapping[str, Any], dataset: str, overlap_family: str) -> IdentityRecord:
    """Adapt auxiliary or canonical rows without guessing suppressed identities."""
    sid = row.get('source_id') or row.get('email_id') or row.get('record_id')
    if sid is None:raise ValueError('Every source row needs a stable source/email ID')
    sid = str(sid)
    own_id = sid if sid.startswith(dataset + ':') else dataset + ':' + sid
    metadata = row.get('metadata') or {}
    message_id = row.get('rfc_message_id') or metadata.get('message_id') or row.get('message_id')
    # source_message_id may be an anonymized filename or simulator number.
    # It is never promoted to a globally shared RFC Message-ID.
    origin_ids = []
    for alias in row.get('origin_ids', []):
        if not isinstance(alias, dict) or not alias.get('namespace') or not alias.get('value'):
            raise ValueError('Explicit origin alias must have namespace/value')
        origin_ids.append((str(alias['namespace']),str(alias['value'])))
    if dataset == 'enron':origin_ids.append(('enron_canonical_id',sid))
    elif row.get('enron_email_id'):origin_ids.append(('enron_canonical_id',str(row['enron_email_id'])))
    body = row.get('authored_message')
    if body is None:body = row.get('current_message')
    if body is None:body = row.get('body')
    if body is None:body = row.get('text', '')
    view_fields = ['raw_body','raw_text','text','source_text','authored_message','original_source_text','source_body']
    views = [row.get(k) for k in view_fields]
    context = row.get('thread_context')
    if isinstance(context, str):
        views.append(context)
    elif isinstance(context, list):
        for turn in context:
            if isinstance(turn, str):views.append(turn)
            elif isinstance(turn, dict):
                views.extend(turn.get(k) for k in view_fields+['current_message','body'])
    additional_texts = tuple(dict.fromkeys(v for v in views if isinstance(v,str) and v and v != body))
    # Parsed thread_id denotes a verified source conversation. Raw source
    # metadata (e.g. Airspace's simulator Thread: 0) is not reply evidence.
    thread_id = row.get('thread_id')
    if thread_id is None and row.get('source_thread_verified') is True:
        thread_id = row.get('source_thread_id')
    identity_complete = bool(row.get('overlap_identity_complete', True))
    if dataset.casefold() in ENRON_DERIVED - {'enron'} and not origin_ids and not message_id:
        # A reconstructed/full-length derivative is still not an identified
        # original email. Text length alone cannot clear origin uncertainty.
        identity_complete = False
    return IdentityRecord(
        own_id, dataset, overlap_family, str(row.get('subject') or ''), str(body or ''),
        str(message_id) if message_id else None,
        str(thread_id) if thread_id is not None else None,
        tuple(origin_ids), sid, bool(row.get('fragment') or dataset == 'parakweet'),
        identity_complete,
        additional_texts,
    )


@dataclass
class LeakageIndex:
    records: dict[str, dict[str, Any]]
    links: list[dict[str, str]]
    policy: dict[str, Any] = field(default_factory=dict)

    def export(self) -> dict[str, Any]:
        return {'version': 'global-leakage-v2.1', 'policy': self.policy,
                'records': self.records, 'links': self.links}

    def partition_conflicts(self, assignments: Mapping[str, str]) -> list[dict[str, Any]]:
        unknown = set(assignments) - self.records.keys()
        if unknown:
            raise ValueError(f'Unindexed assigned records: {sorted(unknown)}')
        grouped = defaultdict(list)
        for rid, partition in assignments.items():
            grouped[self.records[rid]['leakage_group_id']].append((rid, partition))
        return [{'leakage_group_id': group, 'partitions': sorted({p for _, p in members}),
                 'record_ids': sorted(r for r, _ in members)}
                for group, members in sorted(grouped.items())
                if len({p for _, p in members}) > 1]

    def training_exclusions(self, train_ids: Iterable[str], protected_ids: Iterable[str]) -> dict[str, str]:
        train_ids, protected_ids = list(train_ids), list(protected_ids)
        missing = (set(train_ids) | set(protected_ids)) - self.records.keys()
        if missing:
            raise ValueError(f'Unindexed records cannot train: {sorted(missing)}')
        groups = {self.records[r]['leakage_group_id'] for r in protected_ids}
        families = {self.records[r]['overlap_family'] for r in protected_ids}
        excluded = {}
        for rid in train_ids:
            row = self.records[rid]
            if row['leakage_group_id'] in groups:
                excluded[rid] = 'protected_component_overlap'
            elif not row['identity_complete'] and row['overlap_family'] in families:
                excluded[rid] = 'unresolved_origin_or_fragment_in_protected_overlap_family'
        return excluded


def build_global_index(records: Iterable[IdentityRecord], *, min_fragment_tokens: int = 8,
                       min_fragment_chars: int = 40, near_threshold: float = 0.92,
                       containment_threshold: float = 0.95) -> LeakageIndex:
    """Group identities, real source threads, exact bodies, near and fragment copies.

    No artificial candidate cap silently omits near matches. Common sentences
    may overgroup; that causes conservative exclusions, never a training permit.
    Different snapshot populations produce different component IDs; every
    assignment must bind to the same complete index snapshot.
    """
    if not 0 < near_threshold <= 1 or not 0 < containment_threshold <= 1:
        raise ValueError('Similarity thresholds must be in (0,1]')
    if min_fragment_tokens < 5 or min_fragment_chars < 1:
        raise ValueError('Fragment matching needs at least five tokens and positive length')
    canonical_rows = sorted(records, key=lambda r: r.record_id)
    if len({r.record_id for r in canonical_rows}) != len(canonical_rows):
        raise ValueError('Record IDs must be globally unique')
    rows, texts, primary_offsets = [], [], []
    for row in canonical_rows:
        primary_offsets.append(len(rows))
        for view in dict.fromkeys((row.body,) + row.additional_texts):
            rows.append(row); texts.append(view)
    parent = list(range(len(rows)))
    tokens = [normalize_tokens(t) for t in texts]
    fps = [fingerprint_content(r.subject, t) for r,t in zip(rows,texts)]
    owners: dict[tuple[str, str], int] = {}
    links = []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    def join(i, j, reason):
        a, b = find(i), find(j)
        if a != b:
            parent[max(a, b)] = min(a, b)
            if rows[i].record_id != rows[j].record_id:
                links.append({'left': min(rows[i].record_id,rows[j].record_id),
                              'right': max(rows[i].record_id,rows[j].record_id), 'reason': reason})

    for i, (row, fp) in enumerate(zip(rows, fps)):
        keys = [('same_record_text_view',row.record_id)]
        if row.source_id:
            keys.append(('source:' + row.dataset, row.source_id))
        if row.message_id:
            mid = normalize_message_id(row.message_id)
            if mid:
                keys.append(('message_id', mid))
        if row.thread_id:
            keys.append(('thread:' + row.dataset, row.thread_id))
        keys += [('origin:' + namespace, value) for namespace,value in row.origin_ids]
        for name in ['body_exact', 'body_tokens', 'body_compact', 'subject_body']:
            value = getattr(fp, name)
            if value:
                keys.append((name, value))
        for key in keys:
            if key in owners:
                join(i, owners[key], key[0])
            else:
                owners[key] = i

    # Inverted five-token shingles find all candidates without comparing every
    # pair. No shared five-token shingle means these near criteria cannot pass.
    postings = defaultdict(set)
    shingle_counts = []
    for i, tok in enumerate(tokens):
        shingles = {tok[k:k+5] for k in range(max(0,len(tok)-4))}
        shingle_counts.append(len(shingles))
        candidates = Counter()
        for shingle in shingles:
            candidates.update(postings[shingle])
        for j in sorted(candidates):
            if find(i) == find(j):
                continue
            short, long = (i,j) if len(tok) <= len(tokens[j]) else (j,i)
            st, lt = tokens[short], tokens[long]
            shared = candidates[j]
            short_count = shingle_counts[short]
            # Necessary subset check before ordered containment. This skips
            # expensive scans sharing only a boilerplate phrase; no possible
            # exact-contained sequence is removed and there is no candidate cap.
            all_short_shingles = short_count > 0 and shared == short_count
            # A protected authored email may be copied into a much larger
            # quoted context. Size-ratio gates cannot safely omit that copy.
            if all_short_shingles and len(st) >= 20 and len(fps[short].normalized_body) >= 120:
                if any(lt[k:k+len(st)] == st for k in range(len(lt)-len(st)+1)):
                    join(i,j,'substantial_ordered_text_containment'); continue
            if rows[short].fragment:
                if all_short_shingles and len(st) >= min_fragment_tokens and len(fps[short].normalized_body) >= min_fragment_chars:
                    # Exact ordered fragment containment, not merely shared words.
                    if any(lt[k:k+len(st)] == st for k in range(len(lt)-len(st)+1)):
                        join(i,j,'derived_fragment_containment'); continue
            if min(len(tok),len(tokens[j])) >= 20 and min(len(fps[i].normalized_body),len(fps[j].normalized_body)) >= 120:
                ratio = min(len(tok),len(tokens[j])) / max(len(tok),len(tokens[j]))
                union_count = shingle_counts[i] + shingle_counts[j] - shared
                if ratio >= .90 and union_count and shared / union_count >= near_threshold:
                    join(i,j,'near_token_shingles'); continue
                # Formatting/signature stripping may make a derived email shorter.
                if len(st) / len(lt) >= .50 and short_count and shared / short_count >= containment_threshold:
                    join(i,j,'long_body_shingle_containment')
        for shingle in shingles:
            postings[shingle].add(i)

    components = defaultdict(set)
    for i, row in enumerate(rows):
        components[find(i)].add(row.record_id)
    group_ids = {root: 'global-v2-' + digest('\0'.join(sorted(ids))) for root, ids in components.items()}
    exported = {}
    for i in primary_offsets:
        row, fp = rows[i], fps[i]
        identity_complete = row.identity_complete
        # Short fragments with no recoverable original identity remain unresolved
        # even if an own-dataset sentence ID exists.
        if row.fragment and not row.origin_ids and not row.message_id:
            identity_complete = False
        if not fp.eligible and not row.origin_ids and not row.message_id:
            identity_complete = False
        exported[row.record_id] = {
            'dataset': row.dataset, 'overlap_family': row.overlap_family,
            'leakage_group_id': group_ids[find(i)], 'identity_complete': identity_complete,
            'fragment': row.fragment, 'body_exact_sha256': fp.body_exact,
            'body_tokens_sha256': fp.body_tokens,
            'normalized_subject_sha256': digest(fp.normalized_subject) if fp.normalized_subject else None,
            'origin_identity_sha256': [digest(ns + '\0' + value) for ns,value in row.origin_ids],
            'message_id_sha256': digest(normalize_message_id(row.message_id)) if row.message_id else None,
            'additional_text_view_sha256': [digest(t) for t in row.additional_texts],
        }
    return LeakageIndex(exported, links, {
        'record_order': 'sorted globally unique record_id', 'near_shingle_size': 5,
        'near_jaccard': near_threshold, 'long_containment': containment_threshold,
        'fragment_min_tokens': min_fragment_tokens, 'fragment_min_chars': min_fragment_chars,
        'cross_family_text_matching': True, 'source_threads_are_dataset_qualified': True,
        'raw_and_thread_context_views_indexed': True, 'text_views_indexed':len(rows),
        'unresolved_same_family_training_is_quarantined': True,
        'limitation': 'Fingerprint/near matching cannot prove absence of paraphrase or concealed identities; only original source aliases are exact identity evidence.',
    })
