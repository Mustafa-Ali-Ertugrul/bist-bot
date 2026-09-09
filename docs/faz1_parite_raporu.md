# Faz 1 Raporu — Maliyet Modeli Paritesi (Kontrat + Motor)

Tarih: 2026-08-28
Kapsam: Nihai Plan (v3) Faz 1 — kanonik ticaret kontratı, altın testler,
motor parite doğrulaması ve motor spread/slippage ayrıştırma düzeltmesi (Seçenek A).

## 1. Yapılan İş

### 1.1 Kanonik ticaret kontratı — `src/bist_bot/trade_contract.py` (yeni)
- `ExitReason` enum'u: STOP_LOSS, TAKE_PROFIT, MAX_HOLD, DATA_END, SIGNAL_EXIT.
- `TradeOutcome` (frozen dataclass): her taraf için fill fiyatı, spread,
  slippage, komisyon, borsa ücreti, BSMV, damga vergisi ve net kâr/zarar
  dahil tam ayrıştırma.
- `calculate_trade_outcome(...)`: kapalı formülün saf Python karşılığı.
  Ara yuvarlama yok; gap önce/sonra stop önceliği intrabar taramasıyla
  deterministik; maksimum elde tutma süresi (5 seans, giriş seansı 0) donduruldu.
- BSMV sınırlaması: motor `CostModel.bsmv_bps` satış-tarafı notional bazlı
  olduğundan parite `bsmv_pct=0.0 / bsmv_bps=0.0` ile kurulur; BSMV doğruluğu
  salt kontrat birim testleriyle güvence altında. Adapter uyumsuzluğu
  gelecek iş olarak kayıt altında.

### 1.2 Motor düzeltmesi — `src/bist_bot/backtest/engine.py` (Seçenek A, 5 düzenleme)
- Birim maliyet hesabına spread artık dahil değil; spread referans fiyat
  bazlı ve bilgilendirme amaçlı, fill fiyatının içinde.
- Satış tarafı maliyet/gelir hesabına spread eklenmiyor; slippage kolları
  spread'i dışarıda bırakıyor.
- `_fee_components` yalnızca nakit ücretleri (komisyon, BSMV, borsa ücreti,
  damga vergisi) döndüren bir yardımcı olarak kaldı; `"spread"`/`"total"`
  anahtarları artık ölü fakat zararsız (özel yardımcı, temizlik isteğe bağlı).

### 1.3 Testler — `tests/test_trade_contract_parity.py` (yeni)
- 16 altın kontrat testi: sıfır maliyet kimliği, salt spread, STOP,
  STOP_GAP, TARGET, TARGET_GAP, SAME_BAR_STOP_FIRST, MAX_HOLD, DATA_END,
  BSMV (`bsmv_pct=%5`), minimum komisyon tabanı, doğrulama (negatif giriş,
  geçersiz seans sayısı, bilinmeyen çıkış nedeni, 1 seanstan az veri),
  seans uyuşmazlığı.
- `ParityBacktester` + 7 satırlı parite çerçevesi: satır 0 eylemsiz (motor
  `df.iloc[:i]` geçmişinin boş olmaması için), 1–6 arası parite penceresi.
  Giriş sinyali geçmiş uzunluğu 1 iken (bar endeksi 1, open 100.0), çıkış
  sinyali geçmiş uzunluğu 6 iken (bar endeksi 6, open 103.0) tetiklenir;
  `close[5] == open[6] == 103.0` olduğundan motor çıkış referans fiyatı
  kontratın MAX_HOLD referansıyla birebir aynıdır.
- Motor 54 satırlık alt sınırı (`len(df) < 50 → None`) sebebiyle çerçeve
  sabit 103.2 fiyatlı dolgu barlarıyla 54 satıra tamamlanır.
- `notional=10_000.0` (motor sermayesi) ile çağrı; varsayılan 100.000
  kullanılırsa pay sayısı 999 olur ve parite bozulur — testte sabitlenmiştir.
- Motor `BacktestTrade` modelinde `shares` alanı olmadığından pay sayısı
  yalnızca kontrat tarafında doğrulanır; exit_reason eşitliği motorda
  farklı string sabitleri ("STOP_LOSS" vb.) kullandığından Faz 1'de
  doğrulanmaz (Faz 3 konusu).

## 2. Parite Sonucu

Aynı giriş/çıkış referansları, aynı seans verisi ve aynı ücret
parametreleriyle motor ile kontratın ürettiği sonuçlar birebir örtüşüyor:

| Büyüklük | Motor (2 ondalık) | Kontrat (tam hassasiyet) |
|---|---|---|
| Giriş fill | 100.05 | 100.05 |
| Çıkış fill | 102.9485 | 102.9485 |
| Pay sayısı | — (modelde yok) | 99 |
| Brüt kâr | 297.00 | 297.0000 |
| Net kâr | 277.81 | 277.807434679 |
| Spread maliyeti | 6.03 | 6.0291 |
| Slippage | 4.02 | 4.0194 |
| Komisyon | 8.04 | 8.0387406 |
| Borsa ücreti | 1.11 | 1.1053268325 |

Toleranslar: fill fiyatları `abs=1e-4`, maliyet kalemleri `abs=1e-6`.
Kalan farklar yalnızca motorun ekrana iki ondalıkla yazmasından
kaynaklanıyor; içsel hesap artık kontratla aynı.

## 3. Doğrulama

- `pytest tests/test_trade_contract_parity.py -q` → **17 passed**
  (16 altın + 1 motor paritesi).
- `pytest tests/test_backtest_costs.py tests/test_backtest_vectorized.py
  tests/test_backtest_engine_integration.py tests/test_trading_costs.py -q`
  → **21 passed**.
- Tam test paketi → **1336 passed, 2 skipped** (psycopg2 kurulu değil,
  ortam kaynaklı skip).
- `ruff check src tests` → **All checks passed!**
  (İki düzeltme uygulandı: `collections.abc.Sequence` importu,
  `zip(..., strict=True)`.)
- `mypy src/bist_bot --ignore-missing-imports` → **2 hata**, ikisi de
  `src/bist_bot/backtest/signal_replay.py:733,736`
  (`comparison-overlap`) — bu oturumda dokunulmayan, önceden var olan
  hatalar. Bu oturumun dosyaları mypy-strict temiz.
- Baseline dosyaları `results/baseline_legacy_430.csv` ve
  `results/baseline_legacy_508.csv` değiştirilmedi.
- Kapsam: yalnızca `backtest/engine.py` (M), `risk/costs.py` (M),
  `trade_contract.py` (yeni), `tests/test_trade_contract_parity.py` (yeni).

## 4. Kalan İşler ve Risk

- **Önceden var olan mypy hataları** (`signal_replay.py:733,736`) bu
  fazın kapsamı dışında bırakıldı; CI'da kırmızı üretmeye devam edebilir.
  Ayrı bir görev olarak ele alınmalı. Risk: düşük.
- **BSMV adapter uyumsuzluğu**: motor satış-tarafı notional bazlı BSMV
  modeliyle kontratın komisyon-tabanlı mantığı farklı. Paritede her iki
  taraf da sıfırlandı; birleştirme ayrı tasarım kararı gerektiriyor.
  Risk: orta (maliyet hesaplarında tek kaynak yok).
- **`_fee_components` ölü anahtarları** (`"spread"`, `"total"`): motor
  düzeltmesinden sonra okunmuyor. Zararsız; temizlik isteğe bağlı.
- Motorun `BacktestTrade` modeline `shares` alanı ekleyip eklememek
  Faz 3 parite sorunuyla birlikte değerlendirilecek.

## 5. Sonuç

Faz 1 hedefine ulaşıldı: kanonik kontrat altın testlerle sabitlendi, motor
spread/slippage ayrıştırmasını kontrattaki gibi yapıyor ve rastgele
senaryolardan bağımsız, belirli bir parite setiyle doğrulandı. Sonraki faz
için giriş noktası: Faz 2 (maliyet modeli yeniden kalibrasyonu / senaryo
analizi) veya doğrudan Faz 3 (adapter ve exit_reason birleştirmesi).