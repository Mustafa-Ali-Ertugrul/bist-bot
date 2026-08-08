"""KAP (Kamuyu Aydınlatma Platformu) scraper'ı."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup

from bist_bot.newsbot.utils import clean_text

from .base import BaseScraper

try:
    from curl_cffi import requests as _http

    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover - curl_cffi requirements.txt'te garantili
    import requests as _http

    _HAS_CURL_CFFI = False


class KapScraper(BaseScraper):
    """KAP'tan haber/bildirim çeken scraper.

    Önce JSON API ('memberDisclosureQuery') denenir. curl_cffi Chrome TLS
    fingerprint'i taklit ederek WAF engelini aşar; API çökerse ana sayfa
    HTML'den linkler toplanır.
    """

    API_URL = "https://www.kap.org.tr/tr/api/memberDisclosureQuery"
    FALLBACK_URL = "https://www.kap.org.tr/tr/"
    MAX_ITEMS = 50

    def fetch_articles(self) -> list[dict[str, Any]]:
        # 1) JSON API dene — curl_cffi impersonation ile (WAF bypass), ilk hata sonrası 1 retry
        for attempt in range(2):
            try:
                payload = {
                    "fromDate": (datetime.now(UTC) - timedelta(days=1)).strftime("%d.%m.%Y"),
                    "toDate": datetime.now(UTC).strftime("%d.%m.%Y"),
                    "member": "",
                    "disclosureClass": "",
                    "index": "",
                    "market": "",
                    "isLate": "",
                }
                kwargs: dict[str, Any] = {"data": payload, "headers": self.headers, "timeout": 15}
                if _HAS_CURL_CFFI:
                    kwargs["impersonate"] = "chrome110"

                res = _http.post(self.API_URL, **kwargs)

                if res.status_code == 200 and res.text.strip().startswith("["):
                    data = res.json()
                    articles: list[dict[str, Any]] = []
                    for item in data[: self.MAX_ITEMS]:
                        item_id = item.get("id") or item.get("bidirimId") or item.get("notificationId")
                        title = clean_text(item.get("title") or item.get("baslik") or "")
                        content = clean_text(item.get("content") or item.get("icerik") or title)

                        if not item_id or not title:
                            continue

                        articles.append(
                            {
                                "url": f"https://www.kap.org.tr/tr/BildirimDetay/{item_id}",
                                "title": title,
                                "content": content,
                                "published_at": datetime.now(UTC),
                            }
                        )
                    if articles:
                        self.logger.info("kap_json_success", count=len(articles), attempt=attempt)
                        return articles
            except Exception as exc:
                self.logger.warning("kap_json_failed", error=str(exc), attempt=attempt)

            if attempt == 0:
                time.sleep(2)

        # 2) HTML fallback — ana sayfadaki makul linkleri topla
        return self._html_fallback()

    def _html_fallback(self) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        try:
            kwargs: dict[str, Any] = {"headers": self.headers, "timeout": 15}
            if _HAS_CURL_CFFI:
                kwargs["impersonate"] = "chrome110"

            res = _http.get(self.FALLBACK_URL, **kwargs)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                title = clean_text(a.get_text())
                if len(title) < 10 or "javascript" in href or href in ("/tr/", "/tr"):
                    continue
                if not href.startswith("http"):
                    href = f"https://www.kap.org.tr{href}"
                articles.append(
                    {
                        "url": href,
                        "title": title,
                        "content": title,
                        "published_at": datetime.now(UTC),
                    }
                )
                if len(articles) >= 20:
                    break
            if not articles:
                self.logger.warning("kap_zero_articles")
        except Exception as exc:
            self.logger.error("kap_html_fallback_failed", error=str(exc))
        return articles
