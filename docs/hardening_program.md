# BIST Bot Sağlamlaştırma ve Doğruluk Programı (v1.0)

Tarih: 2026-08-27 · Durum: KABUL EDİLDİ (uygulama başlamadı) · Sahip: kullanıcı + build agent

Kaynak: iki bağımsız salt-okunur denetim (validasyon metodolojisi + veri/runtime güvenilirliği),
mevcut sonuç artifact'ları, kullanıcı kararları. Bu doküman programın tek doğruluk kaynağıdır;
sonradan yapılan her değişiklik sürüm numarasıyla (v1.1, v1.2…) kayıt altına alınır.

---

## 1. Amaç ve Bağlayıcı Kararlar

Botu "yüksek görünen skorlar üreten" bir sistemden; ölçülebilir, tekrarlanabilir ve gerçekçi
işlem maliyetleri sonrasında ekonomik avantaj sağlayıp sağlamadığı **kanıtlanabilen** bir
araştırma ve execution sistemine dönüştürmek.

Bağlayıcı kararlar (değişmez):

- İlk kapsam yalnızca **AL / GÜÇLÜ AL** sinyalleridir. SAT/GÜÇLÜ SAT ayrı program olmadan
  bu sisteme girmez.
- Ana doğruluk tanımı: **maliyet sonrası net kârlı kapanan işlem oranı** (`net_pnl > 0`).
- Hedef: doğrulanmış örneklemde **≥ %70 net kazanma oranı**. Bu hedef garanti edilemez;
  edge yoksa sistem bunu dürüstçe gösterir ve durur.
- `%70` bir optimizasyon hedefi (objective function) **değil**; promotion gate'in bir
  parçasıdır. Win rate tek başına optimize edilmez; expectancy, PF ve drawdown kapıları
  kaldırılamaz.

## 2. Başarı Sözleşmesi

### 2.1 İşlem tanımı

1. Yalnız kanonik `AL` / `GÜÇLÜ AL` sinyali işlem açar.
2. Aynı `(ticker, timeframe, source_bar_close, strategy_version)` için en fazla bir sinyal.
3. Sinyal mumunda giriş yoktur; giriş **sonraki işlem yapılabilir mumun açılışında**dır.
4. Gap fill kuralı deterministiktir (gap-through-stop/target açık tanımlı).
5. Stop/target kuralları deterministiktir; aynı mumda ikisi de görülürse **stop-first**.
6. Stop/target tetiklendiğinde exit fiyatı bar close'u olarak keyfi yazılamaz.
7. `target_hit`, `stop_hit`, `eod_close`, `max_hold_exit`, `gross_win`, `net_win` ayrı alanlar.
8. Maksimum tutma süresi **5 BIST işlem günü** olarak donduruldu.
9. `net_pnl > 0` tek kazanma tanımıdır; `TARGET_HIT` + net zarar = kayıp.

### 2.2 Eligible işlem tanımı (örneklem sayımında kullanılır)

Örneklem kapılarındaki "işlem" sayısı yalnızca şu koşulların tamamını karşılayan işlemlerdir:

- kanonik AL/GÜÇLÜ AL sinyalinden açılmış,
- unique key ile tekilleştirilmiş (duplicate/quarantine/NOT_TRACKED hariç),
- canonical execution model ile simüle veya fiilen gerçekleşmiş,
- **kapanmış** (outcome kesinleşmiş) işlem.

`NOT_TRACKED` ve karantinaya alınan satırlar hiçbir metrik paydasına girmez.

### 2.3 R tanımı

`1R = |entry_price − initial_stop_price| × position_size`

Expectancy hem TL hem R cinsinden raporlanır. `%75 win rate` ile `-0.1R expectancy`
üreten sistem başarısız sayılır.

## 3. %70 İddiasının Üç Seviyesi

- **Seviye A (araştırma):** gözlenen net win rate ≥ %70.
- **Seviye B (terfi):** gözlenen ≥ %70 **ve** Wilson %95 alt sınır ≥ %65 **ve** ekonomik
  kapılar geçilmiş.
- **Seviye C (istatistiksel iddia):** Wilson %95 alt sınır > %70. Nihai ve en zor hedef.

**Kapı aritmetiği notu (bilinçli muhafazakârlık):** n=300'de gözlenen tam %70, Wilson alt
sınırı ≈ %64.6 verir — yani terfi kapısı fiilen **~%71+ gözlemlenen** oran gerektirir.
Bu bir hata değil, kuralın bilinen sonucudur; kural bu haliyle korunur.

## 4. Geçiş Kapıları

### 4.1 Araştırma adayı

| Kriter | Eşik |
|---|---|
| Eligible kapanmış AL işlemi | ≥ 200 |
| Unique ticker | ≥ 20 |
| Kohort zaman kapsamı | ≥ 60 BIST işlem günü (span, bkz. not) |
| Rejim çeşitliliği | ≥ 4 anlamlı rejim dilimi (bull/bear/side × vol) |
| Net win rate | ≥ %70 |
| Wilson %95 alt sınır | ≥ %60 |
| Profit factor | ≥ 1.25 |
| Net expectancy | ≥ +0.10R/işlem |
| Maks. portföy drawdown | ≤ %12 |
| 2× maliyet stresinde PF | ≥ 1.0 |
| Tek ticker toplam net kâr payı | ≤ %20 |

### 4.2 Canlıya terfi adayı

| Kriter | Eşik |
|---|---|
| Eligible işlem (dokunulmamış OOS + prospective paper toplamı) | ≥ 300 |
| Kohort zaman kapsamı | ≥ 120 BIST işlem günü (span) |
| Net win rate | ≥ %70 |
| Wilson %95 alt sınır | ≥ %65 |
| Expectancy / PF / DD / stress / yoğunlaşma | 4.1'deki tüm eşikler korunmuş |

**"İşlem günü" = span:** kohortun kapsadığı BIST işlem günü aralığı; "işlem yapılan gün
sayısı" değil. Örneklem temposu ve takvim süresi **ayrı kapılardır** — stratejiyi zorla
trade üretmeye iten kota (ör. "haftada X işlem") **konmaz**. Bunun yerine doğal sinyal
frekansı ve `time-to-required-sample` ölçülür ve raporlanır.

**Bağımsızlık:** n sayısı "n bağımsız gözlem" iddiası taşımaz. Tüm istatistiksel çıkarımda
ticker / gün / rejim kümelemmesi hesaba katılır (bkz. §9).

## 5. P0-A — Metrik, Cost ve Outcome Sözleşmesi

Amaç: backtest, replay, paper ve live tracker'ın **tek bir gerçekliği** ölçmesi.

### 5.1 Bilinen somut hatalar (ilk sırada düzeltilir)

1. `backtest/engine.py`: spread hem fill fiyatını kötüleştirip hem ayrıca ücret olarak
   alınıyor → çift sayım kaldırılır.
2. `services/signal_outcome_tracker.py`: stop/target temasında exit fiyatı olarak o anki
   close yazılıyor → trigger seviyesinde fill yazılır (gap kuralıyla).
3. `db/repositories/signals_repository.py::get_performance_stats`: `NOT_TRACKED` paydaya
   giriyor → çıkar.
4. `reports/score_correlation.py`: `win = net_pnl>0 OR TARGET_HIT` → yalnız `net_pnl>0`;
   target-hit ayrı metrik.
5. `backtest/models.py`: Sharpe işlem getirilerine `sqrt(252)` uyguluyor → günlük portföy
   getirilerinden hesaplanır (P1 portföy simiyle tamamlanır).
6. `reports/performance.py`: `expectancy_r` aslında payoff ratio → doğru hesapla değiştirilir.

### 5.2 Tek maliyet motoru

- `TradingCosts` tek kaynak; backtest/replay/paper/tracker aynı motoru çağırır.
- Sıfır maliyet senaryosunda **tüm** maliyet alanlarının gerçekten sıfır olduğu fixture ile
  kanıtlanır (mevcut test `stamp_tax_bps`/`spread_bps` default'larını kaçırmıştı).
- Sürümlenen preset'ler: `BASE` / `REALISTIC` / `STRESS`.
- **Aksiyon (kullanıcı girdisi):** `REALISTIC` preset kullanıcının gerçek broker komisyon
  tarifesiyle kalibre edilir (tarife temin edilene kadar preset'in `DRAFT` etiketi taşır).
- Stress yalnız 2× toplam maliyet değil; **slippage duyarlılık** senaryosu da koşulur.

### 5.3 Execution model (deterministik durumlar)

`normal next-open fill`, `gap-through-stop`, `gap-through-target`, `limit-up/down`,
`suspension`, `missing bar`, `zero/invalid volume`, `partial fill`, `no executable
liquidity`, `order rejection`, `stale signal`, `market closed`, `max-hold exit`.

Backtest "teorik dolmuş" ile "gerçekten doldurulabilir" durumları ayırt eder.

### 5.4 Outcome şeması

Her işlem en az: `entry_time, entry_price_expected, entry_price_executable, exit_time,
exit_price_expected, exit_price_executable, quantity, gross_pnl, total_cost, net_pnl,
initial_risk, r_multiple, target_hit, stop_hit, eod_close, max_hold_exit, net_win,
outcome_provenance, strategy_version, data_version, cost_version, execution_version`.

### 5.5 Kanonik metrikler (tüm raporlarda aynı tanım)

Net win rate + Wilson CI · target/stop-hit rate · ort./medyan net getiri · expectancy (TL ve
R) · profit factor · payoff ratio · maks. drawdown · exposure · turnover · işlem başına
maliyet · sinyal coverage/frekans · n / işlem günü / unique ticker / rejim dağılımı.

### 5.6 Golden fixture ve teslimatlar

- `tests/golden/trade_contract/` — sabit fiyatlı referans senaryolar (yukarıdaki tüm
  execution durumlarını kapsayan JSON fixture'lar).
- `tests/test_trade_contract_parity.py` — **yeni** test: aynı fixture üzerinde
  backtest == replay == paper == tracker; giriş, çıkış, maliyet, outcome ve net PnL
  kuruş seviyesinde eşleşmeli.
- Etkilenen dosyalar: `risk/costs.py`, `backtest/models.py`, `backtest/engine.py`,
  `backtest/signal_replay.py`, `services/signal_outcome_tracker.py`,
  `services/paper_trade_service.py`, `services/shadow_trade_service.py`,
  `reports/performance.py`, `reports/score_correlation.py`,
  `db/repositories/signals_repository.py` + ilgili test dosyaları.

**Geçiş şartı:** golden fixture parite testi tam geçmeden P0-B'ye geçilmez.

## 6. P0-B — Market-Data Sözleşmesi

### 6.1 Zaman standardı

- Ingestion sınırında **UTC-aware** zorunlu; naive timestamp reddedilir.
- `Europe/Istanbul` yalnızca seans takvimi, gösterim ve raporlama içindir.
- Gelecek timestamp fail-closed.
- **Trigger ve trend frame'lerinin ikisi de** freshness kontrolünden geçer (mevcut kod
  yalnız trigger'a bakıyor).
- Seans dışı manuel tarama stale veriyi yeni sinyal gibi kaydedemez.
- 15m istenen çağrıda günlük StockAnalysis fallback **kesinlikle geçersizdir**.

### 6.2 OHLCV kalite kontrolleri

Monoton+tekil timestamp · beklenen interval · eksik mum/seans oranı ·
`high ≥ max(open,close)` · `low ≤ min(open,close)` · pozitif-sonlu fiyat/hacim · future-bar
sınırı · split/dividend ve aşırı getiri kontrolü · sıfır/eksik hacim politikası ·
metadata (provider, actual interval, adjustment, fetch time, last-bar time).

### 6.3 Point-in-time bilgi erişilebilirliği

Teknik OHLCV dışındaki her bilgi (macro, fundamental, news, şirket olayları) için
`observation_time` ≠ `available_at` ayrımı zorunludur; yalnız o anda **bilinir** olan veri
feature set'e girebilir. Örn. 18:30'da açıklanan bilanço 17:00 sinyalinin feature'ı olamaz.

### 6.4 Corporate actions

Raw + adjusted veri, adjustment policy ve split/dividend olayları birlikte tutulur;
kullanılan serinin adjustment politikası manifest'e yazılır.

### 6.5 Provider fallback

`None` / boş / kısmi / kalite başarısız payload = provider hatası (circuit breaker sayılır).
Kısmi batch'te yalnız eksik ticker'lar ikinci provider'dan **batch** olarak tamamlanır.
Yanlış fallback adı startup'ta reddedilir. Retry: total deadline + exponential backoff +
jitter; rate limiter thread-safe. Tekil/batch/chart/fallback yolları aynı adjusted/raw
politikasını kullanır.

### 6.6 D1 — Tarihsel Intraday Veri Karar Kapısı (KRİTİK)

Canlı stratejinin tetiği **15m**; mevcut araştırma altyapısı ağırlıklı **günlük bar** ile
çalışıyor. Bu çözülmeden yapılan hiçbir kanonik araştırma koşusu "canlı stratejiyi temsil
eder" iddiası taşıyamaz. P2 başlamadan önce **bir** seçim yapılır:

- **(a)** ≥ 3 yıllık 15m BIST geçmişi güvenilir bir kaynaktan temin edilir (ücretli olabilir)
  ve araştırma dataset'i 15m tetik + günlük trend ile kurulur; **veya**
- **(b)** araştırma kapsamı açıkça **günlük-bar sinyal sözleşmesine** indirgenir; stratejinin
  15m tetik katmanı P4 prospective fazda ayrıca doğrulanır (bu durumda canlıya terfi,
  15m katmanının prospective doğrulamasını da içerir).

D1 kararı bu dokümanın v1.1'ine kaydedilir; kararsız P2 başlatılamaz.

**Geçiş şartı:** yanlış frekans / stale-future bar / adjustment uyuşmazlığı sıfır; canonical
evrende coverage eşik üstü.

## 7. P0-C — DB, Migration, Idempotency (sermaye güvenliği)

1. `scan_once()` typed durum döndürür: `SUCCESS / PARTIAL / NO_DATA / STALE_HALT /
   CIRCUIT_OPEN / FAILED`. Watchdog yalnız geçerli veri + yeterli coverage + başarılı
   persistence'ı başarı sayar.
2. Idempotency: `scan_runs` tablosu + deterministik run anahtarı; sinyal unique key
   `(ticker, timeframe, source_bar_close, strategy_version)`; paper/ledger DB unique
   constraint; broker deterministic client-order-id; sinyal+scan log tek transaction;
   bildirim/broker için transactional outbox; retry duplicate sinyal/emir/işlem/bildirim
   üretmez; açık ticker pozisyonu varken ikinci paper pozisyon açılmaz.
3. Migration: ORM ↔ Alembic eşitleme (`score_breakdown`, outcome provenance,
   `paper_trades.direction`, `trade_ledger`, unique/check/index, timezone politikası);
   SQLite runtime DDL kapanır; gerçek PostgreSQL'de upgrade → uygulama testi → rollback
   provası yapılır.
4. Timeout/concurrency: timeout worker'a cooperative deadline iletir; timeout sonrası arka
   planda yazan scan olmaz; process-local mutex yerine distributed/advisory lock; API/UI/
   worker aynı mutable `StrategyEngine`'i eşzamanlı paylaşmaz.
5. State ownership: outcome/shadow state DB'de; CSV yalnız export.

**Geçiş şartı:** concurrent+retry testlerinde duplicate = 0; kill/restart sonrası durum
kaybı / yarım batch yok.

## 8. P1 — Parity ve Doğru Walk-Forward

### 8.1 Decision kernel

Sinyal kararı side-effect'siz ortak kernel'e indirilir: indikatörler, skor, ADX/rejim,
MTF confluence, macro gate, chase/counter-trend, **günlük frameden** likidite (15m'in son
20 mumundan değil), stop/hedef seçimi. Live, replay ve backtest aynı kernel'i çağırır.
Kernel saf fonksiyondur, test edilebilir.

### 8.2 Sürüm dondurma ve invalidation

`strategy_version`, `feature_version`, `cost_version`, `execution_version`, `data_version`
ayrı ayrı freeze edilir. **Final OOS açıldıktan sonra** bunlardan herhangi biri
değişirse final test **geçersiz** sayılır; yeni sürümle yeni final test gerekir.
Değişiklik sonrası "sonuç hâlâ geçerli" yorumu yapılamaz.

### 8.3 Walk-forward protokolü

- OOS pencereye yeterli warm-up geçmişi verilir; test sınırı öncesi emir açılamaz; ilk OOS
  sinyali continuous-history koşusuyla birebir aynı olmalı (testle kanıtlanır).
- Sabit-strateji testi "rolling temporal holdout", parametre seçen test "nested
  walk-forward" olarak ayrıştırılır; 252 günlük train ile 63 günlük test ham getirilerini
  karşılaştıran mevcut overfit flag kaldırılır.
- Per-window ortalama yerine **tek kronolojik birleşik OOS equity curve** kurulur ve
  acceptance gate'e bağlanır; gerçek OOS max drawdown bu eğriden hesaplanır.
- Sharpe günlük portföy getirilerinden hesaplanır.

### 8.4 Portföy simülasyonu

Ortak sermaye · eşzamanlı açık pozisyonlar · pozisyon boyutu · sektör/korelasyon limitleri ·
turnover · likidite/capacity · günlük risk limiti · **katılım cap'i**: işlem başına bar
hacminin en fazla %5'i (yapılandırılabilir); cap'i aşan işlemler capacity-limited olarak
işaretlenir ve raporlanır.

**Geçiş şartı:** golden market-data fixture'da live kernel / backtest / replay sinyal
zamanı, giriş-çıkış, outcome ve PnL'de birebir aynı.

## 9. P2 — Araştırma Veri Seti, İstatistik, Baseline

1. Immutable, point-in-time veri seti (D1 kararına göre 15m+günlük veya yalnız günlük).
2. Kronolojik dönemler: geliştirme/train → validation → calibration → **dokunulmamış final
   test**. Final test tüm strateji kararları bitene kadar açılmaz.
3. Label horizon'u kadar **purge + embargo**; aynı günün ticker'ları split'in iki tarafına
   düşemez (same-day grouping).
4. Tüm random search'ler seed'li; denenmiş kombinasyonlar kayıt altında.
5. Baseline'lar **aynı sermaye, maliyet, exposure ve holding kısıtları** altında
   karşılaştırılır: XU100 buy-and-hold · PIT eşit ağırlıklı evren · basit momentum ·
   cash/risk-free · mevcut conservative · research_v1.
6. İstatistik: Wilson (win rate) · gün/blok bootstrap (getiri, DD, PF) · tarihe göre
   clustered karşılaştırma · çoklu deneme düzeltmesi (FDR) · deflated/probabilistic Sharpe.
7. Her deneyin ekonomik ve istatistiksel kabul kuralı **önceden** yazılır (pre-commit).

**Geçiş şartı:** sızıntı sıfır; aynı manifest+seed ile yeniden üretilebilir; aday maliyet
sonrası baseline'ları geçer.

## 10. P3 — Strateji Hata Analizi ve İyileştirme (tuning yalnız bu fazda)

1. **Sinyal hunisi:** tüm barlar → veri geçerli → likidite geçerli → rejim → ADX → MTF →
   macro → skor geçerli → actionable AL → executed → net outcome. Her aşamada
   sayım/reddetme oranı/sonraki net outcome ölçülür.
2. **Ablation:** momentum, trend, volume/OBV, structure, ADX, MTF, macro, counter-trend,
   chase, likidite, stop/hedef — tek tek çıkarılır; yalnız dokunulmamış validation'da net
   ekonomik katkı veren bileşen kalır. `+indikatör = +performans` varsayımı yasak.
3. **Segment analizi:** rejim, volatilite, likidite quintile, sektör, gün içi saat, ticker,
   skor/confidence bucket, entry gap, sinyal-giriş gecikmesi. Zararlı segmentte ilk aksiyon
   **filter/abstain**; segmente özel yeni strateji son çare.
4. **Seçici işlem:** score olasılık değildir → purged calibration setinde
   `score → P(net_win)` (isotonic/Platt) kalibre edilir; işlem şartı
   `P(net_win) yeterli AND EV > 0 AND risk uygun`. Coverage zorunlu rapordur; zorla trade
   kotası yok (bkz. §4 span notu).
5. **Stop/hedef/holding sweep:** win rate'i hedef küçültmekle yükseltmek yasak; her sweep
   WR + expectancy(R) + PF + DD + turnover ile birlikte değerlendirilir; sweep yalnız
   walk-forward içinde; gap/limit/suspension/slippage/no-fill senaryoları dahil.
6. **ML en son:** mevcut test AUC 0.4707 → mevcut meta-model terfi edilemez. Sıra:
   constant-prevalence baseline → lojistik regresyon → kalibrasyon → feature stability +
   permutation importance → XGBoost ancak basit baseline gerçekten geçilirse. Label sözleşmesi:
   gerçekten üretilecek AL sinyalleri + next-bar-open giriş + kanonik stop/hedef + kanonik
   maliyet + `net_pnl > 0` + purged/embargoed split.

**Geçiş şartı:** aday profil dokunulmamış validation'da §4.1 kapılarını diğer ekonomik
kriterleri bozmadan geçmeli.

## 11. P4 — Prospective Shadow/Paper + Drift

1. Eski paper/shadow/backfill/legacy outcome'lardan ayrı, temiz
   `strategy_version = research_candidate_X` cohort'u.
2. Önce shadow, sonra paper; gerçek emir yok; paper süresince sürümler freeze.
3. Beklenen fill ↔ gerçekleşen/executable fill farkı kaydedilir.
4. Günlük rapor: WR+Wilson, expectancy, PF, DD, coverage, execution gap, provider/data
   quality, drift, rejim/ticker dağılımı, cost sapması.
5. **Drift izleme (performans düşüşünden ÖNCE):** feature/score/ticker/rejim dağılım drift'i,
   provider/kalite drift'i, execution/slippage drift'i, kalibrasyon drift'i. Örn. %80
   confidence verilen işlemler %55 net-win üretmeye başladıysa bu, WR düşmeden görünmelidir.
6. Kötü sonuçta otomatik threshold değiştirme yok → aday `REJECTED`, araştırmaya dönülür.
7. Backfill-daily outcome'lar live-intraday cohort'a **asla** karıştırılmaz.

**Geçiş şartı:** terfi kapılarının tamamı ileriye dönük veride geçmeli.

## 12. P5 — Kontrollü Canary

Düşük sermayeli canary; hard limitler (max pozisyon, eşzamanlı pozisyon, sektör exposure,
günlük zarar, haftalık DD, turnover, slippage, data staleness). Otomatik kill switch:
stale veri, yanlış interval, DB/outbox backlog, duplicate order, aşırı slippage, günlük
zarar, risk ihlali, drift ihlali, execution uyuşmazlığı. Canary ↔ paper günlük aynı
benchmark altında karşılaştırılır (toleranslar önceden tanımlı: giriş fiyatı farkı, net PnL
sapması). Rollback yalnız strategy/config sürümünü değiştirir; veri geçmişi silinmez.

## 13. P6 — Uzun Vadeli İzleme ve Yeniden Kalibrasyon

Canlı sonrası plan bitmez: sürdürülebilir drift panelleri, dönemsel (pre-commit protokollü,
**manuel**) yeniden kalibrasyon değerlendirmeleri, kapıların canlı karşılıklarının izlenmesi.
Otomatik kendini-kurtarma yoktur; her değişiklik yeni sürüm + yeni doğrulama gerektirir.

## 14. Paralel İş Akışı — Üretim Altyapısı

Mevcut sorunlar: worker deploy edilmiyor · API/UI ayrı ephemeral `/tmp` SQLite · temiz UI
deploy'u timeout validation'ı ihlal edebiliyor · multi-instance duplicate · readiness
koşulsuz 200 · Flask dev server.

Düzeltmeler: shared Cloud SQL/PostgreSQL zorunlu · dedicated singleton worker veya Cloud
Scheduler + Cloud Run Job · distributed/advisory lock · API/UI/worker aynı DB · Alembic
migration deploy öncesi ayrı adım · uyumlu request/scan/UI/Cloud Run timeout bütçesi ·
production WSGI (gunicorn) · gerçek liveness/readiness · provider/data-age/duplicate/scan-
status/outbox/outcome-backlog metrikleri · runtime JSON/CSV'nin image'a girmesi engellenir.

## 15. Kesinlikle Yapılmayacaklar

- P0/P1 bitmeden: threshold tuning, indikatör ekleme, ML promotion, stop/target
  optimizasyonu, backtest sonucuna göre canlı strateji değişikliği.
- `backfill_trade_ledger.py --apply`: P0-C migration + idempotency tamamlanmadan çalıştırılmaz.
- Gerçek broker emir entegrasyonu: deployment hardening + tüm kapılar geçilmeden açılmaz.
- Mevcut uncommitted worktree değişiklikleri korunur; yeni çalışmalarla karıştırılmaz.
- Elle "bence bu PASS" denemez; promotion gate yalnız harness çıktısıyla kesinleşir.

## 16. Doğrulama Komutları ve Ortam Notları

```powershell
# P0-A
uv run pytest tests/test_trade_contract_parity.py tests/test_backtest_costs.py tests/test_trading_costs.py tests/test_signal_replay.py tests/test_signal_outcome_tracker.py tests/test_performance_report.py -q

# P0-B
uv run pytest tests/test_schemas.py tests/test_data_fetcher.py tests/test_data_layer_integration.py tests/test_freshness_gate.py tests/test_universe.py -q

# P0-C
uv run pytest tests/test_scanner.py tests/test_scheduler.py tests/test_repository_signals.py tests/test_paper_trade_service.py tests/test_trade_ledger.py tests/test_order_lifecycle.py -q
uv run alembic heads; uv run alembic upgrade head; uv run alembic current
uv run pytest tests/test_db_postgres.py -q

# P1
uv run pytest tests/test_backtest_strategy_parity.py tests/test_walk_forward_validation.py tests/test_backtest_walkforward.py tests/test_risk_manager_integration.py tests/test_ml_position_sizing.py -q

# Genel kalite kapısı
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bist_bot
uv run pytest
```

Oram notları (dürüst kayıt):

- `ruff check .` şu an 2 export/import script'indeki 6 önceden var olan bulguyla başarısız —
  P0 hijyen maddesi olarak temizlenmeli; "geçti" ancak gerçekten geçince yazılır.
- `mypy` için pyproject'ta yapılandırma yok; ilk kullanımda eklenir.
- Lokal DB testleri için `DATABASE_URL` override (psycopg2 lokalde yok → sqlite).
- Windows/PowerShell: emoji çıktı için `python -X utf8`.

## 17. Kanonik Araştırma Harness'i (otomatik gate)

Yeni harness şu kontrolleri otomatik üretir: `MANIFEST_COMPLETE · CODE/DATA_HASH_PRESENT ·
UNIVERSE_POINT_IN_TIME · TIMESTAMP/FRESHNESS_VALID · NO_FUTURE_BAR · WARMUP_PARITY ·
NO_OOS_OVERLAP · PURGE/EMBARGO_VALID · COST_BASE_PASS · COST_2X_PASS ·
EXECUTION_STRESS_PASS · WILSON_VALID · BOOTSTRAP_VALID · BASELINE_COMPARISON_DONE ·
MIN_SAMPLE_PASS · REGIME_COVERAGE_PASS · TICKER_CONCENTRATION_PASS · AL_ONLY ·
NET_PNL_DEFINED · NO_DUPLICATES · PARITY_PASS` →
`PROMOTION_GATE = PASS | FAIL` (insan yorumuyla geçersizleştirilemez).

## 18. Karar Ağacı ve Temel Prensip

```text
DATA VALID?        → HAYIR: REJECT
POINT-IN-TIME?     → HAYIR: REJECT
PARITY VALID?      → HAYIR: REJECT
WALK-FORWARD VALID?→ HAYIR: REJECT
ISTATİSTİK KAPILARI?→ HAYIR: REJECT
EKONOMİK KAPILARI? → HAYIR: REJECT
PROSPECTIVE PAPER? → HAYIR: REJECT
CANARY             →
LIVE
```

> **Temel prensip:** Botun amacı %70'i göstermeye çalışmak değil; %70 gerçekten yoksa bunu
> kanıtlayıp sistemi başarısız olarak durdurabilmektir.

---

## Ek A — Yürütme Sırası

P0-A (metrik/cost/outcome) → P0-B (data contract + D1 kararı) → P0-C (DB/idempotency/
runtime) → P1 (kernel/parity/walk-forward) → P2 (dataset/istatistik/baseline) → P3
(funnel/ablation/kalibrasyon) → P4 (prospective shadow/paper + drift) → P5 (canary) →
P6 (izleme). Her workstream küçük diff'lerle ilerler; altyapı iş akışı (§14) paralel yürür.

## Ek B — Bilinen Mevcut Durum (kara gerçek, özellikle kanıt için)

Canlı outcome **7/21 = %33.3** (net PnL −TL215) · Shadow **5/23 = %21.7** (brüt −6.76pp) ·
Günlük backfill **98/268 = %36.6** · Eski paper kümesi **%32.5** (rejim karışık) · Replay
**5/7 = %71.4** (n=7, streste negatif) · ML test AUC **0.4707** (Brier 0.2161 >
constant-prevalence baseline). Bu sayılar %70 kanıtı değildir; programın varlık sebebidir.
