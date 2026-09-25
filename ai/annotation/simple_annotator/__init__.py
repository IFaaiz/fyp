"""Small, local-only Flask annotator for the Enron seed batch."""

from .app import create_app

__all__ = ["create_app"]
