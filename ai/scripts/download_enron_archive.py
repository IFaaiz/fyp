"""Resumably download the official CMU CALO Enron tarball using HTTP ranges."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OFFICIAL_URL = "https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz"
EXPECTED_SIZE = 443_254_787
AI_DIR = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_chunk(
    *, url: str, chunk_path: Path, start: int, end: int, total_size: int,
    retries: int = 5,
) -> Path:
    expected = end - start + 1
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        have = chunk_path.stat().st_size if chunk_path.exists() else 0
        if have == expected:
            return chunk_path
        if have > expected:
            chunk_path.unlink()
            have = 0
        request_start = start + have
        request_end = end
        request = Request(
            url,
            headers={
                "Range": f"bytes={request_start}-{request_end}",
                "Accept-Encoding": "identity",
                "User-Agent": "FYP-Enron-archive-fetch/1.0",
            },
        )
        try:
            with urlopen(request, timeout=120) as response:
                if response.status != 206:
                    raise RuntimeError(f"expected HTTP 206, received {response.status}")
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if not match or tuple(map(int, match.groups())) != (request_start, request_end, total_size):
                    raise RuntimeError(f"unexpected Content-Range: {content_range!r}")
                remaining = request_end - request_start + 1
                with chunk_path.open("ab" if have else "wb") as output:
                    while remaining:
                        block = response.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ConnectionError("connection ended before the requested range completed")
                        output.write(block)
                        remaining -= len(block)
            if chunk_path.stat().st_size == expected:
                return chunk_path
            raise ConnectionError(f"incomplete chunk: {chunk_path.stat().st_size}/{expected} bytes")
        except (HTTPError, URLError, TimeoutError, ConnectionError, RuntimeError) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"failed range {start}-{end}: {exc}") from exc
            time.sleep(min(2 ** attempt, 30))
    raise AssertionError("unreachable")


def acquire_archive(
    output: Path, *, url: str = OFFICIAL_URL, total_size: int = EXPECTED_SIZE,
    chunk_size: int = 8 * 1024 * 1024, workers: int = 12,
) -> dict[str, object]:
    if output.exists() and output.stat().st_size == total_size:
        return {
            "url": url,
            "archive": str(output),
            "bytes": total_size,
            "sha256": _sha256(output),
            "already_complete": True,
        }
    if chunk_size <= 0 or workers <= 0 or total_size <= 0:
        raise ValueError("chunk size, workers, and total size must be positive")

    parts_dir = output.with_name(output.name + ".parts")
    ranges = [
        (start, min(start + chunk_size, total_size) - 1)
        for start in range(0, total_size, chunk_size)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    finished_bytes = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_chunk,
                url=url,
                chunk_path=parts_dir / f"{start:012d}-{end:012d}.part",
                start=start,
                end=end,
                total_size=total_size,
            ): (start, end)
            for start, end in ranges
        }
        for future in as_completed(futures):
            start, end = futures[future]
            path = future.result()
            finished_bytes += path.stat().st_size
            print(f"completed range {start}-{end}; {finished_bytes}/{total_size} bytes ready", flush=True)

    assembling = output.with_name(output.name + ".assembling")
    with assembling.open("wb") as target:
        for start, end in ranges:
            part = parts_dir / f"{start:012d}-{end:012d}.part"
            if part.stat().st_size != end - start + 1:
                raise RuntimeError(f"part size mismatch: {part}")
            with part.open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    size = assembling.stat().st_size
    if size != total_size:
        raise RuntimeError(f"assembled archive size {size} != expected {total_size}")
    digest = _sha256(assembling)
    assembling.replace(output)
    return {
        "url": url,
        "archive": str(output),
        "bytes": size,
        "sha256": digest,
        "already_complete": False,
        "parts_directory": str(parts_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=AI_DIR / "data" / "raw" / "enron" / "enron_mail_20150507.tar.gz",
    )
    parser.add_argument("--url", default=OFFICIAL_URL)
    parser.add_argument("--total-size", type=int, default=EXPECTED_SIZE)
    parser.add_argument("--chunk-size", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    try:
        result = acquire_archive(
            args.output,
            url=args.url,
            total_size=args.total_size,
            chunk_size=args.chunk_size,
            workers=args.workers,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
