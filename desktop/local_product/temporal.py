"""Lossless timestamp classification: ambiguity never becomes an instant."""
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import re


def timestamp_info(value: str | None) -> dict:
    result = {"original": value, "kind": "missing", "utc": None}
    if not value or not value.strip():
        return result
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            date.fromisoformat(text)
            result["kind"] = "date_only"
            return result
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            result["kind"] = "naive"
        else:
            result.update(kind="aware", utc=parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
    except (ValueError, TypeError, OverflowError):
        result["kind"] = "malformed"
    return result
