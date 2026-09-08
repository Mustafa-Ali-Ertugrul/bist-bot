# Perakende Abone Ekonomisi — Neden Hedefe Uzağız?

**Tarih:** 2026-08-28 (güncelleme: Adım 1-4 deney sonuçları eklendi)
**Simülasyon:** `scripts/retail_economics.py` — gerçek bot kuralları: 100k TL sermaye, pozisyon başına 20k TL (`MAX_POSITION_SIZE=0.20`), max 5 açık pozisyon (`MAX_OPEN_POSITIONS`), dolu kitapta sinyal atlama. Girdi: `evaluate_july_2026_predictions.py` çıktı CSV'leri (Eyl 2023 – Ağu 2026, ~36 ay).

## 0. Özet tablo — tüm konfigürasyonlar (100k TL sermaye)

| Konfigürasyon | Sinyal/ay | WR | Net/trade | Aylık ort. | Pozitif ay | En kötü ay | Max DD |
|---|---|---|---|---|---|---|---|
| BIST30, pv-gate, mh5 (bugünkü bot) | 9.9 | %53.0 | +%0.41 | **+715 TL** | %53 | −12,833 | −17,505 |
| … + komisyon %0.08 | 9.9 | — | +%0.288 | +505 TL | %50 | −13,225 | −18,829 |
| … + komisyon %0.20 (banka) | 9.9 | — | **+%0.048** | **+84 TL** | %50 | −14,010 | −25,250 |
| … + slippage/spread stresi | 9.9 | — | +%0.228 | +399 TL | %50 | −13,421 | −19,887 |
| BIST30, pv-gate, **mh20** (Deney H) | 9.9 | %49.7 | **+%1.666** | **+1,823 TL** | %53 | **−8,634** | −24,530 |
| BIST30, pv-gate + sideways×1.0 (Deney G) | 20.5 | %47.9 | −%0.012 | **−36 TL** | %47 | −11,057 | −42,524 |
| BIST30, pv-gate + G + H | 20.5 | %42.8 | +%0.760 | +1,144 TL | %44 | −10,889 | −37,100 |
| BIST30 + H + makro-rejim enforce | 8.6 | %48.6 | +%1.380 | +1,403 TL | %44 | −14,253 | −19,571 |
| BIST100, pv-gate, mh5 | 38.5 | %48.1 | +%0.009 | +39 TL | %47 | −15,988 | −56,636 |
| BIST100, pv-gate + mh20 | 38.5 | %45.6 | +%0.904 | +1,663 TL | %50 | −29,306 | −45,440 |

İstatistiksel anlamlılık (tek örneklem t-testi, net getiri > 0):
- BIST30, pv-gate, mh5: t=1.15, p=0.25 → **anlamlı değil**
- BIST30, pv-gate, mh20: n=353, t=3.37, **p=8.5e-4 → anlamlı** ✓
- BIST100, pv-gate, mh20: n=1363, t=1.57, p=0.117 → anlamlı değil (geniş evren edge'i sulandırıyor)

## 1. Adım 1 — Maliyet kırılganlığı (kritik bulgu)

Komisyon senaryoları (taraf başına): base %0.02 / orta %0.08 / banka %0.20 / stres (%0.08 + slippage 10bps + spread 8bps).

| Senaryo | Net/trade | Aylık ort. | 500 TL abonelikte |
|---|---|---|---|
| base (%0.02) | +%0.409 | +715 TL | +215 TL kalır |
| orta (%0.08) | +%0.288 | +505 TL | +5 TL kalır |
| **banka (%0.20)** | **+%0.048** | **+84 TL** | **edge yok** |
| stres | +%0.228 | +399 TL | −101 TL |

**Sonuç:** Stratejinin edge'i komisyona aşırı duyarlı — %0.20 komisyonda (geleneksel banka aracı kurumu) edge istatistiksel olarak yok. Ürün ancak **düşük komisyonlu aracı kurum şartıyla** satılabilir; abonelik sözleşmesi/broker önerisi ürünün parçası olmalı. %0.5 gidiş-dönüş maliyet varsayımı iyimser değil, gerçekçi-kötümser aralıkta; asıl kırılma komisyon kademesinde.

## 2. Adım 2 — Deney G ve H (etkileşim testi)

- **Deney H (mh20) net kazanan:** trade başına net +%0.41 → +%1.67, aylık +715 → **+1,823 TL**, en kötü ay −12.8k → **−8.6k**, edge istatistiksel anlamlı hale geliyor (p=8.5e-4). Bedeli: DD −17.5k → −24.5k (pozisyonlar daha uzun açık kalıyor) ve 5-slot kitapta atlanan sinyal 40 → 156.
- **Deney G (sideways×1.0) RED:** Faz 2'de sinyal başına iyi görünen +497 ek sinyal, portföy kısıtı (5 slot) altında kapasiteyi kötü sinyallerle dolduruyor: G-only −36 TL/ay, H ile kombinasyonu H tek başına'dan kötü (+1,144 < +1,823). **Per-sinyal bulgu portföy seviyesine taşınmıyor** — ders: kapı değerlendirmeleri portföy simülasyonuyla doğrulanmalı.

## 3. Adım 3 — BIST100 evren genişlemesi

- Sinyal hacmi 9.9 → 38.5/ay (4×) ama alınan işlem 197 → 331; **1,032 sinyal dolu kitap nedeniyle atlandı**. Darboğaz sinyal sayısı değil, 5 pozisyon slotu.
- BIST100 mh5: edge tamamen yok (+%0.009/trade) — BIST30 dışı hisselerde mh5 edge'i yok.
- BIST100 mh20: +1,663 TL/ay (BIST30'a yakın) ama tail çok kötü: 2023-10 **−29.3k**, DD **−45k** (%45). Geniş evrenin eklediği hisseler kriz ayında çok daha kötü.
- PnL konsantrasyonu: 96 hissenin 3'ü PnL'nin %50'si.

**Sonuç:** Evren genişlemesi tek başına kazanç değil; önce **sinyal sıralama/seçimi** (hangi 5 sinyal alınacak — şu an FIFO) ve tail kontrolü gerekli. Sıralama kaldıracı (Deney I adayı: skor/olasılıkla seçim) artık en değerli araştırma kalemi.

## 4. Adım 4 — Rejim filtresi (abone deneyimi)

`--macro-regime-mode enforce` + pv-gate + mh20 (BIST30):
- Aylık ort. +1,823 → +1,403 TL (düştü), en kötü ay −8.6k → **−14.3k (kötüleşti!)**, pozitif ay %53 → %44.
- Makro kapı 2023-10'u korumuyor; Deney D'nin reddi bir kez daha doğrulandı. **Rejim kapısı churn sorununu çözmüyor** — tail risk başka yoldan (pozisyon boyutu, slot sayısı, stop disiplini) yönetilmeli.

## 5. Güncel bar durumu (en iyi konfigürasyon: BIST30 + pv-gate + mh20)

| Şart | Hedef | Bugün (BIST30+pv+mh20) | Durum |
|---|---|---|---|
| Edge istatistiksel anlamlı | p < 0.05 | p = 0.0008 | ✅ |
| Aylık net (100k sermaye) | ≥ +4,000 TL | +1,823 TL | ❌ 2.2× eksik |
| Pozitif ay oranı | ≥ %80 | %53 | ❌ |
| Max DD | ≤ %10 | %24.5 | ❌ |
| En kötü ay | ≥ −%5 sermaye | −%8.6 | ❌ |
| Maliyet dayanıklılığı | orta tarifede edge | %0.08'de +505 TL/ay (zayıf), %0.20'de yok | ⚠️ düşük komisyon şart |

**Not:** mh20 artık üründe aktif (2026-08-28: `MAX_HOLDING_DAYS=28` takvim günü ≈ 20 iş günü, bot PID 27708 ile canlıda). Bu tablo aktivasyon öncesi per-sinyal değerlendirmesine dayanıyor; canlı paper sonuçları 4-6 hafta içinde bu tablonun gerçek zamanlı doğrulaması olacak.

## 6. Kök nedenler (güncel)

1. ~~Edge kanıtlanmamış~~ → **mh20 ile çözüldü (p=8.5e-4)**; mh20'yi varsayılan yapma kararı gerekli.
2. **Kapasite darboğazı:** 5 slot × 20k, mh20 ile ~15-20 gün dolu → ayda ~5-7 yeni işlem. Aylık TL'yi artırmanın tek yolu slot başına getiri değil, **doğru sinyali seçmek** (FIFO yerine sıralama) ve/veya slot sayısı/boyutu politikası.
3. **Maliyet kırılganlığı:** edge yalnızca düşük komisyonlu aracı kurumda var.
4. **Tail risk:** rejim kapısı çözmüyor; 2023-10 tipi ay hâlâ −8.6k (BIST30) / −29k (BIST100).
5. **Pozitif ay %53:** abone deneyimi için yetersiz; aylık agregatta edge hâlâ gürültüde boğuluyor.

## 7. mh hassasiyet taraması + yıl kırılımı (Deney H robustluk kanıtı)

Backtester'da zaman bazlı çıkış olmadığından (`_find_exit_index` yalnız stop/target/ters-sinyal/veri-sonu), WF OOS koşusu mh için anlamlı değil; onun yerine hassasiyet eğrisi + yıl kırılımı alındı (BIST30, pv-gate):

| mh (iş günü) | net/trade | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|---|
| 5 | +%0.41 | +715 TL | %53 | −12,833 | −17,505 |
| 10 | +%0.93 | +1,327 TL | %56 | −8,474 | −16,705 |
| 15 | +%0.89 | +1,082 TL | %44 | −9,921 | −27,816 |
| **20** | **+%1.67** | **+1,823 TL** | %53 | −8,634 | −24,530 |
| 25 | +%1.74 | +1,802 TL | **%58** | −9,387 | −17,391 |
| 30 | +%1.76 | +1,804 TL | %53 | −9,085 | −17,555 |

Eğri mh20'de şanslı bir nokta değil: mh≥20 platosu (~+1,800 TL/ay) ve mh25'te daha iyi DD/pozitif-ay dengesi. Kazanımın kaynağı tutarlı: RR≈2 hedeflerin dolması 5 iş gününden fazla zaman istiyor.

Yıl kırılımı (mh20, per-sinyal net): 2023 −%1.04 (WR %33) / 2024 **+%4.33** (%62) / 2025 −%0.17 (%41) / 2026 **+%3.65** (%59). Kazanım gerçek ama rejime bağlı; 2023-tipi yıl hâlâ negatif.

## 8. Deney I — sinyal sıralama (skorla seçim) sonucu

Kitap doluyken günün adaylarını FIFO yerine `score` ile seçme (`retail_economics.py --rank-by score`):

| Evren+konfig | seçim | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|---|
| BIST30+mh20 | fifo | +1,823 TL | %53 | −8,634 | −24,530 |
| BIST30+mh20 | score | +1,771 TL | %56 | −9,733 | −23,422 |
| BIST100+mh20 | fifo | +1,538 TL | %50 | −29,306 | −45,440 |
| BIST100+mh20 | score | +1,319 TL | %50 | **−18,546** | **−32,017** |

**Sonuç: zayıf kaldıraç.** BIST30'da nötr (−52 TL/ay), BIST100'de aylık düşer ama tail belirgin iyileşir. Skorun sıralama gücü sınırlı (Faz 2 IC bulgusuyla tutarlı: score_total IC +0.046, p=0.30). FIFO'da kalıyoruz; daha iyi bir sıralama sinyali (ör. pv_bull, likidite, kalibre olasılık) ileride ayrı deney olabilir.

## 9. Aktivasyon — mh20 ürüne alındı (2026-08-28)

- **Semantik fark düzeltildi:** canlı `position_manager` takvim günü sayıyor (`(now − entry_time).days`), evaluate script iş günü. 20 iş günü ≈ **28 takvim günü**. Önceki canlı varsayılan 5 takvim günü ≈ 3 iş günü idi — canlı bot değerlendirilen mh5 baseline'ından bile erken çıkıyordu.
- `subsettings.py`: `MAX_HOLDING_DAYS` varsayılan **5 → 28** (`.env` override etmiyor, doğrulandı). `position_manager.py` bayat yorumu güncellendi.
- Bot yeniden başlatıldı (PID 27708): ilk iki tarama temiz (fetched=99, actionable 1→2, stale_data_halt yok).
- Tam paket: **1425 passed** (yeni: retail_economics 3 test).

## 10. Deney J — slot/boyut politikası (2026-08-28, AKTİVE EDİLDİ)

5×20k yerine daha fazla slot × daha küçük pozisyon (`retail_economics.py --max-open/--position-tl`):

### BIST100 + mh20 (canlı evren)

| slot×boyut | seçim | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|---|
| 5×20k (eski) | fifo | +1,538 TL | %50 | −29,306 | −45,440 |
| 6×16.7k | fifo | +1,943 TL | %61 | −22,100 | −36,900 |
| 7×14.3k | fifo | +2,132 TL | **%67** | −16,194 | −36,608 |
| **8×12.5k** | **fifo** | **+2,350 TL** | %64 | −15,243 | −32,366 |
| 9×11.1k | fifo | +1,968 TL | %64 | −12,767 | −33,243 |
| 10×10k | fifo | +2,036 TL | %61 | −12,090 | −29,403 |
| 8×12.5k | score | +1,965 TL | %58 | −12,204 | −26,013 |
| 7×14.3k | score | +2,080 TL | %56 | −14,071 | **−26,178** |

### BIST30 + mh20 (karşılaştırma)

| slot×boyut | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|
| 5×20k | +1,823 TL | %53 | −8,634 | −24,530 |
| 8×12.5k | +1,507 TL | %53 | −9,018 | **−12,836** |
| 10×10k | +1,245 TL | %50 | −9,515 | −12,334 |

**Bulgular:**
1. **Canlı evren (BIST100) için 8×12.5k her metrikte 5×20k'ya üstün:** aylık +1,538→+2,350 TL, pozitif ay %50→%64, en kötü ay −29.3k→−15.2k, DD −45.4k→−32.4k. Kapasite darboğazı (1033 atlanan sinyal) kırılınca evren genişlemesi değer kazandı.
2. Çeşitlendirme DD'yi yarıya indiriyor (BIST30: −24.5k→−12.8k); gelir maliyeti sınırlı.
3. Skor sıralama hâlâ gelir pahasına tail iyileştiriyor; FIFO'da kalındı.

**Aktivasyon (2026-08-28):** `MAX_OPEN_POSITIONS` 5→8 ve `MAX_POSITION_SIZE` 0.20→0.125 (iki subsettings sınıfında, `.env` override yok). Bot PID 28212 ile canlıda. 1425 passed, ruff temiz.

## 11. Güncel bar durumu (BIST100 + pv-gate + mh20 + 8×12.5k)

| Şart | Hedef | Bugün | Durum |
|---|---|---|---|
| Edge istatistiksel anlamlı | p<0.05 | p=0.0008 (BIST30); p=0.117 (BIST100 per-sinyal) | ⚠️ kısmen |
| Aylık net (100k) | ≥+4,000 TL | **+2,350 TL** | ❌ 1.7× eksik (başlangıçta 5.6× idi) |
| Pozitif ay | ≥%80 | **%64** | ❌ yaklaşıyor (%53 idi) |
| Max DD | ≤%10 | %32 | ❌ |
| En kötü ay | ≥−%5 | −%15.2 | ❌ iyileşti (−%29 idi) |

**Kalan mesafe:** gelir ve pozitif-ay barları yaklaştı; DD/tail barı hâlâ uzak → sıradaki tek kanıtlı kaldıraç tail yönetimi (volatilite hedefli boyutlandırma, Deney K).

## 12. Deney K — volatilite/risk-parite boyutlandırma (2026-08-28)

Sim'e canlı botun risk-bazlı boyutlandırması eklendi (`--sizing risk`: pozisyon = risk_bütçesi / stop_mesafesi, cap'li; `risk/sizing.py:apply_position_budget`'ın aynası). BIST100 + mh20, 8 slot, cap 12.5k:

| sizing | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|
| fixed 12.5k | +2,350 TL | %64 | −15,243 | −32,366 |
| **risk 1,000 TL (sermayenin %1'i)** | +1,992 TL | **%69** | **−14,751** | **−24,386** |
| **risk 2,000 TL (%2 — canlının mevcut ayarı)** | **+2,401 TL** | %67 | −15,309 | −32,331 |
| risk 3,000 TL (%3) | +2,354 TL | %64 | −15,243 | −32,366 |

BIST30 + mh20'de risk 1,000: en kötü ay −9,018→−7,567, gelir −85 TL/ay maliyetle.

**Bulgular:**
1. **Canlı botun mevcut %2 risk bütçesi (`MAX_TOTAL_RISK_PCT=2.0`) optimum noktada** — gelir (+2,401) ve pozitif-ay (%67) açısından fixed 12.5k'yı da geçiyor. Sim'deki sabit-TL modeli yaklaşık temsildi; canlı konfigürasyon zaten doğru. **Canlı değişiklik gerekmedi.**
2. %1 risk bütçesi muhafazakâr alternatif: gelir −%17 ama DD −%25 ve pozitif ay **%69** (80% barına en yakın nokta). Abone deneyimini önceleyen bir profil seçilirse tek satır `.env` değişikliği yeter.
3. %3+ risk bütçesi hiçbir şey kazandırmıyor (cap her yerde bağlıyor).

## 13. Güncel bar durumu (BIST100 + pv-gate + mh20 + 8 slot + risk %2)

| Şart | Hedef | Bugün | Durum |
|---|---|---|---|
| Edge istatistiksel anlamlı | p<0.05 | p=0.0008 (BIST30); p=0.117 (BIST100 per-sinyal) | ⚠️ kısmen |
| Aylık net (100k) | ≥+4,000 TL | **+2,401 TL** (risk %2) | ❌ 1.7× eksik |
| Pozitif ay | ≥%80 | **%67** (%1 riskle %69) | ❌ yaklaşıyor |
| Max DD | ≤%10 | %32 (%1 riskle %24) | ❌ en büyük açık |
| En kötü ay | ≥−%5 | −%15 | ❌ |

**Kalan tek büyük açık: DD/tail.** Per-sinyal boyutlandırma (Deney K) DD'yi %45→%24-32 bandına indirdi; %10 barına ulaşmak için kalan araç **piyasa-seviyesi risk kısma** (index volatilitesi yüksekken tüm pozisyonları küçült / kitabı kapat) — per-sinyal değil portföy-seviyesi rejim yönetimi. Bu, sim'e endeks verisi eklemeyi gerektiren bir sonraki araştırma adımı.

## 14. Deney L — piyasa-seviyesi volatilite hedefleme (2026-08-28)

Sim'e `--market-scale-file` eklendi (date,scale → pozisyon çarpanı; scale=0 giriş bloke). XU100.IS cache'e çekildi (750 gün); 20 günlük rolling std (yıllıklandırılmış) volatilite serisinden 5 varyant üretildi (medyan vol %22.7, p75 %26.8). Taban: BIST100+mh20, 8 slot, risk 2,000:

| varyant | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|
| taban (ölçeksiz) | +2,401 TL | %67 | −15,309 | −32,331 |
| median50 (vol>medyan → ×0.5) | +1,774 TL | %67 | −11,810 | −19,519 |
| **p75_50 (vol>p75 → ×0.5)** | **+2,126 TL** | %64 | −14,425 | **−22,059** |
| p75_25 (vol>p75 → ×0.25) | +1,989 TL | %64 | −13,983 | −22,684 |
| p75_0 (vol>p75 → giriş bloke) | +1,493 TL | %61 | −15,002 | −23,039 |
| cont (sürekli ters-vol, clip 0.25-1) | +2,211 TL | %64 | −14,277 | −24,595 |

**Bulgular:**
1. **p75_50 en iyi denge:** gelir −%11 karşılığı DD −%32. Giriş bloklama (p75_0) gelir kaybını hak etmiyor; sürekli ölçek (cont) p75_50'nin her iki tarafında da geride.
2. Kombinasyon cephesi (risk bütçesi × market ölçeği): risk1000+median50 → aylık +1,417, **en kötü ay −9,124 (−%9.1 — ilk kez −%10 altı)**, DD −16,292.
3. Canlı aktive etmek için `risk_manager`'a endeks-vol girdisi gerekecek (src değişikliği) — henüz yapılmadı.

## 15. Deney N — hedef R/R sweep (mh20, BIST100)

`--target-rr 1.5/2.5/3` (2 = mevcut). 8 slot, risk 2,000:

| rr | WR | net/işlem | aylık | pozitif ay | DD |
|---|---|---|---|---|---|
| 1.5 | %48.7 | +%0.176 | +388 TL | %61 | −56,961 |
| **2 (mevcut)** | %47.7 | **+%1.363** | **+2,401 TL** | **%67** | −32,331 |
| 2.5 | %43.3 | +%0.966 | +1,545 TL | %58 | −40,402 |
| 3 | %44.1 | +%0.933 | +1,393 TL | %56 | −30,776 |

**Bulgu:** RR=2 net optimum; rr1.5'te maliyetler işlem ekonomisini yutuyor (+388 TL/ay, DD −57k). `FALLBACK_TARGET_RR=2.0` doğrulandı, değişiklik yok.

## 16. Deney O — stop ATR çarpanı (mh20, BIST100)

Evaluate script'e `--stop-atr-mult` eklendi (enrichment sonrası `stop_loss_atr` override; indicators.py'deki sabit 2.0'ın deneysel aşımı). 8 slot, risk 2,000:

| stop×ATR | WR | aylık | pozitif ay | DD |
|---|---|---|---|---|
| 1.5 | %43.0 | +732 TL | %50 | −27,930 |
| **2 (mevcut)** | %47.7 | **+2,401 TL** | **%67** | −32,331 |
| 2.5 | %46.3 | +1,566 TL | %56 | −30,682 |
| 3 | %51.5 | +2,100 TL | %64 | **−23,451** |

**Bulgular:**
1. stop3.0: gelir −%12 karşılığı DD −%27 ve WR %51.5 — düşük-DD alternatif. Geniş stop risk-parite boyutlandırmayla otomatik küçülüyor (tutarlı).
2. stop3.0+p75_50: +1,939 / DD −19,893. stop3.0+risk1000+median50: **+976 / DD −10,813 (%10.8 — ilk kez DD barına değdi)**, en kötü ay −7,573 (−%7.6 ✓).
3. stop1.5 (dar stop) çöküyor: gürültü stop'ları WR %43'e düşürüyor.

## 17. Deney M — trailing stop, mh20 ile yeniden test (BIST100)

Evaluate script'e `--trailing-atr-mult` eklendi (peak close − k×ATR; önceki barın close/ATR'si ile güncelleme — look-ahead yok; `diagnose_signal_edge.simulate_exit` semantiğinin aynası). 8 slot, risk 2,000:

| çıkış kuralı | WR | aylık | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|---|
| sabit stop (mevcut) | %47.7 | +2,401 TL | %67 | −15,309 | −32,331 |
| trail 1.5×ATR | %35.6 | −12 TL | %53 | −19,167 | −39,307 |
| trail 2×ATR | %38.0 | +410 TL | %47 | −16,366 | −41,295 |
| **trail 3×ATR** | %45.5 | **+2,450 TL** | %64 | **−11,516** | **−22,818** |

**Bulgular:**
1. **trail3 sabit stop'a her boyutta baskın:** gelir +%2, DD −%29, en kötü ay −%25. mh5'te başarısız olan trailing, mh20'de (geniş nefes payı) işe yarıyor — kâr kilitleme artık stop-out'lardan önce tail'i kısaltıyor.
2. trail1.5/2 kârı erken boğuyor (WR %35-38): k×ATR < 3 runner'ları öldürüyor.
3. trail3 kombinasyonları: trail3+p75_50 → +2,089 / **DD −17,767**; trail3+median50 → +1,722 / DD −15,361; trail3+risk1000+median50 → **+1,386 / DD −14,859**.

## 18. Deney P — buy score eşiği (mh20, BIST100)

`--buy-threshold 15/25/30` (20 = mevcut). 8 slot, risk 2,000:

| eşik | WR | aylık | pozitif ay | DD |
|---|---|---|---|---|
| 15 | %45.2 | +1,372 TL | %61 | −42,734 |
| **20 (=25, mevcut)** | %47.7 | **+2,401 TL** | **%67** | −32,331 |
| 25 | bt20 ile birebir aynı | | | |
| 30 | %44.5 | +744 TL | %53 | −33,783 |

**Bulgular:** bt20-25 aralığında skor dağılımı boş (birebir aynı sonuç); eşik 15 sinyal seli (DD −42.7k), 30 kıtlık (+744). **bt=20 optimum, mevcut doğrulandı.**

## 19. Deney R — yeni şampiyonun yıl/rejim robustluğu

**trail3+p75_50** (yeni standart aday) yıl kırılımı (8 slot, risk 2,000, 508 işlem):

| yıl | işlem | pnl | WR |
|---|---|---|---|
| 2023 | 61 | −2,762 TL | %33 |
| 2024 | 159 | +14,012 TL | %47 |
| 2025 | 174 | +56,169 TL | %50 |
| 2026 | 114 | +7,803 TL | %43 |

Pozitif ay %64; en iyi ay +13,317; en kötü ay −12,499. Tek zayıf yıl 2023 (−2.8k, küçük); 2025 anormal güçlü — gelir tahmininde 2025'e yaslanmamalı (medyan yıl ~+2k/ay bandı).

## 20. Güncel deney cephesi (gelir ↔ DD)

| konfigürasyon | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|
| fixed 12.5k (Deney J şampiyonu, eski) | +2,350 TL | %64 | −15,243 | −32,366 |
| risk2000 (Deney K) | +2,401 TL | %67 | −15,309 | −32,331 |
| **trail3 (max gelir)** | **+2,450 TL** | %64 | −11,516 | −22,818 |
| **trail3+p75_50 (yeni standart aday)** | +2,089 TL | %64 | −12,499 | **−17,767** |
| trail3+median50 | +1,722 TL | %64 | −11,984 | −15,361 |
| trail3+risk1000+median50 (konservatif aday) | +1,386 TL | %64 | −9,366 | −14,859 |
| stop3+risk1000+median50 (sabit-stop konservatif) | +976 TL | %61 | −7,573 | −10,813 |

**Yorum:**
1. trail3 ailesi eski cepheyi her yerde daraltıyor: aynı gelirden DD −%29 (trail3 vs risk2000), aynı DD'den gelir +%42 (trail3+risk1000+median50 +1,386 vs stop3+risk1000+median50 +976 hariç — DD −%37 daha derin ama gelir −%32... stop3 konfigürasyonu DD-absolut minimumda kalmaya devam ediyor).
2. Ürün paketi adayları: **Standart = trail3+p75_50** (+2,089/ay, DD −%18), **Konservatif = trail3+risk1000+median50** (+1,386/ay, DD −%15) veya DD-absolut için **stop3+risk1000+median50** (+976/ay, DD −%11, en kötü ay −%7.6 ✓).
3. Canlıya trail3 + p75_50 taşımak `position_manager` (trailing) + `risk_manager` (endeks-vol ölçeği) src değişiklikleri gerektirir — sıradaki implementasyon kararı.

### Çapraz kombinasyon tamamlama (grid kapanışı)

Trail3 ile slot sayısı ve stop3 çaprazı test edildi (8 slot, risk 2,000 taban):

| konfigürasyon | aylık ort. | pozitif ay | en kötü ay | DD |
|---|---|---|---|---|
| trail3 8×12.5k (şampiyon) | +2,450 TL | %64 | −11,516 | −22,818 |
| trail3 6×16.6k | +1,700 TL | %61 | −18,460 | −34,413 |
| trail3 10×10k | +2,118 TL | %61 | −10,652 | −25,632 |
| stop3+trail3 | +1,957 TL | %58 | −17,938 | −30,173 |
| stop3+trail3+p75_50 | +1,560 TL | %58 | −14,983 | −29,783 |
| stop3+trail3+r1000+median50 | +948 TL | %53 | −8,911 | −15,646 |

**Bulgular:**
1. **8 slot trailing ile de optimum:** 6 slot konsantrasyon cezası (DD −34.4k), 10 slot iyileştirme yok.
2. **stop3×trail3 üst üste binmiyor** — ikisi aynı işi farklı yoldan yapıyor (geniş nefes + kâr kilidi); kombinasyon her metrikte baskılanıyor. İkisinden birini seç: sabit geniş stop (stop3) veya trailing (trail3); trail3 daha iyi.
3. Test edilen eksenlerin tamamı: mh (5-30), rr (1.5-3), stop ATR (1.5-3), trailing k (1.5-3), buy threshold (15-30), slot (5-10), risk bütçesi (%1-3), market ölçeği (5 varyant). Kazananlar: mh20-28, rr2, trail3, bt20, 8 slot, risk %2, p75_50/median50 ölçek.

## 21. Sonraki araştırma adayları

1. **Canlı aktivasyon kararı:** trail3 (trailing stop) + p75_50 (endeks-vol ölçeği) src implementasyonu — muhafazakâr/standart paket ayarı `.env` ile.
2. **Canlı paper doğrulaması:** 4-6 hafta paper sonuçları tabloyu gerçek zamanlı test edecek (bot şu an mh28+8slot+risk%2 sabit-stop ile çalışıyor).
3. **Ürün kararı:** düşük-komisyon broker şartı abonelik koşulu olarak yazılmalı (Deney 1: %0.20 komisyonda edge sıfır).




## Artefaktlar

- `scripts/retail_economics.py` (+ `tests/test_retail_economics.py`): `--rank-by`, `--sizing risk`, `--risk-budget-tl`, `--position-cap-tl`, `--market-scale-file`
- `scripts/evaluate_july_2026_predictions.py`: `--sideways-mult`, `--tickers-file`, `--target-rr`, `--stop-atr-mult`, `--trailing-atr-mult`, `--buy-threshold`
- `scripts/refresh_wf_cache.py`: `--tickers-file` desteği (XU100.IS dahil 101 sembol cache'te)
- `results/market_scale_{median50,p75_50,p75_25,p75_0,cont}.csv` — Deney L ölçek dosyaları
- `results/retail_N_rr{1.5,2.5,3}.csv`, `results/retail_O_stop{1.5,2.5,3}.csv`, `results/retail_M_trail{1.5,2,3}.csv`, `results/retail_P_bt{15,25,30}.csv`
- `results/retail_cost_{mid,bank,stress}.csv`, `results/retail_G_only.csv`, `retail_H_only.csv`, `retail_GH_combo.csv`, `retail_bist100_{base,H}.csv`, `retail_H_macro.csv`
- `results/bist100_tickers.csv`, `results/bist100_missing.csv`

---

*İlk sürüm (2026-08-28): BIST30 pv-gate mh5 analizi — aşağıda arşiv.*

## Arşiv: İlk analiz (BIST30, pv-gate, mh5)

| Metrik | Değer |
|---|---|
| Toplam net PnL (36 ay) | +25,754 TL |
| Aylık ortalama / medyan | +715 / +443 TL |
| Pozitif ay oranı | %53 (19/36) |
| En kötü ay | −12,833 TL (2023-10) |
| Realized equity max DD | −17,505 TL (%17.5) |
| Yıllık kırılım | 2023: −10,727 / 2024: +8,824 / 2025: +5,859 / 2026: +21,798 |
| t-testi | t=1.15, p=0.25 (anlamsız) |
| PnL konsantrasyonu | 30 hissenin 2'si (DSTKF, TUPRS) %50 |

Abonelik kırılması: 500 TL/ay'da +215 TL kalır; 1,000 TL'de abone zarar eder. Karşılaştırma: 100k TL %45 mevduat ≈ +3,750 TL/ay risksiz.
