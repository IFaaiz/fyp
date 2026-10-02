"""Acquire the official CMU Airspace v1.0 archive and syntax document."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.datasets.airspace import (  # noqa: E402
    ARCHIVE_URL,
    METHODOLOGY_URL,
    OFFICIAL_PAGE,
    SYNTAX_URL,
    VERSION,
    sha256_file,
)


USER_AGENT = "FYP-Airspace-dataset-acquisition/1.0"
# Locally observed official bytes, not a publisher-provided checksum.
PINNED_SHA256 = {
    "archive": "04f8c82dc96ca00d565b5598e73424e35dbac4692ffa4d98271fe0c54bcc31a7",
    "syntax_document": "a7471383aaf08455035b6e25fe48ca83b4c14708020bb4aa0033a092734922f2",
}


def _fetch(url: str, target: Path, *, timeout: int = 120) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("cmu.edu"):
        raise ValueError(f"refusing non-CMU or non-HTTPS source: {url}")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=timeout) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or not final.hostname or not final.hostname.endswith("cmu.edu"):
            raise ValueError(f"official URL redirected outside HTTPS CMU: {response.geturl()}")
        with target.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        return response.geturl()


def acquire(raw_dir: Path) -> dict[str, object]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    assets = {
        "archive": (ARCHIVE_URL, raw_dir / "Airspace_wargaming_1.0.zip"),
        "syntax_document": (SYNTAX_URL, raw_dir / "README_EmailSyntax_1.0.pdf"),
    }
    results: dict[str, dict[str, object]] = {}
    for key, (url, target) in assets.items():
        downloaded_url = url
        downloaded = False
        if not target.exists():
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}-", suffix=".part", dir=raw_dir)
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                downloaded_url = _fetch(url, temp_path)
                if temp_path.stat().st_size == 0:
                    raise RuntimeError(f"official endpoint returned an empty file: {url}")
                if sha256_file(temp_path) != PINNED_SHA256[key]:
                    raise ValueError(f"official asset differs from reviewed release: {key}; investigate a new version separately")
                os.replace(temp_path, target)
                downloaded = True
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
        actual_hash = sha256_file(target)
        if actual_hash != PINNED_SHA256[key]:
            raise ValueError(f"existing immutable asset differs from reviewed release: {key}")
        results[key] = {
            "url": url,
            "final_url": downloaded_url,
            "path": str(target.resolve()),
            "bytes": target.stat().st_size,
            "sha256": actual_hash,
            "downloaded_this_run": downloaded,
            "file_mtime_utc": datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat(),
        }

    archive_mtime = Path(results["archive"]["path"]).stat().st_mtime  # type: ignore[arg-type]
    manifest: dict[str, object] = {
        "dataset": "airspace",
        "version": VERSION,
        "acquired_at_utc": datetime.fromtimestamp(archive_mtime, timezone.utc).isoformat(),
        "official_page": OFFICIAL_PAGE,
        "archive_url": ARCHIVE_URL,
        "syntax_document_url": SYNTAX_URL,
        "methodology_citation_url": METHODOLOGY_URL,
        "terms": {
            "redistribution_permitted": False,
            "preserve_and_report_version": True,
            "cite_methodology_paper_and_official_page": True,
            "send_resulting_publication_references_to": "steinfeld@cmu.edu",
            "fabricated_content_share_stated_by_cmu": ">90%",
        },
        "assets": results,
    }
    manifest_path = raw_dir / "acquisition.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path.resolve())
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=AI_DIR / "data" / "raw" / "airspace")
    args = parser.parse_args()
    result = acquire(args.raw_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
