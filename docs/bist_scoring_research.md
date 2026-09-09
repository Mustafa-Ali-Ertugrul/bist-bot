# BIST Skorlama Araştırması ve Uygulama İlkeleri

> Araştırma tarihi: 27 Ağustos 2026  
> Kapsam: Borsa İstanbul payları için açıklanabilir karar-destek skoru  
> Uyarı: Bu sistem kişiye özel yatırım danışmanlığı vermez. Skorlar belirsizlik, veri hatası, işlem maliyeti ve piyasa rejimi riski taşır.

## 1. Amaç ve yöntem

Bu çalışma, skorlama motoruna daha fazla indikatör eklemek için değil; hangi bilgi ailelerinin gerçekten ayrı ekonomik bilgi taşıdığını, hangilerinin yalnızca aynı fiyat geçmişini farklı biçimde tekrar ettiğini ve BIST'e özgü hangi kuralların sinyalleri uygulanamaz hâle getirebildiğini belirlemek için hazırlanmıştır.

Kaynak önceliği:

1. Borsa İstanbul, SPK, KAP, MKK, Takasbank, TCMB, TÜİK ve KGK gibi birincil kaynaklar.
2. Hakemli ve geniş örneklemli akademik çalışmalar.
3. Türkiye/BIST'e özgü ampirik çalışmalar.
4. Alanın temel kitapları.
5. Uygulamacı metinleri yalnızca hipotez üretmek için; tek başına ağırlık/eşik kanıtı olarak değil.

Bir faktörün canlı skora girebilmesi için dört koşul aranır:

- Karar anında gerçekten erişilebilir, point-in-time veri.
- Ekonomik gerekçe ve bağımsız bilgi içeriği.
- İşlem maliyeti ve likidite sonrası uygulanabilirlik.
- Kronolojik, veri sızıntısız ve çoklu-deneme düzeltmeli doğrulama.

## 2. Mevcut sistemin durumu

Canlı skor bugün normalize edilmiş OHLCV verisinden üretiliyor:

1. `StrategyEngine.analyze()`
2. teknik indikatör zenginleştirmesi
3. `calculate_score_and_reasons()`
4. momentum, trend, hacim ve yapı bileşenleri
5. rejim, momentum teyidi, OBV/uyum/cap filtreleri
6. sinyal sınıflandırma, risk boyutlandırma ve çoklu-zaman confluence

Temel analiz modülü canlı skorun parçası değildir. Mevcut snapshot yalnızca P/E, piyasa değeri, sektör ve 52-hafta aralığı gibi az sayıda alan içerir. KAP yayın zamanı, dosya sürümü, konsolidasyon türü, TMS 29 rejimi ve restatement geçmişi tutulmadığından bu veriyi geçmiş skora eklemek look-ahead bias yaratır.

Mevcut teknik skorda önemli korelasyon riski vardır:

- RSI, Stochastic ve CCI kısa-horizon fiyat konumunun farklı dönüşümleridir.
- EMA/SMA, MACD ve ADX trend bilgisinin kısmen örtüşen dönüşümleridir.
- Bollinger, destek/direnç ve divergence sinyalleri yine aynı OHLC geçmişinden türetilir.
- Ham teorik bileşen üst sınırları farklıdır: momentum 45, trend 70, hacim 26, yapı 50. Ham toplam bu ölçek farkını ekonomik kanıt gibi yorumlayabilir.

## 3. Kanıt hiyerarşisi

### 3.1 Güçlü çekirdek adaylar

- **Orta vadeli momentum/trend:** Klasik kanıt 3-12 aylık kazananların görece devamlılığıdır. En son günler/haftalar kısa-vadeli reversal ve mikro-yapı etkisi taşıyabilir.
- **Değer:** Tek P/E yerine sektör-uygun birden fazla oran ve gerçek/normalize kazanç kullanılmalıdır.
- **Kârlılık ve kalite:** Brüt/operasyonel kârlılık, nakit dönüşümü, tahakkuk kalitesi, bilanço güvenliği.
- **Kazanç momentumu/PEAD:** BIST çalışmaları olumlu sinyal gösterir; yalnızca gerçek KAP yayın zamanı ve point-in-time beklenti verisiyle kullanılabilir.

### 3.2 Risk ve uygulanabilirlik katmanı

- İşlem değeri, spread, serbest dolaşım ve fiyat etkisi.
- Gerçekleşen/downside volatilite, drawdown ve beklenen kısa düşüş riski.
- Korelasyon, sektör yoğunluğu ve marjinal portföy riski.
- Komisyon, kayma, kademe, fiyat limiti, kısmi gerçekleşme ve taşıma maliyeti.

Likidite beklenen getiriye pozitif bonus olarak verilmemelidir. Akademik “illiquidity premium” çoğu zaman tam da uygulanması en pahalı hisselerde görünür. Bu nedenle likidite öncelikle gate/capacity katmanıdır.

### 3.3 Koşullu yardımcılar

- Hacim yalnızca fiyat yönü, normal hacim ve piyasa fazıyla birlikte yorumlanmalıdır.
- ADX yön değil trend gücü ölçer.
- ATR yön değil ölçek/risk ölçer.
- RSI/MACD/Bollinger sabit eşikleri evrensel kanun değildir; sürekli dönüşüm veya etkileşim özelliği olarak kullanılmalıdır.
- Makro rejim sinyal yönünü otomatik tersine çevirmek yerine pozisyon/risk ağırlığını kademeli değiştirmelidir.

## 4. BIST'e özgü zorunlu bağlam

### 4.1 Seans ve müzayede

Borsa İstanbul'da sürekli işlem ve tek fiyat/call auction yöntemleri birlikte kullanılır. Açılış, sürekli işlem, devre kesici emir toplama, kapanış müzayedesi ve kapanış fiyatından işlemler aynı veri üretim süreci değildir. İntraday hacim ve volatilite bunlar ayrılmadan karşılaştırılmamalıdır.

### 4.2 Fiyat limitleri ve devre kesiciler

Fiyat limitine kilitlenen getiri dengeli piyasa fiyatı değil, sansürlü gözlemdir. Menkul kıymet devre kesicisi ve piyasa-geneli devre kesici farklı olaylardır. Borsa İstanbul FAQ'sına göre piyasa-geneli mekanizma BIST 100'de önceki kapanışa göre %6 veya daha büyük düşüşte tetiklenir ve seans sonuna kadar açığa satış uptick kuralını etkinleştirir.

### 4.3 VBTS, brüt takas ve açığa satış

VBTS tedbirleri; açığa satış/kredili işlem yasağı, brüt takas, emir tipi kısıtı veya tek fiyat yöntemi gibi farklı etkiler taşıyabilir. Tek bir `restricted=true` alanı yeterli değildir; her tedbir başlangıç ve bitiş seansıyla ayrı tutulmalıdır.

### 4.4 Kurumsal işlemler

Temettü, bedelli/bedelsiz, bölünme, birleşme ve hak kullanımı fiyat serilerini mekanik olarak değiştirir. Momentum ve getiri yalnızca Borsa metodolojisiyle uyumlu düzeltilmiş seri üzerinde hesaplanmalıdır.

### 4.5 TMS 29

Enflasyon muhasebesi Türkiye şirketlerinin zaman serisinde rejim kırığı yaratır. Net parasal pozisyon kazancı/kaybı sıradan faaliyet kârı gibi puanlanamaz. Bankalar ile sanayi şirketleri aynı oran modeliyle değerlendirilemez. Her bilanço gözlemi raporlama standardı, konsolidasyon, TMS 29 durumu, satın-alma gücü tarihi ve KAP yayın zamanı taşımadan canlı modele girmemelidir.

## 5. Temel analiz için hedef veri modeli

Gelecek inkrementte KAP tabanlı versioned filing store şu alanları tutmalıdır:

- şirket/menkul kıymet kimliği
- mali dönem ve dönem uzunluğu
- konsolide/konsolide olmayan
- KAP bildirim kimliği ve gerçek yayın zamanı
- ilk işlem yapılabilir seans
- ilk bildirim/düzeltme/iptal/superseded ilişkisi
- denetim türü ve görüşü
- TMS/TFRS/TMS 29/BDDK raporlama rejimi
- raporlanan ve analistçe düzeltilmiş değer
- veri çıkarım zamanı ve kaynak satırı

Sektör modelleri ayrılmalıdır:

- **Sanayi/hizmet:** ROIC, brüt kârlılık, marj, nakit dönüşümü, tahakkuk, net borç, faiz karşılama, reel büyüme, yatırım getirisi, EV tabanlı değerleme.
- **Banka:** ROAE/ROAA, net faiz marjı, takipteki kredi, Stage 2/3, karşılık, sermaye yeterliliği, fonlama ve P/B'nin sürdürülebilir ROE ile ilişkisi.
- **GYO/holding/sigorta:** kendi ekonomik ve muhasebe yapılarına ayrı model.

## 6. `research_v1` uygulaması

İlk inkrement yalnızca mevcut, güvenilir OHLCV bileşenlerini yeniden birleştirir. Varsayılan `conservative` profil değişmez. Profil şu şekilde açılır:

```text
STRATEGY_PROFILE=research_v1
```

Ham skorlar önce kendi teorik cap'lerine bölünür ve `[-1, 1]` aralığına alınır. Sonra ağırlıklar toplamı bire normalize edilir:

```text
component_contribution = clamp(raw_component / component_cap, -1, 1)
                         * normalized_weight
                         * 100
```

Başlangıç araştırma öncülleri:

| Kod bileşeni | Ağırlık | Gerekçe |
|---|---:|---|
| Trend | 0.60 | Mevcut OHLCV içinde orta-horizon devamlılık kanıtına en yakın aile |
| Momentum (osilatör/tepki) | 0.15 | Kısa-horizon reversal koşullu ve maliyet hassas |
| Hacim | 0.15 | Onay/uygulanabilirlik bilgisi; tek başına yön sinyali değil |
| Yapı | 0.10 | Bollinger/destek/divergence için bağımsız kanıt daha zayıf |

Bu ağırlıklar “optimum” ilan edilmez. Bunlar backtest öncesi, literatür-temelli shrinkage öncülleridir. Kodda negatif ağırlıklar ve toplamı sıfır ağırlıklar açıkça reddedilir.

`score_breakdown`, araştırma profilinde ham indikatör puanlarını değil etkili ağırlıklı katkıları gösterir. Rejim çarpanı, counter-trend bastırma, OBV/chase/agreement cap ve düşük ADX cezasının net etkisi `adjustments` altında tutulur; böylece açıklama toplamı final skora bağlanabilir.

## 7. Neden varsayılan profil değiştirilmedi?

Yeni profil için henüz şu kanıtlar yoktur:

- yeterli point-in-time BIST evreni ve delist edilmiş hisseler
- kurumsal işlem/VBTS/seans durumu geçmişi
- gerçek spread ve piyasa-etki maliyeti
- ayrı train/validation/test dönemleri
- çoklu deneme kaydı ve seçim yanlılığı düzeltmesi
- farklı enflasyon/kur/faiz rejimlerinde kararlılık

Bu kanıtlar olmadan varsayılanı değiştirmek, araştırma bulgularına aykırı biçimde canlı sistemde test yapmak olur.

## 8. Zorunlu doğrulama protokolü

1. Point-in-time evren; bugünkü BIST 30/50/100 üyelerini geçmişe taşımama.
2. Delist edilmiş, birleşmiş ve işlemden kaldırılmış hisseleri koruma.
3. Kurumsal işlem ve fiyat-limitlerini tarihsel olarak uygulama.
4. Kronolojik walk-forward; rastgele train/test bölme yok.
5. Örtüşen etiket pencerelerinde purge ve embargo.
6. Normal, stresli ve kriz işlem maliyetleri.
7. TRY nominal, TÜFE reel ve USD getiri raporu.
8. Yıl, sektör, likidite kovası ve piyasa rejimi bazında sonuç.
9. Rank IC, hit-rate, calibration, turnover, drawdown, expected shortfall ve kapasite.
10. `conservative`, `research_v1`, eşit-ağırlık ve basit momentum baseline karşılaştırması.

## 9. Yol haritası

### Inkrement 1 — tamamlanan temel

- Sürümlenmiş `research_v1` profil.
- Normalize ve ağırlıklı teknik aile bileşimi.
- Legacy profiller için geriye uyumluluk.
- Final skorla uzlaşan açıklanabilir katkılar.

### Inkrement 2 — veri ve piyasa güvenliği

- Likidite gate'ini meta-modelden ayırma.
- İşlem değeri, stale/zero-volume, fiyat limiti ve halt/VBTS bayrakları.
- Backtest ile canlı risk yolunun parity'si.

### Inkrement 3 — gerçek momentum ve risk özellikleri

- Günlük trend verisinden 63/126 günlük, son 5-20 günü atlayan momentum.
- Gerçekleşen/downside volatilite ve drawdown.
- Cross-sectional, sektör-nötr robust rank.

### Inkrement 4 — KAP temel veri deposu

- Point-in-time filing store.
- TMS 29 ve sektör-özel modeller.
- Kalite, kârlılık, değer ve earnings-surprise bileşenleri.

### Inkrement 5 — makro ve portföy katmanı

- TCMB/TÜİK yayın zamanı güvenli kur/faiz/enflasyon verisi.
- Firma/sektör beta etkileşimleri.
- Shrinkage covariance, risk katkısı ve kapasite kısıtları.

## 10. Seçilmiş kaynakça

### Resmi kaynaklar

- Borsa İstanbul, Equity Market FAQ: https://www.borsaistanbul.com/en/faq/equity-market
- Borsa İstanbul, Market Functioning: https://www.borsaistanbul.com/en/markets/equity-market/market-functioning
- Borsa İstanbul, Equity Market Procedure: https://www.borsaistanbul.com/files/equity-market-procedure.pdf
- KAP, General Information: https://kap.org.tr/en/about/general-information
- KGK, TMS 29 uygulama rehberi güncellemesi: https://kgk.gov.tr/ContentAssignmentDetail/5079/Enflasyon-Muhasebesi-Uygulama-Rehberinin-Gu%CC%88ncellenmesi
- IFRS Foundation, IAS 29: https://www.ifrs.org/issued-standards/list-of-standards/ias-29-financial-reporting-in-hyperinflationary-economies/
- SPK mevzuat sistemi: https://mevzuat.spk.gov.tr/
- TCMB EVDS: https://evds2.tcmb.gov.tr/
- TÜİK veri portalı: https://data.tuik.gov.tr/

### Makaleler

- Sharpe (1964), CAPM: https://doi.org/10.1111/j.1540-6261.1964.tb02865.x
- Fama & French (1992), size/value: https://doi.org/10.1111/j.1540-6261.1992.tb04398.x
- Fama & French (2015), five-factor model: https://doi.org/10.1016/j.jfineco.2014.10.010
- Jegadeesh & Titman (1993), momentum: https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- Carhart (1997), momentum factor: https://doi.org/10.1111/j.1540-6261.1997.tb03808.x
- Novy-Marx (2013), profitability: https://doi.org/10.1016/j.jfineco.2013.01.003
- Asness, Frazzini & Pedersen (2019), quality: https://doi.org/10.1007/s11142-018-9470-2
- Amihud (2002), illiquidity: https://doi.org/10.1016/S1386-4181(01)00024-6
- Pástor & Stambaugh (2003), liquidity risk: https://doi.org/10.1086/374184
- Harvey, Liu & Zhu (2016), factor zoo/multiple testing: https://doi.org/10.1093/rfs/hhv059
- McLean & Pontiff (2016), factor decay: https://doi.org/10.1111/jofi.12365
- Hou, Xue & Zhang (2020), anomaly replication: https://doi.org/10.1093/rfs/hhy131
- Novy-Marx & Velikov (2016), trading costs: https://doi.org/10.1093/rfs/hhv063
- Atılgan, Demirtaş & Günaydın (2016), BIST liquidity: https://doi.org/10.1080/00036846.2016.1170935
- Ahlatcıoğlu & Okay (2021), Turkey PEAD: https://doi.org/10.1016/j.bir.2020.09.001
- Doğan, Kevser & Demirel (2022), BIST six-factor: https://doi.org/10.1155/2022/3392984
- Candemir & Karahan (2024), BIST individual-stock factor tests: https://www.sciencedirect.com/science/article/pii/S221484502400084X
- Gökçen (2026), Turkish equity factor investing: https://www.sciencedirect.com/science/article/pii/S2214845026001043

### Kitaplar

- Benjamin Graham & David Dodd, *Security Analysis*.
- Aswath Damodaran, *Investment Valuation*.
- Stephen Penman, *Financial Statement Analysis and Security Valuation*.
- Richard Grinold & Ronald Kahn, *Active Portfolio Management*.
- Andrew Lo & A. Craig MacKinlay, *A Non-Random Walk Down Wall Street*.
- Marcos López de Prado, *Advances in Financial Machine Learning* — özellikle purge/embargo ve backtest leakage; yöntemler bağımsız doğrulama gerektirir.
- John Hull, *Risk Management and Financial Institutions*.
- John Murphy, *Technical Analysis of the Financial Markets* — uygulamacı referansı; sabit indikatör eşikleri için tek başına bilimsel kanıt sayılmaz.
