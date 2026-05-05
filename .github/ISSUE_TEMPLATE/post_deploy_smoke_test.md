---
name: Post-Deploy Smoke Test
title: "Post-deploy smoke test – <tarih>"
labels: ["deploy", "smoke-test", "manual-check"]
assignees: []
---

## Deploy bilgisi

- **Commit SHA:**
- **Deploy tarihi:**
- **API URL:**
- **UI URL:**

---

## 1) Dashboard ve Scan Detail tutarliliği

- [ ] Uygulamaya giriş yapildi
- [ ] Bir scan çalistirildi
- [ ] Dashboard'daki `Taranan varlik` sayisi not alindi
- [ ] Scan Detail sayfasina geçildi
- [ ] `Scanned` degeri ile karşilaştirildi
- [ ] **Beklenen:** iki sayi ayni (`kesin`)

## 2) Invariant check doğrulamasi

- [ ] Scan Detail sayfasinda invariant göstergesi kontrol edildi
- [ ] `accounted / total` değerine bakildi
- [ ] Başarili durumda `✓` ve `accounted == total`
- [ ] Eğer `✗` varsa hangi outcome'un eksik sayildiği not alindi

## 3) Empty-state davranişi

- [ ] Scan tamamlandiktan sonra Dashboard'a dönüldü
- [ ] `Veri henüz hazir değil` görünmemeli
- [ ] Actionable signal `0` olsa bile scan özeti görünmeli
- [ ] Hatali durum: scan var ama dashboard boş ekran veriyor mu? **Hayir**

## 4) Outcome accounting kontrolü

- [ ] Dashboard rejection breakdown bölümü kontrol edildi
- [ ] Generated / rejected accounting görünüyor
- [ ] Hiçbir ticker sessizce kaybolmamiş
- [ ] Özellikle şu durumlar gözlemlendi:
  - [ ] `hold_neutral_zone`
  - [ ] `confluence_failed`
  - [ ] `insufficient_data`
  - [ ] Timeout / error varsa onlar da görünüyor

## 5) Sayfa geçişlerinde veri stabilitesi

- [ ] Dashboard → Scan Detail → Dashboard geçişi yapildi
- [ ] Sayfa yenilendi
- [ ] Yeniden giriş yapilip tekrar kontrol edildi
- [ ] **Beklenen:** sayaçlar değişip bozulmamali, cache yüzünden eski veri görünmemeli

## 6) Sinyal olmayan scan testi

- [ ] Hiç actionable signal üretmeyen bir scan senaryosu çaliştirildi
- [ ] Dashboard yine scan count gösteriyor
- [ ] “veri yok” değil, “0 signal” mantigiyla davraniyor
- [ ] Scan Detail'de rejection / outcome toplami kapaniyor

## 7) Karisik outcome testi

- [ ] Mümkünse şu karisimi içeren bir scan çaliştirildi:
  - Bazı ticker’lar rejected
  - Bazilari hold / watch
  - Bazilari insufficient data
- [ ] **Beklenen:** hepsi bir outcome bucket’ina düşmeli, toplam sayilar kapanmali

## 8) Analysis sayfasi regresyon testi

- [ ] Analysis sayfasina girildi
- [ ] Sayfa açilmali
- [ ] Plotly grafikler render olmali
- [ ] Eski `yaxis` hatasi görünmemeli

## 9) Son akis / son sinyaller bölümü

- [ ] Dashboard'daki `Son Akis` veya kayitli sinyal alani kontrol edildi
- [ ] Veri varsa doğru doluyor
- [ ] Veri yoksa misleading değil net empty state gösteriyor

## 10) Görsel / UX kontrolü

- [ ] Gereksiz `Logout` başliği sizmayor
- [ ] Nav tekrarlari yok
- [ ] Boş alanlar anlamsiz büyük değil
- [ ] Metrik kartlari birbiriyle çelişmiyor

---

## Pass / Fail

| Kriter | Durum |
|--------|-------|
| Dashboard ve Scan Detail ayni scan sayisini gösteriyor | ☐ Pass ☐ Fail |
| Invariant check `✓` | ☐ Pass ☐ Fail |
| Empty-state yanliş tetiklenmiyor | ☐ Pass ☐ Fail |
| Outcome’lar eksiksiz sayiliyor | ☐ Pass ☐ Fail |
| Refresh / page transition sonrasi veri bozulmuyor | ☐ Pass ☐ Fail |
| Analysis sayfasi patlamiyor | ☐ Pass ☐ Fail |

**Genel sonuç:** ☐ PASS ☐ FAIL

---

## Notlar / Gözlemler

<!-- Deploy sirasinda fark edilen ek ayrintilar, hatalar veya şüpheli davranişlar buraya yazilir. -->
