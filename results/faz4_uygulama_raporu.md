# Faz 0/A/B/C/D Uygulama Raporu — "Saat Gibi Çalışan Sistem" (22.08.2026)

> Onaylı planın (v2 gözden geçirmelerle) A+B+C+D fazları uygulandı ve canlıya alındı.
> Doğrulama: **1243 pytest PASS** (2 skip: Postgres koşullu) · ruff src/ temiz · mypy temiz · Docker redeploy + smoke PASS.

## Faz 0 — Snapshot & Baseline
- `pg_dump` yedeği (8.9 MB) alındı; **restore provası** geçici DB üzerinde PASS.
- Veri envanteri: `results/data_inventory_baseline.md` (NULL PnL stoğu 3.222, PENDING 5.500).

## Faz A — Veri Onarımı (uygulandı)
- **A1 PnL backfill**: 3.222 NULL satır üretim fonksiyonuyla onarıldı; **405 drift satırı** düzeltildi (kök neden: Faz 3 öncesi "yanlış işlemi kapatma" hatası — kar kardeş işleme yazılıyordu); `chk_paper_profit_filled_on_exit` CHECK constraint eklendi; tüm yazımlar `paper_pnl_backfill_audit` tablosunda. → `results/backfill_pnl_raporu.md`
- **A2 Outcome backfill**: 155 actionable sinyal replay ile puanlandı (106 STOP / 46 TARGET / 3 TIMEOUT), 5.005 radar → `NOT_TRACKED`, 340 penceresi açık sinyal PENDING bırakıldı (barlar birikince re-run). Provenance: `outcome_source` kolonu (live_tracker / backfill_daily) + `backfilled_at`. → `results/backfill_outcome_raporu.md`
- Düzeltilmiş haftalık gerçek: **+%511.6 toplam, +%0.22/işlem, %32.5 kazanma** (önceki kısmi görünüm +%1091.9/%60 sanıyordu — radar işlemleri zararmış).

## Faz B — Doğruluk (P0)
- **B1 Seans modeli**: 17:30 sabiti kalktı. Sürekli işlem 10:00–**18:00**, kapanış seansı 18:00–**18:10**, EOD muhasebesi **18:12** (settings-güdümlü: `MARKET_CLOSE_HOUR`, `SESSION_CLOSE_BUFFER_MINUTES`, `EOD_CLOSE_DELAY_MINUTES`). Yarım gün `MARKET_HALF_DAY_HOUR:00`. Tatil takvimi son kullanma uyarısı (`warn_if_calendar_expiring`).
- **B2 EOD state machine**: hata artık günü "done" yapmıyor; 8 dk sonra retry (maks 2 deneme); final başarısızlıkta 🚨 Telegram. `close_positions_at_eod` alt-pass hatalarını scheduler'a yükseltiyor.
- **B3 Kapanış yolu**: `close_paper_trade(trade_id=...)` id-bazlı (çift OPEN karışması imkânsız); fiyat yoksa sessiz skip → sayaç + 5 eksikte Telegram uyarısı (spam'siz, günlük dedup); legacy `update_paper_close`/`update_all_paper_close` kaldırıldı (üretimde çağırıcısı yoktu); `queue_actionable_signals` per-signal guard + processed/failed özeti. "if not prices: return" erken çıkışı kaldırıldı (tüm veri yokken bile miss'ler sayılıyor).
- **B4 Tazelik kapısı**: seans içinde son bar >30dk eskiyse ticker atılır; **>%20 bayat → uyarı** (günde 1), **≥%40 → tarama tamamen durur** + 🛑 Telegram (yanlış güven üretilmez). Metrikler: `bist_stale_data_total`, `bist_stale_symbol_ratio`.

## Faz C — Saat Gibi Çalışma
- **C1**: SIGTERM yakalanıyor (`docker stop` artık graceful; log'da doğrulandı: SIGTERM → scheduler_stopped) + `stop_grace_period: 30s`.
- **C2**: Worker'a HTTP yüzeyi (`worker_http.py`): `/healthz` (liveness — healthcheck bunda, restart loop riski yok), `/readyz` (iş sağlığı: scan yaşı; 503 degrade), `/metrics` (Prometheus).
- **C3**: Scheduler-içi watchdog — seans içinde 30dk başarılı tarama yoksa Telegram (60dk cooldown) + toparlanınca "geri geldi" mesajı; `bist_alert_send_fail_total` alarm kanalının kendisini izliyor.
- **C4**: 3 retry tükenmesi → 🚨 escalation + `bist_scan_retry_exhausted_total` + recovery eventi.
- **C5**: Grid hizalama korundu; startup taraması ile grid slotu arası <5dk ise sonraki slota atlanır (çift tarama yok).
- **C6**: `scripts/deploy.ps1` — seans saatinde (10:00–18:00 TSİ) uyarı/onay, `BISTBotWorker` Task Scheduler görevi kontrolü (bu makinede görev yok — tek worker garantili), deploy sonrası smoke.
- **C7**: Prometheus worker'ı scrape ediyor (2 hedef UP doğrulandı); **7 alert kuralı** yüklü (scan stale, fail rate, stale-data, EOD fail, worker down, alert-kanal-fail); Grafana "BIST Bot Overview" dashboard'u provision edildi; `METRICS_PUBLIC` iç ağ için açık.

## Faz D — Config Tek Kaynak
- **D1**: Worker-only `MTF_ENABLED: "false"` kaldırıldı — araştırma: veri zaten iki zaman diliminde çekiliyordu, ayar sadece motor trend onayını kapatıyordu (API/worker sinyal sapması, performans kazancı sıfır). Dönem ayrımı: `results/baseline_after_mtf.md`.
- **D2**: `.env` duplikat anahtar temizlendi (`TELEGRAM_MIN_SCORE`).
- **D3**: Bozuk sayısal/bool env değerleri kayıt altında; `CONFIG_STRICT=true` (üretim container'ları) iken startup fail-closed.

## Bilinen açık kalemler (Faz E/F/G'ye kaldı)
- 340 PENDING outcome: barlar biriktikçe `backfill_signal_outcomes.py` re-run edilmalı (ilk Pazartesi akşamı).
- Paper beta gate (E/F/G fazları): E2E smoke CI, Postgres port kapatma, Grafana admin şifresi, Alembic disiplini, Cloud Run yüzey incelemesi — beta öncesi.
- Prometheus alert'lerin Alertmanager/Telegram'a bağlanması (şimdilik UI + watchdog çift katman).

## Deploy notu
22.08 (Cumartesi, seans kapalı) `docker compose up -d --build` ile yayına alındı. Worker/api/ui healthy; `/healthz`,`/readyz`,`/metrics` ve Prometheus hedefleri doğrulandı; graceful shutdown test edildi. Pazartesi 10:00 ilk seans yeni kodla açılacak.
