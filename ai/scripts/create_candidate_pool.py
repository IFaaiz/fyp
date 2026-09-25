"""Build a capped Enron annotation pool with cue, thread, and sampling reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

AI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AI_DIR.parent
sys.path.insert(0, str(AI_DIR))

from src.datasets.candidate_filter import write_candidate_pool  # noqa: E402


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def make_report(stats: dict[str, Any], output: Path, metadata: str) -> str:
    lines = [
        "# Enron candidate pool report",
        "",
        f"- Canonical input records: {stats['input_records']:,}",
        f"- Input threads: {stats['input_threads']:,}",
        f"- Cue candidates available: {stats['keyword_candidates']:,}",
        f"- Direct matches available: {stats['direct_candidates_available']:,}",
        f"- Context only candidates available: {stats['context_only_candidates_available']:,}",
        f"- No cue records available: {stats['nonkeyword_available']:,}",
        f"- Selected records: {stats['records_selected']:,} (target {stats['target_count']:,}; overage {stats['target_exceeded']:,})",
        f"- Selected direct matches: {stats['selected_direct_matches']:,}",
        f"- Selected context only matches: {stats['selected_context_only_matches']:,}",
        f"- Selected random nonmatches: {stats['selected_random_nonmatching']:,} (requested {stats['random_sample_target']:,})",
        f"- Selected thread expansion records: {stats['selected_thread_expansion']:,}",
        f"- Multi cue records: {stats['multi_cue_records']['selected']:,} selected / {stats['multi_cue_records']['available']:,} available",
        f"- Thread-ID groups: {stats['threads_selected']:,} selected; {stats['full_threads_selected']:,} fully selected groups; {stats['partial_threads_selected']:,} partial groups ({stats['partial_thread_proportion']:.1%} partial)",
        f"- Selection mode: {stats['thread_mode']} — {stats['thread_cap_semantics']}",
        f"- Secondary thread suggestions enabled: {stats['secondary_thread_linking']['enabled']}",
        f"- Input pairs suggested: {stats['secondary_thread_linking']['suggested_pairs']:,} "
        f"({stats['secondary_thread_linking']['suggested_records']:,} records; "
        f"confidence {stats['secondary_thread_linking']['confidence'] or 'not used'})",
        f"- Eligible singleton rows / buckets: {stats['secondary_thread_linking'].get('eligible_singleton_rows', 0):,} / "
        f"{stats['secondary_thread_linking'].get('normalized_subject_buckets', 0):,}",
        f"- Oversized subject buckets skipped: {stats['secondary_thread_linking'].get('oversized_subject_buckets_skipped', 0):,} "
        f"({stats['secondary_thread_linking'].get('oversized_subject_records_skipped', 0):,} records)",
        f"- Link coverage among eligible rows: {stats['secondary_thread_linking'].get('one_to_one_coverage_of_eligible_rows', 0.0):.2%}",
        f"- Deterministic seed: {stats['seed']}",
        f"- Candidate pool JSONL: {display_path(output)}",
        f"- Sampling metadata sidecar: {metadata}",
        "",
        "## Thread sizes",
        "",
        f"> {stats['thread_completeness_note']}",
        "",
        "| Measure | Input thread-ID groups | Selected thread-ID groups |",
        "| --- | ---: | ---: |",
        f"| Minimum | {stats['input_thread_sizes']['min']:,} | {stats['selected_thread_sizes']['min']:,} |",
        f"| Median | {stats['input_thread_sizes']['median']:,} | {stats['selected_thread_sizes']['median']:,} |",
        f"| 90th percentile | {stats['input_thread_sizes']['p90']:,} | {stats['selected_thread_sizes']['p90']:,} |",
        f"| Maximum | {stats['input_thread_sizes']['max']:,} | {stats['selected_thread_sizes']['max']:,} |",
        "",
        "## Sampling category coverage",
        "",
        "| Category | Available | Selected with any category cue | Primary-category selections | Coverage |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    from src.datasets.candidate_filter import CATEGORY_LABELS
    for category, counts in stats["sampling_category_counts"].items():
        available = counts["available"]
        selected = counts["selected"]
        coverage = f"{selected / available:.1%}" if available else "—"
        lines.append(
            f"| {CATEGORY_LABELS[category]} | {available:,} | {selected:,} "
            f"| {counts['primary_selected']:,} | {coverage} |"
        )
    category_counts = stats["sampling_category_counts"]
    primary_selected = sum(
        counts["primary_selected"]
        for category, counts in category_counts.items()
        if category != "random"
    )
    random_selected = category_counts.get("random", {}).get("primary_selected", 0)
    expansion_selected = stats["selected_thread_expansion"]
    unique_selected = primary_selected + random_selected + expansion_selected
    lines.extend([
        "",
        "Counts for Selected with any category cue can overlap because one record may match multiple categories. Primary-category selections are exclusive: "
        f"{primary_selected:,} primary-category rows + {random_selected:,} random rows + "
        f"{expansion_selected:,} thread-expansion rows = {unique_selected:,} unique selected rows.",
    ])
    risk = stats["cue_recall_risk"]
    lines.extend([
        "",
        "## Candidate recall risk",
        "",
        f"- Nonempty current_message but empty authored prefix after quote trimming: {risk['nonempty_current_message_empty_authored_prefix']:,} / {stats['input_records']:,}.",
        f"- Records with any raw lexical cue: {risk['raw_keyword_hit_records']:,}; remaining direct candidates after quote trimming and precision guards: {risk['post_trim_guarded_candidate_records']:,}.",
        f"- Records losing cues at quote trimming: {risk['records_losing_any_cue_at_quote_trim']:,}; records losing cues at precision guards: {risk['records_losing_any_cue_at_precision_guard']:,}.",
        "",
        "Quote trimming can miss a task if it appears only inside forwarded or quoted text. Precision guards can suppress implicit or subject-only tasks. These are potential candidate-recall risks; the affected records are not known false negatives.",
        "",
        "| Cue | Lost at quote trimming | Suppressed by precision guards |",
        "| --- | ---: | ---: |",
    ])
    for cue in sorted(set(risk["cue_instances_lost_at_quote_trim"]) |
                      set(risk["cue_instances_suppressed_by_precision_guard"])):
        lines.append(
            f"| {cue} | {risk['cue_instances_lost_at_quote_trim'].get(cue, 0):,} "
            f"| {risk['cue_instances_suppressed_by_precision_guard'].get(cue, 0):,} |"
        )
    lines.extend([
        "",
        "## Qualitative cue audit",
        "",
        "Manual review across two rounds and multiple sampled records in each category found useful examples such as meeting reschedules, explicit deadlines, and approval requests, alongside noise from blood-drive meetings, market and execution notices, Datek margin calls, Economist HTML, newsletters, access requests, generic report attachments, mailing-list notices, product ads, and attachment-list removal requests. Follow-up subjects without task context also produced hits. Duplicate-looking records with identical bodies can remain as separate candidates when they have distinct source Message-IDs; the canonical identity contract is ID-based, so review pools may still contain near-duplicates.",
        "",
        "The random stratum means no current cue matched; it is not a set of verified negatives. It contains implicit actions (for example, requests to discuss something), meeting messages including a subject abbreviated ‘Mtg’, and ordinary personal mail.",
        "",
        "When secondary linking is enabled, derived thread IDs group only strict one-to-one heuristic pairs. The output preserves each original ID in source_thread_id, marks thread_link_method='heuristic' and thread_link_confidence='high_unverified', and adds prior-message context to the later record. The rule confidence is uncalibrated; it does not recover all real conversations.",
        "",
        "## Fine-grained cue coverage",
        "",
        "| Cue | Direct available | Direct selected | Context available | Context selected | Unique available | Unique selected | Coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for cue, counts in stats["cue_counts"].items():
        available = counts["unique_available"]
        selected = counts["unique_selected"]
        coverage = f"{selected / available:.1%}" if available else "—"
        lines.append(
            f"| {cue} | {counts['direct_available']:,} | {counts['direct_selected']:,} "
            f"| {counts['context_available']:,} | {counts['context_selected']:,} "
            f"| {available:,} | {selected:,} | {coverage} |"
        )
    lines.extend([
        "",
        "## Sender distribution",
        "",
        "Selected sender counts by rank (addresses omitted):",
        "",
    ])
    for rank, count in enumerate(stats["senders_selected_top_50"].values(), start=1):
        lines.append(f"- Rank {rank}: {count:,}")
    lines.extend([
        "",
        "Input sender counts by rank, top 50 (addresses omitted):",
        "",
    ])
    for rank, count in enumerate(stats["senders_input_top_50"].values(), start=1):
        lines.append(f"- Rank {rank}: {count:,}")
    lines.extend([
        "",
        "Keyword cues and random sampling strata are review-sampling aids. They do not assign project labels; the canonical record labels and annotation status remain unchanged.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=AI_DIR / "data" / "interim" / "enron.jsonl",
        help="canonical Enron JSONL (default: %(default)s)",
    )
    parser.add_argument(
        "--output", type=Path,
        default=AI_DIR / "data" / "interim" / "enron_candidates.jsonl",
        help="candidate pool JSONL (default: %(default)s)",
    )
    parser.add_argument("--target-count", type=int, default=8000)
    parser.add_argument("--random-sample-count", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--secondary-thread-links", action="store_true",
        help="write a derived pool with strict one-to-one heuristic thread suggestions",
    )
    parser.add_argument(
        "--thread-mode", choices=("fit", "whole"), default="fit",
        help="fit enforces the record cap and marks partial threads; whole may exceed the target",
    )
    parser.add_argument(
        "--require-whole-threads", action="store_true",
        help="alias for --thread-mode whole for complete-thread annotation batches",
    )
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument(
        "--report", type=Path,
        default=AI_DIR / "reports" / "enron_candidate_pool.md",
    )
    args = parser.parse_args()
    mode = "whole" if args.require_whole_threads else args.thread_mode
    stats = write_candidate_pool(
        args.input, args.output,
        random_sample_count=args.random_sample_count, seed=args.seed,
        target_count=args.target_count, thread_mode=mode,
        metadata_jsonl=args.metadata,
        use_secondary_thread_links=args.secondary_thread_links,
    )
    metadata_display = stats["metadata_jsonl"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(make_report(stats, args.output, metadata_display), encoding="utf-8")
    stats["report_markdown"] = display_path(args.report)
    stats_path = args.output.with_suffix(".stats.json")
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": display_path(args.output),
        "metadata": metadata_display,
        "stats": display_path(stats_path),
        "report": display_path(args.report),
        **stats,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
