# Changelog

Tum degisiklikler chronolojik sirayla listelenir.

## [Unreleased]

### Fixed
- ADX hesaplama hizalamasi duzeltildi (`indicators.py`): `pd.Series(plus_dm)` yerine
  `df["plus_dm"]` kullanilarak pandas index alignment saglandi. Bu duzeltme
  sayesinde `detect_regime()` artik gercek BULL/BEAR/SIDEWAYS ayrimi yapiyor.

### Changed
- `BUY_THRESHOLD`: 10 → 15 (dusuk-vol hisselerde daha secici giris)
- Regime-aware trade filtering eklendi
- `MIN_REGIME_PERSISTENCE = 2`: En az 2 bardizinin ayni rejimde kalma gereksinimi
- `MOMENTUM_CONFIRMATION = 4.0`: Dusuk ADX durumunda %4 momentum gereksinimi
- `SIDEWAYS_EXTRA_THRESHOLD = 5`: Yatay piyasada ekstra filtreleme

### Performance
Backtest sonuclari (2y, THYAO/ASELS/EREGL/GARAN):

| Ticker | Onceki Getiri | Yeni Getiri | Delta | Onceki Trade | Yeni Trade |
|--------|--------------|-------------|-------|--------------|-------------|
| THYAO.IS | +17.9% | +24.4% | +6.4% | 23 | 26 |
| ASELS.IS | +9.9% | +33.6% | +23.7% | 2 | 22 |
| EREGL.IS | +0.0% | +39.3% | +39.3% | 0 | 31 |
| GARAN.IS | +0.0% | +62.4% | +62.4% | 0 | 33 |

- 4/4 hissede iyilesme, ortalama +33% getiri artisi
- THYAO'da aşiri islem azaltildi (34→26)
