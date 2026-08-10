"""BIST temel veri (fundamental) hızlı tarama script'i.

PE oranına göre sıralama yapar, ekrana tablo basar ve CSV olarak kaydeder.
Kullanım:

    python scripts/run_fundamentals_screen.py                        # tüm watchlist
    python scripts/run_fundamentals_screen.py --max-pe 25 --limit 15
    python scripts/run_fundamentals_screen.py --watchlist THYAO.IS,ASELS.IS
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from bist_bot.app_logging import get_logger
from bist_bot.config.settings import settings
from bist_bot.data.fundamentals import (
    format_fundamentals_table,
    save_fundamentals_csv,
    screen_fundamentals,
)

logger = get_logger(__name__, component="fundamentals_screen")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BIST temel veri taraması")
    parser.add_argument(
        "--watchlist",
        type=str,
        default=None,
        help="Virgülle ayrılmış ticker listesi (varsayılan: settings WATCHLIST)",
    )
    parser.add_argument(
        "--max-pe",
        type=float,
        default=None,
        help="Üst PE sınırı (örn. 25); değerli hisseleri eleyip ucuzları gösterir",
    )
    parser.add_argument(
        "--min-market-cap-mln",
        type=float,
        default=None,
        help="Minimum piyasa değeri (milyon $); değer yfinance marketCap cinsindendir",
    )
    parser.add_argument(
        "--include-negative-pe",
        action="store_true",
        help="Zarar eden (negatif PE) şirketleri de listele",
    )
    parser.add_argument("--limit", type=int, default=20, help="Tabloda gösterilecek satır")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="CSV çıktı yolu (varsayılan: results/fundamentals_YYYYMMDD.csv)",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    from bist_bot.data.fetcher import BISTDataFetcher

    fetcher = BISTDataFetcher()
    tickers = (
        [t.strip() for t in args.watchlist.split(",") if t.strip()]
        if args.watchlist
        else list(getattr(settings, "WATCHLIST", []) or [])
    )
    if not tickers:
        print("Boş watchlist — tarama yapılamadı.")
        return

    logger.info("fundamentals_screen_started", ticker_count=len(tickers))
    min_cap = args.min_market_cap_mln * 1_000_000 if args.min_market_cap_mln else None
    rows = screen_fundamentals(
        fetcher,
        tickers,
        max_pe=args.max_pe,
        min_market_cap_tl=min_cap,
        include_negative_pe=args.include_negative_pe,
    )

    print(format_fundamentals_table(rows, limit=args.limit))
    print(f"\nToplam uygun hisse: {len(rows)}")

    output = Path(args.output) if args.output else REPO_ROOT / "results" / f"fundamentals_{datetime.now():%Y%m%d}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    save_fundamentals_csv(rows, str(output))
    print(f"CSV kaydedildi: {output}")


if __name__ == "__main__":
    main()