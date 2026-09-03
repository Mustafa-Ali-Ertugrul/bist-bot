# Veri Envanteri Baseline — 22.08.2026

> Kaynak: production Postgres `bist_bot` (pg_dump yedeği restore testi ile doğrulandı: `backups/bist_bot_backup_2026-08-22.sql`, 8.9 MB)

| Metrik | Değer |
|---|---|
| signals toplam | 5.500 |
| signals outcome=PENDING | 5.500 (%100) |
| signals actionable (AL/GÜÇLÜ AL/SAT) | 263 |
| paper_trades toplam | 3.892 |
| paper OPEN | 0 |
| **paper NULL PnL (exit_price dolu)** | **3.222** |
| scan_log toplam | 247 |
| son tarama | 2026-08-21 14:15:28 UTC (17:15 TSİ) |

Notlar:
- NULL PnL stoğu yalnız bu haftanın 1.776 satırı değil; geçmiş haftalardan gelen toplam 3.222 satır onarım bekliyor.
- Restore provası: yedek `bist_bot_restoretest` geçici DB'sine restore edildi, satır sayıları doğrulandı, DB droplandı. PASS.
