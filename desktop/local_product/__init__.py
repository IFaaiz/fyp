"""Offline email archive and review foundation."""

from .models import EmailRecord, LABELS, SCOPE_VALUES, SPAN_TYPES
from .store import EmailStore

__all__ = ["EmailRecord", "EmailStore", "LABELS", "SCOPE_VALUES", "SPAN_TYPES"]
