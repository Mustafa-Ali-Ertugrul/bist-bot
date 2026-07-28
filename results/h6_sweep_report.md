# H6 — MTF Confluence SMA20/EMA200 Eğim Çelişkisi Sweep Sonuçları

Aşağıdaki tablo H6 Confluence Blokajı (SMA20 eğimi ile EMA200 yönü çeliştiğinde TrendBias/Rejim Nötrleme) açık (ON) ve kapalı (OFF) durumlarının walk-forward metrikleri üzerindeki etkisini göstermektedir.

## Metrik Karşılaştırma (BIST30, 3 Yıllık Veri, 7 Pencere)

| Metrik | H6 ON (Aktif - Varsayılan) | H6 OFF (Pasif - Baseline) | Fark / Etki |
|---|---|---|---|
| **OOS Median Getiri %** | 0.82% | 0.82% | Nötr (Değişmedi) |
| **OOS Ortalama Getiri %** | 0.02% | 0.07% | -0.05 pp (Gürültü) |
| **OOS Aşırı Uyum (Overfitting) Oranı** | **35.7%** (10/28) | **46.4%** (13/28) | **-10.7 pp (Aşırı uyum azaldı - Pozitif)** |
| **Stres OOS Median Getiri %** | 0.47% | 0.47% | Nötr (Değişmedi) |
| **Stres Aşırı Uyum Oranı** | **35.7%** (10/28) | **46.4%** (13/28) | **-10.7 pp (Aşırı uyum azaldı - Pozitif)** |
| **Sağlam (Robust) Hayatta Kalanlar** | **8** | **6** | **+2 Sağlam Ticker (TUPRS, ENKAI eklendi)** |

## Teşhis & Karar

- **h6_confluence_neutralized Sayacı:** Walk-forward test pencerelerinde toplam **3602** satırda SMA20 ve EMA200 eğimlerinin çeliştiği tespit edilmiş ve rejim SIDEWAYS'e zorlanarak nötrleştirilmiştir.
- **Karar:** **H6 AKTİF KALMALIDIR (mtf_confluence_block_enabled = True).** 
  Çelişki filtresi median getiri performansını düşürmeden aşırı uyum (overfitting) oranını %46.4'ten %35.7'ye düşürmüş ve sağlam hisse senedi sayısını 6'dan 8'e çıkarmıştır. Whipsaw (testere piyasa) durumlarında false-positive sinyalleri filtrelemede seçici ve etkindir.
