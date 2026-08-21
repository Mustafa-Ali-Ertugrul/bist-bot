# Z2 Parity Check — Walk-Forward A/B

- **Koşu zamanı (UTC±):** 2026-08-21T13:23:27+03:00
- **Before commit:** `300723d3c03a62f6f41a8132d765d4d8bd7f3be3` (Z2 öncesi, 300723d hattı)
- **After commit:** `28b79b7f2f106a05c4c1bff5be2214e2c4c1f76c` (Z2 sonrası)
- **Süre:** 102 sn
- **Veri:** Aynı OHLCV cache'i (`~/.cache/bist_bot/wf_data`) — iki koşu bit-identical fiyatlara bakar
- **Sonuç:** PASS — delta=0 (beklenen: Z2 yalnızca canlı risk yolunu değiştirir)

## Farklar

Fark yok: tüm ticker × tüm kolon değerleri identik.

## Yorum

Z2, `risk/stops.py::determine_final_levels` (canlı yol) üzerindedir; backtest
motoru vektörel stop/target'ı kendisi üretir (ayrık sözleşme,
`results/stop_target_parity.md`). Bu nedenle walk-forward çıktısının
değişmemesi **beklenen** sonuçtur. Fark görülürse: (1) cache paylaşımı bozulmuş
olabilir (--force-download ile iki koşuya da taze veri alın), (2) Z2 commit'i
backtest yoluna sızdırma yapmış olabilir — diff'lenmesi gerekir.
