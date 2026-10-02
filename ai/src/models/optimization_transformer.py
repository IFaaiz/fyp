"""Portable inference helpers for the DistilBERT optimization experiments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .silver_classifier import LABEL_ORDER


MAX_LENGTH = 512


def canonical_text(row: dict[str, Any]) -> str:
    """Return the authored subject/body text from an approved canonical row."""
    for key in ("canonical_text", "text"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    subject = row.get("subject")
    body = row.get("authored_message", row.get("body"))
    if isinstance(body, str) and body.strip():
        return f"[SUBJECT] {subject.strip() if isinstance(subject, str) else ''}\n[BODY] {body.strip()}"
    current_message = row.get("current_message")
    if isinstance(current_message, str) and current_message.strip():
        from .transfer_diagnostic import record_text
        return record_text(row)
    raise ValueError(f"canonical row {row.get('email_id', '<unknown>')} has no authored text")


def encode_layout(tokenizer: Any, text: str, layout: str, max_length: int = MAX_LENGTH) -> list[list[int]]:
    """Make one 512-token view or two consecutive views for a long email."""
    if max_length != MAX_LENGTH:
        raise ValueError("the approved DistilBERT experiments use a fixed 512-token window")
    if layout == "head512":
        return [tokenizer.encode(text, add_special_tokens=True, truncation=True, max_length=max_length)]

    content = tokenizer.encode(text, add_special_tokens=False, truncation=False)
    cls_id = tokenizer.cls_token_id
    sep_id = tokenizer.sep_token_id
    if cls_id is None or sep_id is None:
        raise ValueError("tokenizer must define CLS and SEP token IDs")
    if layout == "head_tail_320_192":
        if len(content) <= max_length - 2:
            return [[cls_id, *content, sep_id]]
        # 320 tokens in the head segment and 192 in the tail segment, counting
        # their separator tokens. The complete sequence therefore stays <=512.
        head = [cls_id, *content[:318], sep_id]
        tail = [*content[-191:], sep_id]
        return [head + tail]
    if layout == "two_chunk":
        first = [cls_id, *content[: max_length - 2], sep_id]
        chunks = [first]
        remainder = content[max_length - 2 : 2 * (max_length - 2)]
        if remainder:
            chunks.append([cls_id, *remainder, sep_id])
        return chunks
    raise ValueError(f"unknown transformer input layout: {layout}")


def _batch_inputs(tokenizer: Any, sequences: list[list[int]], device: Any, torch: Any) -> dict[str, Any]:
    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        raise ValueError("tokenizer must define a pad token")
    ids = torch.full((len(sequences), MAX_LENGTH), pad_id, dtype=torch.long, device=device)
    mask = torch.zeros((len(sequences), MAX_LENGTH), dtype=torch.long, device=device)
    for index, sequence in enumerate(sequences):
        clipped = sequence[:MAX_LENGTH]
        ids[index, : len(clipped)] = torch.tensor(clipped, dtype=torch.long, device=device)
        mask[index, : len(clipped)] = 1
    return {"input_ids": ids, "attention_mask": mask}


def predict(bundlepath: str | Path, canonicalrows: list[dict[str, Any]]) -> list[list[float]]:
    """Return an N x 9 probability matrix in LABEL_ORDER for canonical rows."""
    if not canonicalrows:
        return []
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Transformer inference requires the configured torch/transformers runtime") from exc

    bundle = Path(bundlepath)
    metadata_path = bundle / "candidate.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    if metadata.get("label_order", list(LABEL_ORDER)) != list(LABEL_ORDER):
        raise ValueError("candidate label order does not match this repository")
    layout = metadata.get("input_layout", "head512")
    pooling = metadata.get("two_chunk_pooling", "mean")
    batch_size = int(metadata.get("inference_batch_size", 16))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(bundle, local_files_only=True, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        bundle, local_files_only=True, attn_implementation="eager",
    ).to(device)
    model.eval()
    row_sequences = [encode_layout(tokenizer, canonical_text(row), layout) for row in canonicalrows]
    flat_sequences: list[list[int]] = []
    owners: list[tuple[int, int]] = []
    for row_index, chunks in enumerate(row_sequences):
        for chunk_index, sequence in enumerate(chunks):
            owners.append((row_index, chunk_index))
            flat_sequences.append(sequence)

    collected: list[list[float] | None] = [None] * len(flat_sequences)
    use_amp = device.type == "cuda"
    with torch.no_grad():
        for start in range(0, len(flat_sequences), batch_size):
            stop = min(start + batch_size, len(flat_sequences))
            batch = _batch_inputs(tokenizer, flat_sequences[start:stop], device, torch)
            with torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(**batch).logits
            for offset, probabilities in enumerate(logits.float().sigmoid().cpu().tolist()):
                collected[start + offset] = probabilities

    by_row: list[list[list[float]]] = [[] for _ in canonicalrows]
    for owner, values in zip(owners, collected):
        if values is None:
            raise RuntimeError("missing transformer prediction")
        by_row[owner[0]].append(values)
    results: list[list[float]] = []
    for chunks in by_row:
        if len(chunks) == 1:
            results.append(chunks[0])
        elif pooling == "max":
            results.append([max(values) for values in zip(*chunks)])
        else:
            results.append([sum(values) / len(chunks) for values in zip(*chunks)])
    return results
