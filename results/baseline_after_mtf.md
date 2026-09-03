# D1 — MTF Hizalama Baseline Notu (22.08.2026)

## Değişiklik

`docker-compose.yml` scanner-worker servisindeki `MTF_ENABLED: "false"` satırı kaldırıldı. Worker artık API/UI ile aynı varsayılanı (`MTF_ENABLED=true`) kullanıyor.

## Gerekçe (araştırma sonucu)

- Satır 28.07.2026'da #108 commit'inde, gerekçe yorumu veya ilgili test olmadan eklendi.
- Tarama hattı (`fetch_multi_timeframe_all`) zaman dilimi ayarından **bağımsız olarak** hem trend (1g) hem tetik (15m) verisini çeker — kapatmanın performans/latency kazancı yok.
- Ayar yalnızca strateji motorunun günlük trend onayını (`TrendBias`) kullanıp kullanmadığını belirler (`engine_core.py:40`). Kapalıyken worker trend onayı NEUTRAL'a sabitliyordu.
- Sonuç: aynı piyasa için **API ile worker farklı sinyal üretiyordu** (iki farklı sinyal sistemi).

## Etki ve dönem ayrımı

- Worker sinyal dağılımı değişecektir (trend onayı aktif sinyaller → daha az karşıt-trend AL/SAT, eşiğe bağlı farklı actionable dağılımı).
- **Paper istatistiklerinde dönem ayrımı:** 22.08.2026 öncesi worker sinyalleri "pre-mtf-alignment", sonrası "post-mtf-alignment" olarak okunmalı. İki dönem tek seri gibi yorumlanmamalı.
- İlk ölçüm: hizalamadan sonraki ilk tam işlem haftasının (24.08'den itibaren) günlük raporlarında actionable sinyal sayısı ve kazanma oranı izlenmeli; `--score-correlation` P5 tetikleri yeni dönem verisiyle değerlendirilmeli.

## Geri dönüş

Satır geri eklenerek eski davranışa dönülebilir (`MTF_ENABLED: "false"` worker environment bloğuna).
