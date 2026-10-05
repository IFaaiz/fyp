"""Explicit span proposal and gold-event-conditioned native argument links."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import torch
from torch import nn


def _offset_pairs(row: Mapping[str, Any]) -> list[tuple[int, int]]:
    result = []
    for raw in row["token_offsets"]:
        if isinstance(raw, Mapping):
            result.append((int(raw["start"]), int(raw["end"])))
        else:
            result.append((int(raw[0]), int(raw[1])))
    return result


def token_span_bounds(row: Mapping[str, Any], span: Mapping[str, Any]) -> tuple[int, int]:
    """Return inclusive token bounds for a single, exactly aligned segment."""
    segments = span.get("segments", [])
    if len(segments) != 1:
        raise ValueError("span-link diagnostic expects one contiguous source segment")
    segment = segments[0]
    start = int(segment.get("start", segment.get("char_start")))
    end = int(segment.get("end", segment.get("char_end")))
    offsets = _offset_pairs(row)
    inside = [i for i, (left, right) in enumerate(offsets)
              if right > left and left >= start and right <= end]
    if not inside or offsets[inside[0]][0] != start or offsets[inside[-1]][1] != end:
        raise ValueError("native span is not exactly representable by source token boundaries")
    if inside != list(range(inside[0], inside[-1] + 1)):
        raise ValueError("native span maps to nonconsecutive source token indices")
    return inside[0], inside[-1]


def trigger_token_indices(row: Mapping[str, Any], trigger: Mapping[str, Any]) -> list[int]:
    offsets = _offset_pairs(row)
    indices: list[int] = []
    for segment in trigger.get("segments", []):
        start = int(segment.get("start", segment.get("char_start")))
        end = int(segment.get("end", segment.get("char_end")))
        indices.extend(i for i, (left, right) in enumerate(offsets)
                       if right > left and left >= start and right <= end)
    return sorted(set(indices))


class SpanLinkModel(nn.Module):
    """One encoder, two boundary heads, and shared event-conditioned link heads."""

    def __init__(self, encoder_path: str, event_types: Sequence[str],
                 role_keys: Sequence[tuple[str, str]], *, pretrained: bool = True):
        super().__init__()
        from transformers import AutoConfig, AutoModel

        self.encoder = (AutoModel.from_pretrained(encoder_path, local_files_only=True) if pretrained
                        else AutoModel.from_config(AutoConfig.from_pretrained(encoder_path, local_files_only=True)))
        self.event_types = list(event_types)
        self.role_keys = [(str(role), str(qualifier or "")) for role, qualifier in role_keys]
        hidden = int(self.encoder.config.hidden_size)
        projection = 128
        self.start_boundary = nn.Linear(hidden, 1)
        self.end_boundary = nn.Linear(hidden, 1)
        self.start_span_projection = nn.Linear(hidden, projection)
        self.end_span_projection = nn.Linear(hidden, projection)
        self.mean_span_projection = nn.Linear(hidden, projection)
        self.span_presence = nn.Linear(projection, 1)
        self.trigger_projection = nn.Linear(hidden, projection)
        self.event_embedding = nn.Embedding(len(self.event_types), projection)
        self.distance_embedding = nn.Embedding(18, projection)
        self.dropout = nn.Dropout(0.1)
        self.link_classifier = nn.Linear(projection, len(self.role_keys))

    def encode(self, rows: Sequence[Mapping[str, Any]], features: Sequence[Any], device: torch.device,
               encoder_batch_size: int = 4) -> list[torch.Tensor]:
        lengths = [len(row["tokens"]) for row in rows]
        starts = [0]
        for length in lengths:
            starts.append(starts[-1] + length)
        windows = [(row_index, window) for row_index, items in enumerate(features)
                   for window in (items or [])]
        hidden_size = int(self.encoder.config.hidden_size)
        if starts[-1] == 0:
            return [torch.zeros((0, hidden_size), device=device) for _ in rows]
        sums = torch.zeros((starts[-1], hidden_size), device=device, dtype=torch.float32)
        counts = torch.zeros((starts[-1], 1), device=device, dtype=torch.float32)
        for begin in range(0, len(windows), encoder_batch_size):
            batch = windows[begin:begin + encoder_batch_size]
            width = max(len(window["input_ids"]) for _, window in batch)
            ids = torch.zeros((len(batch), width), dtype=torch.long, device=device)
            mask = torch.zeros_like(ids)
            destinations: list[int] = []
            batch_indices: list[int] = []
            positions: list[int] = []
            for batch_index, (row_index, window) in enumerate(batch):
                size = len(window["input_ids"])
                ids[batch_index, :size] = torch.tensor(window["input_ids"], dtype=torch.long, device=device)
                mask[batch_index, :size] = torch.tensor(window["attention_mask"], dtype=torch.long, device=device)
                for position, word_index in window["positions"]:
                    destinations.append(starts[row_index] + word_index)
                    batch_indices.append(batch_index)
                    positions.append(position)
            encoded = self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state
            target = torch.tensor(destinations, dtype=torch.long, device=device)
            values = encoded[batch_indices, positions].float()
            sums = sums.index_add(0, target, values)
            counts.index_add_(0, target, torch.ones((len(destinations), 1), device=device))
        if torch.any(counts == 0):
            raise ValueError("tokenizer windows failed to represent every nonempty source token")
        vectors = sums / counts.clamp_min(1.0)
        return [vectors[starts[i]:starts[i + 1]] for i in range(len(rows))]

    def span_representations(self, words: torch.Tensor,
                             spans: Sequence[tuple[int, int]]) -> torch.Tensor:
        if not spans:
            return words.new_zeros((0, self.start_span_projection.out_features))
        bounds = torch.tensor(spans, dtype=torch.long, device=words.device)
        starts, ends = bounds[:, 0], bounds[:, 1]
        prefix = torch.cat((words.new_zeros((1, words.shape[-1])), words.cumsum(dim=0)), dim=0)
        means = (prefix[ends + 1] - prefix[starts]) / (ends - starts + 1).unsqueeze(-1).to(words.dtype)
        reps = torch.tanh(self.start_span_projection(words[starts])
                          + self.end_span_projection(words[ends])
                          + self.mean_span_projection(means))
        return reps

    def boundary_logits(self, words: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.start_boundary(words).squeeze(-1), self.end_boundary(words).squeeze(-1)

    def span_logits(self, span_representations: torch.Tensor) -> torch.Tensor:
        return self.span_presence(self.dropout(span_representations)).squeeze(-1)

    def role_logits(self, span_reps: torch.Tensor, words: torch.Tensor,
                    spans: Sequence[tuple[int, int]], event_type: str,
                    trigger_indices: Sequence[int]) -> torch.Tensor:
        if not spans:
            return words.new_zeros((0, len(self.role_keys)))
        if event_type not in self.event_types:
            raise ValueError(f"unseen native event type: {event_type}")
        starts = torch.tensor([item[0] for item in spans], dtype=torch.long, device=words.device)
        ends = torch.tensor([item[1] for item in spans], dtype=torch.long, device=words.device)
        event_index = self.event_types.index(event_type)
        type_context = self.event_embedding.weight[event_index]
        if trigger_indices:
            trigger = words[list(trigger_indices)].mean(0)
            trigger_context = self.trigger_projection(trigger)
            center = (min(trigger_indices) + max(trigger_indices)) // 2
            delta = (starts + ends) // 2 - center
            magnitude = torch.log2(delta.abs().float() + 1).floor().long().clamp_max(7)
            distance_bucket = torch.where(delta < 0, 8 - magnitude,
                                          torch.where(delta > 0, 8 + magnitude, 8))
        else:
            trigger_context = words.new_zeros(self.trigger_projection.out_features)
            distance_bucket = torch.full_like(starts, 17)
        context = (span_reps + trigger_context + type_context
                   + self.distance_embedding(distance_bucket))
        return self.link_classifier(self.dropout(torch.tanh(context)))


def rank_span_pairs(span_logits: torch.Tensor, pairs: Sequence[tuple[int, int]],
                    boundary_scores: Sequence[float], *, limit: int = 96) -> list[int]:
    """Deterministic reranking; indices refer to ``pairs``/``span_logits``."""
    span_values = span_logits.detach().float().cpu().tolist()
    ranked = sorted(range(len(pairs)),
                    key=lambda i: (-(boundary_scores[i] + span_values[i]), pairs[i][0], pairs[i][1]))
    return ranked[:limit]


@torch.no_grad()
def propose_spans(model: SpanLinkModel, words: torch.Tensor, *,
                  boundaries_per_side: int = 32,
                  candidate_limit: int = 96) -> list[tuple[int, int]]:
    """Score every valid top-boundary pair, then keep the best learned spans."""
    count = len(words)
    if count == 0:
        return []
    start_logits, end_logits = model.boundary_logits(words)
    start_values = start_logits.detach().float().cpu().tolist()
    end_values = end_logits.detach().float().cpu().tolist()
    start_positions = sorted(range(count), key=lambda i: (-start_values[i], i))[:boundaries_per_side]
    end_positions = sorted(range(count), key=lambda i: (-end_values[i], i))[:boundaries_per_side]
    boundary_pairs = [(s, e) for s in start_positions for e in end_positions if s <= e]
    boundary_pairs.sort(key=lambda pair: (-(start_values[pair[0]] + end_values[pair[1]]), pair[0], pair[1]))
    pairs = boundary_pairs
    if not pairs:
        return []
    reps = model.span_representations(words, pairs)
    presence = model.span_logits(reps)
    boundary_scores = [start_values[s] + end_values[e] for s, e in pairs]
    chosen = rank_span_pairs(presence, pairs, boundary_scores,
                             limit=candidate_limit)
    return [pairs[index] for index in chosen]

