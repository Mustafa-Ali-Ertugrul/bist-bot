"""Tests for fundamentals screening helpers."""

from __future__ import annotations

from bist_bot.data.fundamentals import (
    FundamentalRow,
    format_fundamentals_table,
    save_fundamentals_csv,
    screen_fundamentals,
)


class StubFetcher:
    def __init__(self, infos: dict) -> None:
        self.infos = infos

    def get_stock_info(self, ticker: str) -> dict:
        return self.infos.get(ticker, {})


def test_screen_sorts_by_pe_and_filters_non_positive() -> None:
    fetcher = StubFetcher(
        {
            "A.IS": {"name": "A", "sector": "GIDA", "market_cap": 1e9, "pe_ratio": 12.5},
            "B.IS": {"name": "B", "sector": "BANKA", "market_cap": 2e9, "pe_ratio": 5.0},
            "C.IS": {"name": "C", "sector": "X", "market_cap": 1e9, "pe_ratio": -4.0},
            "D.IS": {"name": "D", "sector": "Y", "market_cap": 1e9, "pe_ratio": None},
        }
    )
    rows = screen_fundamentals(fetcher, ["A.IS", "B.IS", "C.IS", "D.IS"])
    assert [r.ticker for r in rows] == ["B.IS", "A.IS"]
    assert rows[0].pe_ratio == 5.0


def test_screen_applies_max_pe_and_market_cap_filter() -> None:
    fetcher = StubFetcher(
        {
            "A.IS": {"name": "A", "sector": "S", "market_cap": 1e9, "pe_ratio": 30.0},
            "B.IS": {"name": "B", "sector": "S", "market_cap": 3e9, "pe_ratio": 10.0},
        }
    )
    rows = screen_fundamentals(fetcher, ["A.IS", "B.IS"], max_pe=25, min_market_cap_tl=2e9)
    assert [r.ticker for r in rows] == ["B.IS"]


def test_include_negative_pe_flag() -> None:
    fetcher = StubFetcher(
        {"C.IS": {"name": "C", "sector": "X", "market_cap": 1e9, "pe_ratio": -4.0}}
    )
    assert screen_fundamentals(fetcher, ["C.IS"]) == []
    rows = screen_fundamentals(fetcher, ["C.IS"], include_negative_pe=True)
    assert [r.ticker for r in rows] == ["C.IS"]


def test_screen_handles_string_pe() -> None:
    fetcher = StubFetcher(
        {"E.IS": {"name": "E", "sector": "S", "market_cap": 1e9, "pe_ratio": "12.3"}}
    )
    rows = screen_fundamentals(fetcher, ["E.IS"])
    assert len(rows) == 1
    assert rows[0].pe_ratio == 12.3


def test_format_table_contains_header_and_rows() -> None:
    rows = [
        FundamentalRow(
            ticker="B.IS",
            name="B",
            sector="BANKA",
            market_cap=2e9,
            pe_ratio=5.0,
            high_52w=10.0,
            low_52w=5.0,
        )
    ]
    text = format_fundamentals_table(rows, limit=5)
    assert "Ticker" in text
    assert "B.IS" in text
    assert "5.0" in text


def test_format_table_empty_message() -> None:
    assert "bulunamadı" in format_fundamentals_table([])


def test_save_csv_roundtrip(tmp_path) -> None:
    rows = [
        FundamentalRow(
            ticker="B.IS",
            name="B",
            sector="BANKA",
            market_cap=2e9,
            pe_ratio=5.0,
            high_52w=10.0,
            low_52w=None,
        )
    ]
    path = tmp_path / "fundamentals.csv"
    save_fundamentals_csv(rows, str(path))
    text = path.read_text(encoding="utf-8")
    assert "pe_ratio" in text
    assert "B.IS" in text
