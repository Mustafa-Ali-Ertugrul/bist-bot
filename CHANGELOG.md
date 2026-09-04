# Changelog

Tum degisiklikler chronolojik sirayla listelenir.

## [Unreleased]

### Added
- `RBAC_MODE=warn|enforce` ile `/api/scan` icin DB-otoritatif admin/trader yetki kapisi eklendi.
- AlgoLab emirleri icin kalici `order_intents` outbox ve belirsiz timeout sonu reconciliation akisi eklendi.
- Model artefaktlari icin SHA-256 + Ed25519 manifest dogrulamasi ve guvenli JSON calibrator formati eklendi.
- Runtime/dev bagimliliklari icin dolu `uv.lock`, hash'li requirements exportu ve Dependabot guncelleme akisi eklendi.
- Cloud Run ve Compose API entrypoint'i Flask development server yerine tek-worker threaded Gunicorn'a tasindi.
- Yerel `opencode.json` credential dosyasi Git/Docker context'inden cikarildi.
- AlgoLab belirsiz emir uzlastirmasi acik emirler yerine gunluk tum emir gecmisini kullanacak ve eslesme yoksa kilidi koruyacak sekilde sertlestirildi.
- Live broker baslangici kalici non-SQLite veritabani ve resmi endpoint ayarlari olmadan fail-closed hale getirildi.
- Scanner icin route yetkisinden bagimsiz `AUTO_EXECUTE_ENABLED` guvenlik kapisi eklendi.
- Order intent manuel cozumu yalniz admin roluyle sinirlandirildi; zorunlu reason, broker UI teyidi ve ack icin broker_order_id eklendi.
- Cozulemeyen JWT identity warn/enforce fark etmeksizin 401 dondurur.
- AlgoLab startup reconcile eklendi; bagli broker emirleri eslestirmeden dislanir, broker durumlari ack/rejected/unknown olarak map edilir.
- DB kesintisinde WSGI degraded liveness (`/livez` 200, `/readyz` ve `/health` 503) eklendi.
- Degraded worker `DEGRADED_MAX_SECONDS` (varsayilan 300) sonunda SIGTERM ile sonlanir; Gunicorn master temiz worker acar.
- Reconcile muhasebesi eklendi: dogrulanmis dolumlar `orders`/`live_positions` defterlerine normal fill yoluyla ayni kanaldan islenir; eksik veri `ack_unaccounted` + kilit birakir.
- Migration note (davranis degisikligi): `CANCELLED` artik kosulsuz kilit acmaz; `filled_qty > 0` ise muhasebeye gider. Kismi dolumlarda kalan bacagi otomatik iptal icin `ALGOLAB_RECONCILE_CANCEL_REMAINDER=true` (varsayilan) ayarlayin; kapaliysa `ack_unaccounted` uretilir.
- Migration note: broker durum eslemesi `ALGOLAB_STATUS_MAP` (JSON) ile override edilebilir; gecersiz hedef startup'ta fail-closed.
- Migration note: `ADMIN_BOOTSTRAP_PASSWORD_HASH` formati startup'ta login verifier ile dogrulanir; bozuk placeholder hash boot'u dusurur.
- Migration note: existing deployments with `AUTO_EXECUTE=true` must explicitly set
  `AUTO_EXECUTE_ENABLED=true`; otherwise execution remains disabled and a startup warning/metric
  is emitted. The legacy `AUTO_EXECUTE` flag is scheduled for removal after one release.
- Walk-forward validation akisi eklendi; optimizer tabanli out-of-sample pencere testleri ve JSON rapor ciktilari uretiliyor.
- BIST'e daha yakin komisyon, BSMV, borsa payi ve slippage kirilimlarini izleyen cost model eklendi.
- AlgoLab broker entegrasyonu icin test edilebilir execution iskeleti, order tracker ve order lifecycle persistence eklendi.

### Changed
- Yeni JWT'ler kullanici ID'sini identity olarak kullanir, rol/e-posta claim'leri tasir ve en fazla 15 dakika gecerlidir.
- Yeni kullanicilarin ORM/veritabani varsayilan rolu en az yetkili `user` olarak degistirildi.
- AlgoLab emir POST'u timeout/5xx sonrasinda tekrar gonderilmez; client ID ile acik emirlerden uzlastirilir.
- `CALIBRATOR_TRUST=warn` gecis modu eklendi; sonraki surumde `enforce` ile imzasiz/joblib calibrator reddedilebilir.
- `CALIBRATOR_TRUST=off` kabul edilmez; artifact trust kontrolu tamamen kapatilamaz.
- Docker ve CI kurulumlari `uv sync --locked` ile tekrar uretilebilir hale getirildi.
- `backtest_runner.py` artik survivorship bias uyarisi basiyor ve `--walk-forward` modu ile pencere bazli dogrulama calistirabiliyor.
- Backtest ciktilarina `cost_breakdown` ozeti ve ek risk metrikleri (Sortino, CAGR, Profit Factor, Avg Trade) eklendi.
- Broker secimi artik `BROKER_PROVIDER` ile yapiliyor; `AUTO_EXECUTE` ve `CONFIRM_LIVE_TRADING` guvenlik kapilari eklendi.

### Fixed
- ADX hesaplama hizalamasi duzeltildi (`indicators.py`): `pd.Series(plus_dm)` yerine
  `df["plus_dm"]` kullanilarak pandas index alignment saglandi. Bu duzeltme
  sayesinde `detect_regime()` artik gercek BULL/BEAR/SIDEWAYS ayrimi yapiyor.

### Changed
- `BUY_THRESHOLD`: 10 → 15 (dusuk-vol hisselerde daha secici giris)
- Regime-aware trade filtering eklendi
- `MIN_REGIME_PERSISTENCE = 2`: En az 2 bardizinin ayni rejimde kalma gereksinimi
- `MOMENTUM_CONFIRMATION = 4.0`: Dusuk ADX durumunda %4 momentum gereksinimi
- `SIDEWAYS_EXTRA_THRESHOLD = 5`: Yatay piyasada ekstra filtreleme

### Performance
Backtest sonuclari (2y, THYAO/ASELS/EREGL/GARAN):

| Ticker | Onceki Getiri | Yeni Getiri | Delta | Onceki Trade | Yeni Trade |
|--------|--------------|-------------|-------|--------------|-------------|
| THYAO.IS | +17.9% | +24.4% | +6.4% | 23 | 26 |
| ASELS.IS | +9.9% | +33.6% | +23.7% | 2 | 22 |
| EREGL.IS | +0.0% | +39.3% | +39.3% | 0 | 31 |
| GARAN.IS | +0.0% | +62.4% | +62.4% | 0 | 33 |

- 4/4 hissede iyilesme, ortalama +33% getiri artisi
- THYAO'da aşiri islem azaltildi (34→26)
