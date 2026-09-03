# BIST-Bot Teknik Yol Haritası (Roadmap)

Bu doküman, BIST-Bot projesinin mevcut "Sinyal + Paper Trade" yapısından, ölçeklenebilir ve profesyonel bir "Algoritmik İşlem (Algo Trading) Motoruna" dönüştürülmesi için izlenecek teknik adımları içerir.

## ✅ Durum — 21 Ağustos 2026 (Program Kapanışı)

> Bu bölüm, aşağıdaki tarihsel planın güncel durumunu özetler. Alt başlıklardaki eski maddelerin büyük bölümü bu programla kapatıldı; dokümanın gerisi tarihsel plana aittir.

| Program | İçerik | PR |
|---|---|---|
| **Faz 1 + 1.5** | Kanonik sinyal sınıflandırması (`categorize`), tek-geçiş günlük rapor, radar A/B/C kademeleri, grup bildirimi robust koruması, paper price-priority | #110 |
| **Faz 2** | Actionable outcome tracking (MFE/MAE, STOP/TARGET/EOD, DB geri yazım) + volatilite-adaptif stop/hedef (ATR fallback, MIN_STOP %1.5) + skor↔getiri korelasyon raporu; walk-forward parity **delta=0** | #110, kanıt #111 |
| **Faz 3** | Pozisyon disiplini: EOD close (post-close pası) + trailing stop + yaşam döngüsü sözleşmesi + likidite (5M₺ ADV) görünürlüğü + skor-decay uyarısı (≥15:30) | #112 (+P1.1) |
| **P5.0** | Kalibrasyon tetik görünürü (`--score-correlation` içi sayaç: ≥30 outcome / 10 işlem günü) | #113 |
| **Operasyon** | `--daily-report` CLI fix; runtime state dosyalarının untrack+ignore + `ShadowTradeService` test stub'u (git/OneDrive veri bütünlüğü) | #114, #115 |

**Günlük kontrol (EOD pası sonrası):** `python scripts/check_eod_pass.py` — log + outcome satırları + P5 tetik durumu + git hijyeni, tek komut.

**Bir sonraki veri kontrol noktası:** P5 kalibrasyon tetiği (~4-5 Eylül, veri saati 24 Ağustos'ta başladı). Koşu ve karar kuralları: `results/score_calibration_protocol.md` → çıktı `results/score_calibration_YYYY-MM-DD.md`.

**Bilinçli olarak ayrı proje olanlar (bu roadmap'in dışında):** KAP/haber entegrasyonu, sentiment analizi (SASA/ASTOR tipi), spread/kademe derinliği filtresi (yeni veri kaynağı gerektirir), `RESULTS_DIR` → Docker named volume (opsiyonel).

## 🔴 Aşama 1: Hemen Yapılacaklar (Hızlı Kazanımlar)
- [ ] `strategy.py` içindeki gömülü değerleri (magic numbers) tek yere taşı (`config/settings.py` veya `strategy_params.py`).
- [ ] Skor ağırlıkları, eşikler ve indikatör periyotları için tek bir parametre şeması (dataclass) oluştur.
- [ ] `backtest.py` içinde performans profili çıkar; en yavaş bölümleri (darboğazları) ölç.
- [ ] `risk_manager.py` için korelasyon hesaplamalarını hızlandıracak bir önbellek (cache) katmanı ekle.
- [x] `README.md` dosyasını güncelle: Sistemin şu an "live trading" (canlı işlem) değil, "signal + paper trade" platformu olduğunu açıkça belirt. *(tamamlandı: README üst banner + yanlış clone URL düzeltildi)*
- [ ] ML meta-model + olasılık kalibrasyonu (`Platt`/`isotonic`) + fractional Kelly pozisyon boyutlamasını üst seviye öncelik olarak devreye al.

## 🟡 Aşama 2: Kısa Vade (Performans ve Optimizasyon)
- [ ] `backtest.py`'yi mümkün olduğu kadar vektörel (vectorized) hale getirerek iteratif (for döngüsü) işlemlerden kurtar.
- [ ] Grid search / random search ile strateji parametre optimizasyonu (optimizer) ekle.
- [ ] Walk-forward validation (İleriye dönük doğrulama) ekleyerek tek dönemlik "curve-fit" (aşırı uyum) riskini azalt.
- [ ] Slippage (kayma) modelini sabit bir yüzde yerine; hacim, volatilite ve spread duyarlı hale getir.
- [ ] Backtest sonuçlarını tek formatta (JSON/CSV) kaydet ve özet metrikler (Sharpe, Max Drawdown vb.) üret.
- [ ] `app_metrics.py` katmanını thread-safe hale getir ve `prometheus_client` registry entegrasyonu ile sayaç yarışlarını kaldır.
- [ ] `OfficialProvider` retry/backoff akışını `RateLimitError.retry_after` semantiği ile üretim kullanımına göre sertleştir; 429/5xx davranışlarını testlerle doğrula.

## 🔵 Aşama 3: Orta Vade (Mimari ve Soyutlama)
- [x] Aracı kurumlar (Broker) için bir `ExecutionProvider` soyutlaması (interface) tasarla. *(tamamlandı: `execution/base.py` → `ExecutionBroker`, `place_order`/`get_balance` API'si)*
- [x] Paper trade (sanal işlem) ile Live Execution (canlı işlem) arayüzlerini birbirinden ayır. *(tamamlandı: `execution/paper_broker.py` + `execution/live.py`; eski `broker/` paketi kaldırıldı)*
- [x] Emir yaşam döngüsü modeli eklendi (durumlar: `created` -> `sent` -> `partial` -> `filled` -> `cancelled` -> `rejected`). *(tamamlandı: `execution/base.py` → `OrderState` enum'ı tüm durumları içeriyor)*
- [ ] Portföy ve risk kararlarını, genel tarama (scan) akışından bağımsız ayrı bir servis (microservice mantığı) haline getir.
- [ ] AlgoLab sandbox/doğrulama checklist'i oluştur; resmi HTTP path'leri teyit edilmeden canlı modu açma.
- [ ] Matriks/Foreks/Finnet adaptörleri için de aynı canlı kullanım politikası ve sandbox/mock doğrulama adımlarını zorunlu hale getir.

## 🟢 Aşama 4: Uzun Vade (Ölçekleme ve Makine Öğrenmesi)
- [ ] Kural tabanlı stratejinin yanına ML (Makine Öğrenmesi) tabanlı bir skorlayıcı veya meta-model ekle.
- [ ] ML meta-model için sinyal olasılık kalibrasyonu (`Platt`/`isotonic`) kur; pozisyon boyutlamayı Kelly / fractional Kelly ile besle.
- [ ] Özellik mühendisliği (Feature Engineering) katmanı kur: Rejim, volatilite, hacim profili, piyasa genişliği (breadth), sektörel göreceli güç.
- [ ] Modeller için çevrimiçi (online) veya periyodik yeniden eğitme (retraining) ardışık düzeni (pipeline) tasarla.
- [ ] Veri yükü arttığında SQLite yerine PostgreSQL + TimescaleDB geçiş planını devreye al.
- [ ] PostgreSQL + TimescaleDB geçişi için şema, retention/compression, backfill ve dual-write cutover planını önceden dokümante et.

---

## 🎯 Başarı Kriterleri
- [ ] Strateji parametreleri kod (mantık) değiştirilmeden dışarıdan güncellenebilir olmalı.
- [ ] Backtest süresi vektörel işlemler sayesinde belirgin şekilde saniyelere/milisaniyelere düşmeli.
- [ ] Aynı backtest, Walk-Forward Validation sayesinde farklı piyasa dönemlerinde daha stabil sonuçlar vermeli.
- [x] Paper trade ile canlı işlem (Live trade) motorları mimari olarak aynı arayüzü (interface) sorunsuzca kullanabilmeli. *(sağlandı: iki também `execution.base` aynı taban sınıfını kullanıyor)*
- [ ] Risk hesapları (özellikle korelasyon), tekrar eden ve işlemciyi yoran pahalı işlemlerden kurtulmalı.
