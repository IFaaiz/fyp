"""Review-only deterministic cues and an opt-in AI-silver diagnostic bridge."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Protocol

from .models import EmailRecord, LABELS, NON_PROJECT_LABEL


@dataclass(frozen=True, slots=True)
class Cue:
    label: str
    field: str
    text: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class ReviewSuggestion:
    method: str
    status: str
    labels: tuple[str, ...]
    evidence: tuple[Cue, ...]
    human_gold: bool = False
    review_required: bool = True


class DiagnosticClassifier(Protocol):
    name: str

    def predict(self, record: EmailRecord) -> dict[str, Any]: ...


_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "MEETING",
        re.compile(r"\b(?:schedule|reschedule|join|attend|invite(?:d|s)?|let'?s meet|meet tomorrow|meeting is (?:at|on)|calendar invite)\b", re.I),
        "meeting_coordination",
    ),
    (
        "DEADLINE",
        re.compile(r"\b(?:deadline|due\s+(?:date|by|on)|overdue|extension|extended deadline|submit\s+by|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?))\b", re.I),
        "explicit_deadline_cue",
    ),
    (
        "REPORT_REQUEST",
        re.compile(r"\b(?:please|could you|would you|can you|kindly)\s+(?:send|share|provide|submit|forward)\b[^.!?\n]{0,120}\b(?:report|document|draft|minutes|proposal|status|plan)\b", re.I),
        "explicit_document_request",
    ),
    (
        "DEPARTMENTAL_INPUT",
        re.compile(r"\b(?:please|could you|would you|can you)\s+(?:send|provide|share|submit)\b[^.!?\n]{0,100}\b(?:figures|input|updates|data)\b[^.!?\n]{0,80}\b(?:finance|hr|engineering|marketing|operations|department|team)\b", re.I),
        "explicit_department_input_request",
    ),
    (
        "ACTION_REQUEST",
        re.compile(r"\b(?:please|could you|would you|can you|kindly)\s+(?:review|update|prepare|complete|confirm|check|revise|organize|organise|send|call|contact|finish)\b", re.I),
        "explicit_operational_request",
    ),
    (
        "FOLLOW_UP",
        re.compile(r"\b(?:following up|follow up|checking in|reminder|just a reminder|still waiting|any update on|chasing)\b", re.I),
        "explicit_follow_up_cue",
    ),
    (
        "APPROVAL",
        re.compile(r"\b(?:please|could you|would you|can you|kindly)\s+(?:approve|sign off|authorize|authorise)\b", re.I),
        "explicit_approval_request",
    ),
    (
        "GENERAL_UPDATE",
        re.compile(r"\b(?:has been approved|has been moved|was moved|has been completed|has completed|is complete|is blocked|we completed|we submitted|we sent|decision is|the decision)\b", re.I),
        "explicit_state_change_cue",
    ),
)


def rule_baseline(record: EmailRecord) -> ReviewSuggestion:
    """Suggest candidate labels only; every result needs human review.

    The cues are retrieval aids rather than labels. They see only the current
    authored message, never the inherited subject or ``quoted_history``. No
    dates, people, owners, or extraction spans are inferred by this baseline.
    """
    cues: list[Cue] = []
    # Subject lines are often inherited by replies. They can provide context,
    # but must never independently trigger a label when the authored message
    # itself has no operational cue.
    field_name, text = "current_message", record.current_message
    matches_by_label = {
        label: list(pattern.finditer(text))
        for label, pattern, _rule_id in _RULES
    }
    # Avoid double counting one document request as a generic action, while
    # retaining a second independent action elsewhere in the authored text.
    document_action_spans = [
        (match.start(), match.end())
        for label in ("REPORT_REQUEST", "DEPARTMENTAL_INPUT", "APPROVAL")
        for match in matches_by_label[label]
    ]
    for label, _pattern, rule_id in _RULES:
        matches = matches_by_label[label]
        if label == "ACTION_REQUEST":
            matches = [
                match
                for match in matches
                if not any(start <= match.start() and match.end() <= end for start, end in document_action_spans)
            ]
        if matches:
            cue = Cue(label, field_name, matches[0].group(0), rule_id)
            if cue not in cues:
                cues.append(cue)
    labels = tuple(label for label in LABELS if any(cue.label == label for cue in cues))
    return ReviewSuggestion(
        method="RULE_BASELINE_V1",
        status="REVIEW" if labels else "ABSTAIN",
        labels=labels,
        evidence=tuple(cues),
    )


class ExistingAISilverClassifier:
    """Lazy wrapper over the repository's frozen diagnostic classifier.

    The caller must opt in. Scores and labels are always tagged as diagnostic
    and remain in review; this adapter does not train or tune any model.
    """

    name = "AI_SILVER_DIAGNOSTIC"

    def __init__(self, ai_root: str | Path) -> None:
        self.ai_root = Path(ai_root).resolve()
        self._predict_candidate = None
        self._decode = None
        self._labels: tuple[str, ...] = ()
        self._spec: dict[str, Any] | None = None

    @classmethod
    def from_repository(cls, repository_root: str | Path) -> "ExistingAISilverClassifier":
        return cls(Path(repository_root) / "ai")

    def _load(self) -> None:
        if self._spec is not None:
            return
        selection_path = self.ai_root / "annotation" / "optimization_final_selection.json"
        try:
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError("The frozen AI-silver selection manifest is unavailable.") from exc
        primary_run_id = selection.get("primary_run_id")
        candidates = selection.get("candidates", [])
        spec = next((item for item in candidates if item.get("run_id") == primary_run_id), None)
        if not isinstance(spec, dict):
            raise RuntimeError("The frozen AI-silver selection has no primary candidate.")
        ai_parent = str(self.ai_root)
        if ai_parent not in sys.path:
            sys.path.insert(0, ai_parent)
        try:
            from src.models.optimization_benchmark import LABEL_ORDER, decode
            from src.models.optimization_runtime import predict_candidate
        except ImportError as exc:
            raise RuntimeError(
                "AI-silver inference needs the AI environment dependencies; use ai/.venv or omit --ai-silver."
            ) from exc
        self._predict_candidate = predict_candidate
        self._decode = decode
        self._labels = tuple(LABEL_ORDER)
        self._spec = spec

    def predict(self, record: EmailRecord) -> dict[str, Any]:
        self._load()
        assert self._spec is not None and self._predict_candidate is not None and self._decode is not None
        row = {
            "subject": record.subject,
            "current_message": record.current_message,
            "authored_message": record.current_message,
        }
        try:
            probabilities = self._predict_candidate(self._spec, [row])
            labels = self._decode(
                probabilities,
                self._spec["thresholds"],
                self._spec["mode"],
                self._spec.get("fallback", False),
            )[0]
            scores = {name: float(value) for name, value in zip(self._labels, probabilities[0])}
        except Exception as exc:
            raise RuntimeError("The selected AI-silver diagnostic model could not score this message.") from exc
        # Guard against unexpected model labels entering product categories.
        allowed = {*LABELS, NON_PROJECT_LABEL}
        selected = tuple(label for label in labels if label in allowed)
        return {
            "method": self.name,
            "status": "REVIEW",
            "labels": selected,
            "scores": scores,
            "run_id": self._spec.get("run_id"),
            "human_gold": False,
            "review_required": True,
            "scope_uncertainty_available": False,
        }
