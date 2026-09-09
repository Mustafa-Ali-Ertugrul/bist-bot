# Deney E — Faz 2/3/4 Raporu: Kapılar, Fill, Çıkış

**Tarih:** 2026-08-28 · **Script:** `scripts/diagnose_signal_edge.py --phase {2,3,4}` · **Parity çıpası her koşuda PASS (508/508)**

Önkoşul: Deney F (pv_confirmation_required) uygulanmış durumda; bu fazlar **baseline davranışı** (gate kapalı) üzerinde ölçüldü — yani bulgular "mevcut sistemin kapıları" hakkında.

## Faz 2 — Kapı ve eşik marjinal etkisi (`results/expE_faz2_gate_ab.csv`)

Her varyantta 30 hisse için sinyaller yeniden üretildi; kaldırılan/eklenen kümelerin 5g forward getirisi (baz ii) ölçüldü.

| Kapı varyantı | Kaldırılan küme | Eklenen küme | Hüküm |
|---|---|---|---|
| **sideways ×1.0** (çarpanı kaldır) | — | **n=497, +%0.89, up %56.3** | **S2 DOĞRULANDI:** sideways ×0.4, mevcut sinyallerden DAHA İYİ bir kümeyi boğuyor. Kapı tersine çalışıyor. |
| no_momentum_confirmation | — | n=6, +%1.42 [indicative] | Kapı fiilen etkisiz (neredeyse hiç sinyal elemiyor) |
| no_obv_divergence | — | n=91, −%0.10, up %48.4 | OBV cap hafif faydalı (engellediği küme negatif eğilimli) — korunmalı |
| ctm 0.0→1.0 | n=60, +%0.99, up %53.3 | n=61, +%0.42 | Karışık; ctm=0 iyi bir kümeyi de kesiyor |
| **chase_on** | **n=92, +%2.01, up %62.0** | — | **Chase kapısı açılırsa EN İYİ kümeyi keser.** Bu koşularda chase'in kapalı tutulması doğruydu (bb_above_upper +%2.3 bulgusuyla uyumlu) |
| agreement_on | — | — | Etkisiz |

**Eşik taraması** (baseline skorları üzerinde): 15→2563 sinyal +%0.27, 20→1094 +%0.45, 25→508 +%0.27, 30→249 +%0.29, 35→134 +%0.06, 40→73 −%0.00, 45→39 +%0.41. **Monotonluk yok → eşik bilgi taşımıyor** (Faz 1'deki "score kendi sinyallerini sıralayamıyor" bulgusuyla tutarlı).

## Faz 3 — Fill zamanlaması (`results/expE_faz3_fill_ab.csv`)

508 sinyal: **gece gap ort +%0.260**, **açılış-sonrası drift ort −%0.171**.

| Sinyal tipi | n | gap | day1 drift | Yorum |
|---|---|---|---|---|
| rsi<30 (aşırı satım) | 5 | +%0.91 | **−%1.68** | [indicative] oversold sinyaller gap'li açılıp sert geri veriyor |
| bb_above_upper (kırılım) | 52 | +%0.38 | **+%0.45** | momentum günü sonrası devam ediyor — kırılım sinyalleri sağlıklı |
| golden_cross | 91 | +%0.22 | −%0.26 | hafif geri verme |
| macd_bull | 134 | +%0.14 | +%0.01 | nötr |

Sonuç: ertesi-açılış maliyeti ≈ +%0.09 net (gap + drift) — küçük; **fill politikası birincil sorun değil**. Kırılım tipli sinyallerde açılış sonrası devam var; oversold tipli sinyallerde (n çok küçük) gap sonrası fade.

## Faz 4 — Çıkış yüzeyi (`results/expE_faz4_exit_surface.csv`)

508 giriş sabit; 21 politika; ilk ~2/3 (seçim) vs son ~1/3 (test) zaman bölmesi; aynı-bar stop-önce kuralı; net (maliyetli) getiri.

**Test diliminde en iyi 3:** `rr3_mh20` +%0.62 (hit %14), `rr2_mh5_fixed5stop` +%0.20, `rr2_mh20` +%0.14. Mevcut politika `rr2_mh5`: **−%0.22**.

Gözlemler:
1. **Uzun tutma her iki dilimde de daha iyi:** mh20 politikaları (rr2/rr3) seçim diliminde de (+1.1-1.2%) test diliminde de (+0.1-0.6%) mevcut mh5'i geçiyor. Yön tutarlı, büyüklük küçük.
2. mh3 tüm rr'larda felaket (−%0.6-0.7); trailing (k∈{1.5,2,3}) yardımcı olmuyor; MFE-capture her yerde negatif (maliyet hasadı yiyor).
3. Yüzeyin tamamı ±%0.7 içinde → giriş edge'i yokken çıkışla büyük kazanç yaratılamaz; **en iyi çıkış politikası bile sistemi ancak ~sıfıra taşıyor.**

## Faz 5 karar matrisi (güncel)

| Bulgu | Düzeltme | Durum |
|---|---|---|
| score_total sinyalleri sıralayamıyor; pv_bull=0 kovası | **Deney F kapısı uygulandı** (per-signal −88.8k → +162.9k TL) | ✅ tamam |
| **S2: sideways ×0.4 iyi kümeyi boğuyor** | `sideways_score_multiplier` 0.4→1.0 (veya kaldır) | ⏭ sonraki deney adayı |
| **Chase kapısı açıkken en iyi kümeyi kesiyor** | chase_block_enabled=False korunmalı (zaten kapalı koşuldu) | ✅ doğrulandı |
| S4: ertesi açılış maliyeti | ~+%0.09 net — küçük; fill değişikliği gerektirmez | ✅ kapatıldı |
| S5: çıkış geometrisi | mh5→mh20 adımı yön-tutarlı ama etki küçük; OOS doğrulamasıyla düşünülebilir | ⏭ sonraki deney adayı |
| ctm=0 | karışık; dokunma | ✅ kapatıldı |
| OBV divergence cap | korunmalı (engellediği küme negatif) | ✅ doğrulandı |

**Önerilen sonraki iki deney (öncelik sırasıyla):**
1. **Deney G:** `sideways_score_multiplier=1.0` — Faz 2'nin en güçlü bulgusu (+497 sinyal, +%0.89/up %56.3). Deney D/F disipliniyle opt-in flag + per-signal + WF A/B.
2. **Deney H:** `max_hold` uzatma (mh20 ailesi) — ancak Deney G sonrası, kombine etkiyle birlikte walk-forward OOS'ta.

Not: Hiçbir bulgu tek başına WR %60 üretmez; realistic hedef, pv-gate sonrası ~%52-55 bandını sideways düzeltmesiyle yukarı taşımak.
