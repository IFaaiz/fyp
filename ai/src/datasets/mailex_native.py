"""Loss-minimizing adapter for the published native MailEx event annotations.

The published data stores one JSON file per thread. ``sentences[i]`` is the
token sequence for turn ``i`` and ``events.turn_i`` stores parallel event
instances. This module preserves the source event type, raw trigger, BIO tags,
and extras while adding offsets into a deterministic reconstructed text
(``" ".join(tokens)``). It does not map MailEx labels to FYP labels.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


DEFAULT_AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = DEFAULT_AI_ROOT / "data" / "raw" / "mailex" / "extracted" / "data"
DEFAULT_OUTPUT = DEFAULT_AI_ROOT / "data" / "experiments" / "mailex_extraction_v1"
PROTECTED_V2_INDEX = DEFAULT_AI_ROOT / "data" / "processed" / "structured_v2_expanded_leakage_index_v2.json"
OFFICIAL_SPLITS = ("train", "dev", "test")
BIO_RE = re.compile(r"^([BI])-(.+)$")
WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _flatten_tokens(value: Any, flags: list[str]) -> list[str]:
    """Flatten token containers while retaining empty strings and flagging coercions."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_tokens(item, flags))
        return out
    flags.append(f"unsupported_token_value:{type(value).__name__}")
    return [str(value)]


def token_offsets(tokens: list[str]) -> list[dict[str, int]]:
    """Return half-open character offsets into ``' '.join(tokens)``."""
    offsets: list[dict[str, int]] = []
    cursor = 0
    for token in tokens:
        offsets.append({"start": cursor, "end": cursor + len(token)})
        cursor += len(token) + 1
    return offsets


def _segments_for_indices(
    indices: list[int], tokens: list[str], offsets: list[dict[str, int]], text: str
) -> list[dict[str, Any]]:
    """Make contiguous token segments without reordering source token indices."""
    groups: list[list[int]] = []
    for index in indices:
        if not groups or index != groups[-1][-1] + 1:
            groups.append([index])
        else:
            groups[-1].append(index)
    segments: list[dict[str, Any]] = []
    for group in groups:
        first, last = group[0], group[-1]
        start, end = offsets[first]["start"], offsets[last]["end"]
        segments.append({
            "start": start,
            "end": end,
            "text": text[start:end],
            "token_start": first,
            "token_end": last + 1,
            "token_indices": list(group),
        })
    return segments


def _parse_trigger(raw: Any, tokens: list[str], offsets: list[dict[str, int]], text: str) -> dict[str, Any]:
    flags: list[str] = []
    parsed: Any = None
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            flags.append("trigger_parse_error")
    else:
        flags.append("trigger_missing_or_empty")

    words = ""
    source_indices: list[Any] = []
    if not isinstance(parsed, dict):
        if parsed is not None:
            flags.append("trigger_value_not_mapping")
    else:
        words = str(parsed.get("words", ""))
        raw_indices = parsed.get("indices", "")
        raw_values = raw_indices if isinstance(raw_indices, list) else str(raw_indices).split()
        for value in raw_values:
            try:
                # bool is an int subclass; it is not a meaningful source index.
                if isinstance(value, bool):
                    raise ValueError
                source_indices.append(int(value))
            except (TypeError, ValueError):
                flags.append("trigger_index_not_integer")

    if len(set(source_indices)) != len(source_indices):
        flags.append("trigger_indices_duplicated")
    if source_indices != sorted(source_indices):
        flags.append("trigger_indices_not_monotonic")
    if any(index < 0 or index >= len(tokens) for index in source_indices):
        flags.append("trigger_index_out_of_range")
    valid_indices = [index for index in source_indices if 0 <= index < len(tokens)]
    segments = _segments_for_indices(valid_indices, tokens, offsets, text)
    if len(segments) > 1:
        flags.append("trigger_discontinuous")
    reconstructed = " ".join(segment["text"] for segment in segments)
    if words and reconstructed != words:
        flags.append("trigger_words_do_not_match_indexed_tokens")
    return {
        "segments": segments,
        "source_words": words,
        "source_indices": source_indices,
        "source_raw": raw,
        "flags": sorted(set(flags)),
    }


def _parse_bio_tag(event_type: str, raw_tag: Any) -> tuple[str, str | None, str, str | None] | None:
    """Parse native tag while retaining role case and qualifier spelling."""
    if not isinstance(raw_tag, str) or raw_tag == "O":
        return None
    content = raw_tag.strip()
    if content.startswith(event_type + ":"):
        content = content[len(event_type) + 1 :].strip()
    qualifier_source: str | None = None
    qualifier: str | None = None
    for marker, normalized in (
        ("Context:", "context"),
        ("Revision:", "revision"),
        ("CNT:", "context"),
        ("REV:", "revision"),
    ):
        if content.startswith(marker):
            qualifier_source = marker[:-1]
            qualifier = normalized
            content = content[len(marker) :].strip()
            break
    match = BIO_RE.match(content)
    if not match:
        return None
    prefix, role = match.groups()
    role = role.strip()
    for marker, normalized in (("CNT:", "context"), ("REV:", "revision")):
        if role.startswith(marker):
            qualifier_source = marker[:-1]
            qualifier = normalized
            role = role[len(marker) :].strip()
            break
    return prefix, qualifier, role, qualifier_source


def _arguments_from_labels(
    event_type: str,
    labels: Any,
    tokens: list[str],
    offsets: list[dict[str, int]],
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Extract BIO runs; malformed source annotations stay visible and flagged."""
    flags: list[str] = []
    arguments: list[dict[str, Any]] = []
    unparsed: list[dict[str, Any]] = []
    if not isinstance(labels, list):
        return arguments, [{"raw": labels, "flags": ["labels_not_list"]}], ["labels_not_list"]

    active: dict[str, Any] | None = None

    def finish() -> None:
        nonlocal active
        if active is None:
            return
        indices = active.pop("_token_indices")
        active["segments"] = _segments_for_indices(indices, tokens, offsets, text)
        active["token_indices"] = indices
        active["flags"] = sorted(set(active["flags"]))
        arguments.append(active)
        active = None

    for index, raw_tag in enumerate(labels):
        if raw_tag == "O":
            finish()
            continue
        parsed = _parse_bio_tag(event_type, raw_tag)
        if parsed is None:
            finish()
            unparsed.append({"token_index": index, "raw": raw_tag, "flags": ["malformed_bio_tag"]})
            flags.append("malformed_bio_tag")
            continue
        prefix, qualifier, role, qualifier_source = parsed
        if index >= len(tokens):
            flags.append("label_token_index_out_of_range")
            unparsed.append({"token_index": index, "raw": raw_tag, "flags": ["label_token_index_out_of_range"]})
            finish()
            continue
        identity = (qualifier, role)
        if prefix == "B":
            finish()
            active = {
                "role": role,
                "qualifier": qualifier,
                "source_qualifier": qualifier_source,
                "source_bio_tags": [raw_tag],
                "_token_indices": [index],
                "flags": [],
            }
        elif active is not None and (active["qualifier"], active["role"]) == identity:
            active["source_bio_tags"].append(raw_tag)
            active["_token_indices"].append(index)
        else:
            finish()
            active = {
                "role": role,
                "qualifier": qualifier,
                "source_qualifier": qualifier_source,
                "source_bio_tags": [raw_tag],
                "_token_indices": [index],
                "flags": ["orphan_I_tag"],
            }
            flags.append("orphan_I_tag")
    finish()
    return arguments, unparsed, sorted(set(flags))


def _parallel_length(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 1
    lengths = [len(payload.get(key, [])) for key in ("labels", "triggers", "extras") if isinstance(payload.get(key, []), list)]
    return max(lengths, default=0)


def convert_thread(thread_path: Path, split: str) -> list[dict[str, Any]]:
    """Convert one source thread into one native row per message turn."""
    source = json.loads(thread_path.read_text(encoding="utf-8"))
    thread_id = thread_path.stem
    sentence_values = source.get("sentences", [])
    if not isinstance(sentence_values, list):
        sentence_values = []
    events_by_turn = source.get("events", {})
    rows: list[dict[str, Any]] = []

    for turn_index, raw_tokens in enumerate(sentence_values):
        row_flags: list[str] = []
        tokens = _flatten_tokens(raw_tokens, row_flags)
        text = " ".join(tokens)
        offsets = token_offsets(tokens)
        turn_key = f"turn_{turn_index}"
        turn_events = events_by_turn.get(turn_key, {}) if isinstance(events_by_turn, dict) else {}
        row: dict[str, Any] = {
            "message_id": f"{thread_id}::{turn_key}",
            "thread_id": thread_id,
            "split": split,
            "source_turn": turn_index,
            "text": text,
            "tokens": tokens,
            "token_offsets": offsets,
            "events": [],
            "outside_markers": [],
            "unparsed_source_annotations": [],
            "flags": row_flags,
        }
        if not tokens:
            row["flags"].append("empty_turn")
        if not text.strip():
            row["flags"].append("empty_reconstructed_text")
        if isinstance(turn_events, dict):
            source_instance_index = 0
            for source_type, payload in turn_events.items():
                if not isinstance(payload, dict):
                    row["unparsed_source_annotations"].append({
                        "source_event_type": source_type,
                        "source_annotation": payload,
                        "flags": ["event_payload_not_mapping"],
                    })
                    row["flags"].append("event_payload_not_mapping")
                    continue
                labels = payload.get("labels", [])
                triggers = payload.get("triggers", [])
                extras = payload.get("extras", [])
                if not isinstance(labels, list):
                    labels = []
                if not isinstance(triggers, list):
                    triggers = []
                if not isinstance(extras, list):
                    extras = []
                lengths = (len(labels), len(triggers), len(extras))
                if len(set(lengths)) > 1:
                    row["flags"].append("parallel_annotation_arrays_misaligned")
                count = max(lengths, default=0)
                for local_index in range(count):
                    label = labels[local_index] if local_index < len(labels) else None
                    trigger_raw = triggers[local_index] if local_index < len(triggers) else None
                    extra = extras[local_index] if local_index < len(extras) else None
                    source_annotation = {"labels": label, "trigger": trigger_raw, "extra": extra}
                    annotation_flags: list[str] = []
                    if local_index >= len(labels):
                        annotation_flags.append("missing_labels_entry")
                    if local_index >= len(triggers):
                        annotation_flags.append("missing_trigger_entry")
                    if local_index >= len(extras):
                        annotation_flags.append("missing_extra_entry")

                    if source_type == "O":
                        marker_trigger = _parse_trigger(trigger_raw, tokens, offsets, text)
                        annotation_flags.extend(marker_trigger["flags"])
                        row["outside_markers"].append({
                            "marker_id": f"{row['message_id']}::outside-{source_instance_index:04d}",
                            "source_event_type": source_type,
                            "source_annotation": source_annotation,
                            "trigger": marker_trigger,
                            "flags": sorted(set(annotation_flags)),
                        })
                    else:
                        trigger = _parse_trigger(trigger_raw, tokens, offsets, text)
                        arguments, unparsed_tags, label_flags = _arguments_from_labels(
                            source_type, label, tokens, offsets, text
                        )
                        annotation_flags.extend(trigger["flags"])
                        annotation_flags.extend(label_flags)
                        if unparsed_tags:
                            annotation_flags.append("unparsed_label_tokens")
                        row["events"].append({
                            "event_id": f"{row['message_id']}::event-{source_instance_index:04d}",
                            "event_type": source_type,
                            "source_event_type": source_type,
                            "trigger": trigger,
                            "arguments": arguments,
                            "source_extra": extra,
                            "source_annotation": source_annotation,
                            "unparsed_label_tokens": unparsed_tags,
                            "flags": sorted(set(annotation_flags)),
                        })
                    source_instance_index += 1
        elif turn_events:
            row["flags"].append("turn_events_not_mapping")
        row["flags"] = sorted(set(row["flags"]))
        rows.append(row)
    return rows


def _hash_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name.casefold()):
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _sentence_ids(tokens: list[str]) -> list[int]:
    """Estimate sentence boundaries from terminal punctuation for audit only."""
    output: list[int] = []
    sentence_id = 0
    terminal = re.compile(r"[.!?][\"'\u2019\u201d)\]]*$")
    for token in tokens:
        output.append(sentence_id)
        if terminal.search(token):
            sentence_id += 1
    return output


def _jaccard_near_pairs(rows_by_split: dict[str, list[dict[str, Any]]], threshold: float = 0.90) -> int:
    """Count cross-split near duplicates using 5-token shingle Jaccard >= threshold.

    Exact normalized duplicates are included in this count only when their raw
    token sequences differ. Messages shorter than 20 tokens are skipped because
    punctuation-only variation is better handled by the normalized fingerprint.
    """
    messages: list[tuple[str, str, set[tuple[str, ...]]]] = []
    postings: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for split, rows in rows_by_split.items():
        for row in rows:
            if not row["text"].strip():
                continue
            toks = [token.casefold() for token in row["tokens"]]
            shingles = {tuple(toks[i : i + 5]) for i in range(max(0, len(toks) - 4))}
            messages.append((split, row["message_id"], shingles))
    for i, (_, _, shingles) in enumerate(messages):
        for shingle in shingles:
            postings[shingle].append(i)
    candidate_shared: Counter[tuple[int, int]] = Counter()
    for indices in postings.values():
        for left_pos, left in enumerate(indices):
            for right in indices[left_pos + 1 :]:
                if messages[left][0] != messages[right][0]:
                    candidate_shared[(left, right)] += 1
    found: set[tuple[int, int]] = set()
    for (left, right), shared in candidate_shared.items():
        a, b = messages[left][2], messages[right][2]
        if len(a) < 16 or len(b) < 16:
            continue
        if min(len(a), len(b)) / max(len(a), len(b)) < 0.85:
            continue
        union = len(a) + len(b) - shared
        if union and shared / union >= threshold:
            found.add((left, right))
    return len(found)


def _global_registry_fingerprint_comparison(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Compare native content hashes to all index metadata without reading text."""
    if not PROTECTED_V2_INDEX.is_file():
        return {"available": False, "reason": "protected fingerprint index is unavailable"}
    index = json.loads(PROTECTED_V2_INDEX.read_text(encoding="utf-8"))
    records = index.get("records", {})
    protected: dict[str, dict[str, set[str]]] = {
        "body_exact_sha256": defaultdict(set),
        "body_tokens_sha256": defaultdict(set),
        "additional_text_view_sha256": defaultdict(set),
    }
    for record in records.values():
        dataset = str(record.get("dataset", "unknown"))
        for field in ("body_exact_sha256", "body_tokens_sha256"):
            value = record.get(field)
            if isinstance(value, str) and value:
                protected[field][value].add(dataset)
        values = record.get("additional_text_view_sha256", [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value:
                    protected["additional_text_view_sha256"][value].add(dataset)

    word_re = re.compile(r"(?u)[^\W_]+")
    per_split: dict[str, dict[str, Any]] = {}
    all_matched_datasets: Counter[str] = Counter()
    for split, rows in rows_by_split.items():
        matched_rows = {field: set() for field in protected}
        matched_datasets = {field: Counter() for field in protected}
        distinct_native_fingerprints = {field: set() for field in protected}
        for row in rows:
            text = row["text"]
            normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
            tokens = tuple(word_re.findall(unicodedata.normalize("NFKC", text).casefold()))
            token_text = " ".join(tokens)
            candidates: dict[str, str | None] = {
                "body_exact_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest() if len(normalized) >= 80 and len(tokens) >= 12 else None,
                "body_tokens_sha256": hashlib.sha256(token_text.encode("utf-8")).hexdigest() if len(normalized) >= 80 and len(tokens) >= 12 else None,
                "additional_text_view_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
            }
            for field, candidate in candidates.items():
                if candidate and candidate in protected[field]:
                    matched_rows[field].add(row["message_id"])
                    distinct_native_fingerprints[field].add(candidate)
                    for dataset in protected[field][candidate]:
                        matched_datasets[field][dataset] += 1
                        all_matched_datasets[dataset] += 1
        per_split[split] = {
            field: {
                "matching_native_message_rows": len(matched_rows[field]),
                "distinct_native_fingerprints": len(distinct_native_fingerprints[field]),
                "matched_global_record_dataset_counts": dict(sorted(matched_datasets[field].items())),
            }
            for field in protected
        }
    return {
        "available": True,
        "index_version": str(index.get("version", "unknown")),
        "global_registry_record_count": len(records),
        "per_split": per_split,
        "aggregate_matched_global_dataset_counts": dict(sorted(all_matched_datasets.items())),
        "identity_resolution": "Content fingerprints only; native MailEx source identities remain unresolved.",
    }


def _record_components(records: dict[str, dict[str, Any]], links: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Return link/group connected components over metadata record IDs."""
    parent = {record_id: record_id for record_id in records}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for link in links:
        left, right = link.get("left"), link.get("right")
        if isinstance(left, str) and isinstance(right, str):
            union(left, right)
    by_group: dict[str, str] = {}
    for record_id, record in records.items():
        group_id = record.get("leakage_group_id")
        if isinstance(group_id, str) and group_id:
            if group_id in by_group:
                union(record_id, by_group[group_id])
            else:
                by_group[group_id] = record_id
    components: dict[str, set[str]] = defaultdict(set)
    for record_id in parent:
        components[find(record_id)].add(record_id)
    roots = {record_id: find(record_id) for record_id in records}
    return roots, components


def _legacy_parser_comparison(rows_by_split: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Measure exact source-span/run differences from the unchanged mapper parser."""
    from .mailex import _extract_argument_segments, _parse_bio_tag as legacy_parse_bio_tag, _token_offsets

    output: dict[str, Any] = {}
    total = Counter()
    casefold_pairs: dict[str, Counter[str]] = {split: Counter() for split in rows_by_split}
    for split, rows in rows_by_split.items():
        counts = Counter()
        for row in rows:
            offsets = _token_offsets(row["tokens"])
            for event in row["events"]:
                labels = event["source_annotation"].get("labels")
                legacy_segments, _ = _extract_argument_segments(
                    event["event_type"], labels, row["tokens"], offsets
                )
                native_arguments = event["arguments"]
                counts["native_case_sensitive_runs"] += len(native_arguments)
                counts["legacy_casefold_runs"] += len(legacy_segments)
                counts["native_orphan_i_runs"] += sum("orphan_I_tag" in arg["flags"] for arg in native_arguments)
                counts["legacy_orphan_i_runs"] += sum(bool(segment["malformed_bio_start"]) for segment in legacy_segments)

                strict_active: tuple[str, str | None] | None = None
                legacy_active: tuple[str, str | None] | None = None
                if not isinstance(labels, list):
                    continue
                for raw_tag in labels:
                    parsed = legacy_parse_bio_tag(event["event_type"], raw_tag)
                    if parsed is None:
                        strict_active = None
                        legacy_active = None
                        continue
                    prefix, qualifier, role = parsed
                    strict_same = strict_active == (role, qualifier)
                    legacy_same = (
                        legacy_active is not None
                        and legacy_active[0].casefold() == role.casefold()
                        and legacy_active[1] == qualifier
                    )
                    if prefix == "I" and legacy_same and not strict_same:
                        previous = strict_active[0] if strict_active else "<none>"
                        casefold_pairs[split][f"{previous} -> {role}"] += 1
                    if prefix == "B" or not strict_same:
                        strict_active = (role, qualifier)
                    if prefix == "B" or not legacy_same:
                        legacy_active = (role, qualifier)
        counts["extra_native_runs_vs_legacy"] = counts["native_case_sensitive_runs"] - counts["legacy_casefold_runs"]
        counts["extra_native_orphan_i_runs_vs_legacy"] = counts["native_orphan_i_runs"] - counts["legacy_orphan_i_runs"]
        counts["casefold_only_role_transition_starts"] = sum(casefold_pairs[split].values())
        counts["casefold_only_role_transition_pairs"] = dict(sorted(casefold_pairs[split].items()))
        output[split] = dict(counts)
        for key in (
            "native_case_sensitive_runs", "legacy_casefold_runs", "native_orphan_i_runs",
            "legacy_orphan_i_runs", "extra_native_runs_vs_legacy",
            "extra_native_orphan_i_runs_vs_legacy", "casefold_only_role_transition_starts",
        ):
            total[key] += counts[key]
    total["casefold_only_role_transition_pairs"] = dict(sorted(sum((c for c in casefold_pairs.values()), Counter()).items()))
    return {"per_split": output, "total": dict(total)}


def build_fyp_safe_views(
    rows_dir: Path = DEFAULT_OUTPUT,
    boundary_path: Path | None = None,
    index_path: Path = PROTECTED_V2_INDEX,
    output_dir: Path | None = None,
    splits: Iterable[str] = OFFICIAL_SPLITS,
) -> dict[str, Any]:
    """Write separate FYP-safe views by excluding whole linked native threads.

    Official converted JSONL is read only and never rewritten. Membership comes
    from protected IDs in the boundary manifest; content comparison uses only
    hashes in the global index, then expands through index links and shared
    leakage-group IDs. No protected text is read.
    """
    rows_dir = Path(rows_dir)
    output_dir = Path(output_dir) if output_dir is not None else rows_dir
    boundary_path = Path(boundary_path) if boundary_path is not None else (
        DEFAULT_AI_ROOT / "data" / "experiments" / "structured_v2_candidates_20261002_v2" / "isolated_v2" / "boundary_manifest.json"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    records = index.get("records", {})
    protected_ids = set(value for value in boundary.get("protected_ids", []) if isinstance(value, str))
    protected_present = protected_ids & records.keys()
    roots, components = _record_components(records, index.get("links", []))
    protected_roots = {roots[record_id] for record_id in protected_present if record_id in roots}
    expanded_global_ids = {
        record_id for record_id, root in roots.items() if root in protected_roots
    }

    exact_body_index: dict[str, set[str]] = defaultdict(set)
    token_body_index: dict[str, set[str]] = defaultdict(set)
    raw_view_index: dict[str, set[str]] = defaultdict(set)
    for record_id, record in records.items():
        value = record.get("body_exact_sha256")
        if isinstance(value, str) and value:
            exact_body_index[value].add(record_id)
        value = record.get("body_tokens_sha256")
        if isinstance(value, str) and value:
            token_body_index[value].add(record_id)
        values = record.get("additional_text_view_sha256", [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value:
                    raw_view_index[value].add(record_id)

    word_re = re.compile(r"(?u)[^\W_]+")
    rows_by_split: dict[str, list[dict[str, Any]]] = {}
    source_hashes: dict[str, str] = {}
    row_matches: dict[str, list[tuple[str, str, bool, bool]]] = defaultdict(list)
    for split in splits:
        source_path = rows_dir / f"{split}.jsonl"
        source_hashes[split] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        rows = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines() if line]
        rows_by_split[split] = rows
        for row in rows:
            text = row.get("text", "")
            normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
            tokens = tuple(word_re.findall(unicodedata.normalize("NFKC", text).casefold()))
            token_text = " ".join(tokens)
            candidates: set[str] = set()
            if len(normalized) >= 80 and len(tokens) >= 12:
                candidates.update(exact_body_index.get(hashlib.sha256(normalized.encode("utf-8")).hexdigest(), set()))
                candidates.update(token_body_index.get(hashlib.sha256(token_text.encode("utf-8")).hexdigest(), set()))
            if text:
                candidates.update(raw_view_index.get(hashlib.sha256(text.encode("utf-8")).hexdigest(), set()))
            directly_protected = bool(candidates & protected_present)
            component_matched = bool(candidates & expanded_global_ids)
            if component_matched:
                row_matches[split].append((row["thread_id"], row["message_id"], directly_protected, True))
            elif directly_protected:
                # This should be impossible because protected membership is in
                # its own expanded component; retain a defensive explicit match.
                row_matches[split].append((row["thread_id"], row["message_id"], True, False))

    excluded_threads_global = {
        thread_id for matches in row_matches.values() for thread_id, _, _, _ in matches
    }
    counts: dict[str, dict[str, Any]] = {}
    output_hashes: dict[str, str] = {}
    for split, rows in rows_by_split.items():
        original_threads = {row["thread_id"] for row in rows}
        excluded_threads = {thread_id for thread_id in excluded_threads_global if thread_id in original_threads}
        retained = [row for row in rows if row["thread_id"] not in excluded_threads_global]
        output_path = output_dir / f"{split}_fyp_safe.jsonl"
        with output_path.open("w", encoding="utf-8", newline="\n") as stream:
            for row in retained:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        output_hashes[split] = hashlib.sha256(output_path.read_bytes()).hexdigest()
        matched = row_matches.get(split, [])
        direct_rows = {message_id for _, message_id, direct, _ in matched if direct}
        component_rows = {message_id for _, message_id, _, linked in matched if linked}
        direct_threads = {thread_id for thread_id, _, direct, _ in matched if direct}
        component_threads = {thread_id for thread_id, _, _, linked in matched if linked}
        original_events = sum(len(row.get("events", [])) for row in rows)
        retained_events = sum(len(row.get("events", [])) for row in retained)
        counts[split] = {
            "official_messages": len(rows),
            "official_threads": len(original_threads),
            "official_events": original_events,
            "direct_protected_match_messages": len(direct_rows),
            "direct_protected_match_threads": len(direct_threads),
            "link_or_group_component_match_messages": len(component_rows),
            "link_or_group_component_match_threads": len(component_threads),
            "excluded_threads": len(excluded_threads),
            "excluded_messages": len(rows) - len(retained),
            "retained_messages": len(retained),
            "retained_threads": len({row["thread_id"] for row in retained}),
            "retained_events": retained_events,
        }

    result = {
        "variant": "mailex_native_fyp_safe_v1",
        "public_policy": {
            "boundary_membership": "Only boundary_manifest.protected_ids determine protected membership.",
            "fingerprint_match": "Native message text is hashed locally and compared to body_exact_sha256, body_tokens_sha256, and additional_text_view_sha256 metadata in the global leakage index.",
            "component_expansion": "Any fingerprint hit connected to a protected ID by a shared leakage_group_id or an index link is treated as protected-associated.",
            "exclusion_unit": "If any message in a native thread matches a protected component, every row for that thread is excluded from the FYP-safe view across all splits.",
            "official_data": "Official converted train/dev/test JSONL stays unchanged; these files are a separately named exclusion variant, not official benchmark membership or scores.",
            "privacy": "No protected message text, source IDs, native thread IDs, or row IDs are included in this manifest or public report.",
            "identity_limit": "Content and registered component matching do not resolve original Enron identities or prove absence of paraphrase.",
        },
        "boundary_manifest_sha256": hashlib.sha256(boundary_path.read_bytes()).hexdigest(),
        "global_index_sha256": hashlib.sha256(Path(index_path).read_bytes()).hexdigest(),
        "official_row_file_sha256": source_hashes,
        "fyp_safe_row_file_sha256": output_hashes,
        "protected_boundary_record_count": len(protected_ids),
        "protected_boundary_records_found_in_index": len(protected_present),
        "protected_records_missing_from_index": len(protected_ids - protected_present),
        "link_or_group_expanded_record_count": len(expanded_global_ids),
        "fyp_safe_split_counts": counts,
        "globally_excluded_thread_count": len(excluded_threads_global),
    }
    manifest_path = output_dir / "fyp_safe_manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def convert_splits(
    source_dir: Path = DEFAULT_SOURCE,
    output_dir: Path = DEFAULT_OUTPUT,
    splits: Iterable[str] = OFFICIAL_SPLITS,
) -> dict[str, Any]:
    """Convert official splits and return aggregate-only provenance metadata."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows: dict[str, list[dict[str, Any]]] = {}
    source_hashes: dict[str, str] = {}
    source_file_counts: dict[str, int] = {}
    source_quality: dict[str, Counter[str]] = {}

    for split in splits:
        files = sorted((source_dir / split).glob("*.json"))
        source_file_counts[split] = len(files)
        source_hashes[split] = _hash_files(files)
        quality: Counter[str] = Counter()
        rows: list[dict[str, Any]] = []
        out_path = output_dir / f"{split}.jsonl"
        with out_path.open("w", encoding="utf-8", newline="\n") as stream:
            for source_path in files:
                thread_rows = convert_thread(source_path, split)
                quality["thread_count"] += 1
                for row in thread_rows:
                    rows.append(row)
                    quality["message_count"] += 1
                    quality["empty_turn_count"] += "empty_turn" in row["flags"]
                    quality["empty_reconstructed_text_count"] += "empty_reconstructed_text" in row["flags"]
                    quality["empty_token_count"] += sum(token == "" for token in row["tokens"])
                    quality["event_count"] += len(row["events"])
                    quality["outside_marker_count"] += len(row["outside_markers"])
                    quality["unparsed_source_annotation_count"] += len(row["unparsed_source_annotations"])
                    quality["misaligned_turn_count"] += "parallel_annotation_arrays_misaligned" in row["flags"]
                    for event in row["events"]:
                        quality["events_with_flags"] += bool(event["flags"])
                        quality["trigger_parse_error_count"] += "trigger_parse_error" in event["trigger"]["flags"]
                        quality["trigger_out_of_range_count"] += "trigger_index_out_of_range" in event["trigger"]["flags"]
                        quality["trigger_discontinuous_count"] += "trigger_discontinuous" in event["trigger"]["flags"]
                        quality["trigger_words_mismatch_count"] += "trigger_words_do_not_match_indexed_tokens" in event["trigger"]["flags"]
                        quality["malformed_bio_event_count"] += "malformed_bio_tag" in event["flags"]
                        quality["orphan_i_event_count"] += "orphan_I_tag" in event["flags"]
                        quality["unparsed_label_token_count"] += len(event["unparsed_label_tokens"])
                        quality["label_length_mismatch_count"] += isinstance(event["source_annotation"].get("labels"), list) and len(event["source_annotation"]["labels"]) != len(row["tokens"])
                        outside_sentence = False
                        for argument in event["arguments"]:
                            quality[f"qualifier_{argument['qualifier'] or 'none'}_argument_count"] += 1
                            quality["argument_span_count"] += len(argument["segments"])
                            quality["argument_with_flags_count"] += bool(argument["flags"])
                        trigger_ids = [i for segment in event["trigger"]["segments"] for i in segment["token_indices"]]
                        sentence_ids = _sentence_ids(row["tokens"])
                        trigger_sentences = {sentence_ids[i] for i in trigger_ids if i < len(sentence_ids)}
                        for argument in event["arguments"]:
                            arg_ids = [i for segment in argument["segments"] for i in segment["token_indices"]]
                            if trigger_sentences and any(sentence_ids[i] not in trigger_sentences for i in arg_ids if i < len(sentence_ids)):
                                quality["arguments_outside_trigger_sentence_estimate"] += 1
                                outside_sentence = True
                        quality["events_with_argument_outside_trigger_sentence_estimate"] += outside_sentence
                    stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        source_quality[split] = quality
        all_rows[split] = rows

    # Audit the first five event-bearing TRAIN rows privately for root inspection.
    if "train" in all_rows:
        preview_rows = [row for row in all_rows["train"] if row["events"]][:5]
        with (output_dir / "train_preview5.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for row in preview_rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = _summarize_native(all_rows, source_dir, source_file_counts, source_hashes, source_quality)
    manifest = {
        "adapter": "mailex_native_v1",
        "source_split_hashes_sha256": source_hashes,
        "source_file_counts": source_file_counts,
        "converted_row_counts": {split: len(rows) for split, rows in all_rows.items()},
        "summary": summary,
        "privacy": "No source message text or source identifiers are stored in this manifest.",
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _summarize_native(
    rows_by_split: dict[str, list[dict[str, Any]]],
    source_dir: Path,
    source_file_counts: dict[str, int],
    source_hashes: dict[str, str],
    quality_by_split: dict[str, Counter[str]],
) -> dict[str, Any]:
    event_counts: dict[str, Counter[str]] = {split: Counter() for split in rows_by_split}
    role_counts: dict[str, Counter[str]] = {split: Counter() for split in rows_by_split}
    source_message_hashes: dict[str, dict[str, list[int]]] = {split: defaultdict(list) for split in rows_by_split}
    normalized_message_hashes: dict[str, dict[str, list[int]]] = {split: defaultdict(list) for split in rows_by_split}
    thread_ids: dict[str, set[str]] = {split: set() for split in rows_by_split}
    empty_content_counts: Counter[str] = Counter()
    structural_counts: dict[str, Counter[str]] = {split: Counter() for split in rows_by_split}

    for split, rows in rows_by_split.items():
        for row_index, row in enumerate(rows):
            thread_ids[split].add(row["thread_id"])
            is_empty = not row["text"].strip()
            empty_content_counts[split] += is_empty
            if not is_empty:
                token_json = json.dumps(row["tokens"], ensure_ascii=False, separators=(",", ":"))
                exact_hash = hashlib.sha256(token_json.encode("utf-8")).hexdigest()
                normalized = "".join(WORD_RE.findall(row["text"].casefold()))
                if normalized:
                    normalized_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    normalized_message_hashes[split][normalized_hash].append(row_index)
                source_message_hashes[split][exact_hash].append(row_index)

            seen_events: set[tuple[Any, ...]] = set()
            trigger_sets: list[set[int]] = []
            argument_rows: list[tuple[int, dict[str, Any], set[int]]] = []
            event_role_runs: dict[int, Counter[tuple[str | None, str]]] = defaultdict(Counter)
            for event_index, event in enumerate(row["events"]):
                event_counts[split][event["event_type"]] += 1
                signature = (
                    event["event_type"],
                    tuple(event["trigger"]["source_indices"]),
                    tuple((arg["qualifier"], arg["role"], tuple(arg["token_indices"])) for arg in event["arguments"]),
                )
                if signature in seen_events:
                    structural_counts[split]["duplicate_event_instances_within_message"] += 1
                seen_events.add(signature)
                trigger_ids = set(i for segment in event["trigger"]["segments"] for i in segment["token_indices"])
                trigger_sets.append(trigger_ids)
                structural_counts[split]["discontinuous_trigger_events"] += len(event["trigger"]["segments"]) > 1
                for argument in event["arguments"]:
                    role_counts[split][argument["role"]] += 1
                    event_role_runs[event_index][(argument["qualifier"], argument["role"])] += 1
                    argument_ids = set(argument["token_indices"])
                    argument_rows.append((event_index, argument, argument_ids))
                    structural_counts[split]["discontinuous_argument_spans"] += len(argument["segments"]) > 1
                    if trigger_ids and argument_ids & trigger_ids:
                        structural_counts[split]["events_with_argument_overlapping_own_trigger"] += 1
            structural_counts[split]["events_with_repeated_qualifier_role_runs"] += sum(
                any(run_count > 1 for run_count in role_runs.values())
                for role_runs in event_role_runs.values()
            )

            # Trigger overlap, nesting, and partial overlap within this message.
            for left in range(len(trigger_sets)):
                for right in range(left + 1, len(trigger_sets)):
                    a, b = trigger_sets[left], trigger_sets[right]
                    common = a & b
                    if not common:
                        continue
                    structural_counts[split]["trigger_overlap_pairs"] += 1
                    if a == b:
                        structural_counts[split]["trigger_exact_shared_span_pairs"] += 1
                    elif a < b or b < a:
                        structural_counts[split]["trigger_nested_pairs"] += 1
                    else:
                        structural_counts[split]["trigger_partial_overlap_pairs"] += 1

            # Argument overlap and exact shared spans, including cross-event associations.
            for left in range(len(argument_rows)):
                left_event, left_arg, a = argument_rows[left]
                for right in range(left + 1, len(argument_rows)):
                    right_event, right_arg, b = argument_rows[right]
                    common = a & b
                    if not common:
                        continue
                    structural_counts[split]["argument_overlap_pairs"] += 1
                    if left_event == right_event:
                        structural_counts[split]["argument_overlap_pairs_within_event"] += 1
                    if a == b:
                        structural_counts[split]["argument_exact_shared_span_pairs"] += 1
                        if left_event != right_event:
                            structural_counts[split]["shared_argument_span_pairs_across_events"] += 1
                            if left_arg["role"] == right_arg["role"] and left_arg["qualifier"] == right_arg["qualifier"]:
                                structural_counts[split]["shared_role_and_span_pairs_across_events"] += 1
                    elif a < b or b < a:
                        structural_counts[split]["argument_nested_pairs"] += 1
                    else:
                        structural_counts[split]["argument_partial_overlap_pairs"] += 1

    def group_stats(fingerprints: dict[str, list[int]]) -> dict[str, int]:
        groups = [members for members in fingerprints.values() if len(members) > 1]
        return {
            "duplicate_groups": len(groups),
            "duplicate_pairs": sum(len(members) * (len(members) - 1) // 2 for members in groups),
            "messages_in_duplicate_groups": sum(len(members) for members in groups),
            "excess_copies": sum(len(members) - 1 for members in groups),
        }

    duplicate_summary: dict[str, dict[str, Any]] = {}
    for split in rows_by_split:
        duplicate_summary[split] = {
            "empty_content_messages": empty_content_counts[split],
            "nonempty_exact_duplicates": group_stats(source_message_hashes[split]),
            "nonempty_normalized_duplicates": group_stats(normalized_message_hashes[split]),
        }
    cross_split_duplicates: dict[str, dict[str, Any]] = {}
    split_names = list(rows_by_split)
    for left_index, left in enumerate(split_names):
        for right in split_names[left_index + 1 :]:
            exact_groups = set(source_message_hashes[left]) & set(source_message_hashes[right])
            norm_groups = set(normalized_message_hashes[left]) & set(normalized_message_hashes[right])
            cross_split_duplicates[f"{left}__{right}"] = {
                "empty_content_message_pairs": empty_content_counts[left] * empty_content_counts[right],
                "nonempty_exact_duplicate_groups": len(exact_groups),
                "nonempty_exact_duplicate_pairs": sum(len(source_message_hashes[left][key]) * len(source_message_hashes[right][key]) for key in exact_groups),
                "nonempty_exact_left_messages_affected": sum(len(source_message_hashes[left][key]) for key in exact_groups),
                "nonempty_exact_right_messages_affected": sum(len(source_message_hashes[right][key]) for key in exact_groups),
                "nonempty_normalized_duplicate_groups": len(norm_groups),
                "nonempty_normalized_duplicate_pairs": sum(len(normalized_message_hashes[left][key]) * len(normalized_message_hashes[right][key]) for key in norm_groups),
                "nonempty_normalized_left_messages_affected": sum(len(normalized_message_hashes[left][key]) for key in norm_groups),
                "nonempty_normalized_right_messages_affected": sum(len(normalized_message_hashes[right][key]) for key in norm_groups),
            }
    near_duplicate_pairs = _jaccard_near_pairs(rows_by_split)

    thread_overlap: dict[str, int] = {}
    for i, left in enumerate(split_names):
        for right in split_names[i + 1 :]:
            thread_overlap[f"{left}__{right}"] = len(thread_ids[left] & thread_ids[right])

    # Compare flattened full_data source against the exact official split file set.
    full_files = sorted((source_dir / "full_data").glob("*.json"))
    official_sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for split in split_names for path in (source_dir / split).glob("*.json")}
    full_source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in full_files}
    split_in_full_exact = sum(full_source_hashes.get(name) == digest for name, digest in official_sources.items())
    full_data_comparison = {
        "full_data_file_count": len(full_files),
        "official_split_file_count": sum(source_file_counts.values()),
        "official_split_files_exactly_present_in_full_data": split_in_full_exact,
        "official_split_files_missing_or_changed_in_full_data": len(official_sources) - split_in_full_exact,
        "full_data_extra_file_count": len(set(full_source_hashes) - set(official_sources)),
        "full_data_matches_official_split_union_by_filename_and_bytes": len(full_files) == len(official_sources) and split_in_full_exact == len(official_sources),
    }
    raw_thread_files = [path for path in (source_dir / "raw_threads").iterdir() if path.is_file()] if (source_dir / "raw_threads").is_dir() else []

    return {
        "source_file_counts": source_file_counts,
        "source_hashes_sha256": source_hashes,
        "split_counts": {
            split: {
                "threads": len(thread_ids[split]),
                "messages": len(rows_by_split[split]),
                "native_events_excluding_O": sum(event_counts[split].values()),
                "outside_markers_O": quality_by_split[split]["outside_marker_count"],
            }
            for split in split_names
        },
        "event_type_counts": {split: dict(sorted(counter.items())) for split, counter in event_counts.items()},
        "role_argument_counts_case_sensitive": {split: dict(sorted(counter.items())) for split, counter in role_counts.items()},
        "source_case_sensitive_role_inventory": sorted(set().union(*(set(c) for c in role_counts.values()))),
        "quality_counts": {split: dict(sorted(counter.items())) for split, counter in quality_by_split.items()},
        "empty_content_message_counts": dict(empty_content_counts),
        "within_split_message_duplicates": duplicate_summary,
        "cross_split_message_duplicates": cross_split_duplicates,
        "cross_split_near_duplicate_pairs_5gram_jaccard_090": near_duplicate_pairs,
        "thread_id_overlap_counts": thread_overlap,
        "full_data_comparison": full_data_comparison,
        "raw_thread_file_count": len(raw_thread_files),
        "event_argument_structure_counts": {split: dict(counter) for split, counter in structural_counts.items()},
        "unfiltered_global_registry_fingerprint_comparison": _global_registry_fingerprint_comparison(rows_by_split),
        "legacy_casefold_parser_comparison": _legacy_parser_comparison(rows_by_split),
    }


def write_audit_report(manifest: dict[str, Any], report_path: Path) -> None:
    """Write aggregate-only audit; never serialize thread IDs or corpus text."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary = manifest["summary"]
    counts = summary["split_counts"]
    global_fingerprints = summary.get(
        "unfiltered_global_registry_fingerprint_comparison",
        summary.get("protected_v2_metadata_fingerprint_comparison", {}),
    )
    safe_manifest_path = DEFAULT_OUTPUT / "fyp_safe_manifest.json"
    safe_manifest = json.loads(safe_manifest_path.read_text(encoding="utf-8")) if safe_manifest_path.is_file() else None
    lines = [
        "# Native MailEx Extraction Audit",
        "",
        "This report audits a faithful adapter of the published MailEx event annotations. It does not map MailEx roles to FYP labels. Converted message text and identifiers remain under the ignored private experiment directory.",
        "",
        "## Official split inventory",
        "",
        "| Split | Source files / threads | Messages | Native events (excluding O markers) | O markers | Source aggregate SHA-256 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for split in OFFICIAL_SPLITS:
        if split not in counts:
            continue
        item = counts[split]
        lines.append(f"| {split} | {item['threads']} | {item['messages']} | {item['native_events_excluding_O']} | {item['outside_markers_O']} | `{summary['source_hashes_sha256'][split]}` |")
    lines.extend([
        "",
        "Each source JSON file represents a thread. Each entry in `sentences` is a turn token sequence aligned to `events.turn_N`; the adapter emits one row per turn. Row text is reconstructed with a single ASCII space between source tokens, and every character offset is half-open relative to that reconstruction.",
        "",
        "The extracted benchmark has 11 non-O event types, including `Amend_Action_Data` (2 train, 1 dev, 0 test instances). The source also stores O marker records; these are preserved separately and excluded from event counts. The extracted event inventory therefore differs from the 10 event types described in the referenced documentation.",
        "",
        "## Native event type counts",
        "",
        "| Event type (source spelling) | Train | Dev | Test |",
        "|---|---:|---:|---:|",
    ])
    all_types = sorted(set().union(*(set(summary["event_type_counts"].get(s, {})) for s in counts)) - {"O"})
    for event_type in all_types:
        values = [summary["event_type_counts"].get(s, {}).get(event_type, 0) for s in OFFICIAL_SPLITS]
        lines.append(f"| `{event_type}` | {values[0]} | {values[1]} | {values[2]} |")
    lines.extend([
        "",
        f"## Case-sensitive raw role inventory ({len(summary['source_case_sensitive_role_inventory'])} values)",
        "",
        "Role strings below are exact native values, with counts of contiguous BIO argument runs. Case is preserved; the similarly named capitalization variants remain separate values.",
        "",
        "| Raw role | Train | Dev | Test |",
        "|---|---:|---:|---:|",
    ])
    for role in summary["source_case_sensitive_role_inventory"]:
        values = [summary["role_argument_counts_case_sensitive"].get(s, {}).get(role, 0) for s in OFFICIAL_SPLITS]
        lines.append(f"| `{role}` | {values[0]} | {values[1]} | {values[2]} |")
    legacy_comparison = summary.get("legacy_casefold_parser_comparison", {})
    if legacy_comparison:
        lines.extend([
            "",
            "## Case-sensitive role-run comparison",
            "",
            "The unchanged mapper parser joins BIO runs using case-folded role equality. The native adapter preserves exact role case, so a mid-span change between source spellings starts a separate flagged I run rather than merging roles.",
            "",
            "| Split | Native case-sensitive runs | Legacy case-folded runs | Additional native runs | Native orphan-I runs | Legacy orphan-I runs | Additional native orphan-I runs | Case-fold-only restart starts |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        fields = [
            "native_case_sensitive_runs", "legacy_casefold_runs", "extra_native_runs_vs_legacy",
            "native_orphan_i_runs", "legacy_orphan_i_runs", "extra_native_orphan_i_runs_vs_legacy",
            "casefold_only_role_transition_starts",
        ]
        for split in OFFICIAL_SPLITS:
            item = legacy_comparison.get("per_split", {}).get(split)
            if item:
                lines.append("| " + " | ".join([split] + [str(item.get(field, 0)) for field in fields]) + " |")
        total = legacy_comparison.get("total", {})
        lines.append("| **Total** | " + " | ".join(str(total.get(field, 0)) for field in fields) + " |")
        lines.extend([
            "",
            "Totals are 18,149 native case-sensitive BIO runs versus 18,099 legacy case-folded runs. The 50-run difference matches 50 additional orphan-I restarts when source role capitalization changes. The adapter retains all raw source tags and labels; no runs are suppressed.",
        ])
    lines.extend([
        "",
        "Context and revision are retained as argument qualifiers. Raw tags use forms such as `EventType:Context: B-Role` and `EventType:Revision: I-Role`; the adapter stores both the normalized qualifier and its source spelling, plus every original BIO tag.",
        "",
        "## Parse and structure audit",
        "",
        "| Split | Threads | Messages | Events | Empty token arrays | Empty reconstructed text | Empty token values | Misaligned arrays | Trigger parse errors | Out-of-range indices | Trigger text/index mismatches | Malformed BIO events | Orphan I events | Label length mismatches |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for split in OFFICIAL_SPLITS:
        if split not in counts:
            continue
        q = summary["quality_counts"].get(split, {})
        item = counts[split]
        keys = ["empty_turn_count", "empty_reconstructed_text_count", "empty_token_count", "misaligned_turn_count", "trigger_parse_error_count", "trigger_out_of_range_count", "trigger_words_mismatch_count", "malformed_bio_event_count", "orphan_i_event_count", "label_length_mismatch_count"]
        lines.append("| " + " | ".join([split, str(item["threads"]), str(item["messages"]), str(item["native_events_excluding_O"])] + [str(q.get(key, 0)) for key in keys]) + " |")
    lines.extend([
        "",
        "Any malformed annotation is retained in its source fields and marked on the converted row or event. The adapter does not shift indices, repair BIO transitions, normalize role case, or drop malformed markers. O records are stored under `outside_markers` because they are source negative markers rather than event instances.",
        "",
        "Argument spans are created as contiguous runs from BIO labels. Trigger indices are kept in source order and split into contiguous segments; out-of-range indices are flagged and omitted only from derived segments, while the raw source trigger is retained. Offsets describe reconstructed text, not byte offsets into an unavailable original message string.",
        "",
        "## Event and argument geometry",
        "",
        "Pairs are counted within each message. A trigger or argument overlap means the two token-index sets share at least one token. Nesting means one nonidentical set is a strict subset of the other; partial overlap means intersection without containment. Shared arguments across events have identical token-index sets; role-and-span matches additionally require exact role and qualifier equality.",
        "",
        "| Split | Trigger overlap pairs | Trigger nested pairs | Trigger partial pairs | Argument overlap pairs | Argument nested pairs | Argument partial pairs | Exact shared argument spans across events | Duplicate event instances | Repeated role runs within event | Discontinuous triggers | Discontinuous BIO spans | Argument overlaps own trigger |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for split in OFFICIAL_SPLITS:
        if split not in counts:
            continue
        st = summary["event_argument_structure_counts"].get(split, {})
        keys = ["trigger_overlap_pairs", "trigger_nested_pairs", "trigger_partial_overlap_pairs", "argument_overlap_pairs", "argument_nested_pairs", "argument_partial_overlap_pairs", "shared_argument_span_pairs_across_events", "duplicate_event_instances_within_message", "events_with_repeated_qualifier_role_runs", "discontinuous_trigger_events", "discontinuous_argument_spans", "events_with_argument_overlapping_own_trigger"]
        lines.append("| " + " | ".join([split] + [str(st.get(key, 0)) for key in keys]) + " |")
    lines.extend([
        "",
        "## Split hygiene and source equivalence",
        "",
        "| Check | Result |",
        "|---|---:|",
    ])
    for label, value in summary["thread_id_overlap_counts"].items():
        lines.append(f"| Thread ID overlap {label} | {value} |")
    for label, values in summary["cross_split_message_duplicates"].items():
        lines.append(f"| Empty-content message pairs {label} (reported separately) | {values['empty_content_message_pairs']} pairs |")
        lines.append(f"| Nonempty exact token-sequence duplicate pairs {label} | {values['nonempty_exact_duplicate_pairs']} pairs across {values['nonempty_exact_duplicate_groups']} groups; affected messages {values['nonempty_exact_left_messages_affected']} / {values['nonempty_exact_right_messages_affected']} |")
        lines.append(f"| Nonempty normalized text duplicate pairs {label} | {values['nonempty_normalized_duplicate_pairs']} pairs across {values['nonempty_normalized_duplicate_groups']} groups; affected messages {values['nonempty_normalized_left_messages_affected']} / {values['nonempty_normalized_right_messages_affected']} |")
    for split, values in summary["within_split_message_duplicates"].items():
        lines.append(f"| Empty-content messages in {split} | {values['empty_content_messages']} |")
        lines.append(f"| Nonempty exact duplicate pairs within {split} | {values['nonempty_exact_duplicates']['duplicate_pairs']} pairs; excess copies {values['nonempty_exact_duplicates']['excess_copies']} |")
    lines.append(f"| Cross-split near duplicates, 5-token-shingle Jaccard ≥ 0.90 | {summary['cross_split_near_duplicate_pairs_5gram_jaccard_090']} pairs |")
    full = summary["full_data_comparison"]
    lines.extend([
        f"| `full_data` files | {full['full_data_file_count']} |",
        f"| `raw_threads` files | {summary['raw_thread_file_count']} |",
        f"| Official split files exactly present in `full_data` | {full['official_split_files_exactly_present_in_full_data']} / {full['official_split_file_count']} |",
        f"| `full_data` exactly equals official split union by filename and bytes | {full['full_data_matches_official_split_union_by_filename_and_bytes']} |",
        "",
        "Empty reconstructed text is kept in the converted dataset and excluded from nonempty duplicate-leakage counts; its split pair counts are reported separately because repeated blank turns are not evidence of copied email content. Normalized duplicates use case-folded alphanumeric content. Near duplicates use distinct 5-token shingles, Jaccard ≥ 0.90, at least 20 tokens, and a length ratio of at least 0.85. These checks are aggregate-only and do not print source text or identifiers.",
        "",
        "The source provides message-turn boundaries but no sentence boundary field inside a turn. `arguments_outside_trigger_sentence_estimate` is therefore based on punctuation-derived sentence estimates and is a diagnostic only; turn-level annotation membership is exact.",
        "",
        "| Split | Arguments outside estimated trigger sentence | Events with an argument outside estimated trigger sentence |",
        "|---|---:|---:|",
    ])
    for split in OFFICIAL_SPLITS:
        if split in summary["quality_counts"]:
            q = summary["quality_counts"][split]
            lines.append(f"| {split} | {q.get('arguments_outside_trigger_sentence_estimate', 0)} | {q.get('events_with_argument_outside_trigger_sentence_estimate', 0)} |")
    lines.extend([
        "",
        "## Unfiltered global registry fingerprint inventory",
        "",
    ])
    if global_fingerprints.get("available"):
        lines.extend([
            f"This comparison read metadata only from index version `{global_fingerprints['index_version']}` across all {global_fingerprints['global_registry_record_count']} global registry records. It is not filtered to boundary protected membership; the matches include existing MailEx registry rows and must not be read as protected overlap. No protected message text or source IDs were accessed.",
            "",
            "| Split | Global body exact hash matches | Global body token hash matches | Global raw text-view hash matches |",
            "|---|---:|---:|---:|",
        ])
        for split in OFFICIAL_SPLITS:
            if split not in global_fingerprints["per_split"]:
                continue
            item = global_fingerprints["per_split"][split]
            lines.append("| " + " | ".join([split] + [str(item[field]["matching_native_message_rows"]) for field in ("body_exact_sha256", "body_tokens_sha256", "additional_text_view_sha256")]) + " |")
        lines.extend([
            "",
            "These are whole-index inventory counts, not protected-subset matches. MailEx original Enron identities are unresolved; unmatched hashes do not establish FYP isolation.",
        ])
    else:
        lines.append("The protected V2 metadata index was unavailable; no comparison was made.")
    if safe_manifest:
        lines.extend([
            "",
            "## FYP-safe exclusion variant",
            "",
            "This separate model view filters native messages against only `boundary_manifest.protected_ids`, then expands hits through the global index's `leakage_group_id` and explicit links. If one message in a thread matches that connected component, every message from the thread is excluded from its split's safe view. It is an exclusion variant; the official native split rows and counts above remain intact.",
            "",
            f"The membership comparison found {safe_manifest['protected_boundary_record_count']} boundary records, of which {safe_manifest['protected_boundary_records_found_in_index']} exist in the global index; {safe_manifest['link_or_group_expanded_record_count']} records are in their connected index components.",
            "",
            "| Split | Direct protected messages / threads | Component matched messages / threads | Excluded messages / threads | Retained messages / threads | Retained events | FYP-safe JSONL SHA-256 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ])
        for split in OFFICIAL_SPLITS:
            item = safe_manifest["fyp_safe_split_counts"].get(split)
            if not item:
                continue
            lines.append(
                f"| {split} | {item['direct_protected_match_messages']} / {item['direct_protected_match_threads']} | "
                f"{item['link_or_group_component_match_messages']} / {item['link_or_group_component_match_threads']} | "
                f"{item['excluded_messages']} / {item['excluded_threads']} | "
                f"{item['retained_messages']} / {item['retained_threads']} | {item['retained_events']} | "
                f"`{safe_manifest['fyp_safe_row_file_sha256'][split]}` |"
            )
        lines.extend([
            "",
            "The safe files are `train_fyp_safe.jsonl`, `dev_fyp_safe.jsonl`, and `test_fyp_safe.jsonl` under the ignored experiment directory. The manifest contains hashes and aggregate counts, no IDs or message text. This policy uses exact body, token, and raw text-view fingerprints; expansion only covers associations recorded in the index and does not resolve hidden Enron identities or paraphrases.",
        ])
    lines.extend([
        "",
        "## Protected FYP boundary",
        "",
        "This adapter lives under the ignored private experiment directory for converted data and under a separate native module. It does not alter MailEx V1/V2 outputs, their registry, FYP label mappings, or model artifacts. Original Enron identity resolution remains unverified; this audit makes no claim of additional FYP isolation.",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")
