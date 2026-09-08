# Per-Signal WR Neden %50'de Takılı? — Kök Neden Analizi

**Tarih:** 2026-08-28 · **Veri:** `results/prediction_signals_macro_observe.csv` (508 sinyal, BIST30, 2023-09..2026-08) + `~/.cache/bist_bot/wf_data` OHLCV cache

## Tek cümlelik cevap

**Sinyalin öngörü kenarı yok: WR ~%50, botun becerisi değil, piyasanın kendi yukarı-oranı (baseline up-rate %51.8); ~0.49% maliyet de onu hafifçe altına çekiyor.**

## Kanıt

### 1. Sinyal, koşulsuz baseline'ı geçemiyor (edge negatif)

Aynı 30 hissede, aynı dönemde, giriş=açılış → ~5 bar sonrası kapanış:

| Ölçü | Bot sinyalleri (n=508) | Koşulsuz tüm günler (n=22.085) |
|---|---|---|
| 5g fwd ortalama | **+0.27%** | **+0.45%** |
| 5g fwd medyan | +0.18% | +0.23% |
| up-rate | %50.6 | **%51.8** |

**Edge = −0.18%/sinyal.** Ufuk uzadıkça daha da kötüleşiyor:

| Ufuk | Sinyal ort | Baseline ort | Edge | Edge (2023-10 hariç) |
|---|---|---|---|---|
| 5 gün | +0.25% | +0.58% | **−0.33%** | +0.11% |
| 10 gün | +0.58% | +1.21% | **−0.63%** | +0.12% |
| 20 gün | +1.47% | +2.53% | **−1.06%** | **−0.38%** |

Yani bileşik skor (RSI, golden-cross, momentum, yapı, hacim) BIST30'da rastgele gün seçiminden **daha kötü** gün seçiyor; 2023-10 çıkarılsa bile edge ≈ 0 (5–10 günde +0.11%, 20 günde negatif).

### 2. Hedef ulaşılmaz → çıkışlar gürültüye teslim

- `target_rr=2.0` ile hedef = 2×risk. 5 günlük pencerede **hedefe ulaşan sinyal: %5 (24/508)**; stopa değen: %17.
- Çıkışların **%78'i MAX_HOLD** (5. gün zorla kapat) → sonuç ~ koşulsuz 5g getiri dağılımı = WR ~ piyasa up-rate'i ~ %50.
- 2:1 R asimetrisi fiilen çalışmıyor: teoride %34 WR yeterli olurdu ama hedef neredeyse hiç tutmuyor; kazançlar MAX_HOLD'da +0.82% ortalama ile sınırlı kalıyor.

### 3. Maliyet tabağı

Round-trip ~**%0.489** (~489 TL/100k). Gross beklenti +%0.27 iken net beklenti **−%0.175**: maliyet 14 sinyali kazançtan zarara çeviriyor. Edge sıfıra yakınken maliyet doğrudan WR ve PnL düşürüyor.

### 4. WR %50'nin bileşimi

```
WR ≈ piyasa up-rate (%51.8)  +  sinyal seçim etkisi (≈ −1 puan)  −  maliyet etkisi (≈ −3 puan)  ≈  %47–48
```

## Neden 60'a çıkarılamadı?

Eşik (buy=25→…), kapı (H1/H3/H6, makro rejim) ve profil ayarlarının tümü **aynı sıfır-edge dağılımını yeniden dilimliyor**: hangi alt-kümeyi seçersen seç, koşulsuz baseline'ı anlamlı geçen bir sinyal alt-kümesi yok (skor kovaları 25-35/35-45/45-55/55+ arasında farksız, 55+ bile negatif). WR 60 için gereken şey ayar değil, **ölçülebilir bilgi içeren yeni bir edge kaynağı**.

## İma edilen sonraki adımlar (öneri, karar kullanıcının)

1. **Feature-level IC analizi:** her skor bileşeninin 5/10/20g forward getiriyle bilgi katsayısı (Spearman IC) — hangi bileşenlerin gerçekten sinyal taşıdığını ölç, taşımayanları at.
2. **Giriş zamanlaması:** sinyal günü kapanış vs ertesi açılış — gap/reversion cezası var mı?
3. **Çıkış tasarımı:** MAX_HOLD %78'ken stop/target geometrisi fiilen rol oynamıyor; ya hedefi ulaşılabilir yap (daha küçük rr) ya da zaman-tabanlı çıkışı bilinçli tasarımla.
4. Edge bulunmadan yapılacak her kapı/eşik optimizasyonu aynı ~%50 WR üzerinde gezinir.

Not: WF OOS'un pozitif (+1.19% mean) olması ile çelişki yok — WF sermaye simülasyonunda tek pozisyon + stop/target asimetrisi (kazanan +%13 vs kaybeden −%7.6) ve pencere birleşimi farklı bir ölçüm; per-signal metrikleri (WR, beklenti) ayrı tutulmalı.
