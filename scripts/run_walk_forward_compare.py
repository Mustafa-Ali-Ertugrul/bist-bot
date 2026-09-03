"""Compare conservative vs research_v1 profiles with day-based walk-forward.

Usage (from repo root):
    uv run python scripts/run_walk_forward_compare.py
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import warnings
from pathlib import Path

import pandas as pd
import yfinance as yf

from bist_bot.strategy.params import StrategyParams
from bist_bot.validation import WalkForwardValidator

warnings.filterwarnings("ignore")

# curl_cffi cannot read CA bundles from Unicode (OneDrive "Masaüstü") paths on
# Windows (curl error 77). Copy the CA bundle to an ASCII-only temp path and
# point both curl_cffi and the environment at it.
_CA_SRC = Path(__import__("certifi").where())
_CA_DST = Path(tempfile.gettempdir()) / "opencode" / "cacert.pem"
if not _CA_DST.exists():
    _CA_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_CA_SRC, _CA_DST)
os.environ["CURL_CA_BUNDLE"] = str(_CA_DST)

CACHE_DIR = Path("data") / "cache_ohlcv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TICKERS = [
    "THYAO.IS",
    "GARAN.IS",
    "ASELS.IS",
    "EREGL.IS",
    "BIMAS.IS",
    "SISE.IS",
    "FROTO.IS",
    "KCHOL.IS",
    "ARCLK.IS",
    "TUPRS.IS",
]

PROFILES: dict[str, StrategyParams] = {
    "conservative": StrategyParams.conservative(),
    "research_v1": StrategyParams.research_v1(),
}


def _normalize_ohlcv(df):
    if df is None or df.empty:
        return df
    out = df.copy()
    if getattr(out.columns, "nlevels", 1) > 1:
        out.columns = [
            c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in out.columns
        ]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename = {}
    for c in list(out.columns):
        if c in {"adj close", "adj_close"}:
            rename[c] = "close"
    if rename:
        out = out.rename(columns=rename)
    return out


def _load_ticker(ticker: str, session) -> pd.DataFrame | None:
    """Download with CSV cache + curl_cffi session to bypass Yahoo TLS fingerprinting."""
    cache_path = CACHE_DIR / f"{ticker.replace('.', '_')}.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if not df.empty:
            return df
    for attempt in range(3):
        try:
            raw = yf.download(
                ticker,
                period="3y",
                auto_adjust=True,
                progress=False,
                session=session,
            )
        except Exception:
            raw = None
        if raw is not None and not raw.empty:
            norm = _normalize_ohlcv(raw)
            norm.to_csv(cache_path)
            time.sleep(1.0)
            return norm
        time.sleep(10.0 * (attempt + 1))
    return None


def _frame(wf: WalkForwardValidator, session) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, params in PROFILES.items():
        validator = WalkForwardValidator(
            train_window=wf.train_window,
            test_window=wf.test_window,
            step_size=wf.step_size,
            commission_bps=wf.commission_bps,
            slippage_bps=wf.slippage_bps,
            initial_capital=wf.initial_capital,
            strategy_params=params,
        )
        for ticker in TICKERS:
            df = _load_ticker(ticker, session)
            if df is None or df.empty:
                rows.append(
                    {
                        "profile": name,
                        "ticker": ticker,
                        "windows": 0,
                        "is_mean": None,
                        "oos_mean": None,
                        "oos_dd": None,
                        "oos_sharpe": None,
                        "overfit": "NO_DATA",
                    }
                )
                continue
            result = validator.run(ticker, df)
            if result is None:
                rows.append(
                    {
                        "profile": name,
                        "ticker": ticker,
                        "windows": 0,
                        "is_mean": None,
                        "oos_mean": None,
                        "oos_dd": None,
                        "oos_sharpe": None,
                        "overfit": "NO_WINDOWS",
                    }
                )
                continue
            rows.append(
                {
                    "profile": name,
                    "ticker": ticker,
                    "windows": len(result.windows),
                    "is_mean": result.is_aggregate["mean_total_return_pct"],
                    "oos_mean": result.oos_aggregate["mean_total_return_pct"],
                    "oos_dd": result.oos_aggregate["mean_max_drawdown_pct"],
                    "oos_sharpe": result.oos_aggregate["mean_sharpe_ratio"],
                    "overfit": "YES" if result.has_overfitting_warning else "no",
                }
            )
    return rows


def main() -> None:
    from curl_cffi import requests as cffi_requests

    session = cffi_requests.Session(impersonate="chrome", verify=str(_CA_DST))
    wf = WalkForwardValidator(
        train_window=252,
        test_window=63,
        step_size=63,
        commission_bps=2.0,
        slippage_bps=5.0,
        initial_capital=100_000.0,
    )
    print(
        f"WF: train={wf.train_window} test={wf.test_window} step={wf.step_size} "
        f"costs={wf.commission_bps}bp+{wf.slippage_bps}bp  tickers={len(TICKERS)} "
        f"profiles={list(PROFILES)}"
    )
    print("=" * 96)

    rows = _frame(wf, session)

    for name in PROFILES:
        subset = [r for r in rows if r["profile"] == name]
        print(f"--- {name} ---")
        for r in subset:
            if r["is_mean"] is None:
                print(f"  {r['ticker']:<10} {r['overfit']}")
                continue
            print(
                f"  {r['ticker']:<10} windows={r['windows']:>2}  "
                f"IS={r['is_mean']:>8.2f}%  OOS={r['oos_mean']:>8.2f}%  "
                f"DD={r['oos_dd']:>7.2f}%  Sharpe={r['oos_sharpe']:>7.3f}  "
                f"overfit={r['overfit']}"
            )
        valid = [r for r in subset if r["oos_mean"] is not None]
        if valid:
            import statistics as st

            oos = [float(r["oos_mean"]) for r in valid]  # type: ignore[arg-type]
            dd = [float(r["oos_dd"]) for r in valid]  # type: ignore[arg-type]
            sh = [float(r["oos_sharpe"]) for r in valid]  # type: ignore[arg-type]
            wins = sum(1 for v in oos if v > 0)
            print(
                f"  SUMMARY: n={len(valid)}  OOS mean={st.mean(oos):.2f}%  "
                f"OOS median={st.median(oos):.2f}%  win-rate={wins}/{len(valid)}  "
                f"DD mean={st.mean(dd):.2f}%  Sharpe mean={st.mean(sh):.3f}"
            )
        print("=" * 96)

    # head-to-head per ticker
    by_ticker: dict[str, dict[str, object]] = {}
    for r in rows:
        if r["is_mean"] is None:
            continue
        key = str(r["ticker"])
        by_ticker.setdefault(key, {})[str(r["profile"])] = float(r["oos_mean"])  # type: ignore[arg-type]
    print("HEAD-TO-HEAD (OOS mean %, research_v1 - conservative):")
    for ticker, prof in sorted(by_ticker.items()):
        c = prof.get("conservative")
        v = prof.get("research_v1")
        if c is None or v is None:
            print(f"  {ticker:<10} incomplete")
            continue
        diff = float(v) - float(c)
        better = "research_v1" if diff > 0 else ("conservative" if diff < 0 else "tie")
        print(f"  {ticker:<10} cons={c:>8.2f}%  res={v:>8.2f}%  diff={diff:>+7.2f}  -> {better}")
    print("=" * 96)
    print("DONE")

    # persist results
    out_csv = Path("results") / "walk_forward_profile_comparison.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"saved: {out_csv}")


if __name__ == "__main__":
    main()
