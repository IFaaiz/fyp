from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Iterator


@contextmanager
def temporary_directory() -> Iterator[str]:
    """Create test scratch under the writable, ignored desktop workspace."""
    scratch = Path(__file__).resolve().parents[1] / ".local" / "test-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as temp:
        yield temp
