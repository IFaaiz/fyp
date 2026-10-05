"""Bounded gold-event-conditioned native MailEx span-link diagnostic."""

from .model import SpanLinkModel, propose_spans, token_span_bounds

__all__ = ["SpanLinkModel", "propose_spans", "token_span_bounds"]
