# BIST-Bot Teknik Yol Haritası (Roadmap)

Bu doküman, BIST-Bot projesinin mevcut "Sinyal + Paper Trade" yapısından, ölçeklenebilir ve profesyonel bir "Algoritmik İşlem (Algo Trading) Motoruna" dönüştürülmesi için izlenecek teknik adımları içerir.

## 🔴 Aşama 1: Hemen Yapılacaklar (Hızlı Kazanımlar)
- [ ] `strategy.py` içindeki gömülü değerleri (magic numbers) tek yere taşı (`config/settings.py` veya `strategy_params.py`).
- [ ] Skor ağırlıkları, eşikler ve indikatör periyotları için tek bir parametre şeması (dataclass) oluştur.
- [ ] `backtest.py` içinde performans profili çıkar; en yavaş bölümleri (darboğazları) ölç.
- [ ] `risk_manager.py` için korelasyon hesaplamalarını hızlandıracak bir önbellek (cache) katmanı ekle.
- [ ] `README.md` dosyasını güncelle: Sistemin şu an "live trading" (canlı işlem) değil, "signal + paper trade" platformu olduğunu açıkça belirt.
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
- [ ] Aracı kurumlar (Broker) için bir `ExecutionProvider` soyutlaması (interface) tasarla.
- [ ] Paper trade (sanal işlem) ile Live Execution (canlı işlem) arayüzlerini birbirinden ayır.
- [ ] Emir yaşam döngüsü modeli ekle (durumlar: `created` -> `sent` -> `partial` -> `filled` -> `cancelled` -> `rejected`).
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
- [ ] Paper trade ile canlı işlem (Live trade) motorları mimari olarak aynı arayüzü (interface) sorunsuzca kullanabilmeli.
- [ ] Risk hesapları (özellikle korelasyon), tekrar eden ve işlemciyi yoran pahalı işlemlerden kurtulmalı.
