# A1 — Paper PnL Backfill Raporu (22.08.2026)

> Script: `scripts/backfill_paper_pnl.py` · Yedek: `backups/bist_bot_backup_2026-08-22.sql` (restore provası PASS) · Test: 12/12 PASS

## Yapılanlar

1. **3.222 NULL PnL satırı onarıldı** (`actual_profit_pct` boş, `exit_price` dolu) — üretim fonksiyonu `PaperTradeService.net_profit_pct` (komisyon+damga+BSMV dahil, yön farkındalıklı) ile hesaplandı.
2. **405 drift satırı düzeltildi** (`DRIFT_REPAIRED`): kök neden — Faz 3 öncesi "en yeni OPEN satırı kapat" hatası. Aynı hissede iki açık işlem varken kar eski işlemin girişine göre hesaplanıp yeni satıra yazılıyordu; saklanan değer kendi satırının fiyatlarıyla tutmuyordu. Her satırın gerçek PnL'ı kendi `signal_price`+`exit_price` çiftinden yeniden hesaplandı (audit: eski→yeni).
3. **CHECK constraint eklendi**: `chk_paper_profit_filled_on_exit` — `exit_price` doluysa `actual_profit_pct` NULL olamaz. Aynı hata türü DB seviyesinde imkânsız.
4. Tüm yazımlar `paper_pnl_backfill_audit` tablosuna kayıtlı (3.222 REPAIRED + 405 DRIFT_REPAIRED). İkinci çalıştırma: 0 aday (idempotent PASS).
5. Cross-check: 669 dolu satır kontrol edildi — 135 birebir, 129 fee-delta (bilinen legacy gross fallback), 405 beklenmedik (yukarıda kök nedeni).

## Düzeltilmiş Haftalık Gerçek (17–21 Ağustos)

| Metrik | Onarım öncesi (kısmi görünüm) | **Onarım sonrası (gerçek)** |
|---|---|---|
| PnL kayıtlı işlem | 602 | **2.378 (%100)** |
| Toplam getiri | +%1091.9 | **+%511.6** |
| İşlem başına ort. | +%1.81 | **+%0.22** |
| Kazanma oranı | %60 | **%32.5** |

**Yorum:** Görünmez kalan 1.776 işlem (Pzt–Çar radar işlemleri) ağırlıklı zararla kapanmış. Bu, hafta içinde alınan "yalnızca actionable sinyal işlem açar" disiplin kararını doğruluyor: Per–Cum (yeni rejim) izole performansı işlem başına +%1.10 iken, eski rejim bütününün ortalaması +%0.22'ye düşüyor. Eski rejimin işlem başına gerçek ortalaması ≈ −%0.10 civarındadır (602×1.81 − 2378×0.22 kıyaslamasından).

## Kalan risk

- Quarantine: 0 satır (tüm adaylar kesin hesaplanabildi).
- Eski `close_price` kolonu kullanan yollar (legacy) B3 kapsamında kaldırılacak.
