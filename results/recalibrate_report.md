# Champion Rekalibrasyon Raporu (v2 adım 4 — pilot)

Tarih: 2026-09-17 · Pilot evren: 10 likit (THYAO ASELS GARAN AKBNK EREGL TUPRS
BIMAS KCHOL SAHOL ISCTR) · 2y günlük bar · train 63 / test 21 / step 21 /
purge 10 / embargo 5 / warmup 60 / exit-extension 28 · maliyet realistic
(15/20/30bps + vergi/harç) · hedef RR 0.5 · champion bandı 28-33 + pv-gate.

Kaynak: `results/recalibrate_diagnose.json`, `results/recalibrate_search.json`
Reprodüksiyon: `scripts/recalibrate_champion.py --mode {diagnose,search}`

## Teşhis (mevcut champion, OOS havuzlanmış)

n=17, **WR %94.1 [73–99], ort. net +0.957pp, PF 2.87.**
12 kazanan (+0.34…+2.47pp, çoğu aynı/gün-ertesi TP), 1 gerçek kayıp
(EREGL −8.68pp STOP_LOSS, 6 günde kana kana), 4 pozisyon uzatmada TP ile çözüldü.

Bulunan ölçüm artefaktı (düzeltildi): exit-extension yokken 4 açık pozisyon
test-sonunda FINAL_CLOSE ile kesilip "zarar" yazılmıştı (BIMAS −5.28 dahil).
Çıkış çözümlemesi eklenince tablo yukarıdaki hale geldi.

**Şerh:** n=17 incedir; tek kuyruk (EREGL) sonucu taşıyor. THYAO/AKBNK 2 yılda
sıfır OOS işlem üretti (bant onlar için çok dar).

## Arama (bant sabit, 8 aday × seed 7)

| # | buy | adx | rsi_os | pv | train fit | OOS n | OOS WR | OOS net | PF |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 28 | 15 | 30 | on | −0.70 | – | – | – | – |
| 2 | 24 | 25 | 25 | off | −1.06 | – | – | – | – |
| 3 | 32 | 15 | 35 | on | −1.01 | – | – | – | – |
| 4 | 24 | 15 | 30 | off | −1.25 | – | – | – | – |
| 5 | 24 | 15 | 25 | off | −1.25 | – | – | – | – |
| 6 | **24** | **25** | **25** | **on** | **−0.60** | **44** | **%75** | **−0.22pp** | **0.85** |
| 7 | 32 | 25 | 35 | on | −0.76 | – | – | – | – |
| 8 | 32 | 25 | 30 | on | −0.84 | – | – | – | – |

En iyi aday (buy 24/adx 25/rsi_os 25/pv on): OOS n=44, WR %75 [61–85],
ort. net **−0.222pp**, PF 0.85, kazanan +1.72pp'ye karşı kaybeden **−6.05pp**.

## Hüküm (v2 §4 kriterleri: WR ≥%45-50, PF >1.2, kabul edilebilir DD)

- En iyi aday: WR ✓, **PF 0.85 ✗** → KRİTER KARŞILANMIYOR.
- Champion: PF 2.87 ✓ ama n=17 + tek-kuyruk-kırılgan ✗ (kabul edilemez güven).
- Train fitness 8 adayın 8'inde de negatif → manzara düz-negatif; eşik
  oynamakla düzelmiyor.

**Bağlayıcı kısıt eşikler değil, kayıp asimetrisi:** kazanan +1.6pp'ye karşı
kaybeden −6…−8.7pp. WR %75-94 bile bu kuyruğu taşıyamıyor. v2'nin "%40 altı
strateji baştan" kuralının ruhu burada geçerli: bant-içi ayar değil,
**stop/kuyruk disiplini** gerekli (geniş stoplu kurulumlar, gap-sonrası kanama,
zaman-stop/trailing yokluğu).

## Sıradaki (öneri)

1. Kuyruk deneyleri: max stop mesafesi filtresi, zaman-stop (hedefe X günde
   yürümezse çık), geniş-stop kurulumda küçültülmüş boyut — aynı harness'ta
   aday olarak.
2. Tam evren (100) doğrulaması — pilot likitlerde iyimserlik olabilir
   (replay setindeki yan hisseler negatifti).
3. Kazanan aday → önce shadow, sonra küçük canlı (v2 champion/challenger).
4. Satış kapalı; kriterler sağlanmadan açılmamalı (mevcut durum: sağlanmıyor).
