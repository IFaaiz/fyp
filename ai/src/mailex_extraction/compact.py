"""Shared DistilBERT trigger and event-conditioned argument baseline.

Every source word is encoded through overlapping windows. Window embeddings
are averaged at the first wordpiece, then argument heads see the complete
message and a pooled trigger. There is no silent right truncation. Predictions
are extractive word spans; discontinuous trigger grouping is not learned.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from transformers import AutoConfig, AutoModel, AutoTokenizer


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(rows):
    types = sorted({e["event_type"] for r in rows for e in r["events"]})
    roles = sorted({(a["role"], a.get("qualifier") or "") for r in rows for e in r["events"] for a in e["arguments"]})
    return types, roles


def word_indices(span, row):
    result = []
    for seg in span.get("segments", []):
        start, end = seg["start"], seg["end"]
        result.append([i for i, off in enumerate(row["token_offsets"]) if off[0] >= start and off[1] <= end])
    return [indices for indices in result if indices]


def token_bounds(row):
    """Accept list-pair and explicit object offsets without relocating text."""
    offsets = row["token_offsets"]
    if offsets and isinstance(offsets[0], dict):
        return [(off["start"], off["end"]) for off in offsets]
    return [tuple(off) for off in offsets]


def canonical_rows(rows):
    for row in rows:
        row["token_offsets"] = token_bounds(row)
        assert len(row["tokens"]) == len(row["token_offsets"])
        for token, (start, end) in zip(row["tokens"], row["token_offsets"]):
            assert row["text"][start:end] == token
        # Empty source tokens have zero-width evidence and no wordpieces. Keep
        # the exact text while explicitly removing them from this model view.
        keep = [i for i, token in enumerate(row["tokens"]) if token]
        row["model_source_token_indices"] = keep
        row["tokens"] = [row["tokens"][i] for i in keep]
        row["token_offsets"] = [row["token_offsets"][i] for i in keep]
    return rows


def encode_features(row, tokenizer, max_length=512, stride=128):
    if not row["tokens"]:
        return None
    encoded = tokenizer(row["tokens"], is_split_into_words=True, truncation=True,
                        max_length=max_length, stride=stride, return_overflowing_tokens=True)
    windows = []
    seen = set()
    for index, ids in enumerate(encoded["input_ids"]):
        word_ids = encoded.word_ids(index)
        positions = []
        previous = None
        for position, word in enumerate(word_ids):
            if word is not None and word != previous:
                positions.append((position, word))
                seen.add(word)
            previous = word
        windows.append({"input_ids": ids, "attention_mask": encoded["attention_mask"][index], "positions": positions})
    if seen != set(range(len(row["tokens"]))):
        raise ValueError("Tokenizer did not represent every source token")
    return windows


class CompactExtractor(nn.Module):
    def __init__(self, encoder_path, event_types, role_keys, *, loss_family="categorical_bio", pretrained=True):
        super().__init__()
        self.encoder = (AutoModel.from_pretrained(encoder_path, local_files_only=True) if pretrained
                        else AutoModel.from_config(AutoConfig.from_pretrained(encoder_path, local_files_only=True)))
        self.event_types, self.role_keys = list(event_types), [tuple(r) for r in role_keys]
        self.loss_family = loss_family
        hidden = self.encoder.config.hidden_size
        self.trigger = nn.Linear(hidden, (3 if loss_family == "categorical_bio" else 2) * len(event_types))
        self.word_projection = nn.Linear(hidden, 128)
        self.trigger_projection = nn.Linear(hidden, 128)
        self.event_embedding = nn.Embedding(len(event_types), 128)
        self.argument = nn.Linear(128, 2 * len(role_keys) + (loss_family == "categorical_bio"))
        if loss_family == "categorical_bio":
            self.distance_embedding = nn.Embedding(18, 128)
        self.dropout = nn.Dropout(0.1)

    def encode(self, rows, features, device, encoder_batch_size=8):
        lengths = [len(r["tokens"]) for r in rows]
        starts = np.cumsum([0] + lengths).tolist()
        all_windows = [(i, w) for i, fs in enumerate(features) for w in (fs or [])]
        hidden_size = self.encoder.config.hidden_size
        sums = torch.zeros((starts[-1], hidden_size), device=device)
        counts = torch.zeros((starts[-1], 1), device=device)
        for begin in range(0, len(all_windows), encoder_batch_size):
            batch = all_windows[begin:begin + encoder_batch_size]
            width = max(len(w["input_ids"]) for _, w in batch)
            ids = torch.zeros((len(batch), width), dtype=torch.long, device=device)
            mask = torch.zeros_like(ids)
            target, batch_index, positions = [], [], []
            for j, (i, window) in enumerate(batch):
                n = len(window["input_ids"])
                ids[j, :n] = torch.tensor(window["input_ids"], device=device)
                mask[j, :n] = torch.tensor(window["attention_mask"], device=device)
                for position, word in window["positions"]:
                    target.append(starts[i] + word)
                    batch_index.append(j)
                    positions.append(position)
            encoded = self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state
            idx = torch.tensor(target, device=device)
            values = encoded[batch_index, positions].to(sums.dtype)
            sums = sums.index_add(0, idx, values)
            counts.index_add_(0, idx, torch.ones((len(target), 1), device=device))
        if starts[-1] and torch.any(counts == 0):
            raise ValueError("Unrepresented source word")
        vectors = sums / counts.clamp_min(1)
        return [vectors[starts[i]:starts[i + 1]] for i in range(len(rows))]

    def argument_logits(self, words, event_index, trigger_indices):
        pooled = words[trigger_indices].mean(0) if trigger_indices else words.new_zeros(words.shape[-1])
        trigger = self.trigger_projection(pooled)
        context = trigger + self.event_embedding.weight[event_index]
        projected = self.word_projection(words)
        if self.loss_family == "categorical_bio":
            if trigger_indices:
                positions = torch.arange(len(words), device=words.device)
                distance = torch.where(positions < min(trigger_indices), positions - min(trigger_indices),
                                       torch.where(positions > max(trigger_indices), positions - max(trigger_indices), 0))
                magnitude = torch.log2(distance.abs().float() + 1).floor().long().clamp_max(7)
                buckets = torch.where(distance < 0, 8 - magnitude, 8 + magnitude)
            else:
                buckets = torch.full((len(words),), 17, device=words.device, dtype=torch.long)
            context = context + self.distance_embedding(buckets)
            projected = projected + 0.25 * projected * trigger
        return self.argument(self.dropout(torch.tanh(projected + context)))


def make_targets(row, model, device):
    n = len(row["tokens"])
    trigger_target = torch.zeros((n, 2 * len(model.event_types)), device=device)
    events = []
    for event in row["events"]:
        event_index = model.event_types.index(event["event_type"])
        indices = word_indices(event["trigger"], row)
        for group in indices:
            trigger_target[group[0], 2 * event_index] = 1
            trigger_target[group[1:], 2 * event_index + 1] = 1
        arg_target = torch.zeros((n, 2 * len(model.role_keys)), device=device)
        for argument in event["arguments"]:
            key = (argument["role"], argument.get("qualifier") or "")
            if key not in model.role_keys:
                continue  # Explicit unseen TRAIN role: not a learned output class.
            role_index = model.role_keys.index(key)
            for group in word_indices(argument, row):
                arg_target[group[0], 2 * role_index] = 1
                arg_target[group[1:], 2 * role_index + 1] = 1
        events.append((event_index, [i for group in indices for i in group], arg_target))
    return trigger_target, events


def categorical_targets(row, model, device):
    trigger_binary, events_binary = make_targets(row, model, device)
    paired = trigger_binary.reshape(len(row["tokens"]), len(model.event_types), 2)
    # Explicit representational limitation: B takes precedence when same-type
    # source trigger BIO states collide. Native gold instances remain intact.
    trigger = torch.where(paired[..., 0] > 0, 1, torch.where(paired[..., 1] > 0, 2, 0)).long()
    events = []
    for event_index, indices, binary in events_binary:
        present = binary.sum(-1) > 0
        if torch.any(binary.sum(-1) > 1):
            raise ValueError("Native argument BIO has overlapping role targets in one event")
        target = torch.where(present, binary.argmax(-1) + 1, 0).long()
        events.append((event_index, indices, target))
    return trigger, events


def categorical_probabilities(logits, count, *, trigger):
    if trigger:
        scores = logits.reshape(len(logits), count, 3).softmax(-1)
        winners = scores.argmax(-1)
        states = torch.arange(3, device=logits.device)
        return (scores * (winners[..., None] == states))[..., 1:].reshape(len(logits), count * 2)
    scores = logits.softmax(-1)
    winners = scores.argmax(-1)
    states = torch.arange(scores.shape[-1], device=logits.device)
    return (scores * (winners[:, None] == states))[:, 1:]


def positive_weights(rows, model):
    triggers = torch.zeros(2 * len(model.event_types))
    arguments = torch.zeros(2 * len(model.role_keys))
    trigger_total = argument_total = 0
    for row in rows:
        target, events = make_targets(row, model, "cpu")
        triggers += target.sum(0)
        trigger_total += len(row["tokens"])
        for _, _, target in events:
            arguments += target.sum(0)
            argument_total += len(row["tokens"])
    # TRAIN-only class weighting. Cap prevents singleton roles dominating loss.
    return ((trigger_total - triggers) / triggers.clamp_min(1)).clamp(1, 50), ((argument_total - arguments) / arguments.clamp_min(1)).clamp(1, 50)


def segments_from_logits(logits, row, keys, threshold, *, probabilities=False):
    probabilities = (logits if probabilities else logits.sigmoid()).detach().cpu().numpy()
    output = []
    for key_index, key in enumerate(keys):
        active = []
        for i in range(len(probabilities)):
            b_score = probabilities[i, 2 * key_index]
            i_score = probabilities[i, 2 * key_index + 1]
            # B and I are independent training logits but mutually exclusive
            # decoder states for one label. Letting both fire fragments an
            # argument at every token where B merely clears the threshold.
            begin = b_score >= threshold and b_score >= i_score
            inside = i_score >= threshold and i_score > b_score
            if active and (begin or not inside):
                output.append((key, active))
                active = []
            if begin or inside:
                active.append(i)
        if active:
            output.append((key, active))
    return output


def source_span(row, indices):
    start, end = row["token_offsets"][indices[0]][0], row["token_offsets"][indices[-1]][1]
    return {"segments": [{"start": start, "end": end, "text": row["text"][start:end],
                           "token_start": row["model_source_token_indices"][indices[0]],
                           "token_end": row["model_source_token_indices"][indices[-1]] + 1}]}


@torch.inference_mode()
def predict(model, rows, features, device, threshold=0.5, mode="end_to_end", batch_size=4):
    model.eval()
    results = []
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        vectors = model.encode(batch, features[start:start + batch_size], device)
        for row, words in zip(batch, vectors):
            candidates = []
            if len(words):
                if mode == "end_to_end":
                    logits = model.trigger(words)
                    categorical = model.loss_family == "categorical_bio"
                    if categorical:
                        logits = categorical_probabilities(logits, len(model.event_types), trigger=True)
                    candidates = [(key, indices, None) for key, indices in segments_from_logits(
                        logits, row, model.event_types, threshold, probabilities=categorical)]
                else:
                    for event in row["events"]:
                        key = event["event_type"]
                        if key not in model.event_types:
                            continue
                        indices = [i for group in word_indices(event["trigger"], row) for i in group] if mode == "gold_type_trigger" else []
                        candidates.append((key, indices, event["trigger"] if mode == "gold_type_trigger" else None))
            events = []
            for ordinal, (key, indices, oracle_trigger) in enumerate(candidates):
                argument_logits = model.argument_logits(words, model.event_types.index(key), indices)
                categorical = model.loss_family == "categorical_bio"
                if categorical:
                    argument_logits = categorical_probabilities(argument_logits, len(model.role_keys), trigger=False)
                arguments = []
                for (role, qualifier), arg_indices in segments_from_logits(argument_logits, row, model.role_keys, threshold, probabilities=categorical):
                    arguments.append({"role": role, "qualifier": qualifier or None, **source_span(row, arg_indices)})
                if mode == "gold_type_trigger":
                    trigger = oracle_trigger
                else:
                    trigger = source_span(row, indices) if indices else {"segments": []}
                events.append({"event_id": f"prediction_{ordinal}", "event_type": key, "trigger": trigger, "arguments": arguments})
            results.append({"message_id": row["message_id"], "split": row["split"], "text": row["text"], "events": events})
    return results


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
