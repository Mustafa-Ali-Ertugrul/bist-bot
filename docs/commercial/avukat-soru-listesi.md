# Avukat görüşü için soru listesi (taslak)

> Amaç: satış açmadan önce ürünün SPK, KVKK ve tüketici hukuku açısından
> konumunu yazılı olarak netleştirmek. Metin hukuki görüş değildir.

## Ürünün tanımı (avukata verilecek özet)

Bist-Bot, Borsa İstanbul payları için **gün sonu** verilerle çalışan bir analiz
aracıdır:

- Hazır taramalar (RSI dip, ortalama kesişimi, hacim şoku, 52 hafta zirvesi vb.)
  ve kullanıcının kendi kurduğu filtreler
- Hisse sayfası: grafik, temel oranlar, çeyreklik tablo
- İzleme listesi ve elle girilen portföyün XU100 ve para piyasasıyla kıyası
- Kullanıcının seçtiği alarmlar ve günde bir kez gönderilen akşam özeti
- **Yapılmayanlar:** emir iletimi, aracı kurum hesabına erişim, otomatik alım-satım,
  kişiye özel al/sat tavsiyesi, hedef fiyat veya stop seviyesi yayınlama.

Eski sürümde al/sat sinyali ve stop/hedef içeren mesajlar vardı; **kaldırıldı**.
Müşteri grubuna sinyal gönderimi kod seviyesinde devre dışı.

## A. SPK / yatırım hizmetleri

1. Tarama sonuçları, temel oranlar ve alarmlar SPKn m.37 kapsamında **yatırım
   danışmanlığı** sayılır mı? Hangi özellik sınırı aşar?
2. Ücretli abonelik bu değerlendirmeyi değiştirir mi?
3. Kullanıcının kendi filtresini kurması ve kendi portföyünü girmesi, ürünü
   "araç" konumuna taşır mı?
4. "RSI 30'un altında", "52 hafta zirvesi" gibi kural açıklamaları ve tarama
   adları tavsiye niteliğinde sayılır mı? Hangi ifadelerden kaçınmalıyız?
5. Portföy takibi (kullanıcının kendi işlemleri) portföy yöneticiliği kapsamına
   girer mi? Kesin sınır nedir?
6. Sayfalardaki "yatırım tavsiyesi değildir" uyarısı yeterli mi; metin nasıl
   olmalı? Her mesaja eklenmeli mi?
7. Ürünü SPK izni almadan satmanın pratik yolu nedir: araç konumlandırması,
   ücretsiz sunum, lisanslı bir kurumla ortaklık veya başka bir model?
8. Veri sağlayıcının sözleşmesindeki "türetilmiş veri" kısıtı SPK
   değerlendirmesini etkiler mi?

## B. Borsa İstanbul veri lisansı

1. Gün sonu verinin web uygulamasında abonelere gösterimi için alt dağıtıcı
   sözleşmesi yeterli mi?
2. Türetilmiş analizler için ayrı ürün lisansı gerekir mi?
3. Kullanıcı başına mı, site başına mı lisans alınmalı?
4. Lisans sona erdiğinde arşivdeki veri ne kadar süre tutulabilir?
5. Kaynak atfı zorunlu mu; metni nasıl olmalı?

## C. KVKK

1. Veri sorumlusu kimdir; yurt dışındaki barındırma/ödeme sağlayıcıları için
   hangi aktarım mekanizması gerekir?
2. VERBİS kaydı bu ölçekte gerekli mi; eşik nedir?
3. Telegram sohbet kimliği ve portföy işlemleri "özel nitelikli" sayılır mı?
4. Aydınlatma metni ve açık rıza ayrımı doğru mu kurgulanmış? Pazarlama
   iletileri için İYS kaydı gerekir mi?
5. Hesap silme akışı (kişisel tablolar silinir, denetim kayıtları anonim kalır)
   yeterli mi? Fatura kayıtlarının saklanması nasıl olmalı?
6. Veri ihlali bildirim süreci ve kayıt yükümlülüğü nedir?

## D. Tüketici ve e-ticaret

1. Mesafeli satış sözleşmesi ve ön bilgilendirme formu yeterli mi?
2. Dijital hizmette cayma hakkı istisnası nasıl uygulanır; kullanıcıya hangi
   onayı aldırmalıyız?
3. Abonelik yenileme, iptal ve iade kuralları nasıl yazılmalı?
4. e-Arşiv fatura yükümlülüğü ve fatura üzerinde yer alması gereken bilgiler?
5. Ücretsiz katman ve deneme süresi için ek koşul gerekir mi?

## E. Sorumluluk ve metinler

1. Kullanım koşullarındaki sorumluluk sınırı (son 12 ay abonelik bedeli)
   geçerli mi? Tüketiciye karşı sınırlandırılabilir mi?
2. Veri hatası, gecikme ve kesinti için sorumluluk reddi nasıl yazılmalı?
3. Metinlerin son hali için hangi belgeleri istersiniz?

## Ekler

- `/legal/kullanim-kosullari`, `/legal/gizlilik`, `/legal/kvkk-aydinlatma`,
  `/legal/mesafeli-satis` taslakları
- Örnek akşam özeti mesajı
- Tarayıcı ve hisse sayfası ekran görüntüleri
- Veri sağlayıcı teklif yazışması

## Beklenen çıktı

- Ürünün SPK kapsamı dışında kalıp kalmadığına dair **yazılı görüş**
- Satış öncesi düzeltilmesi gereken özellik ve metinlerin listesi
- KVKK ve tüketici metinlerinin onaylı son hali
- Gerekliyse alternatif iş modeli önerisi (ücretsiz araç, lisanslı ortaklık vb.)
