"""Readable review evidence and history, retaining exact source text."""

FIELD_LABELS = {
    "project_id": "Project", "kind": "Kind", "title": "Title", "owner": "Owner",
    "department": "Department", "due": "Confirmed due date", "due_text": "Source date phrase",
    "requested_document": "Requested document", "status": "Status",
}
FLAG_LABELS = {
    "OWNER_UNASSIGNED": "Owner is unassigned",
    "DUE_NOT_NORMALIZED": "Confirm the date phrase before setting a due date",
    "DUE_UNRESOLVED": "No confirmed due date",
    "SEGMENTATION_UNCERTAIN": "Authored text is uncertain; compare the original source",
    "PROJECTION_MISMATCH": "Current text differs from the raw-body projection; check the source",
}


def evidence_text(evidence, *, source_id="", revision=None):
    if not isinstance(evidence, dict):
        return "No email span attached to this reversal. See the prior decision."
    return (f"Source: {source_id} · revision {revision}\n"
            f"Exact {evidence.get('field', 'source')} characters {evidence.get('start')}–{evidence.get('end')} (end excluded):\n\n"
            + str(evidence.get("text", "")))


def candidate_text(candidate):
    target = candidate.get("target_item_id")
    return ((f"Update item: {target}\n" if target else "Creates a separate project item.\n")
            + evidence_text(candidate.get("evidence"), source_id=candidate.get("source_id", ""),
                            revision=candidate.get("source_revision")))


def item_text(item):
    fields = item.get("fields", {})
    lines = ["Current approved fields", ""]
    lines.extend(f"{label}: {fields.get(key) or 'Unspecified'}" for key, label in FIELD_LABELS.items())
    lines.extend(["", "Review history", ""])
    for event in item.get("history", []):
        lines.append(f"Version {event.get('version')} · {event.get('action')} · {event.get('timestamp') or event.get('created_at', '')}")
        if event.get("note"):
            lines.append("Review note: " + event["note"])
        for key, change in event.get("diff", {}).items():
            lines.append(f"{FIELD_LABELS.get(key, key)}: {change.get('before') or 'Unspecified'} → {change.get('after') or 'Unspecified'}")
        lines.append(evidence_text(event.get("evidence"), source_id=event.get("source_id", ""), revision=event.get("source_revision")))
        lines.append("")
    return "\n".join(lines)
