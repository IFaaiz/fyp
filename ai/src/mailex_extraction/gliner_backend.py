"""Private GLiNER2.5 backend and exact-offset MailEx adapters.

The model/runtime dependencies and checkpoints live under ``ai/data/cache``;
this module intentionally does not modify the project's shared venv or public
dependency declarations.  MailEx training uses a narrow SchemaTransformer
override because upstream GLiNER2's public InputExample format resolves labels
by matching surface strings and cannot distinguish repeated occurrences.
"""

from __future__ import annotations

import hashlib
import copy
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
AI_ROOT = REPO_ROOT / "ai"
PRIVATE_ROOT = AI_ROOT / "data" / "cache" / "mailex_gliner"
VENDOR_ROOT = PRIVATE_ROOT / "vendor"
CHECKPOINT_REVISION = "7132dc4561c3f94563c6147e75ffa8ef34c4964a"
GLINER2_SOURCE_COMMIT = "3c913c7369301133d3b7699252074c4303ada50e"
CHECKPOINT_DIR = (
    PRIVATE_ROOT
    / "checkpoints"
    / f"gliner2.5-small-v1-{CHECKPOINT_REVISION}"
)
DATA_DIR = AI_ROOT / "data" / "experiments" / "mailex_extraction_v1"
TRAIN_SHA256 = "9672bcd3c2ee4453cf8919735647616204136e0324c36cc49a399bbabee4f333"
DEV_SHA256 = "fdab07806e641b916975db4324395cde8a30b6942cf775ef38b575f39c9b677d"


@dataclass(frozen=True)
class FieldBinding:
    field_name: str
    role: str
    qualifier: str | None


@dataclass(frozen=True)
class MailExOntology:
    """Ontology derived solely from the approved TRAIN rows."""

    event_types: tuple[str, ...]
    fields_by_event: Mapping[str, tuple[FieldBinding, ...]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}: {actual}")
    return actual


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path.name}:{line_no}") from exc


def derive_ontology(train_path: Path, *, verify_fingerprint: bool = True) -> MailExOntology:
    """Build event/role/qualifier vocabulary from TRAIN, never DEV or TEST."""
    if verify_fingerprint:
        verify_sha256(train_path, TRAIN_SHA256)
    fields: dict[str, set[tuple[str, str | None]]] = defaultdict(set)
    event_types: set[str] = set()
    for row in iter_jsonl(train_path):
        for event in row.get("events", []):
            event_type = event["event_type"]
            event_types.add(event_type)
            for argument in event.get("arguments", []):
                fields[event_type].add(
                    (argument["role"], argument.get("qualifier"))
                )
    key = lambda item: (item[0].casefold(), (item[1] or "").casefold(), item[0], item[1] or "")
    sorted_events = tuple(sorted(event_types))
    fields_by_event = {
        event_type: tuple(
            FieldBinding(f"arg_{index:03d}", role, qualifier)
            for index, (role, qualifier) in enumerate(sorted(fields[event_type], key=key))
        )
        for event_type in sorted_events
    }
    return MailExOntology(sorted_events, fields_by_event)


def _gliner_imports():
    vendor = str(VENDOR_ROOT)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from gliner2 import AutoExtractor  # type: ignore[import-not-found]

    return AutoExtractor


def load_extractor(*, device: str = "cuda", checkpoint: Path = CHECKPOINT_DIR):
    checkpoint = Path(checkpoint).resolve()
    if not (checkpoint / "config.json").is_file():
        raise ValueError(f"Local GLiNER checkpoint needs config.json: {checkpoint}")
    AutoExtractor = _gliner_imports()
    import torch
    from gliner2.processor import SchemaTransformer

    torch.set_num_threads(4)
    model = AutoExtractor.from_pretrained(
        str(checkpoint), local_files_only=True
    )
    base_processor = model.processor
    processor_class = OffsetSchemaTransformer.make(SchemaTransformer)
    model.processor = processor_class(
        tokenizer=base_processor.tokenizer,
        sampling_config=base_processor.sampling_config,
        token_pooling=base_processor.token_pooling,
        word_splitter=base_processor.word_splitter,
    )
    model.to(device)
    return model


def build_schema(
    model: Any,
    ontology: MailExOntology,
    event_types: Sequence[str] | None = None,
):
    """Create one natural, trigger-anchored record group per TRAIN type."""
    selected_types = tuple(event_types or ontology.event_types)
    schema = model.create_schema()
    for event_type in selected_types:
        builder = schema.structure(
            event_type,
            mode="natural",
            anchor="trigger",
            occurrence_policy="all",
        )
        builder.field(
            "trigger",
            dtype="str",
            description="A source text segment that identifies the event trigger.",
            cardinality="required_one",
        )
        for binding in ontology.fields_by_event[event_type]:
            q = f"; qualifier {binding.qualifier}" if binding.qualifier else ""
            builder.field(
                binding.field_name,
                dtype="list",
                description=f"Source text argument for role {binding.role}{q}.",
                cardinality="zero_or_more",
            )
    return schema


def _flatten_field_value(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _span_from_model(value: Any, text: str) -> tuple[dict[str, Any], bool]:
    """Keep only model-emitted offsets; never recover them by searching text."""
    if not isinstance(value, Mapping):
        return ({"text": str(value), "start": None, "end": None,
                 "flags": ["missing_model_offsets"]}, False)
    raw = str(value.get("text", ""))
    start, end = value.get("start"), value.get("end")
    span: dict[str, Any] = {
        "text": raw,
        "start": start if isinstance(start, int) else None,
        "end": end if isinstance(end, int) else None,
    }
    grounded = (
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= len(text)
        and text[start:end] == raw
    )
    if not grounded:
        span["flags"] = ["offset_surface_mismatch"]
    if "confidence" in value:
        span["confidence"] = float(value["confidence"])
    return span, grounded


def prediction_row(
    source_row: Mapping[str, Any],
    model_output: Mapping[str, Any],
    ontology: MailExOntology,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Map model record groups to evaluator rows while retaining raw offsets."""
    text = str(source_row.get("text", ""))
    events: list[dict[str, Any]] = []
    diagnostics = {"records": 0, "grounded_trigger_segments": 0,
                  "grounded_argument_segments": 0, "ungrounded_segments": 0,
                  "events_without_grounded_trigger": 0}
    for event_type in ontology.event_types:
        for record in _flatten_field_value(model_output.get(event_type)):
            if not isinstance(record, Mapping):
                continue
            diagnostics["records"] += 1
            trigger: dict[str, list[dict[str, Any]]] = {"segments": []}
            raw_trigger = record.get("trigger")
            has_grounded_trigger = False
            for raw_span in _flatten_field_value(raw_trigger):
                span, grounded = _span_from_model(raw_span, text)
                trigger["segments"].append(span)
                if grounded:
                    has_grounded_trigger = True
                    diagnostics["grounded_trigger_segments"] += 1
                else:
                    diagnostics["ungrounded_segments"] += 1
            if not has_grounded_trigger:
                diagnostics["events_without_grounded_trigger"] += 1
            arguments: list[dict[str, Any]] = []
            for binding in ontology.fields_by_event[event_type]:
                for raw_span in _flatten_field_value(record.get(binding.field_name)):
                    span, grounded = _span_from_model(raw_span, text)
                    if grounded:
                        diagnostics["grounded_argument_segments"] += 1
                    else:
                        diagnostics["ungrounded_segments"] += 1
                    arguments.append({
                        "role": binding.role,
                        "qualifier": binding.qualifier,
                        "segments": [span],
                    })
            events.append({
                "event_type": event_type,
                "trigger": trigger,
                "arguments": arguments,
            })
    events.sort(key=lambda item: (
        min((s.get("start") for s in item["trigger"]["segments"]
             if isinstance(s.get("start"), int)), default=len(text)),
        item["event_type"],
    ))
    row = {
        "message_id": source_row.get("message_id"),
        "thread_id": source_row.get("thread_id"),
        "split": source_row.get("split", "dev"),
        "text": text,
        "events": events,
    }
    return row, diagnostics


class OffsetSchemaTransformer:
    """Factory for a private GLiNER transformer subclass with exact labels.

    GLiNER2's public training data converter searches for each text surface and
    labels all matching occurrences. This override retains each source event's
    explicit segment offsets through to its natural-record target tensors.
    """

    @staticmethod
    def make(base_class: type):
        class _OffsetAwareSchemaTransformer(base_class):
            def _collate_batch(self, batch, max_len=None, error_policy="raise"):
                """Keep source text byte-exact and reject implicit truncation.

                The public GLiNER2 collator adds a synthetic final period and
                turns empty text into ``.`` before constructing offsets. Those
                characters are not in MailEx source text. Windows are already
                measured against the encoder limit, so this adapter transforms
                the original body and verifies the final encoded length.
                """
                if error_policy not in ("raise", "skip", "fallback"):
                    raise ValueError(f"unknown error_policy {error_policy!r}")
                transformed_records = []
                for text, schema in batch:
                    if hasattr(schema, "build"):
                        schema = schema.build()
                    elif hasattr(schema, "schema"):
                        schema = schema.schema
                    text = str(text)
                    if not text.strip():
                        if error_policy == "skip":
                            continue
                        raise ValueError("empty/whitespace MailEx body has no source tokens")
                    token_count = len(list(self.word_splitter(text, lower=True)))
                    if max_len is not None and token_count > max_len:
                        raise ValueError(
                            f"native MailEx window has {token_count} words above max_len={max_len}"
                        )
                    try:
                        transformed = self._transform_record(
                            {"text": text, "schema": copy.deepcopy(schema)},
                            max_len=None,
                        )
                        encoded_length = len(transformed.input_ids)
                        if encoded_length > 512:
                            raise ValueError(
                                f"native MailEx window encodes to {encoded_length} tokens above 512"
                            )
                        transformed_records.append(transformed)
                    except Exception:
                        if error_policy == "skip":
                            continue
                        # Keep this adapter strict: the stock fallback inserts
                        # fabricated text and would sever source offsets.
                        raise
                return self._pad_batch(transformed_records)

            def _build_outputs(self, processed, schema, text_tokens, len_prefix):
                results = super()._build_outputs(
                    processed, schema, text_tokens, len_prefix
                )
                exact = schema.get("_mailex_exact_targets")
                if exact is None:
                    return results
                if len(text_tokens) < len_prefix:
                    raise ValueError("invalid GLiNER prefix/text token layout")
                source_text = schema["_mailex_text"]
                word_boundaries = [
                    (start, end)
                    for _, start, end in self.word_splitter(source_text, lower=True)
                ]
                if len(word_boundaries) != len(text_tokens) - len_prefix:
                    raise ValueError(
                        "GLiNER text word count differs from exact-offset source map"
                    )
                for result in results:
                    if result.get("task_type") != "json_structures":
                        continue
                    tokens = result.get("schema_tokens", [])
                    parent = str(tokens[2]).split(" [DESCRIPTION] ")[0] if len(tokens) > 2 else ""
                    targets = exact.get(parent)
                    if targets is None:
                        raise ValueError(f"missing exact-offset targets for {parent!r}")
                    field_names = [
                        tokens[i + 1]
                        for i, token in enumerate(tokens[:-1])
                        if token == self.C_TOKEN
                    ]
                    records = []
                    for target in targets:
                        fields = []
                        for field_name in field_names:
                            raw_spans = target.get(field_name, [])
                            if field_name == "trigger":
                                positions = [_char_span_to_inclusive_words(
                                    raw_spans[0], word_boundaries, len_prefix
                                )] if raw_spans else []
                                fields.append(positions)
                            else:
                                positions = [
                                    _char_span_to_inclusive_words(
                                        span, word_boundaries, len_prefix
                                    )
                                    for span in raw_spans
                                ]
                                fields.append(positions)
                        records.append(fields)
                    result["output"] = [len(records), records]
                return results

        return _OffsetAwareSchemaTransformer


def _char_span_to_inclusive_words(
    char_span: Sequence[int],
    mapped: Sequence[tuple[int, int]],
    prefix_word_count: int = 0,
) -> tuple[int, int]:
    """Map one exact half-open character span to GLiNER's inclusive word IDs."""
    char_start, char_end = int(char_span[0]), int(char_span[1])
    if char_start < 0 or char_end <= char_start:
        raise ValueError(f"invalid source span [{char_start},{char_end})")
    first = next((i for i, (start, end) in enumerate(mapped)
                  if start == char_start and end > start), None)
    last = next((i for i in range(len(mapped) - 1, -1, -1)
                 if mapped[i][1] == char_end and mapped[i][0] < char_end), None)
    if first is None or last is None or last < first:
        raise ValueError(
            f"GLiNER word boundaries cannot represent source span [{char_start},{char_end})"
        )
    return first + prefix_word_count, last + prefix_word_count


def build_training_record(
    row: Mapping[str, Any],
    ontology: MailExOntology,
    model: Any,
    event_types: Sequence[str],
) -> dict[str, Any]:
    """Make one packed-schema GLiNER row with private exact-offset targets.

    Every packed event group is present for every example, including empty
    (negative) groups, so training has the same query surface as inference.
    """
    text = str(row.get("text", ""))
    selected_types = tuple(event_types)
    exact_targets: dict[str, list[dict[str, list[list[int]]]]] = {
        event_type: [] for event_type in selected_types
    }
    schema_obj = build_schema(model, ontology, selected_types)
    schema: dict[str, Any] = schema_obj.build()
    events_by_type: dict[str, list[Mapping[str, Any]]] = {
        event_type: [ev for ev in row.get("events", []) if ev["event_type"] == event_type]
        for event_type in selected_types
    }
    for event_type in selected_types:
        bindings = ontology.fields_by_event[event_type]
        group_targets = []
        for event in events_by_type[event_type]:
            segments = event.get("trigger", {}).get("segments", [])
            if not segments:
                raise ValueError(f"event {event.get('event_id')} lacks a trigger segment")
            # Natural anchors are contiguous. Use the source-first segment as a
            # documented pivot; the full native trigger remains in gold data.
            pivot = min(segments, key=lambda s: (int(s["start"]), int(s["end"])))
            if text[int(pivot["start"]):int(pivot["end"])] != pivot.get("text"):
                raise ValueError("source trigger segment does not match reconstructed text")
            target = {"trigger": [[int(pivot["start"]), int(pivot["end"])]]}
            for binding in bindings:
                target[binding.field_name] = []
            for argument in event.get("arguments", []):
                key = (argument.get("role"), argument.get("qualifier"))
                binding = next((item for item in bindings
                                if (item.role, item.qualifier) == key), None)
                if binding is None:
                    raise ValueError(f"TRAIN ontology missing role/qualifier pair {key!r}")
                for segment in argument.get("segments", []):
                    start, end = int(segment["start"]), int(segment["end"])
                    if text[start:end] != segment.get("text"):
                        raise ValueError("source argument segment does not match reconstructed text")
                    target[binding.field_name].append([start, end])
            group_targets.append(target)
        exact_targets[event_type] = group_targets
    schema["_mailex_exact_targets"] = exact_targets
    schema["_mailex_text"] = text
    return {"text": text, "schema": schema}


def private_package_versions() -> dict[str, str]:
    vendor = str(VENDOR_ROOT)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from importlib.metadata import PackageNotFoundError, version
    names = ("gliner2", "torch", "transformers", "pydantic", "peft", "accelerate", "protobuf")
    out = {}
    for name in names:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not-installed"
    return out
