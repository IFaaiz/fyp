"""Fetch the two pinned official sentence-transformer checkpoints for the optimization run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download


AI_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = AI_DIR / "data/cache/sentence-transformers"
MODEL_IDS = (
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-mpnet-base-v2",
)
MODEL_FILES = [
    "config.json", "config_sentence_transformers.json", "sentence_bert_config.json",
    "modules.json", "1_Pooling/config.json", "2_Normalize/config.json",
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "vocab.txt", "vocab.json", "merges.txt", "model.safetensors",
]
PINNED_MODEL_FILES = set(MODEL_FILES) | {"1_Pooling/config.json", "2_Normalize/config.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", choices=("minilm", "mpnet", "all"), default="all")
    args = parser.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output = CACHE_DIR / "optimization_embedding_checkpoints.json"
    results = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else []
    selected_ids = MODEL_IDS if args.encoder == "all" else (
        "sentence-transformers/all-MiniLM-L6-v2" if args.encoder == "minilm"
        else "sentence-transformers/all-mpnet-base-v2",
    )
    for model_id in selected_ids:
        snapshot = Path(snapshot_download(
            repo_id=model_id, cache_dir=str(CACHE_DIR), allow_patterns=MODEL_FILES,
        ))
        files = sorted(path for path in snapshot.rglob("*") if path.is_file())
        config_names = (
            "sentence_bert_config.json",
            "config.json",
            "modules.json",
            "1_Pooling/config.json",
        )
        configs = {}
        for name in config_names:
            path = snapshot / name
            if path.is_file():
                try:
                    configs[name] = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    configs[name] = {"unparsed": True}
        item = {
            "model_id": model_id,
            "snapshot_path": str(snapshot.resolve()),
            "revision": snapshot.name,
            "files": {
                path.relative_to(snapshot).as_posix(): sha256(path)
                for path in files if path.relative_to(snapshot).as_posix() in PINNED_MODEL_FILES
            },
            "config": configs,
            "size_bytes": sum(
                path.stat().st_size for path in files
                if path.relative_to(snapshot).as_posix() in PINNED_MODEL_FILES
            ),
        }
        results = [existing for existing in results if existing.get("model_id") != model_id]
        results.append(item)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    for result in results:
        print(json.dumps({key: result[key] for key in ("model_id", "snapshot_path", "revision", "size_bytes")}, indent=2))


if __name__ == "__main__":
    main()
