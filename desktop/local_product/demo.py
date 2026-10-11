"""Explicit synthetic workflow examples; never a mailbox or evaluation corpus."""
from .models import EmailRecord


def seed_demo(store):
    examples = (
        ("request", "Please send the design report by Friday 2026-10-16.\nSchedule the design meeting for Tuesday 2026-10-13."),
        ("extend", "Extend the design report deadline to Monday 2026-10-19."),
        ("reassign", "Assign the design report to Alex instead of Sam."),
        ("delivery", "The design report is attached. Please confirm receipt."),
    )
    return store.import_records([
        EmailRecord(source_id=f"synthetic-workflow:{key}", source_name="SYNTHETIC_WORKFLOW_DEMO",
            thread_id="synthetic-design-conversation", message_id=f"<{key}@synthetic.invalid>",
            subject="Synthetic design project", sender="demo@synthetic.invalid",
            recipients=["reviewer@synthetic.invalid"], body_raw=body, current_message=body,
            timestamp=f"2026-10-{12 + index:02}T09:00:00+05:00", timestamp_kind="sent",
            attachment_names=["synthetic-design-report.docx"] if key == "delivery" else [],
            provenance={"synthetic": True, "purpose": "functional demonstration, not training/gold"})
        for index, (key, body) in enumerate(examples)
    ])
