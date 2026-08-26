# A2 — Outcome Backfill Raporu

Tarih: 26.08.2026 15:06 UTC · Mod: APPLY

## Siniflandirma

| Karar | Adet | Anlam |
|---|---|---|
| SCORED_BACKFILL | 268 | Replay ile puanlandi (outcome_source=backfill_daily) |
| NOT_TRACKED | 625 | Radar / non-actionable / giris olusmadi |
| WINDOW_OPEN | 102 | Pencere acik; PENDING birakildi, tekrar kosulur |
| NO_DATA | 0 | Bars yok; PENDING birakildi |

## Puanlanan Sinyaller

- Toplam: 268 · Kazanan: 98 (kazanma orani 36.6%)

> **Semantik notu:** Backfill sonuctemel gunluk-bar T+1 semantigi tasir
> (giris = sinyal sonrasi ilk bar acilisi; cikis = kalici stop/hedef).
> Canli tracker intraday semantigi kullanir. Ayni alanlarda saklanirlar
> ama `outcome_source` ile ayristirilirlar; kalibrasyon filtresi
> `outcome_source='live_tracker'` kullanmalidir.