# Deney E — Faz 0 + Faz 1 Raporu: WR %50'nin Kök Nedeni

**Tarih:** 2026-08-28 · **Script:** `scripts/diagnose_signal_edge.py` · **Veri:** cache-only (`~/.cache/bist_bot/wf_data`, 30 hisse × 3y) · **Reproducibility:** `results/expE_reproducibility.txt`

**Parity çıpası: PASS** — script, `prediction_signals_macro_observe.csv` referansını 508/508 birebir yeniden üretti (eşitsizlikte koşu dururdu).

---

## Faz 0 — Ölçüm denetimi: ölçü doğru, sinyal gerçekten kötü

| Ölçü | Değer |
|---|---|
| Sinyal 5g fwd (t+1 open → t+5 close, işlenebilir baz) | **+%0.269** ortalama, up-rate **%50.8** |
| Eşleştirilmiş baz (aynı hisse ±30 gün, sinyal-dışı günler) | **+%0.910** ortalama, up-rate **%53.9** |
| **Paired edge (sinyal − baz)** | **−%0.64 / sinyal** |
| Bootstrap CI95 (tarih-blok, b=20) | **[−%1.19, −%0.02]** — sıfırı dışlıyor |
| Bootstrap CI95 (b=40) | [−%1.13, −%0.01] |
| Censoring | 0 sinyal (508/508 tam) |
| Gece gap bileşeni (baz i − baz ii) | +%0.26 ortalama |
| Design effect / efektif n | 1.66 → **efektif n ≈ 307** |
| WR %50→%60 kanıtı için gereken n | **637** (mevcut efektif n'in 2 katı) |

**Yıl kırılımı (up-rate / mean):**
2023: %33.7 / −%1.52 · 2024: %54.4 / +%0.83 · 2025: %53.9 / +%0.20 · 2026: %55.1 / +%1.09

Sonuçlar:
1. **Ölçüm artefaktı (S6) çürütüldü.** Eşleştirilmiş baz + korelasyon düzeltmesi sonrası edge daha da kötü: sinyal günleri aynı hissenin komşu günlerinden istatistiksel olarak anlamlı **daha kötü** (−%0.64, CI sıfırı dışlıyor).
2. 508 sinyal görünürde büyük ama aynı gün çoklu sinyaller nedeniyle efektif n ≈ 307; WR %60 kanıtı için gereken 637'nin yarısındayız. Yani mevcut veriyle "gizli bir %60 edge var da göremiyoruz" hipotezi de kanıtlanamaz — ama ölçülen etki **negatif**, o yüzden bu tartışma akademik.
3. Baz (i) − baz (ii) = +%0.26: sinyalin "bilgisinin" bir kısmı gece gap'i; t+1 açılışta işlem yapan gerçek strateji bunu yakalayamaz.

## Faz 1 — Bileşen IC analizi: toplam skor kendi sinyallerini sıralayamıyor

1250 test (25 özellik × 5 ufuk × 2 baz × 5 koşul), BH FDR %5, aile = (baz × koşul).

### Kritik bulgu — sinyal günü koşulu (n=508, basis ii, h=5)

| Bileşen | IC | p |
|---|---|---|
| **score_total** | **+0.046** | 0.30 |
| score_momentum | +0.008 | 0.86 |
| score_trend | −0.028 | 0.53 |
| **score_volume** | **+0.098** | **0.028** |
| score_structure | −0.022 | 0.62 |

**Birleşik skor, kendi ürettiği 508 sinyalin forward getirisini sıralayamıyor (IC ≈ 0.05, anlamsız).** Dört bileşenden üçü (momentum/trend/structure) sinyal günlerinde tamamen gürültü; yalnız hacim bileşeni zayıf pozitif bilgi taşıyor. Bu, WR'ın %50'de takılmasının birincil mekanik kanıtıdır: skor ile sonuç arasında ilişki yoksa eşik nereye konursa konsun WR piyasa up-rate'ine yapışır.

### Sinyal günlerinde öne çıkan atomik özellikler (h=5)

| Özellik | IC | p | Yorum |
|---|---|---|---|
| pv_bull (fiyat-hacim boğa teyidi) | **+0.166** | 0.0002 | En güçlü sinyal-günü bilgisi |
| bb_above_upper | +0.093 | 0.035 | Güçlü kapanış sinyalleri daha iyi |
| **obv_up** | **−0.092** | 0.038 | **Ters çalışıyor:** OBV yukarı günü alım sinyali daha kötü sonuçlanıyor |
| dist_to_resistance | −0.085 (h=1: −0.102) | 0.058/0.022 | Dirence yakın sinyaller kısa vadede kötü |

### Rejim-koşullu bilgi var ama yıl-stabil değil

| Koşul | En güçlü özellikler (h=5) |
|---|---|
| BEAR (n=5252) | score_structure **+0.083**, plus_di **−0.072**, dist_to_support −0.065, cci/stoch_k ≈ −0.038 (aşırı satım yönünde kazanç → mean-reversion bu rejimde çalışıyor) |
| SIDEWAYS (n=6791) | ema_slope **−0.058** (pozitif eğim → daha kötü), dist_to_resistance −0.042 |
| BULL (n=8212) | rsi +0.046, dist_to_support +0.040, minus_di −0.038 |

**Ancak** yıl-bazlı işaret tutarlılığı: `score_trend`, `score_structure`, `rsi`, `plus_di` — hiçbiri yıllar arasında işaret tutarlı değil (örn. rsi: 2023 −0.097, 2024 +0.050, 2025 −0.077, 2026 +0.065). Bilgi rejim-koşullu **ve dönemsel olarak istikrarsız**: tek dönemli global bir kurala dökülemez.

### Koşulsuz (tüm günler, n≈21.7k)

Hiçbir özellik materyal eşiğine ulaşmıyor (max |IC| ≈ 0.026: plus_di −0.026, score_structure +0.024). Skorun ham maddeleri evrensel öngörü taşımıyor.

## Birleşik suçlu tablosu (şüpheli → hüküm)

| # | Şüpheli | Hüküm | Kanıt |
|---|---|---|---|
| S1 | Oversold puanları | **Kısmen suçlu** | BEAR'da mean-reversion IC'leri pozitif (+0.08 yapı, cci/stoch ters) — ama yıl-stabil değil; sinyal gününde momentum bileşeni IC≈0 |
| S2 | sideways ×0.4 | **Karar Faz 2'de** | SIDEWAYS koşulunda birkaç zayıf IC var; kapının kaldırdığı küme Faz 2 A/B'sinde ölçülecek |
| S3 | Cross puanları | **Masum değil ama etkisiz** | sinyal gününde trend bileşeni IC −0.028 (gürültü); cross'ların bilgisi sinyal içinde yok oluyor |
| S4 | Ertesi açılış cezası | **Doğrulandı (küçük)** | baz i − baz ii = +%0.26/sinyal; WR hedefini etkilemez ama net PnL'i aşındırır |
| S5 | Hedef/stop geometrisi | **İkincil suçlu** | önceki analiz: hedef %5, MAX_HOLD %78 — ancak Faz 0 gösterdi ki asıl sorun girişin edge'i; çıkış ancak edge varken hasat eder |
| S6 | Ölçüm artefaktı | **Çürütüldü** | eşleştirilmiş baz + blok bootstrap + censoring + vol-normalize kontrolleri sonrası edge −%0.64, CI sıfır dışlıyor |
| **Ana suçlu** | **Bileşen aggregasyonu** | **Doğrulandı** | score_total kendi sinyallerini sıralayamıyor (IC 0.05, p=0.30); 3/4 bileşen sinyal gününde gürültü |

## Faz 2–4 için yönlendirme

1. **Faz 2** odağı daraldı: score_volume/pv_bull pozitif, obv_up negatif işaretli → OBV divergence kapısı (şu an long'a karşı tek yönlü cap) ve sideways çarpanı öncelikli toggle adayları.
2. **Faz 3** için hazır sayı: gece gap +%0.26 — fill analizi bunu ayrıştıracak.
3. **Faz 4** giriş edge'i negatifken ancak ikincil önemde; yine de "giriş sabit, çıkış taraması" mevcut planla koşulacak.

## Artefaktlar

- `results/expE_faz0_metrics.csv`, `results/expE_faz0_matched_baseline.csv`
- `results/expE_faz1_feature_panel.parquet` (21.815 hücre), `results/expE_faz1_ic_matrix.csv` (1250 test)
- `results/expE_reproducibility.txt`
- Testler: `tests/test_diagnose_signal_edge.py` (14 test) — tam paket **1398 passed, 2 skipped**
