# Strateji Skor Motoru (Strategy Engine) ve Risk Yönetimi Denetim Raporu

Bu rapor, `strategy/scoring`, `regime`, `MTF`, `confidence` ve `stop-target` modüllerinin statik ve mantıksal denetim sonuçlarını içermektedir. Rapor, canlı sinyal loglarında gözlenen zıt bileşenlerin aynı skorda toplanması, "chase" (kovalama) ve düşen-bıçak senaryolarının ödüllendirilmesi ile güven (confidence) metriğinin uyumsuzluğu gibi kantitatif sorunların kod düzeyindeki kök nedenlerini belirlemektedir.

---

## 1. Hipotez Denetim Detayları

### H1: Zıt Yönlü Bileşenlerin Aynı Skora Eklenmesi ve Birbirini Götürmemesi
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/engine_filters.py:calculate_score_and_reasons:118-123`
    *   **Kod Parçası:**
        ```python
        s1, r1 = momentum_scorer(last, prev)
        s2, r2 = trend_scorer(last, prev)
        s3, r3 = volume_scorer(last, prev)
        s4, r4 = structure_scorer(last)
        score = s1 + s2 + s3 + s4
        ```
*   **Severity:** **KRİTİK**
*   **Kök Neden:** Trend-takipçi (trend-confirming) ve karşıt-trend (counter-trend/mean-reversion) modüllerinin skorları, mantıksal bir hizalama süzgecinden (directional alignment gating) geçirilmeden doğrudan aritmetik olarak toplanmaktadır. Örneğin, güçlü bir düşüş trendinde olan bir hissede (Trend = -20) RSI aşırı satım (+14) ve CCI aşırı satım (+8) gibi tepki yükselişi puanları toplandığında net skor pozitif (+2) çıkabilmektedir. Bu durum, düşen bıçak (falling knife) senaryolarını engellemek yerine skor düzeyinde maskelemektedir.
*   **Walk-Forward Ölçümü:** Bu düzeltildikten sonra, trend ve momentum yönlerinin çeliştiği durumlarda (örn. Trend=Ayı, Momentum=Boğa) sinyal üretimi engellenmelidir. Walk-forward testinde **Max Drawdown (MDD)** değerinde azalma, **Win Rate (Kazanma Oranı)** değerinde artış ve özellikle ayı piyasası dönemlerinde **Sharpe Oranı**'nda belirgin iyileşme ölçülmelidir.

---

### H2: Mean-Reversion ve Trend-Teyit Sinyallerinin Aynı Anda Puan Alması ve Trend Filtresinin Seviyeye Bakması
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/scoring.py:score_trend:88-99`
    *   **Kod Parçası:**
        ```python
        ema_long = last.get(f"ema_{settings.EMA_LONG}")
        if pd.notna(ema_long):
            price = last["close"]
            above_ema = price > ema_long
            ...
            elif above_ema:
                if pd.notna(adx) and adx >= params.adx_threshold:
                    score += params.score_ema_cross
                    reasons.append(f"yükseliş trendi (EMA{settings.EMA_LONG} üzerinde)")
        ```
*   **Severity:** **ORTA**
*   **Kök Neden:** Trend filtresi, uzun vadeli hareketli ortalamanın (EMA200) eğimine (slope) veya yönüne değil, sadece fiyatın ortalamanın üzerinde olup olmadığına (seviye/level) bakmaktadır (`above_ema = price > ema_long`). Fiyatın EMA200 üzerinde olduğu ancak EMA200'ün aşağı eğimli olduğu geçici tepki yükselişlerinde bile sisteme trend teyit puanı eklenmektedir. Bu sırada RSI aşırı satım göstergesi de aynı anda çalışarak pozitif puan üretebilmektedir.
*   **Walk-Forward Ölçümü:** Trend teyit mantığına EMA200 eğiminin (slope) pozitif olması şartı eklendiğinde sahte trend dönüşlerindeki işlemler elenecektir. Walk-forward testlerinde **Profit Factor (Kârlılık Faktörü)** ve **Average Trade Net Return** metriklerinin yükselmesi beklenir.

---

### H3: Aşırı Uzama Durumlarında Momentum/Structure Cezası Yetersizliği ve Chase Ödüllendirilmesi
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/scoring.py:score_structure:265-274` ve `src/bist_bot/strategy/scoring.py:score_momentum:25-33`
    *   **Kod Parçası:**
        ```python
        elif bb_pos == "ABOVE_UPPER":
            score -= params.score_bollinger_extreme
            reasons.append("Fiyat Bollinger üst bandının üstünde → Aşırı uzamış")
        ```
*   **Severity:** **KRİTİK**
*   **Kök Neden:** Fiyat Bollinger üst bandının dışına çıktığında (`ABOVE_UPPER` = -10.0), RSI aşırı alım bölgesine girdiğinde (`rsi > 70` = -14.0) ve dirence çok yakın olunduğunda (`dist_resist < 2` = -6.0) uygulanan toplam ceza puanı en fazla ~-30 ila -38 arasındadır. Buna karşın, güçlü trend ve hacim teyitleri (+70 trend cap ve +26 volume cap) toplamda +96 puana kadar çıkabilmektedir. Bu durumda net skor rahatlıkla +50'nin üzerinde kalıp "GÜÇLÜ AL" sinyali üretmekte ve aşırı şişmiş fiyatlardan alım yapılmasına (chase) yol açmaktadır. Sert bir aşırı uzama blokajı (hard limit/gating) bulunmamaktadır.
*   **Walk-Forward Ölçümü:** Aşırı uzama ve direnç yakınlığı durumlarında sinyal üretimini engelleyen sert filtreler eklendiğinde, walk-forward testlerinde **Ulcer Index (Fiyat Gerileme Endeksi)** düşmeli ve tepe fiyatlardan dönüşlerdeki kayıplar azaldığı için **Sortino Oranı** yükselmelidir.

---

### H4: Hacim Divergence'ının Raw Hacim Artışı Tarafından Ezilmesi
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/scoring.py:score_volume:198-246`
    *   **Kod Parçası:**
        ```python
        if vol_ratio >= min_vol_ratio:
            score += params.score_volume_confirm  # +8.0
        ...
        if vol_spike:
            ...
            score += params.score_volume_spike  # +8.0
        ...
        elif obv_trend == "DOWN":
            score -= params.score_obv_trend  # -4.0
        ```
*   **Severity:** **ORTA**
*   **Kök Neden:** OBV düşüş trendi gibi yapısal hacim uyumsuzlukları (divergence) skordan sadece `-4.0` puan düşürürken, tek günlük hacim artışı veya hacim patlaması (`score_volume_confirm` + `score_volume_spike`) sisteme `+16.0` puan eklemektedir. Benzer şekilde, fiyat-hacim düşüş onayı (`price_volume_direction == "BEARISH_CONFIRMATION"`) sadece `-2.0` puan düşürmektedir. Yapısal dağıtım (distribution) uyumsuzlukları, anlık raw hacim yükselişleri tarafından kolayca ezilmektedir.
*   **Walk-Forward Ölçümü:** OBV trendi negatifken uzun yönlü sinyallerin engellenmesi durumunda, hacimsiz yükselişlerin tepe noktalarında oyuna dahil olma riski sıfırlanacaktır. Walk-forward testinde **Win Rate** ve **Average Loss** metriklerinde iyileşme ölçülmelidir.

---

### H5: Confidence Metriğinin Bileşen Yön Uyumunu Ölçmemesi
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/engine_filters.py:classify_signal:39-53` ve `src/bist_bot/risk/stops.py:determine_final_levels:188-198`
    *   **Kod Parçası:**
        ```python
        if score >= params.strong_buy_threshold:
            return SignalType.STRONG_BUY, "confidence.high"
        ```
*   **Severity:** **KRİTİK**
*   **Kök Neden:** `confidence` (güven) metriği, sinyali oluşturan alt modüllerin yön uyum oranını (agreement ratio) ölçmemektedir. Varsayılan güven değeri doğrudan nihai skorun büyüklüğüne göre belirlenmektedir (Skor >= 48 ise doğrudan `confidence.high`). Risk yönetimindeki alternatif güven hesaplaması ise sadece stop-loss seviyelerinin birbirine yakınlığına (standart sapma) bakmaktadır. Bir sinyalin trendi çok güçlü ancak momentumu aşırı şişmiş ve hacmi uyumsuz olsa bile, net skor yüksek çıktığı için sinyal "Yüksek Güvenli" olarak etiketlenmektedir.
*   **Walk-Forward Ölçümü:** Güven metriği, yön birliği gösteren modüllerin oranına (örn. 4 modülün 4'ünün de pozitif olması = High, 3/4 = Medium, 2/4 = Low) göre hesaplandığında sinyal kalitesi gerçek olasılıkla kalibre olacaktır. Walk-forward'da **High Confidence** etiketli işlemlerin **Win Rate** ve **Profit Factor** değerleri, Low/Medium olanlara kıyasla istatistiksel olarak anlamlı derecede daha yüksek çıkmalıdır.

---

### H6: MTF Confluence Modülünün SMA ve EMA Çelişkilerinde Teyit Vermesi
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/regime.py:get_trend_bias:62-89` ve `src/bist_bot/strategy/regime.py:detect_regime:26-59`
    *   **Kod Parçası:**
        ```python
        if (
            regime == MarketRegime.BULL
            and pd.notna(ema_long)
            and close >= float(ema_long)
            and plus_di >= minus_di
        ):
            return TrendBias.LONG
        ```
*   **Severity:** **ORTA**
*   **Kök Neden:** Üst zaman diliminin trend yönü (`TrendBias.LONG` veya `SHORT`) belirlenirken sadece fiyatın EMA200 üzerinde olması, ADX/DI ilişkisi ve fiyatın SMA20 üzerindeki momentumuna bakılmaktadır. SMA veya EMA çizgilerinin kendi eğim yönleri (slope direction) veya birbirleriyle çelişip çelişmedikleri kontrol edilmemektedir. Bu nedenle, SMA20 eğimi net aşağı yönlüyken fiyatın geçici olarak EMA200 üzerinde olması durumunda bile confluence teyit verilmekte ve *"günlük trend LONG, 15dk tetik destekliyor"* denmektedir.
*   **Walk-Forward Ölçümü:** SMA ve EMA yönlerinin çeliştiği (eğrilerin farklı yönlere baktığı) durumlar "çelişki/nötr" olarak elendiğinde, testere (whipsaw) piyasalarındaki hatalı işlemler elenecektir. Walk-forward'da **Number of Trades** (işlem sayısı) düşerken **Win Rate** ve **Profit Factor** yükselmelidir.

---

### H7: Skor Normalizasyonunda Belirsizlik, Satürasyon ve Asimetri Sorunu
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/engine_filters.py:calculate_score_and_reasons:122` ve `:172`
    *   **Kod Parçası:**
        ```python
        score = s1 + s2 + s3 + s4
        ...
        score = max(-100, min(100, score))
        ```
*   **Severity:** **ORTA**
*   **Kök Neden:** Skor normalizasyonu ağırlıklı bir ortalama (weighted average) değil, bireysel modül skorlarının düz toplamıdır. Modül sınır değerlerinin (cap) toplamı 45 + 70 + 26 + 50 = 191 puana kadar çıkabilmekte, ancak nihai skor `[-100, 100]` aralığına zorla sınırlanmaktadır (hard clamp). Bu durum, çok güçlü trend (+70) ve hacim (+26) olan hisselerde skorun 100 sınırında doymasına (saturation) yol açar. Satürasyon nedeniyle, yapısal aşırı uzama veya direnç yakınlığı gibi negatif unsurlar (örn. -10 veya -15) skoru aşağı çekememektedir (çünkü 141 - 15 = 126, yine 100'e clamp'lenir). Skorlama mantığında yapısal bir asimetri yoktur, ancak doymadan kaynaklı bir maskeleme kusuru vardır.
*   **Walk-Forward Ölçümü:** Ağırlıklı ortalamaya dayalı bir skorlama yapıldığında sinyal skorları hissenin gerçek durumunu daha lineer yansıtacaktır. Walk-forward testlerinde **R-squared** (skor ile gelecek getiri arasındaki ilişki) ve **Information Ratio** yükselmelidir.

---

### H8: Stop/Hedef Metodolojisinde Tutarsızlık ve BIST Günlük Limit sanity-check Eksikliği
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/risk/stops.py:determine_final_levels:137-146` ve `:164-179`
    *   **Kod Parçası:**
        ```python
        levels.final_stop = reasonable_stops[best_stop_method]
        ...
        levels.final_target = reasonable_targets[best_target_method]
        ```
*   **Severity:** **KRİTİK**
*   **Kök Neden:** 
    1. Stop ve hedef seviyeleri tamamen bağımsız mantıklarla seçilmektedir (stop en yakın/en yüksek değer seçilirken, hedef belirli bir öncelik listesine göre seçilir). Bu durum tutarsız R/R planları üretir (örn. Fibonacci stop + Direnç hedef).
    2. BIST ±10% günlük limitine göre hedef fiyat kontrolü yoktur; 1 günlük işlem planında %15 yukarıda hedef belirlenebilmektedir.
    3. BIST fiyat adımları (tick size) kontrol edilmeden direkt `round(..., 2)` yapılmaktadır. BIST'te hisse fiyatına göre fiyat adımları değişmektedir (örn. 50 TL üzeri hisselerde adım 0.05 TL'dir). `round(..., 2)` ile üretilen 50.02 gibi bir fiyat emir gönderiminde borsadan hata dönecektir.
*   **Walk-Forward Ölçümü:** Tutarlı R/R ve BIST fiyat adımları uygulandığında, canlı emir gönderimindeki red oranları sıfıra inecektir. Walk-forward ve canlı testlerde **Slippage** ve **Execution Failure Rate** düşecektir.

---

### H9: BIST100 Beta-Korelasyon Ayrımının Olmaması ve Skorun Market Beta'sından Arındırılmaması
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/risk/correlation.py:build_global_correlation_cache:27` ve `get_correlated_positions`
    *   **Kod Parçası:**
        ```python
        cache = close_frame.pct_change().dropna().corr()
        ```
*   **Severity:** **Düşük**
*   **Kök Neden:** Risk yönetiminde sadece hisseler arası ikili korelasyon (pairwise correlation) matrisi hesaplanmakta, endeks (BIST100) beta korelasyonu ayrımı yapılmamaktadır. Hisselerin skorları piyasa beta'sından arındırılmadığı için, endeks genel bir yükselişteyken tüm hisselerin skoru yapay olarak yükselmekte ve portföy beta riski kontrol edilememektedir.
*   **Walk-Forward Ölçümü:** Beta arındırması (alpha-scoring) uygulandığında, endeksin yatay/düşüş evrelerinde beta gücüyle yükselen zayıf hisseler elenecektir. Walk-forward testinde **Beta-Adjusted Sharpe Oranı** ve **Active Return (Alpha)** artacaktır.

---

### H10: Düşük ADV / Geniş Spread / Float için Pre-filter veya Skor Cezası Eksikliği
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/risk/sizing.py:apply_probability_sizing:99-109` ve `_calc_position_size`
    *   **Kod Parçası:**
        ```python
        if levels.liquidity_value and levels.liquidity_value < min_liquidity_value:
            levels.position_size = 0
            levels.max_loss_tl = 0.0
            levels.blocked_by_liquidity = True
        ```
*   **Severity:** **ORTA**
*   **Kök Neden:** Veri çekim katmanında halka açıklık oranı (float) veya anlık spread verileri bulunmamaktadır. Dolayısıyla bu riskler için ne bir pre-filter ne de skor cezası uygulanabilmektedir. Ortalama işlem hacmi (ADV) kontrolü ise risk manager aşamasında yapılmaktadır ancak `MIN_LIQUIDITY_VALUE_TL` varsayılan değeri `0.0` olduğu için bu kontrol varsayılan ayarlarda tamamen etkisizdir (bypassed). Sığ ve manipülatif hisseler yüksek skor alıp sinyal üretebilmektedir.
*   **Walk-Forward Ölçümü:** ADV ve spread filtreleri aktif edildiğinde sığ hisselerdeki slippage kayıpları engellenecektir. Walk-forward ve canlı canlı testlerde **Realized Slippage** düşecek ve **Win Rate** daha istikrarlı olacaktır.

---

### H11: Sinyal Zaman Damgası ile Sistem Zamanı Arasındaki Zaman Dilimi / Veri Tazeliği Uyuşmazlığı
*   **Durum:** **DOĞRULANDI**
*   **Kanıt:**
    *   **Dosya/Fonksiyon/Satır:** `src/bist_bot/strategy/signal_models.py:_make_expires_at:57-61` ve `is_expired:88-94`
    *   **Kod Parçası:**
        ```python
        timestamp: datetime = field(default_factory=datetime.now)
        ...
        if now is None:
            now = datetime.now(UTC)
        ```
*   **Severity:** **KRİTİK**
*   **Kök Neden:** 
    1. Sinyal nesnesi oluşturulurken `timestamp` alanına varsayılan olarak `datetime.now()` (naive local time, örn. Türkiye saatiyle 10:22) atanmaktadır.
    2. Ancak veri sağlayıcılar ve veritabanı işlemleri UTC zaman damgaları kullanmaktadır.
    3. `is_expired` fonksiyonu çağrıldığında, `now` parametresi boş ise `datetime.now(UTC)` (örn. 07:22 UTC) alınmaktadır.
    4. Karşılaştırma yapılırken local time damgası naive olarak UTC'ye zorlanmakta (`replace(tzinfo=UTC)`), bu da sinyalin geçerlilik süresini yapay olarak 3 saat ileriye kaydırmaktadır (10:22 UTC olarak değerlendirilir). Bu uyuşmazlık nedeniyle sinyaller eskimemekte (expired olmamakta) ve bayat sinyaller saatler sonra bile tetiklenebilmektedir.
*   **Walk-Forward Ölçümü:** Zaman dilimi yönetimi tamamen UTC standardına çekildiğinde, bayat veriler üzerinden işlem açma hatası engellenecektir. Canlı testlerde **Execution Latency** ve **Stale Signal Losses** (bayat sinyal kayıpları) sıfırlanacaktır.

---

## 2. Öncelik Sıralı Fix Listesi

Aşağıdaki liste, hatalı sinyal üretim sıklığı ve finansal etki derecesine göre önceliklendirilmiştir:

| Öncelik | Hipotez | Başlık | Etki / Severity | Fix Türü | Öncelikli Fix Adımı |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **H11** | Zaman Dilimi & Eskime Hatası | **KRİTİK** | Kod Düzeltme | `timestamp` varsayılanını `datetime.now(UTC)` yap ve tüm kontrolleri timezone-aware UTC düzeyinde eşitle. |
| **2** | **H1** | Zıt Yönlü Bileşenlerin Toplanması | **KRİTİK** | Algoritmik | Karşıt-trend göstergeleri (RSI/Stoch/CCI) ile ana trend (EMA/SMA) çeliştiğinde skorları toplama; directional alignment gating uygula. |
| **3** | **H3** | Aşırı Uzama (Chase) Ödülü | **KRİTİK** | Algoritmik | Fiyat Bollinger üst bandı dışındayken veya dirence yakınken uzun yönlü sinyalleri sert filtreyle bloke et. |
| **4** | **H5** | Uyumsuz Güven (Confidence) | **KRİTİK** | Mantıksal | Sinyal güvenini skor büyüklüğüne göre değil, bileşen yön birliği oranına (agreement ratio) göre hesapla. |
| **5** | **H8** | Stop/Hedef & Tick Size Hatası | **KRİTİK** | Operasyonel | BIST fiyat adımlarına (tick size) göre yuvarlama ekle ve hedefleri ±10% günlük borsa limitine göre sınırla. |
| **6** | **H2** | Seviye Bazlı Trend Filtresi | **ORTA** | Matematiksel | EMA200 filtresini sadece fiyat seviyesine göre değil, EMA200 eğrisinin eğimine (slope) göre teyit edecek şekilde güncelle. |
| **7** | **H4** | Hacim Divergence Uyumsuzluğu | **ORTA** | Matematiksel | OBV ve fiyat-hacim divergence durumlarında ceza puanını artır veya uzun yönlü işlemleri sınırla. |
| **8** | **H10** | ADV / Spread Sınırlandırması | **ORTA** | Parametrik | `MIN_LIQUIDITY_VALUE_TL` varsayılan değerini sığ hisseleri eleyecek mantıklı bir baraja yükselt. |
| **9** | **H6** | MTF SMA/EMA Confluence | **ORTA** | Mantıksal | Üst zaman diliminde SMA ve EMA yönleri çeliştiğinde trend bias'ı nötr olarak işaretle. |
| **10** | **H7** | Skor Satürasyonu / Clamp | **ORTA** | Matematiksel | Skor birleşimini düz toplama yerine ağırlıklı ortalama modeline geçir. |
| **11** | **H9** | BIST100 Beta Arındırması | **DÜŞÜK** | İleri Analiz | Hisse skorlarını piyasa beta hareketlerinden arındırarak alpha-scoring modeline geçiş yap. |

---

## 3. Risk ve Fix Bağımlılık Matrisi

1.  **H1 (Zıt Yönlü Bileşenler) ve H5 (Confidence) Bağımlılığı:**
    *   *Açıklama:* H1 düzeltilip yön çelişkileri elenmeden H5 (yön uyum oranına göre güven) düzgün çalışamaz. Çünkü zıt yönlü bileşenlerin birbirini götürmediği bir yapıda yön uyumu her zaman yüksek veya belirsiz çıkacaktır. Sinyal yön uyumu filtresi (H1) en temel adımdır.
2.  **H2 (Trend Slope) ve H6 (MTF Confluence) Bağımlılığı:**
    *   *Açıklama:* H2'de tek zaman dilimli trend filtresi eğime (slope) duyarlı hale getirilmeden, H6'daki çoklu zaman dilimi confluence doğrulaması tam olarak güvenilir olamaz. Üst zaman diliminin trend bias'ı (bias yönü), trend çizgilerinin eğim yönü teyit edilmeden hesaplanmamalıdır.
3.  **H11 (Zaman Dilimi) ve Diğer Tüm Mantıksal Filtreler:**
    *   *Açıklama:* Zaman dilimi uyuşmazlığı (H11) giderilmeden yapılacak tüm algoritmik skor ve filtre iyileştirmeleri anlamsız kalacaktır; çünkü sistem bayat/gecikmeli veriler üzerinden sinyal üretmeye devam edecektir. Bu nedenle H11 birinci öncelikli teknik önkoşuldur.
