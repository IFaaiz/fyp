"""FYP Direct Label Schema V1.1 validation."""

from .validation import (
    EVALUATION_SPAN_TYPES,
    EXTRACTION_SPAN_TYPES,
    LABELS,
    PROJECT_LABELS,
    SCHEMA,
    SCHEMA_VERSION,
    SPAN_TYPES,
    SUPPORT_SPAN_TYPES,
    ValidationResult,
    validate_annotation,
)

__all__ = [
    "EVALUATION_SPAN_TYPES",
    "EXTRACTION_SPAN_TYPES",
    "LABELS",
    "PROJECT_LABELS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SPAN_TYPES",
    "SUPPORT_SPAN_TYPES",
    "ValidationResult",
    "validate_annotation",
]
