"""Product facts/changes are versioned separately from direct-label annotation."""
from datetime import date
from .temporal import timestamp_info

SCHEMA = "fyp-project-item-v1"
KINDS = ("TASK", "MEETING", "DOCUMENT_REQUEST", "DEPARTMENTAL_INPUT", "APPROVAL", "FOLLOW_UP")
STATUSES = ("OPEN", "IN_PROGRESS", "DELIVERED", "COMPLETED", "CANCELLED")
FIELDS = ("project_id", "kind", "title", "owner", "department", "due", "due_text", "requested_document", "status")


def validate_fields(value: dict, *, partial: bool = False) -> dict:
    if not isinstance(value, dict) or set(value) - set(FIELDS):
        raise ValueError("Unsupported project-item fields")
    if any(not isinstance(v, str) or len(v) > 2000 for v in value.values()):
        raise ValueError("Item fields must be bounded strings")
    result = dict(value)
    if not partial:
        result = {"project_id": "default", "kind": "TASK", "title": "", "owner": "", "department": "",
                  "due": "", "due_text": "", "requested_document": "", "status": "OPEN", **result}
    for key in ("project_id", "title"):
        if key in result and not result[key].strip():
            raise ValueError(f"{key} must not be blank")
    if "kind" in result and result["kind"] not in KINDS:
        raise ValueError("Unsupported project item kind")
    if "status" in result and result["status"] not in STATUSES:
        raise ValueError("Unsupported project item status")
    if result.get("due"):
        info = timestamp_info(result["due"])
        if info["kind"] not in {"aware", "date_only"}:
            raise ValueError("Due must be an ISO date or timezone-aware ISO timestamp")
        # For due facts use ISO only, never import permissive RFC mail dates.
        try:
            if info["kind"] == "date_only":
                date.fromisoformat(result["due"])
            else:
                from datetime import datetime
                datetime.fromisoformat(result["due"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Due must be ISO formatted") from exc
    return result
