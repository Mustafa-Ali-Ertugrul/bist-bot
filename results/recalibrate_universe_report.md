# Tam-Evren Doğrulama + RR Süpürmesi (v2 adım 4)

Tarih: 2026-09-17 · Evren: BIST100 snapshot (86 ticker veri) · 2y günlük ·
train 63 / test 21 / step 21 / purge 10 / embargo 5 / warmup 60 /
exit-extension 28 · maliyet realistic · champion bandı 28-33 + pv-gate.

Kaynak: `results/recalibrate_universe100.json`, `recalibrate_rr10.json`,
`recalibrate_rr15.json` · Script: `scripts/recalibrate_champion.py`
(`--universe bist100 --target-rr {0.5,1.0,1.5}`)

## RR süpürmesi (havuzlanmış OOS, gerçekçi maliyet)

| RR | n | WR [%95 CI] | ort. net | kazanan ort. | kaybeden ort. | PF |
|---|---|---|---|---|---|---|
| 0.5 (canlı) | 188 | %71 [64–77] | −0.85pp | +2.31pp | −8.70pp | 0.66 |
| 1.0 | 176 | %62 [55–69] | +0.14pp | +6.16pp | −9.91pp | 1.04 |
| 1.5 | 164 | %51 [44–59] | +0.21pp | +9.78pp | −9.84pp | 1.04 |

## Başabaş matematiği (neden böyle)

Canlı stop `close − 2·ATR`, hedef `risk × 0.5` ≈ 1 ATR. Brüt başabaş:
WR×1 − (1−WR)×2 = 0 → **WR ≥ %66.7**. 1.25pp maliyet (~hedefin %25-30'u)
çıtayı **~%75-80**'e taşır. OOS WR %71 → aritmetik olarak negatif. Sayılar
teoriyi birebir doğruluyor. Champion'un %76 backtest WR'ı baştan
başabaşın altındaymış.

## Hüküm

- RR kolu doğru yönde: 1.0/1.5 beklentiyi pozitife çeviriyor — ama **ince**
  (+0.14/+0.21pp) ve **PF 1.04 < 1.2 barı**; WR %51-62.
- Stop tarafına hiç dokunulmuyor: kayıp ortalaması −9pp sabit. 54 kaybın
  neredeyse tamamı STOP_LOSS/STOP_GAP (−5…−17pp); ikisi gap-açılışı.
- 12 ticker (THYAO TCELL PGSUS MGROS dahil) 2 yılda sıfır işlem → bant+pv
  seçilim yanlılığı; sistem evrenin bir alt kümesinde oynuyor.
- v2 §6 satış kriterleri (WR ≥%50, PF >1.2, n≥100 canlı): **sağlanmıyor.**
  Satış kapalı kalmalı.

## Sıradaki kollar (etki sırasına göre)

1. **Stop disiplini** (dokunulmamış en büyük kol): stop mesafe üst sınırı
   (örn. 2 ATR yerine 1–1.5 ATR veya %4-5 cap), zaman-stop, geniş-stopta
   küçültülmüş boyut. Çekirdek değişiklik ister (`indicators.py:524`
   stop formülü + canlı `risk/stops.py` ile parite + testler).
2. Gap koruması: STOP_GAP kayıpları (ULKER −10.17, CIMSA −11.95) — açılış
   boşluğu kuralı / haber filtresi.
3. Kazanan konfigürasyon → shadow → küçük canlı (champion/challenger).
4. Seçilim yanlılığı: sıfır-işlem ticker'lar için bant/pv gevşetme deneyi
   (ayrı hipotez — kapsama genişletir, beklentiyi inceltir; dikkatli).
