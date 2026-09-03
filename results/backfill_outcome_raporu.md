# A2 — Outcome Backfill Raporu

Tarih: 29.08.2026 09:55 UTC · Mod: APPLY

## Siniflandirma

| Karar | Adet | Anlam |
|---|---|---|
| SCORED_BACKFILL | 1 | Replay ile puanlandi (outcome_source=backfill_daily) |
| NOT_TRACKED | 3 | Radar / non-actionable / giris olusmadi |
| WINDOW_OPEN | 18 | Pencere acik; PENDING birakildi, tekrar kosulur |
| NO_DATA | 46 | Bars yok; PENDING birakildi |

## Puanlanan Sinyaller

- Toplam: 1 · Kazanan: 1 (kazanma orani 100.0%)

> **Semantik notu:** Backfill sonuctemel gunluk-bar T+1 semantigi tasir
> (giris = sinyal sonrasi ilk bar acilisi; cikis = kalici stop/hedef).
> Canli tracker intraday semantigi kullanir. Ayni alanlarda saklanirlar
> ama `outcome_source` ile ayristirilirlar; kalibrasyon filtresi
> `outcome_source='live_tracker'` kullanmalidir.