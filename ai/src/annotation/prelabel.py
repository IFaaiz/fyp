"""Provider-independent parsing of structured AI prelabels.

This module deliberately makes no API calls and never promotes a result to gold.
"""

from __future__ import annotations

from typing import Any

from .span_utils import locate_span
from ..datasets.schemas import LABELS, SPAN_LABELS


def apply_prelabel(record: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    if record.get("annotation", {}).get("status") in {"gold", "human_reviewed"}:
        raise ValueError("cannot overwrite human-reviewed or gold annotations with AI prelabels")
    labels = prediction.get("labels")
    if not isinstance(labels, list) or any(label not in LABELS for label in labels):
        raise ValueError("prediction labels must be a list of known labels")
    if "NON_PROJECT" in labels and len(labels) > 1:
        raise ValueError("NON_PROJECT cannot co-occur with project labels")
    spans = []
    for item in prediction.get("spans", []):
        if item.get("label") not in SPAN_LABELS:
            raise ValueError("unknown span label")
        field = item.get("field", "current_message")
        if field not in {"current_message", "subject"}:
            raise ValueError("invalid span field")
        spans.append(locate_span(record[field], item["text"], label=item["label"], field=field))
    confidence = prediction.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, dict)
        or any(label not in labels or not isinstance(value, (int, float)) or not 0 <= value <= 1 for label, value in confidence.items())
    ):
        raise ValueError("confidence must map predicted labels to values from 0 to 1")
    output = dict(record)
    output["labels"] = list(dict.fromkeys(labels))
    output["spans"] = spans
    output["annotation"] = {
        "status": "ai_prelabelled", "annotator": None,
        "annotation_source": "ai", "confidence": confidence,
        "needs_review": bool(prediction.get("needs_review", False)),
        "ambiguity_note": prediction.get("ambiguity_note"),
    }
    return output
