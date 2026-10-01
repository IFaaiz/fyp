"""Download the official DistilBERT checkpoint to a local, hash-recorded snapshot.

Uses Hugging Face model metadata only to pin the current immutable revision,
then streams files from the official resolve URLs. Existing `.part` files are
resumed with HTTP Range requests. This script does not import PyTorch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MODEL_ID = "distilbert-base-uncased"
DEFAULT_DESTINATION = Path(__file__).resolve().parents[1] / "data/cache/distilbert-base-uncased"
CHUNK_BYTES = 1024 * 1024


def _request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Codex-FYP-transfer-diagnostic/1.0"})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(
    *, model_id: str, revision: str, filename: str, destination: Path,
    expected_size: int | None, expected_sha256: str | None,
) -> dict:
    url = f"https://huggingface.co/{model_id}/resolve/{revision}/{filename}?download=true"
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    if destination.exists():
        current_size = destination.stat().st_size
        current_sha = _sha256(destination)
        if (expected_size is None or current_size == expected_size) and (
            expected_sha256 is None or current_sha == expected_sha256
        ):
            return {"filename": filename, "bytes": current_size, "sha256": current_sha, "reused": True}
        destination.unlink()

    last_error: Exception | None = None
    for attempt in range(1, 6):
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "Codex-FYP-transfer-diagnostic/1.0"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=180) as response:
                status = getattr(response, "status", response.getcode())
                resume = existing > 0 and status == 206
                if existing and not resume:
                    existing = 0
                mode = "ab" if resume else "wb"
                with partial.open(mode) as stream:
                    downloaded = existing
                    last_report = downloaded
                    while True:
                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        stream.write(chunk)
                        downloaded += len(chunk)
                        if downloaded - last_report >= 16 * CHUNK_BYTES:
                            print(f"{filename}: {downloaded:,} bytes", flush=True)
                            last_report = downloaded
                    stream.flush()
                    os.fsync(stream.fileno())
            actual_size = partial.stat().st_size
            if expected_size is not None and actual_size != expected_size:
                raise IOError(f"incomplete {filename}: got {actual_size} bytes, expected {expected_size}")
            actual_sha = _sha256(partial)
            if expected_sha256 is not None and actual_sha != expected_sha256:
                raise IOError(f"SHA-256 mismatch for {filename}")
            partial.replace(destination)
            print(f"{filename}: complete ({actual_size:,} bytes)", flush=True)
            return {"filename": filename, "bytes": actual_size, "sha256": actual_sha, "reused": False}
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            print(f"{filename}: attempt {attempt}/5 failed ({type(exc).__name__})", flush=True)
            if attempt < 5:
                time.sleep(min(attempt * 3, 12))
    raise RuntimeError(f"failed to download {filename}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)

    metadata = _request_json(f"https://huggingface.co/api/models/{args.model_id}?blobs=true")
    revision = metadata.get("sha")
    if not isinstance(revision, str) or not revision:
        raise RuntimeError("official model metadata did not provide an immutable revision")
    siblings = {row["rfilename"]: row for row in metadata.get("siblings", []) if isinstance(row, dict) and row.get("rfilename")}
    required = {"config.json"}
    weight_name = "model.safetensors" if "model.safetensors" in siblings else "pytorch_model.bin"
    required.add(weight_name)
    if "vocab.txt" in siblings:
        required.add("vocab.txt")
    if "tokenizer.json" in siblings:
        required.add("tokenizer.json")
    for optional in ("tokenizer_config.json", "special_tokens_map.json", "added_tokens.json"):
        if optional in siblings:
            required.add(optional)
    missing = sorted(name for name in required if name not in siblings)
    if missing:
        raise RuntimeError(f"official checkpoint is missing required files: {missing}")

    results = []
    for filename in sorted(required):
        entry = siblings[filename]
        lfs = entry.get("lfs") or {}
        expected_sha = lfs.get("sha256") or lfs.get("oid")
        if isinstance(expected_sha, str) and expected_sha.startswith("sha256:"):
            expected_sha = expected_sha.removeprefix("sha256:")
        if isinstance(expected_sha, str) and len(expected_sha) != 64:
            expected_sha = None
        results.append(_download_file(
            model_id=args.model_id,
            revision=revision,
            filename=filename,
            destination=args.destination / filename,
            expected_size=entry.get("size") or lfs.get("size"),
            expected_sha256=expected_sha,
        ))

    report = {
        "model_id": args.model_id,
        "revision": revision,
        "source": "official Hugging Face immutable resolve URLs",
        "destination": str(args.destination.resolve()),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "files": results,
    }
    manifest_path = args.destination / "checkpoint_manifest.json"
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

