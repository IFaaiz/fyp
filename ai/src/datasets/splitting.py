"""Deterministic source-qualified, thread-grouped train/validation/test split."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Iterable

from .validation import validate_split_isolation


def split_by_thread(
    records: Iterable[dict[str, Any]], *,
    ratios: tuple[float, float, float] = (0.75, 0.10, 0.15),
    seed: int = 42,
) -> dict[str, list[dict[str, Any]]]:
    if any(x < 0 for x in ratios) or abs(sum(ratios) - 1.0) > 1e-9:
        raise ValueError("ratios must be nonnegative and sum to 1")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("source_dataset") == "synthetic" and record.get("annotation", {}).get("status") == "gold":
            raise ValueError("synthetic gold record is forbidden")
        groups[(record["source_dataset"], record["thread_id"])].append(record)
    gold_keys = {key for key, group in groups.items() if any(record.get("annotation", {}).get("status") == "gold" for record in group)}
    keys = sorted(set(groups) - gold_keys)
    random.Random(seed).shuffle(keys)
    result: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    for key in sorted(gold_keys):
        result["test"].extend(groups[key])
    targets = dict(zip(result, ratios))
    total = sum(len(group) for group in groups.values())
    for key in sorted(keys, key=lambda k: len(groups[k]), reverse=True):
        eligible = ["train"] if key[0] == "synthetic" else list(result)
        chosen = max(
            eligible,
            key=lambda name: (targets[name] * total - len(result[name]), targets[name], name),
        )
        result[chosen].extend(groups[key])
    errors = validate_split_isolation(result)
    if errors:
        raise AssertionError(errors)
    if any(record.get("annotation", {}).get("status") == "gold" for name in ("train", "validation") for record in result[name]):
        raise AssertionError("gold record assigned outside test")
    return result
