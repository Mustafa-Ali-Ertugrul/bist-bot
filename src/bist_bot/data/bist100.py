"""Static fallback ticker universe for BIST 100 scans."""

import json
from pathlib import Path

_UNIVERSE_DIR = Path(__file__).resolve().parent / "universe"


def _load_members(as_of: str) -> list[str]:
    payload = json.loads((_UNIVERSE_DIR / f"bist100_{as_of}.json").read_text(encoding="utf-8"))
    return [str(m) for m in payload["members"]]


# 2026-09-17: listeler bağımsız güncel kaynaklarla çapraz doğrulandı;
# 10 değişken sembolün tamamı yfinance üzerinde canlı veriyle teyit edildi.
# Endeks üyeliği çeyreklik değişir — bu snapshot'lar "o tarihte bilinen en iyi
# yaklaşık üyelik"tir; resmi kaynakla yenilenmesi önerilir.
BIST100_2023_01_01: list[str] = _load_members("2023-01-01")
BIST100_2024_01_01: list[str] = _load_members("2024-01-01")

# Geriye dönük uyumluluk: mevcut içe aktarımların kullandığı ana liste,
# bilinen en güncel snapshot'tır.
BIST100_TICKERS: list[str] = BIST100_2024_01_01

__all__ = ["BIST100_2023_01_01", "BIST100_2024_01_01", "BIST100_TICKERS"]
