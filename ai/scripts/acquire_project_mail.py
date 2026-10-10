"""Acquire bounded reviewed public archives and mine blank human candidates."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import sys

AI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI))
from src.project_mail.pipeline import acquire, group_templates, join_threads, parse_archive, select, write_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=AI / "config/project_mail_sources_2026-10.json")
    parser.add_argument("--output-dir", type=Path, default=AI / "data/project_mail/2026-10-10")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--offline", action="store_true", help="Use only existing downloaded source bytes.")
    args = parser.parse_args()
    # Corpus outputs must remain within Git-ignored local ai/data.
    out = args.output_dir.resolve()
    if not out.is_relative_to((AI / "data").resolve()):
        parser.error("Corpus output must stay inside ignored ai/data.")
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    rows, sources, failures = [], [], []
    for spec in config["sources"]:
        try:
            if not re.fullmatch(r"[a-z0-9_]+", spec["name"]):
                raise ValueError("Source name must be a safe lowercase filename slug.")
            suffix = ".html" if spec["format"] == "w3c_html" else ".mbox"
            target = out / "raw" / (spec["name"] + suffix)
            if args.offline and not target.exists():
                raise ValueError("Source absent from offline cache.")
            acquired = acquire(spec, target, max_bytes=300_000 if suffix == ".html" else 8_000_000)
            rows.extend(parse_archive(target, spec, acquired["retrieved_at"]))
            sources.append(acquired)
        except Exception as error:
            failures.append({"source": spec["name"], "error": str(error)})
    if not rows:
        print(json.dumps({"acquisitions": sources, "failures": failures, "selected": 0}))
        return 1
    join_threads(rows)
    group_templates(rows)
    selected, summary = select(rows, limit=args.limit)
    write_jsonl(out / "normalized.jsonl", rows)
    write_jsonl(out / "candidates.jsonl", selected)
    # A manifest may contain raw Message-IDs/URLs: keep it local, too.
    manifest = [{k: r[k] for k in ("source_id", "source_name", "project_or_list", "source_url_or_reference", "source_sha256", "raw_message_sha256", "thread_id", "leakage_group", "acquisition_sampling_frame", "sampling_track", "split", "mining", "metadata_quality", "provenance", "license_or_terms_note", "labels", "spans", "scope", "annotation_method", "annotation_tier")} for r in selected]
    write_jsonl(out / "candidate_manifest.jsonl", manifest)
    summary["acquisitions"] = sources
    summary["acquisition_failures"] = failures
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
