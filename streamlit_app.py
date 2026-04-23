# ruff: noqa: E402
from pathlib import Path
import runpy
import sys

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if __name__ == "__main__":
    runpy.run_module("bist_bot.streamlit_app", run_name="__main__")
