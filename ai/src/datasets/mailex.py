"""Convert the published MailEx thread annotations to canonical email JSONL.

MailEx stores one JSON file per thread. Each turn is a token list in
sentences; event annotations are grouped under events.turn_N and hold one BIO
tag sequence per trigger. The parser preserves source annotations and only
emits canonical spans for close semantic matches.
"""

from __future__ import annotations

import ast
from collections import Counter
from difflib import SequenceMatcher
from email.utils import getaddresses
import json
import re
from pathlib import Path
from typing import Any

from .schemas import empty_record, write_jsonl


DEFAULT_AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FULL_DATA = DEFAULT_AI_ROOT / "data" / "raw" / "mailex" / "extracted" / "data" / "full_data"
DEFAULT_RAW_THREADS = DEFAULT_AI_ROOT / "data" / "raw" / "mailex" / "extracted" / "data" / "raw_threads"
DEFAULT_MAPPING = DEFAULT_AI_ROOT / "annotation" / "mailex_mapping.json"
METADATA_ALIGNMENT_THRESHOLD = 0.75
HEADER_RE = re.compile(r"^\s*(FROM|TO|CC|SUBJECT|DATE):\s*(.*)$", re.IGNORECASE)
THREAD_SEPARATOR_RE = re.compile(r"(?m)^\s*-{10,}\s*$")
WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
BIO_RE = re.compile(r"^([BI])-(.+)$")



def _report_path(path: Path) -> str:
    """Use repository-relative paths in saved reports when possible."""
    try:
        return path.resolve().relative_to(DEFAULT_AI_ROOT.parent.resolve()).as_posix()
    except ValueError:
        return str(path)
def _flatten_tokens(value: Any, *, warnings: list[str]) -> list[str]:
    """Flatten the source token list, retaining empty string tokens."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_tokens(item, warnings=warnings))
        return flattened
    warnings.append(f"unsupported token value type: {type(value).__name__}")
    return []


def _parse_header_block(block: str) -> dict[str, Any]:
    """Read the simple headers in MailEx raw_threads, not RFC822 messages."""
    lines = block.splitlines()
    collected: dict[str, list[str]] = {}
    header_end = 0
    current_key: str | None = None
    started = False

    for index, line in enumerate(lines):
        match = HEADER_RE.match(line)
        if match:
            started = True
            current_key = match.group(1).casefold()
            collected.setdefault(current_key, []).append(match.group(2).strip())
            header_end = index + 1
            continue
        if started and not line.strip():
            current_key = None
            header_end = index + 1
            continue
        if started and current_key and line[:1].isspace():
            collected[current_key][-1] += " " + line.strip()
            header_end = index + 1
            continue
        break

    headers = {key: " ".join(values).strip() for key, values in collected.items()}
    body = "\n".join(lines[header_end:]).strip()
    return {"headers": headers, "body": body, "raw_block": block}


def _read_raw_thread(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="replace")
    blocks = [part.strip() for part in THREAD_SEPARATOR_RE.split(content) if part.strip()]
    return [_parse_header_block(block) for block in blocks]


def _compact_text(text: str) -> str:
    return "".join(WORD_RE.findall(text.casefold()))


def _alignment_score(source_text: str, raw_body: str) -> float:
    source_compact = _compact_text(source_text)
    raw_compact = _compact_text(raw_body)
    if not source_compact and not raw_compact:
        return 1.0
    if not source_compact or not raw_compact:
        return 0.0
    return SequenceMatcher(None, source_compact, raw_compact, autojunk=False).ratio()


def _split_addresses(value: str) -> list[str]:
    if not value.strip():
        return []
    parsed = getaddresses([value])
    values = [address.strip() or name.strip() for name, address in parsed]
    return [item for item in values if item]


def _safe_raw_headers(
    thread_id: str,
    tokens_by_turn: list[list[str]],
    raw_threads_dir: Path | None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return raw headers only when turn alignment is credible."""
    empty_headers = [{} for _ in tokens_by_turn]
    status: dict[str, Any] = {
        "available": False,
        "aligned": False,
        "reason": "raw_threads directory not supplied",
        "alignment_threshold": METADATA_ALIGNMENT_THRESHOLD,
    }
    if raw_threads_dir is None:
        return empty_headers, status

    raw_path = raw_threads_dir / thread_id
    if not raw_path.is_file():
        status["reason"] = "raw thread file missing"
        return empty_headers, status

    blocks = _read_raw_thread(raw_path)
    status.update({"available": True, "raw_thread_file": raw_path.name, "raw_block_count": len(blocks)})
    if len(blocks) != len(tokens_by_turn):
        status["reason"] = "raw block count does not match annotated turn count"
        return empty_headers, status

    oldest_first = list(reversed(blocks))
    scores = [
        _alignment_score(" ".join(tokens), block["body"])
        for tokens, block in zip(tokens_by_turn, oldest_first)
    ]
    status["minimum_body_alignment"] = min(scores, default=1.0)
    if any(score < METADATA_ALIGNMENT_THRESHOLD for score in scores):
        status["reason"] = "one or more raw message bodies did not align to the annotated turn"
        return empty_headers, status

    status.update({"aligned": True, "reason": "turn count and normalized body text align"})
    return [block["headers"] for block in oldest_first], status


def _parse_trigger(trigger_value: Any) -> dict[str, Any]:
    if isinstance(trigger_value, dict):
        parsed = trigger_value
    elif isinstance(trigger_value, str) and trigger_value.strip():
        try:
            parsed = ast.literal_eval(trigger_value)
        except (SyntaxError, ValueError):
            return {"raw": trigger_value, "text": "", "token_indices": [], "parse_error": True}
    else:
        return {"raw": trigger_value if isinstance(trigger_value, str) else "", "text": "", "token_indices": []}

    if not isinstance(parsed, dict):
        return {"raw": str(trigger_value), "text": "", "token_indices": [], "parse_error": True}
    raw_indices = parsed.get("indices", "")
    if isinstance(raw_indices, list):
        indices = [int(index) for index in raw_indices if str(index).isdigit()]
    else:
        indices = [int(item) for item in str(raw_indices).split() if item.isdigit()]
    return {
        "raw": trigger_value if isinstance(trigger_value, str) else "",
        "text": str(parsed.get("words", "")),
        "token_indices": indices,
    }


def _parse_bio_tag(event_type: str, tag: Any) -> tuple[str, str | None, str] | None:
    if not isinstance(tag, str) or tag == "O":
        return None
    prefix = event_type + ":"
    content = tag[len(prefix):] if tag.startswith(prefix) else tag
    qualifier: str | None = None
    for marker, normalized in (
        ("Context:", "context"),
        ("Revision:", "revision"),
        ("CNT:", "context"),
        ("REV:", "revision"),
    ):
        if content.startswith(marker):
            content = content[len(marker):].strip()
            qualifier = normalized
            break
    match = BIO_RE.match(content.strip())
    if not match:
        return None
    bio_prefix, role = match.groups()
    role = role.strip()
    for marker, normalized in (("CNT:", "context"), ("REV:", "revision")):
        if role.startswith(marker):
            role = role[len(marker):].strip()
            qualifier = normalized
            break
    return bio_prefix, qualifier, role


def _is_bare_pronoun_participant(text: str) -> bool:
    """Reject generic pronouns as stable participant entities."""
    normalized = " ".join(WORD_RE.findall(text.casefold()))
    return normalized in {
        "i", "me", "myself", "we", "us", "our", "ourselves",
        "you", "yourself", "yourselves", "you guys", "you all",
        "you people", "he", "him", "himself", "she", "her", "herself",
        "they", "them", "themselves", "it", "all of us", "both of us",
    }


def _role_rule(mapping: dict[str, Any], event_type: str, source_role: str) -> dict[str, Any]:
    role_config = mapping.get("argument_role_mappings", {}).get(source_role.casefold())
    if not isinstance(role_config, dict):
        return {
            "status": "unmapped",
            "reason": "No FYP extraction label has a direct equivalent for this source role.",
        }
    event_rule = role_config.get("by_event_type", {}).get(event_type)
    if isinstance(event_rule, dict):
        return event_rule
    default = role_config.get("default")
    if isinstance(default, dict):
        return default
    return {
        "status": "unmapped",
        "reason": "This source role has no mapping for this event type.",
    }


def _token_offsets(tokens: list[str]) -> list[tuple[int, int]]:
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for token in tokens:
        start = cursor
        end = start + len(token)
        offsets.append((start, end))
        cursor = end + 1
    return offsets


def _extract_argument_segments(
    event_type: str,
    labels: Any,
    tokens: list[str],
    offsets: list[tuple[int, int]],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not isinstance(labels, list) or len(labels) != len(tokens):
        actual = len(labels) if isinstance(labels, list) else "not a list"
        return [], [f"BIO sequence length does not match token count ({actual} vs {len(tokens)})"]

    segments: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal active
        if active is None:
            return
        token_start = active["token_start"]
        token_end = active["token_end"]
        char_start = offsets[token_start][0]
        char_end = offsets[token_end - 1][1]
        segments.append({
            "source_role": active["source_role"],
            "qualifier": active["qualifier"],
            "token_start": token_start,
            "token_end": token_end,
            "start": char_start,
            "end": char_end,
            "malformed_bio_start": active["malformed_bio_start"],
        })
        active = None

    for token_index, tag in enumerate(labels):
        parsed = _parse_bio_tag(event_type, tag)
        if parsed is None:
            if tag != "O":
                warnings.append(f"unrecognized BIO tag at token {token_index}: {tag!r}")
            flush()
            continue
        bio_prefix, qualifier, role = parsed
        is_same = (
            active is not None
            and active["source_role"].casefold() == role.casefold()
            and active["qualifier"] == qualifier
        )
        if bio_prefix == "B" or not is_same:
            if bio_prefix == "I" and not is_same:
                warnings.append(f"I tag without matching preceding role at token {token_index}")
            flush()
            active = {
                "source_role": role,
                "qualifier": qualifier,
                "token_start": token_index,
                "token_end": token_index + 1,
                "malformed_bio_start": bio_prefix == "I" and not is_same,
            }
        else:
            active["token_end"] = token_index + 1
    flush()
    return segments, warnings


def _read_split_names(data_root: Path) -> dict[str, str]:
    split_names: dict[str, str] = {}
    for split in ("train", "dev", "test"):
        split_dir = data_root.parent / split
        if split_dir.is_dir():
            for path in split_dir.glob("*.json"):
                split_names[path.stem] = split
    return split_names


def _event_annotations(
    event_map: Any,
    tokens: list[str],
    current_message: str,
    offsets: list[tuple[int, int]],
    mapping: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    source_events: list[dict[str, Any]] = []
    canonical_spans: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not isinstance(event_map, dict):
        return source_events, canonical_spans, ["turn event annotation is not an object"]

    has_non_o_events = any(
        event_type != "O"
        and isinstance(annotation, dict)
        and isinstance(annotation.get("triggers", []), list)
        and len(annotation.get("triggers", [])) > 0
        for event_type, annotation in event_map.items()
    )
    for event_type, annotation in event_map.items():
        if event_type == "O":
            stats["non_event_marker_turns"] += 1
            stats["source_o_marker_turns"] += 1
            if has_non_o_events:
                stats["source_o_with_event_turns"] += 1
            else:
                stats["source_o_only_turns"] += 1
            continue
        if not isinstance(annotation, dict):
            warnings.append(f"event annotation for {event_type} is not an object")
            continue

        triggers = annotation.get("triggers", [])
        label_sets = annotation.get("labels", [])
        extras = annotation.get("extras", [])
        if not isinstance(triggers, list):
            warnings.append(f"{event_type}.triggers is not a list")
            triggers = []
        if not isinstance(label_sets, list):
            warnings.append(f"{event_type}.labels is not a list")
            label_sets = []
        if not isinstance(extras, list):
            warnings.append(f"{event_type}.extras is not a list")
            extras = []
        if len(label_sets) != len(triggers):
            warnings.append(f"{event_type}: labels/triggers count mismatch ({len(label_sets)} vs {len(triggers)})")
        if len(extras) != len(triggers):
            warnings.append(f"{event_type}: extras/triggers count mismatch ({len(extras)} vs {len(triggers)})")

        stats["events_by_type"][event_type] += len(triggers)
        max_instances = max(len(triggers), len(label_sets), len(extras))
        for event_index in range(max_instances):
            trigger = _parse_trigger(triggers[event_index]) if event_index < len(triggers) else {
                "raw": "", "text": "", "token_indices": [], "parse_error": True,
            }
            if trigger.get("parse_error"):
                warnings.append(f"{event_type}[{event_index}]: trigger string could not be parsed")
            label_tags = label_sets[event_index] if event_index < len(label_sets) else []
            raw_extra = extras[event_index] if event_index < len(extras) else ""
            event_id = f"{event_type}:{event_index}"
            source_event = {
                "event_id": event_id,
                "event_type": event_type,
                "trigger_text": trigger["text"],
                "trigger_token_indices": trigger["token_indices"],
                "trigger_raw": trigger["raw"],
                "meta_semantic_roles": raw_extra,
                "arguments": [],
            }
            segments, segment_warnings = _extract_argument_segments(
                event_type, label_tags, tokens, offsets
            )
            warnings.extend(f"{event_type}[{event_index}]: {warning}" for warning in segment_warnings)
            has_direct_mapping = False

            for segment in segments:
                start, end = segment["start"], segment["end"]
                text = current_message[start:end]
                rule = _role_rule(mapping, event_type, segment["source_role"])
                status = str(rule.get("status", "unmapped"))
                if status not in {"direct", "ambiguous", "unmapped"}:
                    status = "unmapped"
                    rule = {"status": status, "reason": f"Unknown mapping status {rule.get('status')!r}."}
                if not text:
                    status = "unmapped"
                    rule = {"status": status, "reason": "Source BIO span contains no text."}
                if segment.get("malformed_bio_start"):
                    candidate_label = rule.get("canonical_label", rule.get("candidate_label"))
                    status = "unmapped"
                    rule = {
                        "status": status,
                        "candidate_label": candidate_label,
                        "reason": "Source BIO argument begins with I without a matching B; retained as source-only annotation.",
                    }
                    stats["malformed_bio_argument_spans"] += 1
                if (
                    status == "direct"
                    and rule.get("canonical_label") == "PARTICIPANT"
                    and _is_bare_pronoun_participant(text)
                ):
                    candidate_label = rule.get("canonical_label")
                    status = "unmapped"
                    rule = {
                        "status": status,
                        "candidate_label": candidate_label,
                        "reason": "Bare pronoun or generic pronoun phrase is not a stable participant entity; retained as source-only annotation.",
                    }
                    stats["bare_pronoun_participant_spans"] += 1

                source_argument = {
                    **segment,
                    "text": text,
                    "mapping_status": status,
                    "candidate_label": rule.get("canonical_label", rule.get("candidate_label")),
                    "mapping_reason": rule.get("reason", ""),
                }
                source_event["arguments"].append(source_argument)
                stats["source_argument_spans"] += 1
                stats["source_argument_roles"][segment["source_role"]] += 1
                if status == "direct":
                    canonical_label = rule.get("canonical_label")
                    if not canonical_label:
                        warnings.append(f"{event_type}[{event_index}]: direct rule has no canonical_label")
                        source_argument["mapping_status"] = "unmapped"
                        source_argument["mapping_reason"] = "Direct mapping rule is missing canonical_label."
                        stats["unmapped_argument_spans"] += 1
                        continue
                    has_direct_mapping = True
                    stats["mapped_argument_spans"] += 1
                    stats["extraction_label_counts"][canonical_label] += 1
                    canonical_spans.append({
                        "label": canonical_label,
                        "text": text,
                        "start": start,
                        "end": end,
                        "field": "current_message",
                        "source_event_type": event_type,
                        "source_event_index": event_index,
                        "source_role": segment["source_role"],
                        "source_qualifier": segment["qualifier"],
                        "mapping_status": "direct",
                        "review_status": "requires_project_scope_human_review",
                    })
                elif status == "ambiguous":
                    stats["ambiguous_argument_spans"] += 1
                else:
                    stats["unmapped_argument_spans"] += 1

            event_counts = stats["events_by_mapping"].setdefault(event_type, Counter())
            event_counts["total"] += 1
            event_counts["mapped" if has_direct_mapping else "unmapped"] += 1
            source_events.append(source_event)

    return source_events, canonical_spans, warnings


def deduplicate_canonical_spans(spans: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Collapse identical training entities while retaining every source argument."""
    merged: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    duplicates = 0
    provenance_fields = (
        "source_event_type", "source_event_index", "source_role",
        "source_qualifier", "mapping_status",
    )
    for span in spans:
        key = (span.get("field", "current_message"), span["start"], span["end"], span["label"])
        provenance = {field: span.get(field) for field in provenance_fields}
        if key not in merged:
            merged[key] = {**span, "source_provenance": [provenance]}
        else:
            merged[key]["source_provenance"].append(provenance)
            duplicates += 1
    return list(merged.values()), duplicates

def _new_stats() -> dict[str, Any]:
    return {
        "threads": 0,
        "messages": 0,
        "usable_messages": 0,
        "empty_messages": 0,
        "non_event_messages": 0,
        "source_event_count": 0,
        "non_event_marker_turns": 0,
        "source_o_marker_turns": 0,
        "source_o_only_turns": 0,
        "source_o_with_event_turns": 0,
        "malformed_bio_argument_spans": 0,
        "bare_pronoun_participant_spans": 0,
        "source_argument_spans": 0,
        "mapped_argument_spans": 0,
        "duplicate_canonical_spans_before": 0,
        "duplicate_canonical_spans_after": 0,
        "ambiguous_argument_spans": 0,
        "unmapped_argument_spans": 0,
        "mapped_event_count": 0,
        "unmapped_event_count": 0,
        "events_by_type": Counter(),
        "events_by_mapping": Counter(),
        "source_argument_roles": Counter(),
        "extraction_label_counts": Counter(),
        "classification_policy": "No FYP classification labels are inferred from MailEx events.",
        "annotation_status_counts": Counter(),
        "metadata_alignment": {
            "raw_thread_files": 0,
            "threads_aligned": 0,
            "messages_with_verified_header_alignment": 0,
            "threads_missing_raw_file": 0,
            "threads_with_turn_count_mismatch": 0,
            "threads_with_low_body_alignment": 0,
            "alignment_threshold": METADATA_ALIGNMENT_THRESHOLD,
            "field_value_counts": Counter(),
        },
        "empty_examples": [],
        "malformed_examples": [],
        "source_file_errors": [],
        "_message_hashes": Counter(),
    }


def _finalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    message_hashes = stats.pop("_message_hashes")
    stats["duplicate_nonempty_message_copies"] = sum(
        count - 1 for count in message_hashes.values() if count > 1
    )
    stats["duplicate_nonempty_message_groups"] = sum(
        1 for count in message_hashes.values() if count > 1
    )
    for field in (
        "events_by_type", "source_argument_roles", "extraction_label_counts",
        "annotation_status_counts",
    ):
        stats[field] = dict(sorted(stats[field].items()))
    stats["events_by_mapping"] = {
        event_type: dict(sorted(counts.items()))
        for event_type, counts in sorted(stats["events_by_mapping"].items())
    }
    stats["mapped_event_count"] = sum(
        counts.get("mapped", 0) for counts in stats["events_by_mapping"].values()
    )
    stats["unmapped_event_count"] = sum(
        counts.get("unmapped", 0) for counts in stats["events_by_mapping"].values()
    )
    stats["source_event_count"] = sum(stats["events_by_type"].values())
    stats["paper_reported_non_event_messages"] = 776
    stats["metadata_alignment"]["field_value_counts"] = dict(
        sorted(stats["metadata_alignment"]["field_value_counts"].items())
    )
    stats["manual_inspection_samples"] = [
        "blair-l_inbox143:turn_1 (business meeting date and time)",
        "beck-s_inbox5:turn_1 (integration testing actions)",
        "bass-e_inbox100:turn_0 (social lunch example; illustrates project-scope review need)",
    ]
    stats["limitations"] = [
        "Canonical message text is reconstructed by joining MailEx tokens with spaces; original RFC822 messages are not present in the annotation JSON.",
        "Only aligned plain-text raw_threads headers can populate sender, recipients, cc, subject, or sent_at. Other metadata stays empty or null.",
        "Canonical labels stay empty and annotation status stays unlabelled; MailEx events are not FYP email classification gold.",
        "Direct spans are provisional, weak source argument proposals mapped to FYP extraction labels. They are not gold and require human review for FYP project scope; source role/event provenance remains attached.",
        "Standalone pronouns and generic pronoun phrases in Meeting Members arguments are retained as source annotations and suppressed from canonical PARTICIPANT spans.",
        "The paper/repository describe 10 event types, while the downloaded archive contains 11 observed non-O event keys including Amend_Action_Data.",
        "The archive has 776 O markers; 4 co-occur with non-O event triggers, leaving 772 O-only turns. The parser reports both counts separately.",
    ]
    return stats


def prepare_mailex(
    *,
    data_dir: Path = DEFAULT_FULL_DATA,
    output_path: Path | None = None,
    stats_path: Path | None = None,
    mapping_path: Path = DEFAULT_MAPPING,
    raw_threads_dir: Path | None = DEFAULT_RAW_THREADS,
) -> dict[str, Any]:
    """Read full_data and write unlabelled canonical JSONL plus real statistics."""
    data_dir = Path(data_dir)
    output_path = Path(output_path) if output_path else DEFAULT_AI_ROOT / "data" / "processed" / "mailex.jsonl"
    stats_path = Path(stats_path) if stats_path else DEFAULT_AI_ROOT / "reports" / "mailex_stats.json"
    mapping_path = Path(mapping_path)
    raw_threads_dir = Path(raw_threads_dir) if raw_threads_dir is not None else None

    if not data_dir.is_dir():
        raise FileNotFoundError(f"MailEx full_data directory not found: {data_dir}")
    if not mapping_path.is_file():
        raise FileNotFoundError(f"MailEx mapping file not found: {mapping_path}")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    stats = _new_stats()
    stats["dataset"] = "MailEx"
    stats["input_dir"] = _report_path(data_dir)
    stats["mapping_version"] = mapping.get("mapping_version")
    stats["metadata_alignment"]["raw_thread_files"] = (
        sum(1 for item in raw_threads_dir.iterdir() if item.is_file())
        if raw_threads_dir is not None and raw_threads_dir.is_dir() else 0
    )

    paths = sorted(data_dir.glob("*.json"))
    split_names = _read_split_names(data_dir)
    records: list[dict[str, Any]] = []
    seen_thread_ids: set[str] = set()

    for source_path in paths:
        try:
            thread_data = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            stats["source_file_errors"].append({"file": source_path.name, "error": str(exc)})
            continue
        if not isinstance(thread_data, dict) or not isinstance(thread_data.get("sentences"), list):
            stats["source_file_errors"].append({
                "file": source_path.name,
                "error": "source JSON must have a sentences list",
            })
            continue

        thread_id = source_path.stem
        if thread_id in seen_thread_ids:
            stats["source_file_errors"].append({"file": source_path.name, "error": "duplicate thread filename"})
            continue
        seen_thread_ids.add(thread_id)
        stats["threads"] += 1

        tokens_by_turn: list[list[str]] = []
        token_warnings_by_turn: list[list[str]] = []
        for sentence in thread_data["sentences"]:
            token_warnings: list[str] = []
            tokens = _flatten_tokens(sentence, warnings=token_warnings)
            tokens_by_turn.append(tokens)
            token_warnings_by_turn.append(token_warnings)

        headers_by_turn, alignment = _safe_raw_headers(thread_id, tokens_by_turn, raw_threads_dir)
        align_stats = stats["metadata_alignment"]
        if alignment.get("aligned"):
            align_stats["threads_aligned"] += 1
            align_stats["messages_with_verified_header_alignment"] += len(tokens_by_turn)
        elif alignment.get("reason") == "raw thread file missing":
            align_stats["threads_missing_raw_file"] += 1
        elif alignment.get("reason") == "raw block count does not match annotated turn count":
            align_stats["threads_with_turn_count_mismatch"] += 1
        elif alignment.get("available"):
            align_stats["threads_with_low_body_alignment"] += 1

        prior_messages: list[str] = []
        thread_events = thread_data.get("events", {})
        if not isinstance(thread_events, dict):
            thread_events = {}

        for turn_index, tokens in enumerate(tokens_by_turn):
            stats["messages"] += 1
            current_message = " ".join(tokens)
            event_map = thread_events.get(f"turn_{turn_index}", {})
            if not isinstance(event_map, dict):
                event_map = {}
            no_text = not current_message.strip()
            if no_text:
                stats["empty_messages"] += 1
                if len(stats["empty_examples"]) < 30:
                    stats["empty_examples"].append(f"{thread_id}:turn_{turn_index}")
            else:
                digest_text = " ".join(WORD_RE.findall(current_message.casefold()))
                if digest_text:
                    stats["_message_hashes"][digest_text] += 1

            email_id = f"mailex:{thread_id}:turn_{turn_index}"
            offsets = _token_offsets(tokens)
            source_events, canonical_spans, annotation_warnings = _event_annotations(
                event_map,
                tokens,
                current_message,
                offsets,
                mapping,
                stats,
            )
            canonical_spans, duplicate_count = deduplicate_canonical_spans(canonical_spans)
            stats["duplicate_canonical_spans_before"] += duplicate_count
            turn_warnings = token_warnings_by_turn[turn_index] + annotation_warnings
            has_length_error = any("BIO sequence length does not match" in item for item in turn_warnings)
            has_token_warning = any("unsupported token value type" in item for item in turn_warnings)
            if not no_text and not has_length_error and not has_token_warning:
                stats["usable_messages"] += 1
            for warning in turn_warnings:
                if len(stats["malformed_examples"]) < 50:
                    stats["malformed_examples"].append({"email_id": email_id, "warning": warning})

            headers = headers_by_turn[turn_index]
            subject = headers.get("subject", "")
            sender_values = _split_addresses(headers.get("from", ""))
            sender = sender_values[0] if sender_values else headers.get("from", "")
            recipients = _split_addresses(headers.get("to", ""))
            cc = _split_addresses(headers.get("cc", ""))
            for field, value in (
                ("subject", subject),
                ("sender", sender),
                ("recipients", recipients),
                ("cc", cc),
                ("sent_at", headers.get("date")),
            ):
                if value:
                    align_stats["field_value_counts"][field] += 1

            non_event = not source_events
            if non_event:
                stats["non_event_messages"] += 1
            record = empty_record(
                email_id=email_id,
                source_dataset="mailex",
                thread_id=thread_id,
                raw_body=current_message,
                subject=subject,
                turn_index=turn_index,
            )
            record.update({
                "current_message": current_message,
                "clean_body": current_message,
                "thread_context": "\n\n".join(prior_messages),
                "sender": sender,
                "recipients": recipients,
                "cc": cc,
                "sent_at": headers.get("date") or None,
                "attachment_names": [],
                "labels": [],
                "spans": canonical_spans,
                "annotation": {
                    "status": "unlabelled",
                    "needs_review": True,
                    "annotator": None,
                    "annotation_source": "dataset",
                    "confidence": None,
                    "mapping_version": mapping.get("mapping_version"),
                    "source_annotations": {
                        "dataset": "MailEx",
                        "source_file": source_path.name,
                        "source_split": split_names.get(thread_id),
                        "text_provenance": "space-joined MailEx sentence tokens",
                        "raw_metadata_alignment": alignment,
                        "non_event_message": non_event,
                        "warnings": turn_warnings,
                        "events": source_events,
                    },
                },
            })
            records.append(record)
            prior_messages.append(current_message)
            stats["annotation_status_counts"]["unlabelled"] += 1

    write_jsonl(output_path, records)
    stats = _finalize_stats(stats)
    stats["output_file"] = _report_path(output_path)
    stats["stats_file"] = _report_path(stats_path)
    stats["canonical_label_count"] = sum(len(record["labels"]) for record in records)
    stats["canonical_span_count"] = sum(len(record["spans"]) for record in records)
    stats["canonical_extraction_label_counts"] = dict(sorted(Counter(span["label"] for record in records for span in record["spans"]).items()))
    stats["duplicate_canonical_spans_after"] = sum(len(record["spans"]) - len({(span.get("field", "current_message"), span["start"], span["end"], span["label"]) for span in record["spans"]}) for record in records)
    stats["processed_record_count"] = len(records)
    stats["source_file_count"] = len(paths)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


__all__ = ["prepare_mailex", "DEFAULT_FULL_DATA", "DEFAULT_RAW_THREADS", "DEFAULT_MAPPING"]
