"""Internal, evidence-grounded annotation schema and FYP label mapper.

This package is deliberately separate from the public canonical annotation
contract in ``ai/annotation/label_schema.json``.
"""

from .mapper import LABELS, MappingResult, map_labels
from .validation import ValidationResult, validate_annotation

__all__ = [
    "LABELS",
    "MappingResult",
    "ValidationResult",
    "map_labels",
    "validate_annotation",
]
