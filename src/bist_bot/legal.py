"""Faz 7: legal documents served by the app.

The texts below are DRAFTS. They must be reviewed by a capital-markets lawyer
before sales open; ``LEGAL_TEXTS_DRAFT`` keeps a visible banner until then.
"""

from __future__ import annotations

from dataclasses import dataclass

DRAFT_NOTICE = (
    "TASLAK: Bu metin satış açılmadan önce sermaye piyasası avukatı tarafından incelenmelidir."
)


@dataclass(frozen=True)
class LegalDocument:
    slug: str
    title: str
    version: str
    body: str


_DISCLAIMER = (
    "<p><strong>Bist-Bot bir analiz aracıdır.</strong> Sitede yer alan taramalar, "
    "oranlar, grafikler ve alarmlar bilgilendirme amaçlıdır; yatırım danışmanlığı, "
    "alım-satım tavsiyesi veya portföy yöneticiliği niteliği taşımaz. Yatırım "
    "kararları ve sonuçları kullanıcıya aittir.</p>"
)

DOCUMENTS: dict[str, LegalDocument] = {
    "kullanim-kosullari": LegalDocument(
        slug="kullanim-kosullari",
        title="Kullanım Koşulları",
        version="2026-10-22-draft",
        body=f"""
<h2>1. Hizmetin kapsamı</h2>
<p>Bist-Bot; Borsa İstanbul paylarına ilişkin gün sonu verileri, tarama sonuçları,
temel oranlar, kişisel izleme listeleri, portföy takibi ve bildirimler sunan bir
yazılım hizmetidir. Hizmet bir yatırım danışmanlığı sözleşmesi değildir.</p>
{_DISCLAIMER}
<h2>2. Hesap</h2>
<p>Kullanıcı doğru bilgi vermekle, hesabını ve şifresini korumakla yükümlüdür.
Hesap paylaşılamaz. Şüpheli erişimde hesap geçici olarak kısıtlanabilir.</p>
<h2>3. Veri ve gecikme</h2>
<p>Veriler gün sonu olarak ve gecikmeli sunulabilir. Veri sağlayıcıdan kaynaklanan
kesinti, hata veya gecikmelerden dolayı oluşan sonuçlardan hizmet sağlayıcı sorumlu
tutulamaz. Verilerin doğruluğu resmi kaynaklardan teyit edilmelidir.</p>
<h2>4. Kabul edilmeyen kullanım</h2>
<p>Verilerin toplu kopyalanması, yeniden satışı, otomatik kazınması ve üçüncü
kişilere dağıtılması yasaktır. Bu tür kullanım hesabın kapatılmasına yol açar.</p>
<h2>5. Ücretlendirme</h2>
<p>Ücretli paketlerin kapsamı ve bedeli satış sayfasında gösterilir. Abonelik,
dönem sonunda kullanıcı iptal etmedikçe yenilenir. Mevcut dönem için yapılan
ödemeler, aksi yazılı olarak belirtilmedikçe iade edilmez.</p>
<h2>6. Sorumluluğun sınırı</h2>
<p>Hizmet "olduğu gibi" sunulur. Dolaylı zararlar, kâr kaybı ve veri kaybı dahil
olmak üzere hizmetten doğan zararlarda sorumluluk, son on iki ayda ödenen abonelik
bedeliyle sınırlıdır.</p>
<h2>7. Değişiklikler ve fesih</h2>
<p>Koşullar güncellenebilir; önemli değişiklikler e-posta veya uygulama içi bildirimle
duyurulur. Kullanıcı hesabını dilediği zaman silebilir.</p>
<h2>8. Uygulanacak hukuk</h2>
<p>Türkiye Cumhuriyeti hukuku uygulanır; İstanbul mahkemeleri yetkilidir.</p>
""",
    ),
    "gizlilik": LegalDocument(
        slug="gizlilik",
        title="Gizlilik ve Çerez Politikası",
        version="2026-10-22-draft",
        body="""
<h2>1. Hangi veriler işlenir</h2>
<ul>
<li>Hesap: e-posta, şifre özeti, plan ve abonelik tarihleri.</li>
<li>Ürün verisi: izleme listeleri, portföy işlemleri, alarmlar, kayıtlı filtreler.</li>
<li>Telegram: yalnızca kullanıcı bağladığında sohbet kimliği ve kullanıcı adı.</li>
<li>Teknik: oturum kayıtları, hata kayıtları, güvenlik denetim kayıtları.</li>
</ul>
<h2>2. Amaç ve hukuki sebep</h2>
<p>Veriler hizmetin sunulması, güvenliğin sağlanması ve yasal yükümlülüklerin yerine
getirilmesi amacıyla; sözleşmenin ifası ve meşru menfaat hukuki sebeplerine dayanarak
işlenir. Pazarlama iletileri yalnızca açık rıza ile gönderilir.</p>
<h2>3. Paylaşım</h2>
<p>Veriler barındırma, ödeme ve mesajlaşma hizmeti sağlayan işleyicilerle, hizmetin
gerektirdiği ölçüde paylaşılır. Yasal talep halinde yetkili kurumlarla paylaşılabilir.
Veriler reklam amacıyla satılmaz.</p>
<h2>4. Saklama süresi</h2>
<p>Hesap verileri hesap açık kaldığı sürece, fatura ve muhasebe kayıtları yasal süre
boyunca saklanır. Hesap silindiğinde kişisel tablolar ve Telegram bağı silinir;
denetim kayıtları anonimleştirilerek tutulabilir.</p>
<h2>5. Haklar</h2>
<p>Kullanıcı verilerine erişme, düzeltme, silme ve taşıma haklarına sahiptir.
Uygulamadaki "Verilerimi indir" ve "Hesabımı sil" işlevleri bu hakları kullanmayı
sağlar.</p>
<h2>6. Çerezler</h2>
<p>Yalnızca oturumun sürdürülmesi için zorunlu, HttpOnly çerez kullanılır. Reklam
veya izleme çerezi kullanılmaz.</p>
""",
    ),
    "kvkk-aydinlatma": LegalDocument(
        slug="kvkk-aydinlatma",
        title="KVKK Aydınlatma Metni",
        version="2026-10-22-draft",
        body="""
<p>6698 sayılı Kişisel Verilerin Korunması Kanunu uyarınca veri sorumlusu Bist-Bot
işletmecisidir.</p>
<h2>İşlenen veriler ve amaçlar</h2>
<ul>
<li>Kimlik ve iletişim (e-posta): hesap oluşturma, oturum, bilgilendirme.</li>
<li>Müşteri işlem verisi (portföy, izleme listesi, alarm): hizmetin sunulması.</li>
<li>Telegram sohbet kimliği: yalnızca kullanıcının talebiyle bildirim gönderimi.</li>
<li>İşlem güvenliği kayıtları: yetkisiz erişimin önlenmesi.</li>
</ul>
<h2>Aktarım</h2>
<p>Veriler; barındırma, ödeme ve mesajlaşma altyapısı sağlayıcılarına hizmetin
gerektirdiği ölçüde aktarılır. Yurt dışına aktarım varsa KVKK'nın ilgili hükümlerine
uygun mekanizma kullanılır.</p>
<h2>Haklar</h2>
<p>Kanunun 11. maddesi kapsamında bilgi talep etme, düzeltme, silme, işlemeye itiraz
etme ve zararın giderilmesini talep etme haklarınız vardır. Başvurular için iletişim
adresi satış sayfasında yayımlanır.</p>
""",
    ),
    "mesafeli-satis": LegalDocument(
        slug="mesafeli-satis",
        title="Mesafeli Satış Sözleşmesi",
        version="2026-10-22-draft",
        body=f"""
<h2>1. Taraflar</h2>
<p>Satıcı: Bist-Bot işletmecisi. Alıcı: sipariş sırasında bilgilerini giren kullanıcı.</p>
<h2>2. Konu</h2>
<p>Elektronik ortamda sunulan yazılım aboneliğinin satışı ve ifası bu sözleşmenin
konusudur. Hizmet kapsamı satış sayfasında ve kullanım koşullarında belirtilir.</p>
<h2>3. Bedel ve ödeme</h2>
<p>Bedel, seçilen paket için satış sayfasında gösterilen tutardır. Ödeme kartla,
yetkili ödeme kuruluşu üzerinden alınır. Fatura, mevzuata uygun şekilde düzenlenir.</p>
<h2>4. İfa</h2>
<p>Hizmet, ödemenin onaylanmasının ardından dijital olarak sunulur. Ayrı bir fiziki
teslimat yoktur.</p>
<h2>5. Cayma hakkı</h2>
<p>Mesafeli Sözleşmeler Yönetmeliği'nin 15/1-(ğ) maddesi uyarınca, elektronik ortamda
anında ifa edilen hizmetlerde cayma hakkı kullanılamaz. Kullanıcı, hizmeti satın
almadan önce bu hususta bilgilendirildiğini kabul eder.</p>
{_DISCLAIMER}
<h2>6. Uyuşmazlık</h2>
<p>Tüketici hakem heyetleri ve tüketici mahkemeleri yetkilidir.</p>
""",
    ),
}


def get_document(slug: str) -> LegalDocument | None:
    return DOCUMENTS.get(slug)


def document_list() -> list[dict[str, str]]:
    return [
        {"slug": doc.slug, "title": doc.title, "version": doc.version} for doc in DOCUMENTS.values()
    ]


__all__ = ["DOCUMENTS", "DRAFT_NOTICE", "LegalDocument", "document_list", "get_document"]
