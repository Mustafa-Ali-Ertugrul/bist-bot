# ruff: noqa: E402
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bist_bot.main import main

if __name__ == "__main__":
    main()
