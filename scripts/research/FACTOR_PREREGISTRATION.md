# Temel veri faktörleri — ön kayıt (2026-09-24, sonuçlar görülmeden)

Bu dosya testlerden **önce** commit edilmiştir; kurallar, dönemler ve kabul
kriteri sonradan değiştirilmez. Sonuç ne olursa olsun beş hipotezin tamamı
raporlanır.

## Veri
- Kaynak: İş Yatırım `HisseTekil` (günlük düzeltilmiş kapanış, piyasa değeri PD,
  TL hacim) ve `MaliTablo` (çeyreklik `2O` özkaynak, `3Z` ana ortaklık net
  kârı, yılbaşından birikimli). `scripts/research/fetch_isyatirim.py`.
- Evren: o tarihteki BIST100 üyeleri (`bist100_pit_quarterly.json`), ≥250/260
  gün geçmiş, 60 günlük medyan TL hacme göre en likit 50.
- Bilanço kullanım gecikmesi (ileriye bakmama): Mart → 15 Haziran, Haziran →
  15 Eylül, Eylül → 15 Aralık, Aralık → ertesi yıl 15 Nisan.
- TTM net kâr: çeyrek YTD + (önceki yıl yıllık − önceki yıl aynı çeyrek YTD).

## Kurallar (aylık, ay sonu sinyal, ertesi gün kapanış işlem, %0.35/yön maliyet, ilk 10 eşit ağırlık)
- **V1 Defter/Piyasa:** en yüksek `2O / PD` (özkaynak > 0).
- **V2 Kâr getirisi:** en yüksek `TTM 3Z / PD` (> 0 olanlar).
- **Q1 Kârlılık (ROE):** en yüksek `TTM 3Z / 2O` (özkaynak > 0).
- **C1 Değer + Momentum:** V1 ve 12-1 ay momentum yüzdelik sıralarının ortalaması.
- **C2 Değer + Kalite:** V2 ve Q1 yüzdelik sıralarının ortalaması.

## Dönemler
- Geliştirme: 2016-04 … 2022-12 (yalnızca raporlanır, hiçbir parametre değiştirilmez).
- **Saklı test: 2023-01 … 2026-09 — tek sefer değerlendirilir.**

## Kabul kriteri (bir kuralın "kâr eden" sayılması için hepsi)
1. Saklı testte net yıllık getiri > XU100 al-tut **ve** > para piyasası.
2. Geliştirme döneminde net yıllık getiri > likit-50 eşit ağırlık.
3. Tüm dönemde aylık XU100 üstü getirinin t-istatistiği ≥ 2.0.
5 hipotez test edildiği için 3. kriterde Bonferroni notu ayrıca verilir (t ≥ 2.6).

Rejim filtresi (T2) yalnızca kabul edilen kurallara ikinci varyant olarak uygulanır.
