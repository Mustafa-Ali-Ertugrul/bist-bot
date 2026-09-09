# BIST Botu — Deney A/B/C Raporu (Walk-Forward A/B)

**Tarih:** 2026-08-28
**Kapsam:** `bot_teshis_raporu.md` §4'teki hızlı deneylerden üçünün (A: havuz filtresi, B: çıkış tasarımı RR, C: trend-onay) walk-forward OOS ölçümü.
**Veri:** `~/.cache/bist_bot/wf_data` (3y, 27.08.2026 yenilemeli), train/test/step = 252/63/63 gün, maliyet: commission 2bp + slippage 5bp/yön.
**Baseline:** `results/walk_forward_bist30_conservative_h3_off.csv` — conservative profil, H3 kapalı, mevcut motor (spread çift sayımı düzeltilmiş, Faz 1).

---

## 1. Sonuç Tablosu (hepsi aynı veri, aynı pencereler)

| Koşu | n | Pozitif OOS | Medyan % | Mean % | Overfit % | Ort. trade |
|---|---|---|---|---|---|---|
| **BASELINE h3_off** | 30 | **%63.3 (19/30)** | 1.01 | 1.19 | %46.7 | 8.9 |
| A: robust8, h3_off | 8 | %50.0 (4/8) | 0.18 | 1.02 | %25.0 | 10.1 |
| A: robust8, h3_on | 8 | %62.5 (5/8) | 0.23 | 1.09 | **%12.5** | 8.9 |
| B: target_rr 1.2 | 30 | %60.0 (18/30) | 1.00 | 0.95 | %40.0 | 9.6 |
| C: trend-onay m0.5 | 30 | %63.3 (19/30) | 1.01 | 1.16 | %46.7 | 8.9 |
| C: trend-onay m0.0 | 30 | %60.0 (18/30) | 1.01 | 1.10 | %46.7 | 8.9 |

**Hiçbiri %70 eşiğini geçemedi.** Üç tek-değişkenli deneyin hiçbiri pozitif payını artırmadı; ikisi (B, C-m0) hafif düşürdü.

## 2. Deney Bulguları

### Deney A — Robust watchlist (8 hisse)
- `results/robust_watchlist.csv` (cost-stress edge-decay filtresinden geçen 8 hisse: ASTOR, TUPRS, PETKM, SISE, GUBRF, ENKAI, ODAS, EKGYO) bu motor durumunda **transfer olamadı**: TUPRS (-%3.0) ve PETKM (-%3.2) filtreyi üreten dönemde güçlü, bu dönemde en kötü iki hisse.
- H3 (chase cap) açılınca overfit %25→%12.5'a indi, pozitif payı %50→%62.5 — ama n=8, Wilson LB çok geniş; karar için yetersiz.
- **Ders:** Geçmiş performanstan türetilen havuz filtresi = seçim yanlılığı riski somutlaştı. Filtre ileriye dönük (yeni OOS ayları) doğrulanmadan kullanılamaz.

### Deney B — target_rr 2.0 → 1.2
- 30/30 hisse değişti (hedef fiyat küresel değişir), net etki negatif: mean 1.19→0.95, pozitif payı 63.3→60.0.
- Kazananlar (MGROS +2.76, SASA +2.48, EKGYO +2.36, AEFES +2.14pp) kaybedenlerle (GUBRF -3.44, VAKBN -2.67, SAHOL -2.19, ENKAI -2.17, ASTOR -2.09pp) dengelendi.
- Overfit %46.7→%40.0 (iyileşme) ama getiri düşüşü daha büyük.
- **Yorum:** RR 1.2 kârlı trade'lerin kârını erken realize ederken, kazanan hisselerin büyük hareketlerini kesti. Teşhisteki "%4.7 TP" sorunu TP sıklığını artırmakla değil, sinyalin kendisiyle ilgili.

### Deney C — Trend-onay (P1-B ilk müdahale)
İki aşamada ölçüldü:
1. **İlk uygulama (ADX ≥ 20 onay):** 30 hissede baseline ile **birebir aynı** sonuç. Teşhis: ADX yönsüz güç ölçüsü — düşen bıçaklarda (güçlü düşüş) ADX yüksek, aşırı-satım satırlarının %50-70'i "onaylı" sayıldı. Ayrıca close>SMA20 aşırı-satım satırlarında hiç gerçekleşmiyor (tanım gereği fiyat bandın altında).
2. **Düzeltilmiş uygulama (close>SMA20 VEYA plus_di>minus_di):** gate bu kez ateşledi (aşırı-satım satırlarının %90+'ı onaysız) ama:
   - **m0.5 (yarı puan):** yalnız 2/30 hisse değişti — puan kaybı hiçbir skoru 25 eşiğinin altına düşürmedi (aşırı-satım kümesi RSI 12.6 + stoch ~12 ile zaten eşiğin üstünde kalıyor).
   - **m0.0 (sıfır puan):** 5/30 hisse değişti; net hafif negatif (EREGL -1.04, TRALT -1.03pp; SASA -0.77pp). Kesilen sinyaller ortalama zararlı değilmiş.
- **Yorum:** BB+CCI puanlarını kısmak tek başına yetmiyor; aşırı-satım sinyalinin asıl taşıyıcısı RSI-extreme (12.6) + stoch kümesi (~12) — onlar dokunulmaz kaldığı sürece eşik geçilmeye devam ediyor. P1-B'nin gerçek çözümü bileşen kısıntısı değil, **eşik/bileşen mimarisi** (teşhis §2 P1-C: skorun sıralama gücü yok).

## 3. Ortak Çıkarım

%49→%63 sıçraması ölçüm hatasının (spread çift sayımı) düzeltilmesiydi; **%63→%70 tek değişkenli ayarlarla gelmiyor.** Üç deney de aynı yapısal duvara çarptı:
- Sinyal felsefesi (aşırı-satım yakalama) ile çıkış tasarımı (trend takibi) uyumsuz — P1-A.
- Skor kalite değil eşik aracı — P1-C.
- Kayıp ayları sinyal seli + korelasyon — P1-D (makro kapısı backtest'te yok, P0-B).

## 4. Kod Değişiklikleri (hepsi additive, varsayılan davranış değişmedi)

| Dosya | Değişiklik |
|---|---|
| `src/bist_bot/strategy/params.py` | `oversold_requires_trend_confirm: bool = False`, `oversold_unconfirmed_score_multiplier: float = 0.5` |
| `src/bist_bot/strategy/scoring.py` | `_oversold_trend_confirmed` (close>SMA20 veya plus_di>minus_di; ADX kabul edilmez), `_oversold_gate`; BB BELOW_LOWER + CCI<-100 dallarına uygulandı |
| `src/bist_bot/validation/walk_forward.py` | `WalkForwardValidator(target_rr=...)` → `Backtester`'a iletilir (factory yolunda uyarı loglanır) |
| `scripts/run_walk_forward_bist30.py` | `--tickers-file`, `--target-rr`, `--oversold-trend-confirm`, `--oversold-unconfirmed-multiplier`; CSV'ye `target_rr`/`oversold_trend_confirm` kolonları; otomatik çıktı adlandırma |
| `tests/test_oversold_trend_confirm.py` | 18 yeni test (flag kapalı değişmezlik, DI onayı, ADX reddi, m0.0 varyantı, target_rr wiring) |

## 5. Doğrulama

- `ruff check` (değişen dosyalar): temiz.
- `pytest -q` tam paket: **1354 passed, 2 skipped** (psycopg2 ortamsal).
- Baseline dosyalarına dokunulmadı; tüm deney çıktıları ayrı dosyalarda:
  - `results/walk_forward_robust_watchlist.csv` (A h3_off)
  - `results/walk_forward_robust_watchlist_h3_on.csv` (A h3_on)
  - `results/walk_forward_expB_rr1.2.csv` (B)
  - `results/walk_forward_expC_tc_m0.5.csv`, `results/walk_forward_expC_tc_m0.csv` (C)

## 6. Sıradaki Kaldıraçlar (bu raporun işaret ettikleri)

1. **P0-B makro kapısı paritesi** — canlıda var, backtest'te yok; 2023-10 tipi aylar hiç ölçülmedi. En yüksek bilgi değeri.
2. **P1-C bileşen mimarisi** — skoru eşik aracı olmaktan çıkaracak yeniden tanımlama (bileşen-döküm CSV + regresyon).
3. **P2-A maliyet kalibrasyonu** — gerçek komisyon/BSMV çizelgesi (kullanıcı verisi bekleniyor).
4. Deney C'nin genişletilmiş varyantı (RSI-extreme + stoch dahil tüm aşırı-satım kümesi gate'lenirse) — ancak P1-C mimarisiyle birlikte anlamlı.

*Rapor, negatif sonuçları olduğu gibi kaydeder; hiçbir deney canlı profile uygulanmadı.*
