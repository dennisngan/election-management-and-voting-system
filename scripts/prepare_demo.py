"""Run from the repository root: uv run --locked python scripts/prepare_demo.py start."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from election.demo.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
