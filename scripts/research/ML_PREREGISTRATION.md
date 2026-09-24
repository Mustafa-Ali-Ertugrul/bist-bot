# Koşullu çok faktörlü model (ML) — ön kayıt (2026-09-24, sonuçlar görülmeden)

Amaç: tek tek kurallar yerine, koşulları piyasa ortamıyla birlikte değerlendiren
bir model — "hangi ortamda hangi koşul işe yarıyor"u kendisi öğrensin.

## Veri ve evren
Parti 1-2 ile aynı: İş Yatırım günlük + çeyreklik tablolar (gecikme kuralları
aynı), XU100 ve USD/TRY (Yahoo), para piyasası = politika faizi × 0.85 (yaklaşık).
Evren: o çeyreğin BIST100 üyeleri, ≥250/260 gün, en likit 50.

## Girdiler (ay sonu, yalnızca o güne kadar bilinen)
Hisse (her ay kesitsel yüzdelik sıraya çevrilir): 1 ay getiri, 6-1 ve 12-1 ay
momentum, 3 ay volatilite, 52 hafta zirveye uzaklık, hacim trendi (21/126 gün
medyan TL hacim), log piyasa değeri, defter/piyasa, kâr getirisi, ROE, kâr
sürprizi, satış büyümesi.
Piyasa (tüm hisselerde aynı): XU100 12 ay getirisi − para piyasası 12 ay,
XU100 1 ay getirisi, XU100 3 ay volatilitesi, USD/TRY 3 ay değişimi, faiz seviyesi.

## Hedef ve model
Hedef: sonraki ayın (işlem gününden işlem gününe) getirisinin kesitsel yüzdelik
sırası. Model: XGBoost regresyon, sabit parametreler: max_depth=3,
n_estimators=300, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8,
min_child_weight=20, seed=0. Ayar/tarama yok.
Eğitim: genişleyen pencere; t ayı için yalnızca hedefi t−1'den önce gerçekleşmiş
aylar (1 ay boşluk). İlk tahmin 2019-01 (eğitim 2016-04 … 2018-11).

## Stratejiler (%0.35/yön maliyet, ertesi gün kapanış işlem)
- **D1 ML10:** tahmini en yüksek 10 hisse, eşit ağırlık, her zaman yatırımda.
- **D2 R+ML10:** aynı, rejim (XU100 12 ay ≤ para piyasası) kapalıyken nakit.

## Kabul kriteri (backtest)
1. Aylık bilgi katsayısı (tahmin–gerçekleşen Spearman) ortalaması > 0, t ≥ 2.0 (2019-01 … 2026-09).
2. D1 hem 2019-2022'de hem 2023-2026'da likit-50 eşit ağırlığı geçer.
3. D2 2023-2026'da hem XU100'ü hem para piyasasını geçer.
Not: 2023-2026 dönemi önceki testlerde görüldü; bu yüzden sonuç ne olursa olsun
D1 ve D2 canlı lige "D grubu" olarak eklenir ve nihai karar canlı veriyle verilir
(LEAGUE_PREREGISTRATION.md kriterleri).
