from __future__ import annotations

from pathlib import Path

import streamlit as st

REPORTS = [
    ("Significant Top 10", Path("data/top10_significant_report.md")),
    ("Strict Profitable Watchlist", Path("data/strict_profitable_watchlist.md")),
    ("Detailed Top 10", Path("data/top10_detailed_report.md")),
]


def render_backtest_page() -> None:
    st.title("Backtest ve Raporlar")
    st.caption("Look-ahead bias fix sonrasi uretilen markdown raporlari burada goruntulenir.")

    for title, path in REPORTS:
        with st.expander(title, expanded=title == "Significant Top 10"):
            if path.exists():
                st.markdown(path.read_text(encoding="utf-8"))
            else:
                st.warning(f"Rapor bulunamadi: {path}")
