# Gece stratejisi (kapanışta al, ertesi sabah sat) — ön kayıt (2026-09-27, sonuçlar görülmeden)

Bu dosya testten **önce** commit edilmiştir; kurallar, dönemler ve kabul kriteri
sonradan değiştirilmez. Sonuç ne olursa olsun üç kuralın tamamı raporlanır.

## Veri
- Yahoo günlük OHLCV (`auto_adjust=False`). Faz 0 kontrolü (2026-09-27, 20 hisse,
  2023-09 … 2026-09): Yahoo kapanışı İş Yatırım resmi kapanışıyla günlerin %99.7'sinde
  aynı, Yahoo açılışı resmi gün aralığının içinde %99.7. Açılış = açılış seansı fiyatı,
  kapanış = kapanış seansı fiyatı kabul edilir.
- Evren: o çeyreğin BIST100 üyeleri (`bist100_pit_quarterly.json`), 60 günlük medyan
  TL hacmine (kapanış × adet) göre en likit 50. Tek günlük |getiri| > %25 olan
  hisse-gece veri hatası sayılıp dışarıda bırakılır.

## İşlem zamanlaması
- t günü kapanışında karar ve alış (kapanış fiyatı), t+1 işlem günü açılışında satış
  (açılış fiyatı). Hafta sonu/tatil: bir sonraki işlem gününün açılışı.
- Sermaye her gece tamamen yatırımda, eşit ağırlık; gündüz getirisi sıfır.

## Kurallar (t günü verisiyle)
- **O1 Tümü:** likit 50'nin tamamı.
- **O2 Gün içi kaybedenler:** gün içi getirisi (kapanış / açılış − 1) en düşük 10 hisse.
- **O3 Güçlü kapanış:** kapanış konumu (kapanış − en düşük) / (en yüksek − en düşük)
  en yüksek 10 hisse (en yüksek = en düşük olanlar hariç).

## Maliyet
Midas BIST komisyonu sıfır. Seans kayması yön başına %0.05 (gidiş-dönüş %0.10);
stres testi yön başına %0.10.

## Kıyas
Para piyasası vekili: politika faizi × 0.85 (`portfolio_research.py`, elle girilmiş
faiz tablosu — bilinen sınırlama). Her t günü için kıyas getirisi, t kapanışından
t+1 kapanışına kadarki takvim günleri üzerinden tahakkuk eder (sermaye bu aralıkta
başka yerde değerlendirilemez).

## Dönemler
- Geliştirme: 2023-09-01 … 2025-06-30 (yalnızca raporlanır).
- **Saklı test: 2025-07-01 … 2026-09-25 — tek sefer değerlendirilir.**

## Kabul kriteri (bir kural için, saklı testte, temel maliyetle)
Günlük (net getiri − para piyasası) ortalaması > 0 **ve** t ≥ 2.4
(3 kural, Bonferroni). Stres maliyeti, en kötü gece ve maksimum düşüş ayrıca raporlanır.

## Açıklama: önceden görülen bilgi
2026-09-27'de, bugünkü 100 hisselik izleme listesi (hayatta kalma yanlılıklı) için
koşulsuz gece getirisinin (O1'e benzer) çeyreklik ortalamaları tüm dönem için
görüldü (her çeyrek pozitif, zayıflayan). Bu nedenle **O1 kör değildir**; O2 ve O3
hiç test edilmedi.

## Canlı paper (backtest sonucundan bağımsız)
O1, O2, O3 ikişer çıkışla (açılış seansı fiyatı; 10:30 fiyatı) canlı paper olarak
izlenir. Canlı liste 17:45'teki fiyatla hesaplanır (işlem yapılabilir olsun diye),
paper alış resmi kapanış fiyatından kaydedilir. Karar: en az 60 işlem günü sonunda
net − para piyasası ortalaması > 0 ve t ≥ 2.6 (6 varyant, Bonferroni).
