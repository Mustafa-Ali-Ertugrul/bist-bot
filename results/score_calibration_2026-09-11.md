# Skor Kalibrasyon Koşusu — 2026-09-11

## 1. Koşu + Tetikleyici

- Koşu: `python main.py --score-correlation` (STRATEGY_PROFILE=champion)
- Tetikleyici: **her iki koşul birden** — 45 kapanmış outcome (≥30) **ve** 11 işlem günü (≥10).
- Veri saati: 24 Ağustos 2026'dan itibaren `results/signal_outcomes.csv` (45 satır).

## 2. Bucket Tablosu (score_correlation.md kopyası)

| Skor | Adet | Win-rate | Ort. Net PnL | Ort. MFE | Ort. MAE | Ort. Tutma (dk) |
|---|---|---|---|---|---|---|
| 25-30 | 27 | %44.4 | -38.94 | 1.53 | -1.72 | 217.8 |
| 30-35 | 10 | %40.0 | -57.26 | 1.63 | -1.45 | 235.7 |
| 35-40 | 3 | %0.0 | -60.31 | 1.06 | -1.26 | 441.0 |
| 40+ | 5 | %60.0 | 21.93 | 1.64 | -2.59 | 180.6 |

| Saat | Adet | Win-rate | Ort. Net PnL |
|---|---|---|---|
| 10-12 | 18 | %27.8 | -82.13 |
| 12-14 | 9 | %55.6 | 36.16 |
| 14-16 | 11 | %63.6 | 9.19 |
| 16-18 | 7 | %28.6 | -91.92 |

**Skor↔pnl Pearson:** 0.147 — **Skor↔MFE Pearson:** 0.035

## 3. Tetiklenen Kural

Protokol tablosu (`results/score_calibration_protocol.md`) satır satır:

- **"Korunur" satırı:** GEREKÇESİZ — win-rate monoton artmıyor (25-30: %44.4 → 30-35: %40.0 düşüş; 35-40: %0.0 çöküş; 40+: %60.0), toplam net win-rate < %50 (45'te 21 win ≈ %46.7), skor↔PnL r = 0.147 ≤ 0.2. Üç koşul da sağlanamadı.
- **"Eşik yükseltme adayı" satırı:** 35-40 bucket'ı win-rate %0.0 < %40 ama **n = 3 < 10** → aday doğmuyor. 25-30 bucket'ı %44.4 ≥ %40 → aday yok. 30-35 %40.0 → sınırda, n = 10 ≥ 10: **sınırda aday** (win-rate tam eşiğe denk; "below" değil).
- **"Faz 4 adayı" satırı:** r = 0.147 ≤ 0 **değil** (pozitif ama zayıf) → bu satır da net tetiklenmiyor.
- **n < 30 satırı:** n = 45 ≥ 30 → uygulanmaz.

**Sonuç:** Net kural satırı tetiklenmedi; en yakın iki satır (30-35 sınır adayı, genel zayıf monotonluk) "inceleme adayı" statüsü.

## 4. Karar

**Karar: EŞİKLER ŞİMDİLİK KORUNUR — Faz 4 (skor modeli incelemesi) adayı açılır.**

Gerekçe:
1. Tek başına monoton olmayan bucket'lar 27/45'lik 25-30 ağırlıklı dağılımın ve 35-40'un n=3 küçük örnekleminin etkisi. 35-40'un %0.0'ı istatistiksel gürültü olabilir (3 işlem, hepsi EOD'a kalmış, ort. 441 dk tutma — giriş saati gecikmesi sinyali).
2. Skor↔PnL r = 0.147 pozitif → skor tamamen bilgi dışı değil, ama 0.2 eşiğinin altında → "koru" için yetersiz, "düz/negatif" için de yetersiz.
3. Protokolün ruhuna uygun davranış: kural eşiklerine tam oturan sonuç yok → hiçbir otomatik değişiklik yapılmaz; inceleme adayı olarak işaretlenir.
4. Yan bulgu (protokol dışı ama kayda değer): 10-12 saat bucket'ı (n=18) %27.8 win-rate ve -82.13 ort. net PnL ile en zayıf dilim; 16-18 de benzer (-91.92). Öğleden sonra (12-16) pozitif. Bu, **giriş saati filtresini** Faz 4 incelemesine girdi olarak taşır.

## 5. Config Değişikliği

**Yok.** Eşikler korundu, commit SHA'sı yok. (Protokol gereği: adaylar walk-forward doğrulaması olmadan canlıya alınmaz.)

## 6. Sonraki Adımlar

- Faz 4 inceleme girdileri: (a) skor ağırlıkları + agreement katkısı, (b) 10-12 / 16-18 saat dilimi performansı, (c) 35-40 bucket'ına örnek birikmesi (n≥10 olunca aday netleşir).
- Sonraki tetikte karşılaştırma tabanı: 2026-09-11 koşusu (45 outcome / 11 gün / r=0.147).
