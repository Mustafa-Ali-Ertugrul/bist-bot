"""Train the frozen ML model used by league strategies D1/D2 (ML_PREREGISTRATION.md).

Uses every month whose next-month target has been realized. Run from
scripts/research:  python train_ml_final.py
"""

from __future__ import annotations

from pathlib import Path

import ml_backtest as mb
import pandas as pd

from bist_bot.strategy import ml_model as ml

OUT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "bist_bot"
    / "data"
    / "models"
    / "ml_d_2026_09.json"
)


def main() -> None:
    months = mb.build_months()[0]
    train = [m for m in months if m["y"] is not None]
    model = ml.fit(pd.concat([m["x"] for m in train]), pd.concat([m["y"] for m in train]))
    model.save_model(OUT)
    print(f"{len(train)} months ({train[0]['date'].date()}..{train[-1]['date'].date()}) -> {OUT}")


if __name__ == "__main__":
    main()
