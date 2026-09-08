# BIST Botu — Kapsamlı Teşhis Raporu

**Tarih:** 2026-08-27
**Kapsam:** 3 yıllık sinyal-işlem kanıtı (2023-09 → 2026-08, 30 BIST30 hissesi), strateji kodu okuması, canlı/paper kanıt tabanı.
**Amaç:** Botun TÜM eksikliklerinin, kanıta ve kod konumlarına bağlanmış olarak listelenmesi. Hiçbir ayar değiştirilmeden önce okunması gereken temel belge.

---

## 0. Yöntem Özeti (sayılar nereden geliyor)

- `scripts/evaluate_july_2026_predictions.py` — genişletilmiş pencere yetenekli değerlendirici; sinyal üretimi canlı ile **aynı** `calculate_score_and_reasons` yolunu kullanan `Backtester._precalculate_signals` üzerinden yapılır (`backtest/engine.py:117-224`).
- Konvansiyonlar: yalnızca **BUY ailesi** sinyalleri değerlendirilir; başarı = `net_pnl > 0`; maksimum 5 işlem günü tutma (giriş barı dahil); 100.000 TL kavramsal/sinyal; RR=2.0; stop = giriş − 2×ATR14 (`indicators.py:472-482`); maliyet = CostModel yarım-spread konvansiyonu, evaluator'da tek yönlü uygulanır (`evaluate_*.py:162-169`).
- **conservative** (canlı profil): n=508 sinyal. **research_v1** (normalize skorlama): n=430 sinyal.
- Canlı kanıt tabanı: 7/21 (%33.3) gerçek, 5/23 (%21.7) gölge, 98/268 (%36.6) günlük backfill.

---

## 1. Genel Tablo: 3 Yıllık Sonuç

| Metrik | conservative (canlı profili) | research_v1 |
|---|---|---|
| İşlem sayısı | 508 | 430 |
| Net kazanma oranı | %47.4 (241/508) | — |
| Ortalama net getiri | **−%0.175** | **+%0.013** |
| Brüt ortalama getiri | +%0.314 | — |
| Maliyet sürüklemesi / işlem | −%0.489 | — |
| Toplam TL | **−88.784 TL** | +5.595 TL |
| t (basit, yanıltıcı derecede iyimser) | −0.61 | +0.04 |

**Verdict:** Bot "bozuk" değil, ama **istatistiksel olarak sıfır kenarlı** — brüt kenar (+%0.31) maliyetlerin (%0.49) altında. 2026 yılı tek başına pozitif (conservative n=108, +%0.62; research_v1 n=99, +%1.12); 2023–2025 toplamı negatif. İyileşme, ayarlarla değil, tablodaki yapısal bulgularla giderilir.

---

## 2. Teşhis Listesi (önem sırasına göre)

### 🔴 P0-A — Canlı motorda spread çift sayımı (maliyet modeli canlıda daha kötü)

- **Bulgu:** `CostModel.spread_bps` yarım-spread olarak tanımlı ve her kademede bir kez uygulanmalı. Evaluator bunu doğru yapar (`evaluate_*.py:162-165`), ama canlı işlem motoru spread'i iki kez sayar. Sonuç: canlı gerçek maliyet > backtest modeli maliyet.
- **Etki:** %0.489'luk model maliyeti bile kenarı siliyor; canlıda daha da ağır. Modellenen hiçbir sonuç canlının en iyi durumu değil.
- **Düzeltme:** Motor kademesinde spread uygulamasının tekilleştirilmesi (hardening programında zaten onaylanmış P0 kalemi). **Durum: kullanıcı onayı bekliyor.**

---

### 🔴 P0-B — Makro rejim kapısı canlıda VAR, backtest'te YOK → kapı hiç değerlendirilmedi

- **Bulgu:** `StrategyEngine.scan_all` BEAR makro rejiminde alım sinyallerini RADAR'a indirir (`strategy/engine.py:674-736`, `MACRO_REGIME_GATE_ENABLED` varsayılan açık; benchmark: THYAO+GARAN+AKBNK). Ancak `Backtester._precalculate_signals` bu kapıyı **içermez** — yalnızca skor üretimini ve momentum kontrolünü yansıtır (`backtest/engine.py:117-174`).
- **Sonuç (iki yönlü ölçüm hatası):**
  1. Bu rapordaki 508 işlemlik sonuç, ayı aylarındaki sinyal selini **olduğu gibi içerir** — canlı bunların bir kısmını demote ederdi. Yani test, canlıdan daha kötüyü ölçmüş olabilir.
  2. Kapının kendisi **hiç backtest edilmemiş, doğrulanmamış**: doğru sinyali mi kesiyor, yoksa 2023-10 gibi ayları gerçekten kurtarıyor mu bilmiyoruz.
- **Kanıt (kapı olsaydı ne değişirdi):** 2023-10: 43 sinyal, WR %16.3, ortalama −%3.95 (yaklaşık −170k TL). Sermaye kıyasları o ay derin BEAR'daydı; kapı bu selin büyük kısmını engellemiş olabilirdi.
- **Düzeltme:** Değerlendiriciye makro rejim kolonu/isteğe bağlı gate ekleyip "gate açık/kapalı" A/B raporu çıkarmak. En yüksek bilgi değerli test.

---

### 🔴 P1-A — Sinyal felsefesi ile çıkış tasarımı uyumsuz (ana yapısal hata)

- **Bulgu:** Sinyal üretimi **aşırı satım / ortalamaya dönüş** bileşenlerine dayalıdır (aşağıda P1-B); çıkış tasarımı ise **trend takibi**: 2×ATR14 stop, RR=2 hedef (giriş + 2×risk ≈ +%10-15 yukarı), 5 gün maksimum tutuş.
- **Kanıt — çıkış dağılımı (508 işlem):**

| Çıkış nedeni | n | WR | Ortalama net | Toplam TL |
|---|---|---|---|---|
| MAX_HOLD (5 gün doldu) | 396 | %54.8 | **+%0.823** | +325.186 |
| TAKE_PROFIT + TARGET_GAP | 24 | %100 | +%13.1 | +319.330 |
| STOP_LOSS | 72 | %0 | −%7.63 | −548.640 |
| STOP_GAP | 14 | %0 | −%12.19 | −170.323 |
| SIGNAL_OPEN | 2 | %0 | −%7.17 | −14.337 |

- İşlemlerin **%83'ü (421/508) zaman aşımıyla** kapanıyor; hedefi vuran işlem **24/508 (%4.7)**. Strateji aslında "5 günlük drift" oynuyor; stop/TP seviyeleri neredeyse hiç kullanılmıyor.
- Tasarımdaki 2:1 RR bedava kazanç varsayımı gerçekleşmemiş: **gerçekleşen ödül/risk oranı 1.03** (ort. kazanç +%5.16 / ort. kayıp −%4.99).
- **Düzeltme yönleri (her biri ölçülecek):** (a) RR'yi 2.0 → 1.0-1.2'ye çekip TP sıklığını artırmak; (b) maksimum tutuşu artırma testi (benimseyen yol zaten kârlı); (c) trailing stop kurulumu (`TRAILING_STOP_ENABLED` şu an False — `config/subsettings.py:443`). Değişiklikten önce A/B koşusu şart.

---

### 🔴 P1-B — "AL" sinyali aslında düşen bıçak yakalama bayrağı (tasarım gereği)

- **Bulgu:** conservative kombinasyonu ham bileşen **toplamıdır** (`scoring.py:393-395`, legacy = `sum(components)`). Teorik tavan 191 puan (momentum 45 + trend 70 + hacim 26 + yapı 50) iken `buy_threshold = 25`. Tek başına aşırı satım kümesi: **RSI-extreme +12.6 + Bollinger-alt +10 + CCI-extreme +8 = 30.6 puan ≥ 25 eşiği**, üstelik momentum-gate bypass sınırı olan 30'un da üzerinde (`engine_filters.py:278-279`: `abs(score) < buy_threshold + sideways_extra_threshold = 30` şartı sağlanmadığı için momentum onayı hiç istenmez).
- **Sonuç:** Trend, momentum, hacim onayı **olmadan**, salt fiyat düşmüşlüğü sinyal üretiyor. Düşüş piyasasında bu tam olarak yanlış davranış: sinyal sayısı **patlar** (2023-10: 43 sinyal/ay — normal ayların 2-3 katı), kalite çöker.
- **Güçlendirici:** `counter_trend_multiplier = 0.0` → momentum ile trend tersleştiğinde momentum puanı tamamen silinir; yani momentum puanının hiçbir zaman söz hakkı yok. Trend bileşeninin masaya girmesi pratikte zor.
- **Düzeltme:** aşırı satım bileşenlerine trend-onay şartı bağlamak (ör. regresyon eğimi > 0 veya fiyat SMA üzerinde olmadan BB/CCI puanları yarım/geçersiz) veya `buy_threshold`'ı bileşen-tavanına göre yeniden ölçeklemek. Walkforward altyapısı zaten mevcut — kullanılmıyor.

---

### 🔴 P1-C — Skorun sıralama gücü yok (kalite metriği değil, yalnız eşik)

- **Kanıt — skor dilimi başına sonuç:**

| Skor dilimi | n | WR | Ortalama net |
|---|---|---|---|
| [25, 30) | 259 | %44.8 | −%0.120 |
| [30, 40) | 176 | %51.1 | −%0.026 |
| [40, 60) | 67 | %46.3 | **−%0.862** ← daha yüksek skor, daha kötü |
| [60+) | 6 | %66.7 | +%0.752 (örnek küçük) |

- Skor arttıkça başarı **monoton olarak artmıyor**. Skor, sinyal kalitesini ayırt edemiyor; sadece bir eşik aracı. En kalabalık dilim [25-30) en düşük WR'ye sahip.
- **Sonuç:** "Eşiği 25→30 yapalım" cazip görünür ama yalnız başına kurtarmaz (30-40 dilimi de ancak başabaş). Asıl iş kalite sinyalini baştan tanımlamak (P1-B'deki yapı).
- **Düzeltme:** Bileşen bazlı sinyal şeffaflığı CSV'ye bileşen dökümü eklemek (hangi sinyal hangi bileşenden gelmiş) — sonra regresyonla hangi bileşenin geleceği tahmin ettiğini ölçmek.

---

### 🔴 P1-D — Ayı aylarında sinyal seli ve korelasyon konsantrasyonu (portföy riski)

- **Kanıt — aylık görünüm (seçmeler, conservative):**

| Ay | n | WR | Ort. net |
|---|---|---|---|
| 2023-10 | 43 | %16.3 | −%3.95 |
| 2024-08/09 | 7 | %0 | ≈ −%5.7 |
| 2025-01 | 15 | %33.3 | −%1.89 |
| 2026-08 | 4 | %100 | +%7.78 |

- Kayıp ayları, **aynı anda en çok sinyal üreten** aylar. 30 hisse aynı günlerde BUY veriyor → pozisyonlar aynı yöne, aynı betaya bağlı; tek senaryo tüm portföyü vuruyor. Stop genişliği (%7.6 ortalama) bunu daha da ağırlaştırıyor.
- **Düzeltme:** (a) sinyal bütçesi/korelasyon tavanı (risk yöneticisinde sektör limitleri var; aylık/günlük bütçe yok); (b) P0-B makro kapısını modele dahil etme; (c) pozisyon senaryo testleri ekleme (günün %kaçı tek ay riskine maruz bırakılıyor).

---

### 🔴 P1-E — Stop genişliği + gap kuyruğu (beklenmeyen −%12'lik kayıplar)

- **Kanıt:** STOP_GAP 14 işlemde ortalama **−%12.19** (en kötüsü −%17.3, DSTKF 2025-09; EKGYO 2024-04, SASA 2023-12, MGROS 2025-03 benzeri). Normal STOP_LOSS bile −%7.63 — stop kurulumunun kendisi (2×ATR14) acıyı erteliyor.
- Gece boşluğu stopu aşınca sistem açılışta −12/−17% ile gerçekleşir; bunun için hiçbir koruma yok.
- **Düzeltme:** maks-hold/stoplama yeniden tasarımı (P1-A) + gap yoğun/olay günü filtreleri + işlem başına maruziyet tavanı (şu an 100k sabit).

---

### 🔴 P1-F — Hisse seçiciliği yok (bir "havuz filtresi" tabloyu çevirirdi)

- **Kanıt — en kötü 5 vs en iyi 5 (n≥8, conservative):**

| En kötü | n | WR | Toplam | En iyi | n | WR | Toplam |
|---|---|---|---|---|---|---|---|
| FROTO | 14 | %21.4 | −37k | ISCTR | 23 | %82.6 | +76k |
| EKGYO | 16 | %25.0 | −57k | TRALT | 18 | %66.7 | +26k |
| EREGL | 21 | %28.6 | −44k | TCELL | 8 | %62.5 | +9k |
| BIMAS | 20 | %30.0 | −48k | TUPRS | 17 | %58.8 | +43k |
| THYAO | 10 | %30.0 | −15k | ASELS | 24 | %58.3 | +46k |

Alt 5 hisse ≈ −200k TL / 81 işlem; üst 5 ≈ +200k TL / 90 işlem. Strateji her hisseye aynı parametreyle yaklaşıyor; hisse bazlı dinamik (volatilite rejimi değişimi, segment değişimi) hiç hesaba katılmıyor.
- **Not:** Bu tablo tek başına "alt 5'i havuzdan çıkar" tavsiyesi değildir (seçim yanlılığı riski vardır); A/B doğrulaması ile test edilmelidir.

---

### 🟠 P1-G — Chase (takipten uzaklaşmış fiyat) engeli profilde KAPALI (ölü parametreler)

- **Bulgu:** `chase_block_enabled` varsayılanı **False** (`strategy/params.py:38`); `conservative()` fabrikası `chase_blocked_score_cap=10.0`, `chase_strong_trend_cap=20.0` value'larını ayarlıyor ama **anahtarı açmıyor** (`params.py:130-131`, `engine_filters.py:64`'te `if not params.chase_block_enabled: return`).
- **Sonuç:** Fiyat zaten aşırı uzamışken alınan sinyaller engellenmiyor. (OBV divergence ve MTF confluence blokları ise profilde AÇIK.)
- **Düzeltme:** anahtarı açıp etkisini ayrı koşuyla ölçmek — hızlı, düşük riskli test.

---

### 🟡 P2-A — Maliyet kalibrasyonu eksik (ve model iki yere hassas)

- **Kanıt:** brüt kenar +%0.314, maliyet −%0.489 → net sıfır. Maliyet hesabının %0.15 kadarı kayma+spread etkisinden, kalanı komisyon/vergi oranlarından geliyor. Gerçek aracı kurum masraf tablosu ile henüz kalibre edilmedi (komisyon + BSMV + gerçek kayma ölçümü).
- **Yorum:** Kenar maliyetin altında olduğu sürece her "ayar iyileştirmesi" maliyet modeli netleşmeden anlamsız ölçülür.
- **Düzeltme:** Gerçek broker ücret tablosunu `CostModel`'a işleyip tüm testleri yeniden koşmak. **Kullanıcıdan beklenen veri: komisyon/BSMV çizelgesi.**

---

### 🟡 P2-B — research_v1 (normalize skorlama) kenar üretmiyor

- **Kanıt:** 430 işlem, ortalama net +%0.013, t=+0.04. Yalnızca 2026 pozitif (+%1.12, n=99); 2023-2025 negatif. Ağırlık-normalize kombinasyon (`scoring.py:397-429`) modelin kaderini değiştirmemiş — çünkü kök neden bileşen seçiminde (P1-B/C), ağırlıklandırmada değil.

---

### 🟡 P2-C — Canlı ile backtest arasında kalan üçüncü parite farkı: MTF kapıları

- **Bulgu:** Canlı motor 15dk/1sa/gün MTF çerçeveleriyle çalışır ve `mtf_confluence_block_enabled=True`'dır (`params.py:135`); günlük-only backtest bu bloğu tetikleyecek çoklu zaman dilimi bağlamını hiç görmez. OBV/bloklar da canlıda varken backtest'te tam olarak karşılıkları ölçülmüyor.
- **Sonuç:** Canlı/backtest eşitliği kurulmadan önce hiçbir backtest sonucu "canlının aynısı" sayılamaz — mevcut durumda bu rapor "model gerçeğinin alt sınırı"dır. **D1 kapsam kararı (canlı 15dk sinyallerini mi, günlük barları mı değerlendireceğiz) hâlâ açık.**

---

### 🟡 P3-A — Sonuç izleyici / kazanma oranı metrik bugları

- **Bulgu:** Haftalık raporun yansıttığı "kazanma oranı" metrikleri, hardening programında belgelenen outcome-tracker tutarsızlıklarından etkileniyor. Canlı %33.3 gerçek WR'nin, gölge %21.7'nin, backfill %36.6'nın aynı protokolle hesaplandığı garanti değil.
- **Etki:** Yönetim kararları yanlış WR ekranına bakarak veriliyor.
- **Düzeltme:** Hardening P0-A2 kapsamındaki metrik onarımı; onaylı listeye dahil.

---

### 🟡 P3-B — Promosyon kıstaslarına mesafe (strateji daha hiçbir kapıyı geçemedi)

- **Kanıt:** Kapılar: research ≥%70 WR / Wilson LB ≥%60; live ≥%70 / LB ≥%65. Mevcut durum: canlı %33.3, gölge %21.7, backfill %36.6 — hiçbir şey kapıya yakın bile değil. 3 yıllık tam örnekte de net kenar sıfır.
- **Yorum:** Bu, "biraz ayar çekelim" aşamasının geçildiğinin kanıtı; sıradaki adım yapısal onarım + yeniden ölçüm olmalı.

---

## 3. Doğru Yapılanlar (kayıt için — bunlara dokunulmamalı)

1. **No-lookahead:** skor/stop/hedef 1 bar kaydırmayla uygulanıyor; ilk 2 bar karantinada (`backtest/engine.py:202-210`). Değerlendirici bunu aynen kullanıyor.
2. **CostModel yarım-spread konvansiyonu** evaluator'da doğru uygulanıyor (`evaluate_*.py:162-165`).
3. **BIST tick yuvarlaması** uygulanıyor (stop SELL'e aşağı, hedef BUY'a yukarı — `backtest/engine.py:189-191`).
4. **Momentum onayı kapısı** varlığı (zayıf momentumda skoru reddeder) — bypass eşiği yüksek skora bağlı; mekanizma var, kalibrasyonu tartışmalı.
5. **Makro rejim altyapısı** canlıda mevcut ve çalışıyor (P0-B'deki sorun mekanizmanın kendisi değil, değerlendirilmemiş olması).
6. **Tek kaynak skor üretimi:** backtest ile canlı aynı `calculate_score_and_reasons` fonksiyonunu kullanıyor — skor seviyesinde parite tam.

---

## 4. Önerilen Müdahale Sırası

1. **Ölçüm onarımları (strateji değişmeden, güvenli):**
   - P0-A spread tekilleştirme (onaylı gündemde).
   - P0-B: evaluator'a makro-rejim kapısı ekle → gate A/B raporu (2023-10'un ne kadarı demote olurdu?).
   - P2-A: gerçek broker ücret tablosunu modele işle (kullanıcıdan veri bekleniyor).
   - P3-A: sonuç izleyici metrik düzeltmeleri.
2. **Hızlı, ölçülebilir, geri alınabilir deneyler (her biri ayrı koşu + rapor):**
   - P1-G: chase bloğunu aç (tek bayrak).
   - P1-B/C: aşırı satım bileşenlerine trend-onay şartı.
   - P1-A: RR 2.0→1.2 / max-hold 5→10 / trailing A/B.
   - P1-F: alt-5 hisse havuz filtresi simülasyonu (seçim yanlılığı etiketiyle).
3. **Yapısal kararlar (tüm kanıtlarla birlikte kullanıcıya):**
   - P1-D portföy sinyal bütçesi; D1 değerlendirme kapsamı; `backfill_trade_ledger.py --apply` (P0-C onayından sonra).

**Altın kural:** Her deney aynı 508 işlemlik pencere üzerinde, net-TL + WR + Wilson LB + aylık dağılım metrikleriyle raporlanır. Tek ay/tek ticker'a bakılarak hiçbir karar verilmez.

---

## 5. Açık Kararlar (durum)

| Konu | Durum | Sahip |
|---|---|---|
| P0-A spread + takipçi/WR düzeltmeleri | Onay bekliyor | Kullanıcı |
| D1 kapsamı (canlı 15dk mi, günlük mü) | Cevap bekliyor | Kullanıcı |
| Broker komisyon/BSMV çizelgesi (P2-A) | Veri bekleniyor | Kullanıcı |
| `backfill_trade_ledger.py --apply` | P0-C sonrası onay gerekli | Kullanıcı |
| Bu rapora dayalı yapı onayı | Bu rapor | Kullanıcı |

---

## 6. Kaynak Dosyalar

- `src/bist_bot/strategy/scoring.py` — bileşen skorları, kombine toplam (satır 364-429)
- `src/bist_bot/strategy/engine_filters.py` — momentum kapısı, chase/OBV filtreleri
- `src/bist_bot/strategy/params.py` — conservative/research_v1 profilleri
- `src/bist_bot/strategy/engine.py` — makro rejim kapısı (643-740), skor çağrısı
- `src/bist_bot/strategy/regime.py` — `detect_macro_regime`, `is_macro_bearish`
- `src/bist_bot/backtest/engine.py` — sinyal ön hesaplama (117-224), çıkış simülasyonu
- `src/bist_bot/indicators.py` — ATR14, stop_loss_atr (472-482)
- `scripts/evaluate_july_2026_predictions.py` — kanıt üretici
- `results/prediction_signals_data_start_to_data_end.csv` — 508 işlemlik kanıt tabanı

*Rapor, strateji değişikliği içermez; değişiklik planı kullanıcı onayından sonra hazırlanacaktır.*