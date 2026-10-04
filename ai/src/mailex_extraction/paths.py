"""Resolve local caches in historical root- and ai-relative configurations."""
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def resolve_local_encoder(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    candidates = [path] if path.is_absolute() else [
        REPOSITORY_ROOT / path, REPOSITORY_ROOT / "ai" / path,
    ]
    existing = {candidate.resolve() for candidate in candidates if candidate.is_dir()}
    if len(existing) != 1:
        raise ValueError(f"Local encoder cache must resolve uniquely: {value!r}")
    return existing.pop()
