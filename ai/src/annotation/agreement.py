"""Inter-rater metrics and disagreement extraction for human annotations."""
from __future__ import annotations
from collections import Counter
from collections.abc import Iterable
from typing import Any
from ..datasets.schemas import LABELS, SPAN_LABELS
from ..datasets.validation import validate_record


def _prf(tp: int, fp: int, fn: int) -> dict[str, int | float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1_denom = 2 * tp + fp + fn
    f1 = 2 * tp / f1_denom if f1_denom else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def _kappa(a_yes: int, b_yes: int, both_yes: int, n: int) -> float | None:
    if not n:
        return None
    both_no = n - a_yes - b_yes + both_yes
    observed = (both_yes + both_no) / n
    expected = (a_yes * b_yes + (n - a_yes) * (n - b_yes)) / n**2
    return (observed - expected) / (1 - expected) if expected != 1 else None


def _span_counter(record: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    return Counter((s.get("label"), s.get("field", "current_message"), s.get("start"), s.get("end"), s.get("text")) for s in record.get("spans", []))


def _maximum_overlap_pairs(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[float]:
    """Maximum-cardinality matching; returned values are matched character IoUs."""
    graph: list[list[tuple[int, float]]] = []
    for a in left:
        edges = []
        for j, b in enumerate(right):
            start, end = max(a["start"], b["start"]), min(a["end"], b["end"])
            if start < end:
                union = max(a["end"], b["end"]) - min(a["start"], b["start"])
                edges.append((j, (end - start) / union))
        graph.append(sorted(edges, key=lambda edge: (-edge[1], edge[0])))
    owners: dict[int, tuple[int, float]] = {}
    def augment(i: int, seen: set[int]) -> bool:
        for j, score in graph[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or augment(owners[j][0], seen):
                owners[j] = (i, score)
                return True
        return False
    for i in range(len(left)):
        augment(i, set())
    return [score for _, score in owners.values()]


def _span_metrics(a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_label: dict[str, Any] = {}
    for label in sorted(SPAN_LABELS):
        etp = efp = efn = otp = ofp = ofn = 0
        ious: list[float] = []
        for a_row, b_row in zip(a_rows, b_rows):
            a = [s for s in a_row.get("spans", []) if s.get("label") == label]
            b = [s for s in b_row.get("spans", []) if s.get("label") == label]
            ca = Counter((s.get("field", "current_message"), s.get("start"), s.get("end"), s.get("text")) for s in a)
            cb = Counter((s.get("field", "current_message"), s.get("start"), s.get("end"), s.get("text")) for s in b)
            etp += sum((ca & cb).values()); efp += sum((ca - cb).values()); efn += sum((cb - ca).values())
            row_matches = []
            fields = {s.get("field", "current_message") for s in a + b}
            for field in fields:
                la = [s for s in a if s.get("field", "current_message") == field]
                lb = [s for s in b if s.get("field", "current_message") == field]
                row_matches.extend(_maximum_overlap_pairs(la, lb))
            otp += len(row_matches); ofp += len(a) - len(row_matches); ofn += len(b) - len(row_matches); ious.extend(row_matches)
        per_label[label] = {"exact": _prf(etp, efp, efn), "overlap": {**_prf(otp, ofp, ofn), "mean_iou": sum(ious) / len(ious) if ious else None}}
    exact = [v["exact"] for v in per_label.values()]
    overlap = [v["overlap"] for v in per_label.values()]
    exact_all = _prf(sum(x["tp"] for x in exact), sum(x["fp"] for x in exact), sum(x["fn"] for x in exact))
    overlap_all = _prf(sum(x["tp"] for x in overlap), sum(x["fp"] for x in overlap), sum(x["fn"] for x in overlap))
    matched_count = sum(x["tp"] for x in overlap)
    weighted_iou = sum(x["mean_iou"] * x["tp"] for x in overlap if x["mean_iou"] is not None)
    return {"exact_micro": exact_all, "overlap_micro": {**overlap_all, "mean_iou": weighted_iou / matched_count if matched_count else None}, "by_label": per_label}


def compare_reviewer_records(reviewer_a_records: Iterable[dict[str, Any]], reviewer_b_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compare shared human records; unresolved empty labels do not count as negatives."""
    a_rows, b_rows = list(reviewer_a_records), list(reviewer_b_records)
    a_by_id = {row.get("email_id"): row for row in a_rows}
    b_by_id = {row.get("email_id"): row for row in b_rows}
    if None in a_by_id or None in b_by_id:
        raise ValueError("every record must have an email_id")
    if len(a_by_id) != len(a_rows) or len(b_by_id) != len(b_rows):
        raise ValueError("duplicate email_id")
    if set(a_by_id) != set(b_by_id):
        raise ValueError(f"reviewer IDs differ; missing from A={sorted(set(b_by_id)-set(a_by_id))[:5]}, missing from B={sorted(set(a_by_id)-set(b_by_id))[:5]}")
    complete_a: list[dict[str, Any]] = []; complete_b: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []; unresolved: list[str] = []
    for email_id in sorted(a_by_id):
        a, b = a_by_id[email_id], b_by_id[email_id]
        for field in (set(a) | set(b)) - {"labels", "spans", "annotation"}:
            if a.get(field) != b.get(field):
                raise ValueError(f"reviewer records disagree on source field {field} for {email_id}")
        for row, name in ((a, "A"), (b, "B")):
            errors = validate_record(row)
            if errors:
                raise ValueError(f"reviewer {name} record {email_id} is invalid: {'; '.join(errors)}")
            ann = row.get("annotation", {})
            if ann.get("annotation_source") != "human" or not ann.get("annotator"):
                raise ValueError(f"reviewer {name} record {email_id} must identify a human annotator")
            if ann.get("status") not in {"human_reviewed", "unlabelled"}:
                raise ValueError(f"reviewer {name} record {email_id} must be human_reviewed or unlabelled")
        status_a, status_b = a["annotation"].get("status"), b["annotation"].get("status")
        reviewed = status_a == status_b == "human_reviewed"
        labels_a, labels_b = set(a.get("labels", [])), set(b.get("labels", []))
        spans_differ = _span_counter(a) != _span_counter(b)
        if not reviewed:
            unresolved.append(email_id)
        if not reviewed or labels_a != labels_b or spans_differ:
            disagreements.append({
                "email_id": email_id, "thread_id": a.get("thread_id"), "source_dataset": a.get("source_dataset"),
                "subject": a.get("subject", ""), "current_message": a.get("current_message", ""),
                "thread_context": a.get("thread_context", ""),
                "metadata": {key: a.get(key) for key in ("sender", "recipients", "cc", "sent_at", "attachment_names")},
                "review_status": {"A": status_a, "B": status_b},
                "labels": {"A": sorted(labels_a), "B": sorted(labels_b)},
                "spans": {"A": a.get("spans", []), "B": b.get("spans", [])},
                "classification_disagreement": labels_a != labels_b, "span_disagreement": spans_differ,
                "unresolved": not reviewed,
            })
        if reviewed:
            complete_a.append(a); complete_b.append(b)
    n = len(complete_a); per_label = {}
    for label in sorted(LABELS):
        a_yes = sum(label in row["labels"] for row in complete_a)
        b_yes = sum(label in row["labels"] for row in complete_b)
        tp = sum(label in a["labels"] and label in b["labels"] for a, b in zip(complete_a, complete_b))
        fp = sum(label in a["labels"] and label not in b["labels"] for a, b in zip(complete_a, complete_b))
        fn = sum(label not in a["labels"] and label in b["labels"] for a, b in zip(complete_a, complete_b))
        tn = n - tp - fp - fn
        per_label[label] = {**_prf(tp, fp, fn), "observed_agreement": (tp + tn) / n if n else None, "specificity": tn / (tn + fp) if tn + fp else None, "cohen_kappa": _kappa(a_yes, b_yes, tp, n)}
    exact_sets = 0; jaccards = []
    for a, b in zip(complete_a, complete_b):
        sa, sb = set(a["labels"]), set(b["labels"]); exact_sets += sa == sb
        union = sa | sb; jaccards.append(len(sa & sb) / len(union) if union else 1.0)
    return {
        "reviewer_a": sorted({row["annotation"]["annotator"] for row in a_rows}),
        "reviewer_b": sorted({row["annotation"]["annotator"] for row in b_rows}),
        "paired_records": len(a_by_id), "compared_records": n,
        "excluded_unresolved_records": len(unresolved), "unresolved_email_ids": unresolved,
        "classification": {"reference_direction": "A is prediction; B is reference for TP/FP/FN", "per_label": per_label,
                            "exact_set_agreement": exact_sets / n if n else None, "exact_set_matches": exact_sets,
                            "mean_jaccard": sum(jaccards) / n if n else None},
        "spans": _span_metrics(complete_a, complete_b), "agreement_is_not_gold": True,
        "disagreements": disagreements,
    }
