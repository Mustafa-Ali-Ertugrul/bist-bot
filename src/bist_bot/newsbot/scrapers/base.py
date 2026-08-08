"""Haber scraper'ları için soyut base sınıf."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from bist_bot.app_logging import get_logger


class BaseScraper(ABC):
    """Tüm haber kaynakları bu sınıftan miras alır."""

    def __init__(self, source_config: dict) -> None:
        self.config = source_config
        self.name = source_config["name"]
        self.url = source_config["url"]
        self.interval_seconds = source_config.get("interval_seconds", 120)
        self.headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) BIST-NewsBot/1.0 (Research)")
        }
        self.logger = get_logger(self.name, component="newsbot.scraper")

    @abstractmethod
    def fetch_articles(self) -> list[dict[str, Any]]:
        """
        Kaynaktan ham veriyi çeker ve standart formatta döndürür.

        Return:
            [{"url": "...", "title": "...", "content": "...",
              "published_at": datetime | None}, ...]
        """


class RssScraper(BaseScraper):
    """RSS/Atom feed'lerinden haber çeken ortak scraper.

    Alt sınıflar sadece `RSS_URL` verir. Göreceli linkler otomatik
    tamamlanır, tarih RFC 2822 / ISO formatlarını `parse_rss_date` ile
    UTC'ye çevirir.
    """

    RSS_URL: str = ""
    MAX_ITEMS: int = 30

    def fetch_articles(self) -> list[dict[str, Any]]:
        import xml.etree.ElementTree as ET

        import requests

        from bist_bot.newsbot.utils import clean_text, parse_rss_date

        try:
            res = requests.get(self.RSS_URL, headers=self.headers, timeout=15)
            res.raise_for_status()
        except Exception as exc:
            self.logger.error("rss_fetch_failed", url=self.RSS_URL, error=str(exc))
            return []

        try:
            root = ET.fromstring(res.content)
        except ET.ParseError as exc:
            self.logger.error("rss_parse_failed", url=self.RSS_URL, error=str(exc))
            return []

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        def children_by_local(element, name: str) -> list:
            return [c for c in element if local_name(c.tag) == name]

        def text_of(element) -> str:
            if element is None or element.text is None:
                return ""
            return element.text

        items = [el for el in root.iter() if local_name(el.tag) in ("item", "entry")]

        articles: list[dict[str, Any]] = []
        for item in items[: self.MAX_ITEMS]:
            title_el = children_by_local(item, "title")
            title = clean_text(text_of(title_el[0]) if title_el else "")

            link_el = children_by_local(item, "link")
            link = ""
            if link_el:
                link = link_el[0].get("href") or text_of(link_el[0])
            if not title or not link:
                continue

            content = title
            for content_tag in ("description", "encoded"):
                desc_el = children_by_local(item, content_tag)
                if desc_el and text_of(desc_el[0]).strip():
                    content = clean_text(text_of(desc_el[0]))
                    break

            if link.startswith("/"):
                from urllib.parse import urljoin

                link = urljoin(self.url, link)

            pub = None
            for pub_tag in ("pubDate", "date", "updated"):
                pub_el = children_by_local(item, pub_tag)
                if pub_el:
                    pub = text_of(pub_el[0])
                    break

            articles.append(
                {
                    "url": link,
                    "title": title,
                    "content": content,
                    "published_at": parse_rss_date(pub),
                }
            )

        self.logger.info("rss_ok", source=self.name, count=len(articles))
        return articles
