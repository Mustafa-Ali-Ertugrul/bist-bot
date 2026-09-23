# Stop-Disiplini Izgarası (v2 adım 4 devamı)

Tarih: 2026-09-17 · Evren: BIST100 (86 ticker) · 2y · train 63/test 21/
purge 10/embargo 5/warmup 60/exit-ext 28 · maliyet realistic ·
champion bandı 28-33 + pv-gate. Motor: `Backtester(max_hold_bars)` yeni
(TIME_STOP, vectorized+iterative, 5 test yeşil, regresyon yok).

Kaynak: `results/recalibrate_u_*.json` · Script:
`scripts/recalibrate_champion.py --stop-cap-{atr,pct} --time-stop-bars`

## Sonuç (havuzlanmış OOS)

| Konfigürasyon | n | WR [%95 CI] | ort. net | kazanan | kaybeden | PF |
|---|---|---|---|---|---|---|
| RR 0.5 (canlı) | 188 | %71 [64–77] | −0.85pp | +2.31 | −8.70 | 0.66 |
| RR 1.0 | 176 | %62 [55–69] | **+0.14pp** | +6.16 | −9.91 | **1.04** |
| RR 1.5 | 164 | %51 [44–59] | **+0.21pp** | +9.78 | −9.84 | **1.04** |
| RR 1.0 + stop-cap %4 | 152 | %55 | −1.14pp | +2.20 | −5.15 | 0.51 |
| RR 1.0 + stop-cap 1.5ATR | 148 | %57 | −0.77pp | +4.64 | −7.88 | 0.77 |
| RR 2.0 + stop-cap %4 | 149 | %38 | −1.17pp | +6.05 | −5.52 | 0.66 |
| RR 2.0 + stop-cap 1.5ATR | 139 | %40 | −0.47pp | +10.79 | −8.06 | 0.90 |
| RR 1.0 + time-stop 10 | 182 | %57 | −0.28pp | +5.75 | −8.13 | 0.92 |
| RR 1.0 + giriş filtresi stop≤%8 | 93 | %48 | −2.03pp | +5.08 | −8.69 | 0.55 |
| Ayrık hedef 1.5ATR (stop 2ATR) | 183 | %66 | −0.37pp | +4.34 | −9.35 | 0.89 |
| Ayrık 1.5ATR + stop-cap %4 | 150 | %47 | −0.88pp | +4.33 | −5.43 | 0.70 |
| RR 1.0 + canlı stop-paritesi | 153 | %50 [42–58] | −1.15pp | +2.02 | −4.28 | 0.47 |
| RR 1.0 + makro kapı (enforce) | 132 | %61 [53–69] | −0.03pp | +5.83 | −9.33 | 0.99 |
| RR 1.0 + trailing 3.0 (Deney M paritesi) | 176 | %61 [54–69] | −0.03pp | +6.10 | −9.77 | 0.99 |
| RR 1.0 + trailing 2.0 | 152 | %48 | −0.97pp | +5.89 | −7.32 | 0.74 |
| Hedefsiz + trailing 2.0 | 143 | %31 | −0.77pp | +11.89 | −6.40 | 0.83 |
| Hedefsiz + trailing 3.0 | 123 | %33 | **+0.39pp** | +17.48 | −8.16 | **1.07** |
| Hedefsiz + trailing 3.5 | 118 | %31 | −0.32pp | +18.32 | −8.50 | 0.95 |
| Hedefsiz + trailing 4.0 | 114 | %33 | +0.37pp | +19.37 | −8.77 | 1.06 |

Not: "Hedefsiz" = `--target-rr 1000` proxy'si (hedef fiilen erişilemez;
çıkışlar trail/sabit stop). n küçülüyor çünkü kazanan işlemler uzuyor ve
periyot içinde kapanamayanlar artıyor (FINAL_CLOSE).

## Neden stop-cap tek başına kaybettiriyor

Hedef stopa bağlı: `hedef = risk × RR`. Stop daralınca hedef de daralır
(cap4'te kazanan +6.16 → +2.20pp); gürültü stopu daha sık vurur (WR %62→%55).
Kayıp küçülür (−9.9→−5.1) ama sıklık artışı + hedef küçülmesi baskındır.
RR 2.0 büyüklüğü geri verir ama WR %38-40'a çöker (v2 %40 ruhuna aykırı).

## Zaman stopu

34 TIME_STOP çıkışı üretti ama net −0.28pp, PF 0.92 — baseline RR1.0'ın
altında. Kazananları da erken kesiyor; tek başına kol değil.

## Canlı stop-paritesi (Adım 1)

`risk/stops.py` aday seçim mantığı (`ATR/Destek/Fib/%/Swing` + %1–10
makullük + en yüksek makul stop + MIN_STOP tabanı) birebir taşınıp
`--parity-stop` ile RR 1.0 evren koşusu yapıldı
(`results/recalibrate_u_parity_rr10.json`, veri parmak izi 2026-09-17):

- WR %71→**%50**, kazanan +2.31→+2.02pp, kayıp −8.70→−4.28pp, PF **0.66→0.47**.
- Canlı seçim = en sıkı makul stop; `hedef = risk × RR` ile hedef de
  küçülüyor ve gürültü stopu daha sık vuruyor — **cap4 deneyiyle aynı tuzak**,
  daha keskin.
- Ölçüm dürüstleşti ama yön ters: bugüne kadarki replay sayıları
  (ham 2ATR stop) canlıya göre **iyimsermiş**; canlı stop mantığı PF'yi
  daha da düşürüyor. Stopu daraltan her yapı, hedef-risk bağı kopmadan
  kaybeder (ayrık-ATR deneyi de aynı tavanı göstermişti: PF 0.89).
- Sonuç: çıkış tarafı sabit-stop+RR geometrisiyle tavana vurdu. Sıradaki
  yapısal bahis trailing-stop (Adım 4) öncesi ucuz filtreler: makro kapısı
  (Adım 2), gap koruması (Adım 3).

## Makro kapısı (Adım 2)

`--macro-mode enforce` bu harness'a bağlandı (Deney D ile aynı
`build_macro_regime_series` + motor kapısı; indeks normalizasyonu yalnızca
macro modu açıkken uygulanır, diğer koşular bit-identical).
`results/recalibrate_u_macro.json`, veri parmak izi 2026-09-17:

- n 176→**132** (44 giriş BEAR günlerde engellendi), WR %62.5→%61.4,
  ort. net +0.14→**−0.03pp**, PF **1.04→0.99**.
- Engellenen 44 işlemin toplam katkısı ≈ **+28pp** (+0.63pp/işlem):
  kapı net kârlı işlemleri kesti — Deney D'nin RED hükmüyle birebir tutarlı
  (orada da engellenen sinyaller net +5.8k TL idi).
- Hüküm: **makro kapısı bu ailede kol değil** — Deney D + bu koşu, iki
  bağımsız harness'ta aynı sonuç. Adım 2 kapandı.

## Trailing paritesi (Adım 4, ilk ölçü)

Motor `trailing_atr_mult` kazandı (Deney M kuralı birebir: `trail =
peak_close − mult·ATR_güncel`, yalnızca sıkılaşır, giriş barı muaf,
`TRAILING_STOP`/`TRAILING_GAP` sebepleri, aynı-bar çakışmada muhafazakâr
stop-önceliği; 6 yeni test + 16 regresyon yeşil).
`--trailing-mult 3.0` = canlı default'un birebir ölçümü
(`results/recalibrate_u_trail30.json`, parmak izi 2026-09-17):

- n 176→**176**, WR %62.5→%61.4, ort. net +0.14→**−0.03pp**, PF **1.04→0.99**.
- Yalnızca **9/176** çıkış trailing'den (8 TRAILING_STOP + 1 TRAILING_GAP):
  mult 3.0 hedef (+2ATR) korunurken neredeyse hiç bağlanmıyor — trail'in
  bağlandığı dar bant (tepe +1ATR..+2ATR arası ters dönüş) küçük.
- Yorum: hedef dururken trailing kanamayı düzeltemez (tavan tezi doğrulandı);
  canlı default replay'den anlamlı farklı değil (±gürültü). Sıradaki
  ızgara: daha sıkı mult (2.0 = ilk stop mesafesi, saf ratchet; 1.5 =
  anında sıkılaşma) ve hedefsiz varyant.

## Trailing ızgarası tamamlama (Adım 4, ikinci ölçüm)

| Koşu | n | WR | ort. net | PF | trailing çıkış |
|---|---|---|---|---|---|
| hedefli trail 2.0 | 152 | %48 | −0.97pp | 0.74 | 55 |
| hedefsiz trail 2.0 | 143 | %31 | −0.77pp | 0.83 | 115 |
| hedefsiz trail 3.0 | 123 | %33 | **+0.39pp** | **1.07** | 66 |
| hedefsiz trail 3.5 | 118 | %31 | −0.32pp | 0.95 | 54 |
| hedefsiz trail 4.0 | 114 | %33 | +0.37pp | 1.06 | 34 |

- Hedefli trail 2.0: trail bağlanınca kazananları erken kesiyor (WR %48).
  Kural: hedef durursa trail'i sıkılaştırma.
- Hedefsiz aile netli: PF, trail mult'a göre **ters-U** (0.83 → 1.07 →
  0.95 → 1.06). Zirve 3.0–4.0; 2.0 hemen altı (ilk stop mesafesi) çok
  sıkı — neredeyse her ters hareket anında stop.
- En iyi konfigürasyon: **hedefsiz + trail 3.0 (PF 1.071, +0.39pp)** —
  aile rekoru (baseline 1.036). Ama profil tamamen farklı: WR %33,
  ort. kazanan +17.5pp, n 176→123. Trend-takip profili; canlı üretim
  sinyal diliyle (hedefli, WR odaklı) uyuşmaz.
- Sınırlama: `--target-rr 1000` hedefsiz proxy; gerçek hedefsiz mod
  (target=None yolu) motor tarafında birinci sınıf değil. n 123'te
  %95 CI geniş — 3.0 vs 4.0 ayrımı gürültü içinde (PF 1.071 vs 1.062).

## Hüküm

- En iyi OOS hâlâ **sade RR 1.0/1.5 (PF 1.04, ince +0.14/+0.21pp)** — hedefli
  ailede **PF>1.2 barına ulaşan yok.** Aile genel rekoru hedefsiz+trail3.0
  (PF 1.07) ama bu farklı strateji profili (WR %33, uzun kazananlar), aynı
  ürün değil.
- Giriş filtresi (stop≤%8) en kötülerden: n 176→93, kayıp ortalaması
  −8.69pp sabit. Geniş-stop kurulumlar orantısız kaybeden değilmiş;
  filtre kazananları da buduyor. (22 işlemde pencere/full-history ATR
  farkı ≤1pp — ölçüm gürültüsü, filtre mekaniği sağlam.)
- Ayrık ATR hedef mekanik olarak çalışıyor (motor `target_atr_mult`,
  8 test yeşil) ama yeni bir cephe açmıyor: 1.5ATR ≈ RR 0.75'e denk,
  eğrinin üzerine çıkamıyor. Cap+ayrık kombinasyonu da zayıf (PF 0.70).
- Aile-içi cephe kapandı: bant+pv-gate+ATR-stop ailesinde kabul gören
  parametre yok. Sıradaki iş parametre değil, yapı (giriş mantığı, gap
  koruması, rejim filtresi) veya canlı-parite/shadow ölçümü.
- Sınırlama: teşhis `Backtester` stop construction kullanır; canlı
  `determine_final_levels` (destek/fib stop adayları, MIN_STOP tabanı,
  tutarlılık kapıları) paritesi ölçülmedi — replay canlıdan sistematik
  sapabilir (iki yönde de).
