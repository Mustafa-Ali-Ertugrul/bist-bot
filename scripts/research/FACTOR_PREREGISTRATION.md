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

## Sonuç (2026-09-24, tek çalıştırma — kurallar değiştirilmedi)

Tek düzeltme: `f.eq` pandas metoduyla çakışıyordu (kolon adı `equity` yapıldı).

| Kural | Geliştirme yıllık | Saklı test yıllık | Tüm dönem t (XU100 üstü) | Karar |
|---|---|---|---|---|
| XU100 | %31.4 | %28.5 | — | — |
| Para piyasası | %12.2 | %30.6 | — | — |
| Likit50 eşit | %37.2 | %20.5 | — | — |
| V1 Defter/Piyasa | %35.2 | %32.0 | +1.01 | RED (kriter 2, 3) |
| V2 Kâr getirisi | %32.1 | %25.3 | +0.38 | RED |
| Q1 ROE | %37.0 | %19.0 | −0.15 | RED |
| C1 Değer+Momentum | %43.6 | %24.9 | +1.36 | RED (kriter 1, 3) |
| C2 Değer+Kalite | %42.5 | %21.4 | +1.17 | RED (kriter 1, 3) |

Hiçbir kural kabul edilmedi. Geliştirme döneminde en iyi görünen iki
kombinasyon (C1, C2) saklı testte hem endeksin hem fonun altında kaldı.

---

# Parti 2 — kâr/satış momentumu (ön kayıt, 2026-09-24, sonuçlar görülmeden)

Aynı veri, evren, gecikme kuralları, maliyet, ilk-10 eşit ağırlık ve dönemler.
Çeyreklik değer = YTD(q) − YTD(q−1) (aynı yıl; Q1 = YTD).
- **E1 Kâr sürprizi vekili:** en yüksek (son çeyrek net kâr − bir yıl önceki aynı çeyrek) / PD.
- **E2 Satış büyümesi:** en yüksek son çeyrek satış / bir yıl önceki aynı çeyrek − 1 (ikisi de > 0).
- **E3 Kâr sürprizi + momentum:** E1 ve 12-1 ay momentum yüzdelik sıralarının ortalaması.

Kabul kriteri parti 1 ile aynı; ancak saklı dönem artık toplam 8 hipotezde
kullanıldığı için 3. kriter **t ≥ 2.7** (Bonferroni, 8 test).
