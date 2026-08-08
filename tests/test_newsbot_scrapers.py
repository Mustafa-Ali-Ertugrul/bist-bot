"""Haber scraper ve dedup testleri."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from bist_bot.newsbot.scrapers.bloomberght import BloombergHtScraper
from bist_bot.newsbot.scrapers.foreks import ForeksScraper
from bist_bot.newsbot.scrapers.kap import KapScraper
from bist_bot.newsbot.utils import canonicalize_url, generate_content_hash, parse_rss_date

MOCK_HTML = """
<html><body>
  <a href="/tr/Haber/123/THY-Yeni-Ucak">THY filosunu genişletiyor, yeni uçak siparişi verdi</a>
  <a href="/tr/Haber/124/Aselsan-Sozlesme">ASELSAN yeni sözleşme imzaladı</a>
  <a href="/tr/">Ana Sayfa</a>
</body></html>
"""

MOCK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item>
    <title><![CDATA[Koç Holding net kâr elde etti]]></title>
    <link>https://www.foreks.com/haber/detay/koc-holding-net-kar-elde-etti</link>
    <description><![CDATA[<p>Koç Holding ikinci çeyrekte <b>19,7 milyar TL</b> net kâr açıkladı.</p>]]></description>
    <pubDate>Sat, 08 Aug 2026 06:48:10 +0000</pubDate>
  </item>
  <item>
    <title>Aselsan Yeni Sözleşme İmzaladı</title>
    <link>/haber/detay/aselsan-sozlesme</link>
    <pubDate>2026-08-08T06:45:00+03:00</pubDate>
  </item>
  <item>
    <title>Başlıksız</title>
  </item>
</channel></rss>
"""


def test_kap_scraper_parsing():
    """HTML fallback path'i mock ile doğrular."""
    scraper = KapScraper({"name": "kap", "url": "https://www.kap.org.tr", "interval_seconds": 60})

    with (
        patch("bist_bot.newsbot.scrapers.kap._http.post", side_effect=Exception("API Timeout")),
        patch("bist_bot.newsbot.scrapers.kap._http.get") as mock_get,
    ):
        mock_response = MagicMock()
        mock_response.text = MOCK_HTML
        mock_get.return_value = mock_response

        articles = scraper.fetch_articles()

        assert len(articles) == 2
        assert "THY" in articles[0]["title"]
        assert articles[0]["url"].startswith("https://www.kap.org.tr")
        assert articles[1]["title"] == "ASELSAN yeni sözleşme imzaladı"


def test_kap_json_api_success_with_curl_cffi():
    """curl_cffi mevcutken JSON API parse edilir; impersonate gönderilir."""
    scraper = KapScraper({"name": "kap", "url": "https://www.kap.org.tr", "interval_seconds": 60})

    with patch("bist_bot.newsbot.scrapers.kap._http.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '[{"id": "123", "title": "THY Kâr", "content": "Detay"}]'
        mock_response.json.return_value = [{"id": "123", "title": "THY Kâr", "content": "Detay"}]
        mock_post.return_value = mock_response

        articles = scraper.fetch_articles()
        assert len(articles) == 1
        assert articles[0]["title"] == "THY Kâr"
        assert articles[0]["url"] == "https://www.kap.org.tr/tr/BildirimDetay/123"

        from bist_bot.newsbot.scrapers.kap import _HAS_CURL_CFFI

        if _HAS_CURL_CFFI:
            assert mock_post.call_args.kwargs.get("impersonate") == "chrome110"


def test_content_hash_dedup():
    """Aynı içerik aynı hash'i üretir; farklı URL farklı hash üretir."""
    hash1 = generate_content_hash("url1", "title1", "content1")
    hash2 = generate_content_hash("url1", "title1", "content1")
    hash3 = generate_content_hash("url2", "title1", "content1")

    assert hash1 == hash2
    assert hash1 != hash3


def test_rss_scraper_parsing():
    """RSS feed'i doğru parse eder: CDATA, göreceli link, tarih."""
    scraper = ForeksScraper(
        {"name": "foreks", "url": "https://www.foreks.com", "interval_seconds": 90}
    )

    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = MOCK_RSS
        mock_response.content = MOCK_RSS.encode("utf-8")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        articles = scraper.fetch_articles()

    assert len(articles) == 2
    assert articles[0]["title"] == "Koç Holding net kâr elde etti"
    assert articles[0]["content"].startswith("Koç Holding ikinci çeyrekte")
    assert articles[0]["published_at"] == datetime(2026, 8, 8, 6, 48, 10)
    assert articles[1]["url"].startswith("https://www.foreks.com")


def test_rss_scraper_handles_fetch_error():
    """Ağ hatasında boş liste döner, exception fırlatmaz."""
    scraper = BloombergHtScraper(
        {"name": "bloomberght", "url": "https://www.bloomberght.com", "interval_seconds": 120}
    )

    with patch("requests.get", side_effect=Exception("timeout")):
        assert scraper.fetch_articles() == []


def test_canonicalize_url_strips_tracking():
    """utm_* ve fbclid parametreleri atılır; fragment temizlenir; gerçek parametre kalmaz."""
    url1 = "https://site.com/haber?utm_source=twitter&id=123&fbclid=abc#yorumlar"
    url2 = "https://site.com/haber?id=123"

    c1 = canonicalize_url(url1)
    c2 = canonicalize_url(url2)

    assert c1 == c2
    assert "utm_source" not in c1
    assert "fbclid" not in c1
    assert "#" not in c1
    assert canonicalize_url("") == ""


def test_parse_rss_date_with_dateutil():
    """RFC 2822 ve ISO formatları UTC'ye çevrilir; naive UTC döner."""
    dt1 = parse_rss_date("Tue, 10 Aug 2026 14:00:00 GMT")
    assert dt1 == datetime(2026, 8, 10, 14, 0, 0)
    assert dt1.tzinfo is None

    dt2 = parse_rss_date("2026-08-10T14:00:00+03:00")
    assert dt2 == datetime(2026, 8, 10, 11, 0, 0)

    dt3 = parse_rss_date("2026-08-08 06:02:54")
    assert dt3 == datetime(2026, 8, 8, 6, 2, 54)

    assert parse_rss_date("gecersiz-tarih") is None
    assert parse_rss_date(None) is None
