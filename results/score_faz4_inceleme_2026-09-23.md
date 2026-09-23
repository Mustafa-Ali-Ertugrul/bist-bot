# Skor Modeli İncelemesi (Faz 4 Adayı Girdi Seti) — 2026-09-23

> 2026-09-11 kalibrasyon koşusunda açılan **"Faz 4 adayı: skor modeli incelemesi"**
> için güncel veri + read-only envanter. Bu doküman yeni bir protokol kararı
> değildir; ilk zorunlu protokol koşusu 2026-09-11'de yapıldı
> (`results/score_calibration_2026-09-11.md`). Config/eşik değişikliği YOKTUR.

## 1. Koşu + Tetik Durumu

- Tarih: 2026-09-23 · Veri: `results/signal_outcomes.csv` (24 Ağustos – 18 Eylül 2026)
- Koşu: `bist_bot.reports.score_correlation.run()` (main.py `--score-correlation`
  ile aynı fonksiyon; `main.py` girişi container/DB init'ini flag kontrolünden
  ÖNCE yaptığı için yerel Postgres yokken çöker — bkz. §5-f bakım notu)
- Kapanan outcome: **46** / 30 · İşlem günü: **12** / 10 → tetik koşulları halen ateşli
- 09-11'e göre delta: **+1 outcome** (TRALT.IS #361), **+1 işlem günü**

## 2. Güncel Bucket Tabloları + 09-11 Delta

| Skor | Adet (Δ) | Win-rate (Δ) | Ort. Net PnL (Δ) | Ort. MFE | Ort. MAE | Ort. Tutma dk (Δ) |
|---|---|---|---|---|---|---|
| 25-30 | 28 (+1) | %42.9 (−1.5pp) | −62.06 (−23.1) | 1.48 | −1.90 | 529.8 (+312.0) |
| 30-35 | 10 (=) | %40.0 (=) | −57.26 (=) | 1.63 | −1.45 | 235.7 (=) |
| 35-40 | 3 (=) | %0.0 (=) | −60.31 (=) | 1.06 | −1.26 | 441.0 (=) |
| 40+ | 5 (=) | %60.0 (=) | 21.93 (=) | 1.64 | −2.59 | 180.6 (=) |

| Saat | Adet | Win-rate (Δ) | Ort. Net PnL (Δ) |
|---|---|---|---|
| 10-12 | 18 | %27.8 (=) | −82.13 (=) |
| 12-14 | 9 | %55.6 (=) | 36.16 (=) |
| 14-16 | 12 (+1) | %58.3 (−5.3pp) | −48.77 (−57.96) |
| 16-18 | 7 | %28.6 (=) | −91.92 (=) |

**Skor↔pnl Pearson: 0.147** (=) · **Skor↔MFE Pearson: 0.044** (+0.009) · Toplam net win: **19/46 = %41.3**

> Düzeltme (09-11 raporu): 09-11 raporu "45'te 21 win ≈ %46.7" yazmış; CSV'den
> yeniden sayım bucket kazanırlarıyla (12+4+0+3) **19/45 = %42.2** eder. Yeni satır
> kayıp olduğundan bugün de 19 win; oran 19/46'ya düştü.

## 3. Yeni Tek Outcome: TRALT.IS #361 — Stop Disiplini Bulgusu

09-11'den bu yana kapanan TEK işlem:

| Alan | Değer |
|---|---|
| Skor | 28.7 (champion bandı [28,33] İÇİNDE) |
| Giriş | 2026-09-12 15:16 TR · 53.80 |
| Stop / Hedef | 52.80 (%1.86) / 54.90 (RR ≈ 1.1) |
| Çıkış | 2026-09-18 20:29 TR · **50.20** · STOP_HIT |
| MFE / MAE | **+%0.19** / −%6.69 |
| Tutma | **8953 dk ≈ 6.2 gün** (kalan portfolio ortalaması ~4 saat) |
| Net PnL | **−686.35** |

- Stop'un **%4.9 ALTINDA** dolgu (gap-through/slip) — stop 52.80, gerçekleşen 50.20.
- 15 dk'luk tarama stratejisi için 6+ gün tutma → EOD taşıma disiplini işlemedi.
- Bu tek işlem, CSV toplam net kaybının (≈ −2.382) **~%29'u**.
- Faz 1 bulgusuyla tutarlı (`results/recalibrate_gap_report.md`, RED hükmü):
  **ana kol skor kalibrasyonu değil, stop/çıkış disiplini.** Skoru bandın tam
  içinde, pv-gate açıkken açılmış bir pozisyon stop tarafında kaybediyor.

## 4. Protokol Kural Değerlendirmesi (satır satır)

| Kural | Durum | Sonuç |
|---|---|---|
| Korunur (monoton + WR≥%50 + r>0.2) | 42.9→40.0→0.0→60.0 monoton DEĞİL; WR %41.3<50; r=0.147≤0.2 | Sağlanmadı |
| Eşik yükseltme adayı (WR<%40 ∧ n≥10) | 25-30: %42.9 (eşik üstü, ama 09-11'in %44.4'ünden düşüşte); 30-35: %40.0 sınırda; 35-40: %0 ama n=3<10 | Doğmadı (25-30 %40'ın altına sarkarsa n=28 ile doğar) |
| Faz 4 adayı (r≤0 ∧ n≥30) | r=0.147>0 | Tetiklenmedi (inceleme zaten açık) |
| n<30 | n=46 | Uygulanmaz |

**Sonuç: net kural satırı tetiklenmedi → eşikler KORUNUR, config değişikliği YOK.**

## 5. Faz 4 İnceleme Girdileri

### (a) Skor kompozisyonu envanteri (canlı champion)

- `champion_wr()` = conservative taban + `buy_threshold=28` / `max_actionable_score=33`
  / `pv_confirmation_required=True`; bant sözleşmesi: `buy_threshold ≤ score ≤ max_actionable_score`
- Conservative taban: sideways ×0.4, ADX 20, counter-trend ×0.0, `agreement_low_cap=15`,
  MTF confluence + OBV divergence blokları açık
- Normalize komponent ağırlıkları (momentum 0.15 / trend 0.60 / volume 0.15 /
  structure 0.10) **yalnız `research_v1`** profilinde aktif; champion ham toplam +
  bileşen cap'leriyle koşuyor → "ağırlık + agreement katkısı" analizi ancak
  research_v1/replay üzerinde yapılabilir (canlı champion'da ağırlık yok)
- Hedef tarafı: `FALLBACK_TARGET_RR=0.5`, `ATR_TARGET_MULT=1.5`, `MAX_SIGNAL_SCORE=33`

### (b) Champion bandına göre yeniden kesim (bucket eşikleri 25/30/35/40 bandla hizalı değil)

| Dilim | n | WR | Net toplam | Champion'da işlenir mi |
|---|---|---|---|---|
| [25,28) | 18 | %44.4 | −1070.8 | HAYIR (buy 28 altı) |
| **[28,33]** | **16** | **%43.8** | **−953.5** | **EVET — eylemde bant** |
| (33,∞) | 12 | %33.3 | −357.4 | HAYIR (cap 33 üstü) |

- 2026-08-29 challenge'ında **%76.4 backtest WR** ile seçilen bant, canlıda
  **n=16'da %43.8** · Bant içi örnek hâlâ az (hedef ≥30); ama mevcut 16 örnek
  challenge iddiasını desteklemiyor.
- 35-40 (n=3) ve 40+ (n=5) bucket'larındaki satırların TÜMÜ champion'da işlenmez
  skorlar → o bucket'lardaki zayıflık champion kararına girdi etmez (09-11
  raporunun 35-40 endişesi champion perspektifinden ikincil).

### (c) Profil karışımı / bant uyumsuzluğu bulgusu (yeni)

08-29 sonrası girişli 15 satırın **8'i champion bandı dışında** (5× skor<28:
25.2/25.2/26.0/25.2/26.0; 3× skor>33: 34.8/33.1/37.1), tarihler 09-02→09-07'ye
yayılmış (tek seferlik restart gecikmesiyle açıklanamaz). `STRATEGY_PROFILE`
mimariye 2026-07-28'de girdi (bedd719). Olası nedenler: canlı süreç farklı
profil env'iyle koşuyor, tracker shadow-kayıt yapıyor (eylemde olmayan
sinyalleri de kaydediyor), veya süreç eski kodla ayakta. **Doğrulama adayı
(operasyonel):** canlı tracker'ın profilini ve CSV'ye yazım kriterini teyit et.
Ayrıca CSV `signal_id` değerleri zamanla monoton değil (361, 09-02..09-07
satırlarında 7367+) — id kaynağı/uzayı da teyit edilmeli.

### (d) Saat dilimleri

10-12 (%27.8, −82.13) ve 16-18 (%28.6, −91.92) hâlâ en zayıf; 14-16 WR %58.3'e
düştü ve ort. net −48.77'ye döndü (TRALT kaybı bu dilimde). Öğleden sonra WR
avantajı PnL'e çevrilemiyor. (Saat bucket'ları koşan makinenin lokal saati —
bu koşuda TR seans saati; sunucuda UTC olur — protokoldeki bilinen sınır.)

### (e) Faz 1 bağlantısı

`results/recalibrate_gap_report.md` (RED): büyük boşluklu OOS girişi nadir
(3/168 ≥%2) ve filtre varyantları PF iyileştirmesi getirmedi. TRALT #361
deseniyle birleşince inceleme önceliği: **skor eşiği değil, stop-slip + EOD
taşıma disiplini** (time-stop / max-hold uygulaması canlıda işliyor mu).

### (f) Bakım notu (kod, read-only gözlem)

`main.py` `--score-correlation` kontrolü (L57) container/DB init'inin (L31-39)
ARDINDA — rapor DB'ye dokunmaz ama giriş yerel Postgres yokken çöküyor. Flag
kontrolü init'e taşınmalı (ayrı bakım commit'i adayı).

## 6. Karar

**Eşikler KORUNUR. Config/commit değişikliği YOK** (protokol kuralı tetiklenmedi).
Faz 4 (skor modeli incelemesi) adayı açık kalır; somut aday sırası:

1. Canlı tracker profil + CSV yazım kriteri doğrulaması (§5-c) — verinin
   yorumlanabilirliği buna bağlı
2. Stop-slip / EOD taşıma disiplini denetimi (§3, §5-e) — TRALT deseni
3. Champion bandı [28,33] canlı doğrulaması için bant-içi örnek birikimi
   (n=16 → ≥30 hedefi; bucket bazlı karar ancak o zaman mümkün)

## 7. Sonraki Karşılaştırma Tabanı

2026-09-23: **46 outcome / 12 gün / r=0.147 / toplam net WR %41.3 (19/46) /
bant-içi [28,33] WR %43.8 (n=16)** — sonraki tetik değerlendirmesi bu tabanla karşılaştırılır.
