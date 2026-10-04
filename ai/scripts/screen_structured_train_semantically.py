"""Rank isolated TRAIN sources for review with an offline pretrained encoder.

Scores are retrieval hints, never annotations, model supervision or predictions.
No EVAL source, old experiment checkpoint or accepted label is consumed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai"))
from src.structured_annotation.workflow import (  # noqa: E402
    _load_boundary, _normalize_record, _verify_candidate_index_fingerprint,
    _verify_train_isolation, sha256_file,
)

QUERIES = {
    "ACTION": "Project team, please complete the assigned implementation task and tell us who is responsible.",
    "DOCUMENT_REQUEST": "Please send the revised project report, estimates, presentation or minutes of meeting.",
    "DEPARTMENT_INPUT": "Finance and Engineering, please provide your departments' inputs for the project deliverable.",
    "APPROVAL": "Please authorize the project change or approve this deliverable before work proceeds.",
    "FOLLOW_UP": "Following up on the project report previously requested: it is still missing; please send it.",
    "MEETING": "The project review meeting is scheduled; let us arrange a call to discuss implementation and next steps.",
    "DEADLINE": "The project task and revised deliverable must be completed and submitted by Friday.",
    "STATUS": "Project implementation is progressing; testing is complete, and the revised documents are attached.",
    "NON_PROJECT_HARD_NEGATIVE": "Routine business administration, a recruitment advertisement, an industry newsletter or a personal lunch invitation.",
}


def windows(row):
    """Head/middle/tail retrieval views; reviewers still read the entire source."""
    subject = row.get("subject", "")
    body = row["current_message"]
    starts = sorted({0, max(0, (len(body) - 1200) // 2), max(0, len(body) - 1200)})
    return [subject + "\n" + body[start:start + 1200] for start in starts]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--boundary", required=True, type=Path)
    p.add_argument("--index", required=True, type=Path)
    p.add_argument("--encoder", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    output = args.output_dir.resolve()
    if (ROOT / "ai/data").resolve() not in output.parents:
        raise ValueError("Retrieval output must stay in private ai/data")
    if output.exists():
        raise FileExistsError("Use a new immutable retrieval output directory")
    index, boundary, index_sha, boundary_sha = _load_boundary(
        index_path=args.index, assignments_path=args.boundary, dataset_id="enron", root=ROOT)
    _verify_train_isolation(index, boundary)
    source_sha = sha256_file(args.source)
    if source_sha != boundary["train_screen_candidates_sha256"]:
        raise ValueError("Source file is not the frozen TRAIN screen")
    rows = [json.loads(line) for line in args.source.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    ids = [row["source_id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate source IDs")
    for row in rows:
        qualified = "enron:" + row["source_id"]
        if boundary["partitions"].get(qualified) != "TRAIN_SCREEN":
            raise ValueError("Source outside TRAIN_SCREEN")
        _verify_candidate_index_fingerprint(
            normalized_record=_normalize_record(row), index_record=index["records"][qualified])

    # Loading local bytes only prevents a silent network model/version change.
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer
    encoder = args.encoder.resolve()
    if not encoder.is_dir():
        raise FileNotFoundError("Encoder must be an existing local snapshot")
    encoder_hashes = {f.relative_to(encoder).as_posix(): sha256_file(f)
                      for f in sorted(encoder.rglob("*")) if f.is_file()}
    tokenizer = AutoTokenizer.from_pretrained(encoder, local_files_only=True)
    model = AutoModel.from_pretrained(encoder, local_files_only=True).eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    torch.set_num_threads(4)

    def encode(texts):
        parts = []
        with torch.inference_mode():
            for start in range(0, len(texts), 32):
                batch = tokenizer(texts[start:start + 32], padding=True, truncation=True,
                                  max_length=256, return_tensors="pt").to(device)
                hidden = model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
                parts.append(pooled.cpu().numpy())
        return np.concatenate(parts)

    query_vectors = encode(list(QUERIES.values()))
    views = []
    bounds = []
    for row in rows:
        start = len(views)
        views.extend(windows(row))
        bounds.append((start, len(views)))
    vectors = encode(views)
    similarities = vectors @ query_vectors.T
    scores = np.stack([similarities[start:end].max(axis=0) for start, end in bounds])
    ranks = {}
    for j, name in enumerate(QUERIES):
        ranks[name] = sorted(range(len(rows)), key=lambda i: (-float(scores[i, j]), ids[i]))
    # Round-robin strata avoid returning one homogeneous top-score bucket.
    selected = []
    used = set()
    for position in range(len(rows)):
        for name in QUERIES:
            i = ranks[name][position]
            if i not in used:
                selected.append(i)
                used.add(i)
    if sha256_file(args.source) != source_sha or sha256_file(args.boundary) != boundary_sha or sha256_file(args.index) != index_sha:
        raise ValueError("Source or isolation snapshot changed during retrieval")
    if any(sha256_file(encoder / name) != digest for name, digest in encoder_hashes.items()):
        raise ValueError("Encoder bytes changed during retrieval")
    output.mkdir(parents=True)
    with (output / "scores.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for i, row in enumerate(rows):
            stream.write(json.dumps({"source_id": ids[i], "original_index": i,
                         "retrieval_scores": {name: float(scores[i, j]) for j, name in enumerate(QUERIES)}}) + "\n")
    manifest = {
        "status": "unreviewed_train_retrieval_only", "source_sha256": source_sha,
        "boundary_sha256": boundary_sha, "index_sha256": index_sha,
        "records_screened": len(rows), "views_encoded": len(views),
        "encoder_path": str(encoder), "encoder_file_hashes": encoder_hashes,
        "queries": QUERIES, "stratum_rankings": ranks, "diverse_review_order": selected,
        "scores_sha256": sha256_file(output / "scores.jsonl"),
        "max_tokens": 256, "window_chars": 1200, "pooling": "attention_mask_mean_l2",
        "selection": "per_query_max_over_head_middle_tail_then_round_robin_unique",
        "accepted_annotations": 0, "evaluation_consumed": False, "model_fit": False,
        "limitations": ["Retrieval similarity does not establish project scope or primitive truth",
                       "Partial retrieval windows can emphasize quoted content; full source review is mandatory",
                       "Stratum overlap and domain bias remain; quotas do not imply accepted positives"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ["status", "records_screened", "views_encoded", "accepted_annotations", "evaluation_consumed", "model_fit"]}))


if __name__ == "__main__":
    main()
