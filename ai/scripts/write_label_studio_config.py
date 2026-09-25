"""Write the Label Studio project XML from the canonical label schema."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
from src.annotation.label_studio_config import make_label_studio_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=AI_DIR / "annotation" / "label_studio" / "config.xml")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(make_label_studio_config(AI_DIR / "annotation" / "label_schema.json"), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
