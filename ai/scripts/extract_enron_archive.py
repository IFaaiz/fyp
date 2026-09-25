"""Safely extract the downloaded CMU CALO Enron tarball into the ignored data tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


AI_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = AI_DIR / "data" / "raw" / "enron" / "enron_mail_20150507.tar.gz"
DEFAULT_TARGET = AI_DIR / "data" / "raw" / "enron" / "full"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_archive(archive_path: Path, target: Path) -> dict[str, object]:
    archive_path = archive_path.resolve()
    target = target.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"archive does not exist: {archive_path}")
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"target directory already contains data: {target}")

    staging = target.with_name(target.name + ".partial")
    staging.mkdir(parents=True, exist_ok=True)
    file_count = 0
    directory_count = 0
    uncompressed_bytes = 0
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe or linked archive member: {member.name!r}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"unsupported archive member type: {member.name!r}")
            if member.isfile():
                file_count += 1
                uncompressed_bytes += member.size
            else:
                directory_count += 1
        archive.extractall(staging, members=members, filter="data")

    maildir = staging / "maildir"
    if not maildir.is_dir():
        raise ValueError(f"archive extraction did not produce expected maildir directory: {maildir}")
    if target.exists():
        target.rmdir()
    staging.replace(target)
    return {
        "archive_path": archive_path.name,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "extracted_path": target.name,
        "maildir_relative_path": "maildir",
        "archive_members": len(members),
        "files_extracted": file_count,
        "directories_extracted": directory_count,
        "uncompressed_file_bytes": uncompressed_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument(
        "--stats-output", type=Path,
        help="optional JSON file for extraction counts and archive checksum",
    )
    args = parser.parse_args()
    result = extract_archive(args.archive, args.target)
    if args.stats_output:
        args.stats_output.parent.mkdir(parents=True, exist_ok=True)
        args.stats_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
