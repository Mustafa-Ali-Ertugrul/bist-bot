# Aylık portföy araştırması (2026-09-24)

Soru: hangi basit, önceden tanımlanmış strateji BIST100 al-tut ve para piyasası
fonunu **hayatta kalma yanlılığı olmadan** yener?

## Adımlar

```powershell
$env:PYTHONIOENCODING="utf-8"
# 1) Tarihli BIST100 üyeliği (repoda hazır; yeni çeyrek eklenince yeniden kur)
.venv\Scripts\python.exe scripts/research/bist100_pit/build_pit_universe.py
# 2) Fiyatlar -> tmp/research_cache (gitignored)
.venv\Scripts\python.exe scripts/research/fetch_prices.py
# 3) Tarihli evrenle backtest
cd scripts/research; ..\..\.venv\Scripts\python.exe pit_backtest.py
```

`portfolio_research.py` ortak fonksiyonları taşır; kendi `main()`'i bugünkü
listeyi geriye taşıdığı için **yanlılıklı** ilk testtir (karşılaştırma için).

## Tarihli üyelik verisi

`src/bist_bot/data/universe/bist100_pit_quarterly.json` — 2016 Q2 … 2026 Q4.
Kaynak: Borsa İstanbul dönemsel değişiklik duyuruları (`bist100_pit/changes.json`).
Yeni çeyrek: duyuru sayfasını `https://www.borsaistanbul.com/node/<id>` ile
kaydedip `parse_announcements.py <html_dir>` çalıştır, sonra 1. adım.
Elle doğrulanan düzeltmeler: `bist100_pit/overrides.json`.

Not: `bist100_2023-01-01.json` ve `bist100_2024-01-01.json` adlarına rağmen
aynı listedir ve **2026 Q1** üyeliğidir.

## Sonuç (2016-04 … 2026-09, gerçekçi maliyet, 1 gün gecikme)

| Strateji | Yıllık | Maks. düşüş | 12 ayda zarar olasılığı |
|---|---|---|---|
| Para piyasası (politika faizi × 0.85, yaklaşık) | %18.4 | 0 | %0 |
| XU100 al-tut | %31.5 | −%25 | %16 |
| T2: XU100 12 ay getirisi > fon ise endeks, değilse fon | %36.7 | −%20 | %4 |
| M2: T2 açıkken 12-1 momentum ilk 10 (likit 50 içinde) | %41.8 | −%23 | %2 |

M2 − XU100: aylık +%0.66, t≈1.2 (istatistiksel olarak kanıtlanmış değil).
2024 (%12 vs fon %40) ve 2026 yılbaşından beri fonun gerisinde. Canlıda
`services/monthly_portfolio_service.py` bu kuralı paper modda izler.
