# Açılış Boşluğu (Gap) Giriş Filtresi Deneyi — Faz 1

Tarih: 2026-09-23 · Evren: BIST100 snapshot (82 ticker veri) · 2y günlük ·
train 63 / test 21 / step 21 / purge 10 / embargo 5 / warmup 60 /
exit-extension 28 · maliyet realistic · champion bandı 28-33 + pv-gate ·
RR 1.0 (recalibrate RR süpürmesinden).

Kaynak: `results/recalibrate_gap_{base,pct2,pct3,pct5,atr10,atr15}.json` ·
Script: `scripts/recalibrate_champion.py` (`--gap-entry-pct` / `--gap-entry-atr`).

Protokol notu: 6 varyant tek process'te, **aynı veri snapshot'u** (tek fetch,
2026-09-23 parmak izi) ile koşuldu → varyantlar arası fark yalnızca filtreden
dir; veri kayması yok. Tüm varyantlar purge/embargo'lu havuzlanmış OOS,
gerçekçi maliyetli.

## Filtre tanımı

- Karar t-1 close, fill t open (motor parity: `enter_signal` shift(1), fill=open).
- Boşluk = (open[t] − close[t-1]) / close[t-1].
- pct varyantı: boşluk ≤ −X% ise girişi atla (X ∈ {2,3,5}).
- ATR varyantı: (close[t-1] − open[t]) > m · ATR[t-1] ise atla (m ∈ {1.0,1.5});
  ATR[t-1] kullanılır — ATR[t] look-ahead olurdu (birim testli).
- Yalnız aşağı boşluk (long-only); iki flag birlikte verilirse UNION.
- Flag'ler default None = kapalı = bit-identical (parite testli).

## Sonuçlar (havuzlanmış OOS, gerçekçi maliyet)

| Varyant | n | WR [%95 CI] | ort. net | kazanan ort. | kaybeden ort. | PF | base'den fark |
|---|---|---|---|---|---|---|---|
| base | 168 | %60.1 [52.6-67.2] | −0.393pp | +6.13pp | −10.23pp | 0.904 | — |
| pct 2% | 165 | %60.6 [53.0-67.7] | −0.386pp | +6.07pp | −10.32pp | 0.905 | 3 giriş bloklandı (2 kayıp + 1 kazanç) |
| pct 3% | 167 | %59.9 [52.3-67.0] | −0.468pp | +6.07pp | −10.23pp | 0.886 | 1 giriş bloklandı (kazanç) |
| pct 5% | 168 | %60.1 [52.6-67.2] | −0.393pp | +6.13pp | −10.23pp | 0.904 | 0 giriş bloklandı |
| ATR 1.0 | 168 | %60.1 [52.6-67.2] | −0.393pp | +6.13pp | −10.23pp | 0.904 | 0 giriş bloklandı |
| ATR 1.5 | 168 | %60.1 [52.6-67.2] | −0.393pp | +6.13pp | −10.23pp | 0.904 | 0 giriş bloklandı |

Bloklanan işlemler (pct2): BRYAT 2026-08-11 −5.44pp (STOP_LOSS), TRENJ
2025-04-07 +12.20pp (TAKE_PROFIT), TRMET 2026-06-19 −9.09pp (STOP_LOSS).
pct3 yalnız TRENJ kazancını attı.

## Yorum

- **Büyük boşlukla giriş nadir:** 168 OOS girişinin yalnızca 3'ünde ≥%2 aşağı
  boşluk, 1'inde ≥%3; ≥%5 veya >1·ATR[t-1] boşlukla giriş **hiç** yok. Filtrenin
  dokunabileceği bir kitle yok.
- **Etki gürültü seviyesinde:** pct2 iki kaybı ve bir kazancı attı (toplam
  +2.3pp / 165 işlem ≈ +0.007pp ort.) — PF 0.904→0.905, anlamsız. pct3 sadece
  kazancı attı, kötüleşti. ATR varyantları hiçbir şey değiştirmedi.
- **17 Eylül motivasyonu genellenmiyor:** "iki gap-açılışlı kayıp" izlenimi
  havuzlanmış OOS'ta sistemik bir desen değil; gap girişleri hem nadir hem
  karışık (kazanç da var).
- **Kabul kriterleri (v2 §4: PF >1.2, WR ≥%45-50, kaybeden ort. −8.7→−5pp):**
  hiçbir varyant sağlamıyor — base de dahil (PF 0.90).
- **Veri kayması notu:** 17 Eylül baz raporundan (n=176, PF 1.04) bugünkü
  snapshot'a (n=168, PF 0.90) profil kaydı; son pencere döndü + gün içi bar.
  Bu deneyin içi tutarlı (tek snapshot); tarihler arası karşılaştırma yapılmaz.

## Çoklu-test / yanlılık notu

6 varyant tek veri diliminde, eşikler önceden belirlenmiş (tarama yok) — yine
de tek dilim, küçük n; herhangi bir varyantın "daha iyi" görünmesi şans
olabilirdi. Bu koşuda hepsi RED olduğundan seçim yanlılığı söz konusu değil.

## Hüküm

**RED — filtre canlıya alınmamalı.** Flag'ler default kapalı kalır (bit-identical
parite korunur); kod kalibrasyon harness'inde deney aracı olarak duruyor.
Beklenti iyileştirmesi gerektiren kol hâlâ **stop disiplini** (kaybeden ort.
−10.2pp, dokunulmamış en büyük kol) ve satış kapısı kapalı kalmalı.

## Sonraki adımlar

1. Faz 2: WIP'in küme-commit/PR'lanması (bu deney kodu F kümesine dahil).
2. Stop disiplini kolları (stop-cap ATR/pct, time-stop) — mevcut stopgrid
   raporundaki adaylar.
3. Satış kapısı: kriterler sağlanana kadar kapalı (v2 §4).
