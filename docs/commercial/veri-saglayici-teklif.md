# Veri sağlayıcı teklif talebi (taslak)

> Bu dosyayı sağlayıcıya göndermeden önce şirket bilgileri, kullanıcı tahmini ve
> bütçe aralığı alanlarını doldurun. Metin, alt dağıtıcılık kapsamını netleştirmek
> için hazırlandı; hukuki taahhüt içermez.

**Konu:** BIST gün sonu verisi ve türetilmiş analizler için alt dağıtıcılık teklifi

Sayın [Sağlayıcı] Yetkilisi,

[Şirket adı] olarak Borsa İstanbul paylarına yönelik bir **analiz ve tarama
uygulaması** geliştiriyoruz. Uygulama yatırım tavsiyesi vermez; kullanıcı kendi
taramasını kurar, gün sonu verilerini ve temel oranları görür, kendi portföyünü
takip eder.

Aşağıdaki kapsam için alt dağıtıcılık ve veri kullanım teklifinizi rica ediyoruz.

## 1. Talep edilen veri

| Veri | Kapsam | Sıklık |
|---|---|---|
| Pay günlük OHLCV | Tüm BIST payları (~630 sembol) | Her işlem günü, kapanış sonrası |
| Düzeltilmiş kapanış | Bedelsiz, bölünme ve temettü düzeltmeli | Günlük |
| Endeks | XU100 (mümkünse XU030 ve sektör endeksleri) | Günlük |
| Temel veriler | Çeyreklik bilanço kalemleri (satış, net kâr, özkaynak) | Çeyreklik |
| Kurumsal işlemler | Bedelsiz/bölünme/temettü takvimi | Olay bazlı |

- Geçmiş derinliği: **2016-01-01**'den itibaren.
- Açılış fiyatı kaynakta yoksa bunu belirtin; mum grafiği yerine çizgi grafik
  kullanıyoruz.
- Veri saat dilimi ve kapanış saati (TR) açıkça yazılmalı.

## 2. Kullanım şekli

- Veriler **web uygulamasında** abonelere gösterilecek (grafik, tarama sonuçları,
  temel oranlar, kişisel portföy karşılaştırması).
- Veriden **türetilmiş** göstergeler üretiyoruz: hareketli ortalamalar, RSI,
  hacim oranı, F/K, PD/DD, tarama eşleşmeleri.
- Veriler toplu olarak indirilebilir dosya olarak sunulmayacak; kullanıcı başına
  ekran erişimi olacak.
- Veri, üçüncü taraflara yeniden satılmayacak.

## 3. Lisans kapsamı soruları

1. Bu kullanım için **alt dağıtıcı** sözleşmesi yeterli mi, yoksa BIST ile
   doğrudan Veri Dağıtım Sözleşmesi mi gerekir?
2. Türetilmiş analizlerin (tarama sonucu, oran, alarm) gösterimi lisans kapsamında
   mı? Ek ürün lisansı gerekiyor mu?
3. Ücretlendirme **kullanıcı sayısına** mı, **siteye** mi, **cihaza** mı bağlı?
   Basamaklar ve KDV durumu nedir?
4. Gecikmeli/gün sonu veri ile eş anlı veri arasındaki ücret farkı nedir?
5. Kaynak atfı nasıl olmalı? (Örn. "Veri: [Sağlayıcı], gün sonu.")
6. Lisans sona ererse verinin arşivlenmesi ve kullanıcıya gösteriminin durdurulması
   için öngörülen süre nedir?

## 4. Teknik beklentiler

- Teslim yöntemi: REST/JSON veya SFTP/CSV. Kimlik doğrulama yöntemi.
- Günlük teslim saati: **18:30 TR**'den önce (tarama ve akşam özeti için).
- Hız limiti, istek kotası ve yeniden deneme politikası.
- Hata/kesinti bildirimi ve SLA.
- Test ortamı veya örnek veri seti.
- Sembol listesi ve sembol değişikliklerinin (kod değişimi, işlem sırası kapanması)
  bildirim yöntemi.

## 5. Ticari beklentiler

- Aylık/yıllık sabit ücret ve kullanıcı başı değişken ücret ayrımı.
- Kurulum/teknik bağlantı bedeli var mı?
- Sözleşme süresi, fesih bildirim süresi, fiyat artış kuralı.
- Pilot dönem (1-3 ay) ve iptal koşulları.
- Ödeme para birimi ve fatura düzeni.

## 6. Şirket bilgileri

- Ticari unvan: [ ]
- Vergi dairesi / VKN: [ ]
- Adres: [ ]
- Yetkili: [ ]
- Tahmini ilk yıl kullanıcı sayısı: [ ]
- Uygulama adresi: [ ]

Saygılarımızla,
[Ad Soyad]
[E-posta] · [Telefon]
