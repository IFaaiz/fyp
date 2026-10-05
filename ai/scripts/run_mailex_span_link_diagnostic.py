"""Run the single preregistered native MailEx span-link diagnostic."""
from __future__ import annotations

import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_ROOT))

from src.mailex_span_link.training import run_experiment  # noqa: E402


if __name__ == "__main__":
    result = run_experiment()
    raise SystemExit(0 if result["status"] in {"complete", "incomplete_budget"} else 2)
