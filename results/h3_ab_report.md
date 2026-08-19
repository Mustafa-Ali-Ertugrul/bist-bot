# H3 Chase Block A/B Walk-Forward Raporu

- Oluşturulma: 2026-08-19T19:02:33+00:00
- H3 ON kolu : `results\wf_bist30_h3_on.csv` (gates=ON, buy=25.0, ctm=0.0)
- H3 OFF kolu: `results\wf_bist30_h3_off.csv` (gates=ON, buy=25.0, ctm=0.0)

## Kısıtlar

- WF cache: yerel parquet, 22.07.2026; period=3y.
- Coverage: 30/30 ticker OK; tüm ticker'lar OK.
- Overfitting tanımı: (1) flag = WF `has_overfitting_warning` payı; (2) struct = IS Ort > 0 ama OOS Ort <= 0 ticker payı.
- Karar eşiği: medyan OOS delta ±0.10 pp.

## Universe Aggregate (status=OK)

| Metrik | H3 ON | H3 OFF | Delta |
| --- | ---: | ---: | ---: |
| ticker OK (n) | 30 | 30 | 0 |
| medyan OOS ort % | 0.50 | 0.69 | -0.19 |
| mean OOS ort % | 0.20 | 1.12 | -0.91 |
| pozitif OOS payı % | 53.3 | 60.0 | -6.7 |
| overfitting share % (flag) | 43.3 | 36.7 | 6.7 |
| IS+/OOS- payı % (struct) | 23.3 | 10.0 | 13.3 |

## Per-Ticker Delta (oos_mean_return, pp)

| Ticker | ON OOS% | OFF OOS% | Δ pp | ON trades | OFF trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| EREGL.IS | -0.77 | -3.41 | 2.63 | 8 | 11 |
| EKGYO.IS | -2.72 | -3.74 | 1.02 | 7 | 8 |
| GARAN.IS | 2.88 | 1.92 | 0.95 | 6 | 8 |
| SASA.IS | -0.25 | -1.14 | 0.88 | 7 | 8 |
| BIMAS.IS | -2.41 | -3.26 | 0.85 | 11 | 12 |
| KRDMD.IS | 1.02 | 0.21 | 0.81 | 9 | 12 |
| PETKM.IS | 3.44 | 2.67 | 0.78 | 7 | 8 |
| AKBNK.IS | 2.56 | 2.56 | 0.00 | 4 | 4 |
| ASTOR.IS | 3.09 | 3.09 | 0.00 | 8 | 8 |
| SISE.IS | 0.87 | 0.87 | 0.00 | 9 | 9 |
| TAVHL.IS | -2.70 | -2.70 | 0.00 | 9 | 9 |
| TCELL.IS | -0.69 | -0.69 | 0.00 | 3 | 3 |
| TOASO.IS | 2.50 | 2.50 | 0.00 | 7 | 7 |
| TUPRS.IS | 4.13 | 4.13 | 0.00 | 11 | 11 |
| YKBNK.IS | 3.74 | 3.74 | 0.00 | 6 | 6 |
| ENKAI.IS | -0.40 | -0.28 | -0.12 | 10 | 10 |
| SAHOL.IS | 0.31 | 0.52 | -0.21 | 6 | 9 |
| PGSUS.IS | -5.91 | -5.61 | -0.30 | 9 | 10 |
| THYAO.IS | -2.61 | -2.25 | -0.37 | 10 | 11 |
| FROTO.IS | -1.81 | -1.32 | -0.49 | 9 | 10 |
| ISCTR.IS | -0.19 | 0.38 | -0.58 | 9 | 11 |
| MGROS.IS | 3.65 | 4.38 | -0.74 | 7 | 9 |
| TRALT.IS | 2.87 | 3.82 | -0.95 | 7 | 8 |
| TTKOM.IS | 0.83 | 2.28 | -1.45 | 9 | 11 |
| GUBRF.IS | 0.70 | 2.28 | -1.58 | 7 | 8 |
| VAKBN.IS | 3.42 | 5.09 | -1.67 | 9 | 10 |
| AEFES.IS | -3.35 | -1.38 | -1.97 | 10 | 11 |
| KCHOL.IS | -3.33 | -0.93 | -2.41 | 10 | 12 |
| ASELS.IS | 7.56 | 10.66 | -3.10 | 11 | 14 |
| DSTKF.IS | -10.28 | 9.13 | -19.41 | 2 | 3 |

Not: diagnose CSV'si yalnızca overextended LONG satırlarını loglar ve CCI/direnç eşiklerinde strict (>, <) kullanır; engine >=/<= ile ve short tarafında da çalışır. Bu yüzden engine'de cap yiyen short girişleri diagnose'de görünmez; gerçek etki için iki kolun OOS farkı ve trade sayısı esas alınır.

## SASA.IS Odak

- ON: OOS=-0.25%, IS=-18.03%, trades=7, overfit_flag=False
- OFF: OOS=-1.14%, IS=-17.43%, trades=8, overfit_flag=False

## Chase Diagnose Özeti (H3 ON kolu)

- chase_candidate_rows (overextended long): 1212
- raw score max / >= 25 satır: 47.00 / 58
- high-score satır (raw > eşik, cap hesaplanan): 48
- h3_actually_capped_rows: 48
- ortalama cap boşluğu (raw-capped): 22.40
- ticker başına capped (top 10): EREGL.IS(4), GUBRF.IS(4), ASELS.IS(3), ASTOR.IS(3), ISCTR.IS(3), MGROS.IS(3), PETKM.IS(3), TOASO.IS(3), AEFES.IS(2), BIMAS.IS(2)

## Karar

- Karar anahtarı: `kill_switch`
- **H3 için kill-switch önerilir (chase_block_enabled=False) — medyan OOS farkı -0.19 pp (< -0.10 pp eşiği). Öneri rapor amaçlıdır; uygulama kullanıcı onayı gerektirir.**

Bu rapor yalnızca öneridir; kill-switch uygulaması kullanıcı onayı gerektirir.
