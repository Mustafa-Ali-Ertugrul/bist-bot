# Dual-Run Raporu: Maliyetsiz vs Gerçekçi (v2 §3)

Tarih: 2026-09-17 · Kaynak: `results/cost_dual_delay{0,1}.json` + `_trades.csv`
Sinyal seti: DB'deki 397 persist sinyal → dedupe sonrası 99 → RADAR/gap/veri/dejenere
elemeleri sonrası **raw n=23 (delay0) / n=13 (delay1)**.

Konfigürasyon: timeout 5 bar · realistic = komisyon 15bps + spread 20bps +
yön başına slippage 30bps (roundtrip **124.9bps = 1.249pp**) · min-risk %0.5
(dejenere giriş filtresi: delay0'da 4, delay1'de 4+ kurban) · delay0/delay1.

## Sonuç tablosu (raw dataset)

| Koşul | n | WR | WR Wilson %95 | ort. net | med. net | TP/SL |
|---|---|---|---|---|---|---|
| zero, delay0 | 23 | %47.8 | [29–67] | −0.54pp | −0.64pp | 11/12 |
| **realistic, delay0** | 23 | **%17.4** | [7–37] | **−1.78pp** | −1.89pp | 11/12 |
| zero, delay1 | 13 | %61.5 | [36–82] | −0.27pp | +0.23pp | 8/5 |
| **realistic, delay1** | 13 | **%15.4** | [4–42] | **−1.52pp** | −1.02pp | 8/5 |

first_actionable: n=3 (delay0) / n=2 (delay1), tamamı SL — low_n, hüküm kurulmaz.

## Ayrıştırma (v2'nin istediği cevap)

**1. Maliyet etkisi (aynı giriş, zero→realistic, delay0): WR −30.4pp, net −1.249pp.**
Kazananların brüt ortalaması **+1.24pp** — roundtrip maliyet (1.25pp) kazananın
tamamını yiyor. 11 brüt-kazananın **7'si maliyetle zarara dönüyor**
(4 net-kazananın brüt ortalaması +2.17pp, neti +0.92pp).
Mekanizma: champion RR 0.5 → küçük hedefler → 1.25pp sürtünme altında eziliyor.

**2. Gecikme etkisi (delay0→delay1, realistic): WR −2pp, n 23→13.**
1 bar gecikme isabeti değil **fırsat setini** küçültüyor: 10 sinyal gap/dejenere/
veri-sonu nedeniyle hiç işleme giremiyor. (delay1 zero WR %61.5 görünüyor ama
n=13, Wilson [36–82] — seçilim yanlılığı + küçük örneklem.)

**3. Yapısal sorun (maliyetten bağımsız): brüt beklenti zaten negatif.**
avgGross −0.54pp (delay0) / −0.27pp (delay1). Kazanan +1.24pp'ye karşı kaybeden
−2.16pp → gerçekleşen asimetri ~0.57; bu WR ile başabaş için gerekenden uzak.
Maliyet sıfır olsa bile bu sette edge yok.

## Hüküm (v2 §3 kabul kuralı)

Kural: "gerçekçi WR maliyetsizden çok düşüyorsa sorun backtest'in iyimserliğidir."
Burada tablo daha ağır: **maliyetsiz WR %47.8 zaten %60 barajının altında VE
gerçekçi %17.4'e çöküyor.** İki katmanlı sorun var:

1. Brüt sinyal edge'i zayıf/negatif (strateji kalibrasyonu gerekli — v2 adım 4).
2. Maliyetler (1.25pp), küçük hedefli (RR 0.5) yapıda kalanı öldürüyor.

Satış kapalı kalmalı (v2 §6 kriterleri: WR ≥%50, PF>1.2 — hiçbiri sağlanmıyor).
Öncelik sırası: önce brüt edge (purge'lu walk-forward rekalibrasyon) → sonra
maliyet-dayanıklılık (hedef büyüklüğü vs sürtünme) → sonra canlı kanıt (n≥100).

## Reprodüksiyon

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src"
.venv\Scripts\python.exe scripts/run_signal_replay.py --dataset raw,first_actionable `
  --cost zero,realistic --entry-delay-bars 0 --min-risk-pct 0.005 --period 2y `
  --out results/cost_dual_delay0.json
# delay1 için --entry-delay-bars 1 --out results/cost_dual_delay1.json
```

Notlar:
- `skipped_no_data=12`: 8 ticker'a bar indirilemedi + dönem-dışı sinyaller.
- `is_radar=45`: raw datasette RADAR sinyaller replay'e girmez (beklenen).
- `skipped_degenerate_risk=4`: giriş stop'a yapışık kurulumlar (örn. EUPWR'de
  R=−416.640 artefaktı bu filtreyle elendi).
