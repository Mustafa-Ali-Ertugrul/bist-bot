# Canlı strateji ligi — ön kayıt (2026-09-24, lig başlamadan önce)

Başlangıç: 2026-09-30 kapanışı. Her ayın son seansında, EOD pass'ten sonra tüm
stratejiler paper olarak yeniden dengelenir (karar günü kapanışı, %0.35/yön
maliyet, nakit kısmı para piyasası getirisi kazanır). Kurallar, gruplar ve
kazanan kriteri bu dosyadan sonra değiştirilmez; yeni strateji eklenirse ayrı
ön kayıtla ve kendi başlangıç tarihiyle eklenir.

Veri: İş Yatırım günlük (düzeltilmiş kapanış, PD, TL hacim) + çeyreklik tablolar
(`2O`, `3Z`, `3C`), XU100 Yahoo. Evren: o çeyreğin BIST100 üyeleri, ≥250/260 gün
geçmiş, 60 gün medyan TL hacme göre en likit 50. Tanımlar
`FACTOR_PREREGISTRATION.md` ile aynı. "R" = rejim filtresi: XU100'ün 12 ay
getirisi para piyasasının 12 ay getirisinden düşükse tamamı nakit.

| Grup | Strateji | Kural |
|---|---|---|
| A | A1 M2 | R + 12-1 momentum ilk 10 |
| A | A2 T2 | R açıkken XU100, değilse nakit |
| A | A3 E1 | kâr sürprizi ilk 10 |
| A | A4 E2 | satış büyümesi ilk 10 |
| A | A5 V1 | defter/piyasa ilk 10 |
| A | A6 C1 | değer+momentum ilk 10 |
| B | B1 R+E1 | R + kâr sürprizi ilk 10 |
| B | B2 R+E2 | R + satış büyümesi ilk 10 |
| B | B3 R+V1 | R + defter/piyasa ilk 10 |
| B | B4 R+C1 | R + değer+momentum ilk 10 |
| B | B5 R+Q1 | R + ROE ilk 10 |
| B | B6 R+C2 | R + değer+kalite ilk 10 |
| C | C1 MOM5 | 12-1 momentum ilk 5 |
| C | C2 MOM20 | 12-1 momentum ilk 20 |
| C | C3 E2-5 | satış büyümesi ilk 5 |
| C | C4 E2-20 | satış büyümesi ilk 20 |
| C | C5 V1-20 | defter/piyasa ilk 20 |
| C | C6 EW50 | likit 50 eşit ağırlık |

Kıyaslar: XU100 al-tut, para piyasası.

## Kazanan kriteri (satışa aday ilan etmek için hepsi)
1. Canlı dönem ≥ 12 ay.
2. Canlı dönemde net getiri > para piyasası **ve** > XU100.
3. Backtest (2016-04 … 2026-09) + canlı aylık XU100 üstü getirinin t ≥ 2.0.
4. Ligde 2. koşulu sağlayanlar içinde en yüksek canlı getiri.

Ara raporlar her ay verilir ama karar değildir. 6. ayda para piyasasının
10 puandan fazla gerisinde kalan strateji "zayıf" olarak işaretlenir (izlenmeye devam eder).
18 strateji yarıştığı için tek bir ayın ya da çeyreğin liderliği anlamsızdır.
