"""Faz A: KAP disclosures, corporate actions and their API surface."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask
from flask.testing import FlaskClient

from bist_bot.config.settings import settings
from bist_bot.dashboard import create_dashboard_app
from bist_bot.data.isyatirim import _tr_date, _tr_number, parse_corporate_action_rows
from bist_bot.data.kap import KapDisclosure, parse_disclosures, parse_publish_date
from bist_bot.db import DataAccess, DatabaseManager
from bist_bot.db.repositories.market_data_repository import (
    DailyBar,
    Instrument,
    MarketDataRepository,
)
from bist_bot.services.corporate_actions_service import CorporateActionsService
from bist_bot.services.kap_service import KapService, TickerMatcher, normalize_company_name
from bist_bot.services.stock_profile_service import snapshot_row
from bist_bot.strategy.scans import FundamentalContext, scan_dividend_yield

# ---------------------------------------------------------------------------
# KAP parsing
# ---------------------------------------------------------------------------


def test_publish_date_is_converted_from_istanbul_to_utc() -> None:
    parsed = parse_publish_date("23.10.2026 22:20:42")
    assert parsed == datetime(2026, 10, 23, 19, 20, 42)
    assert parsed.tzinfo is None


def test_publish_date_rejects_garbage() -> None:
    assert parse_publish_date("2026-10-23") is None
    assert parse_publish_date(None) is None


def test_parse_disclosures_skips_malformed_and_dedupes() -> None:
    payload = [
        {
            "disclosureIndex": 2,
            "title": "B ŞİRKETİ A.Ş.",
            "subject": "Yeni",
            "summary": "özet\n",
            "publishDate": "23.10.2026 09:00:00",
        },
        {
            "disclosureIndex": 2,
            "title": "B ŞİRKETİ A.Ş.",
            "subject": "Yeni (tekrar)",
            "summary": None,
            "publishDate": "23.10.2026 09:00:00",
        },
        {"disclosureIndex": "abc", "publishDate": "23.10.2026 09:00:00"},
        {"disclosureIndex": 3, "publishDate": "bozuk"},
        {
            "disclosureIndex": 1,
            "title": "A ŞİRKETİ A.Ş.",
            "subject": "Eski",
            "summary": None,
            "publishDate": "23.10.2026 08:00:00",
        },
    ]
    rows = parse_disclosures(payload)
    assert [row.disclosure_index for row in rows] == [2, 1]
    assert rows[0].subject == "Yeni (tekrar)", "last duplicate wins"
    assert rows[0].url.endswith("/tr/Bildirim/2")
    assert rows[0].published_date == date(2026, 10, 23)


def test_parse_disclosures_returns_empty_for_a_non_list() -> None:
    assert parse_disclosures({"success": False}) == []


# ---------------------------------------------------------------------------
# Ticker matching
# ---------------------------------------------------------------------------


def test_company_name_normalisation_drops_legal_suffixes() -> None:
    assert normalize_company_name("AKİŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş.") == (
        "AKIS GAYRIMENKUL YATIRIM"
    )
    assert normalize_company_name("Türk Hava Yolları A.O.") == "TURK HAVA YOLLARI"


def test_matcher_resolves_legal_form_and_suffix_differences() -> None:
    matcher = TickerMatcher.build(
        [
            Instrument(
                code="AKSGY",
                ticker="AKSGY.IS",
                name="Akış Gayrimenkul Yatırım Ortaklığı A.Ş.",
                sector=None,
            ),
            Instrument(
                code="THYAO",
                ticker="THYAO.IS",
                name="Türk Hava Yolları",
                sector=None,
            ),
        ]
    )
    assert matcher.match("AKİŞ GAYRİMENKUL YATIRIM ORTAKLIĞI A.Ş.") == "AKSGY"
    assert matcher.match("TÜRK HAVA YOLLARI A.O.") == "THYAO"


def test_matcher_refuses_ambiguous_titles() -> None:
    matcher = TickerMatcher.build(
        [
            Instrument(code="AAAA", ticker="AAAA.IS", name="ABC", sector=None),
            Instrument(code="BBBB", ticker="BBBB.IS", name="ABC A.Ş.", sector=None),
        ]
    )
    assert matcher.match("ABC A.Ş.") is None


def test_matcher_returns_none_for_unknown_title() -> None:
    matcher = TickerMatcher.build(
        [Instrument(code="THYAO", ticker="THYAO.IS", name="Türk Hava Yolları", sector=None)]
    )
    assert matcher.match("BAMBAŞKA BİR ŞİRKET A.Ş.") is None


# ---------------------------------------------------------------------------
# Repository + KapService
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path) -> MarketDataRepository:
    manager = DatabaseManager(sqlite_path=str(tmp_path / "kap.db"))
    manager.initialize()
    repository = MarketDataRepository(manager)
    repository.upsert_instruments(
        [
            Instrument(code="THYAO", ticker="THYAO.IS", name="Türk Hava Yolları", sector="Ulaşım"),
            Instrument(
                code="GARAN", ticker="GARAN.IS", name="Garanti Bankası", sector="Bankacılık"
            ),
        ]
    )
    return repository


def _disclosure(
    index: int = 10,
    *,
    title: str = "TÜRK HAVA YOLLARI A.O.",
    subject: str = "Özel Durum Açıklaması",
    when: datetime | None = None,
) -> KapDisclosure:
    published = when or datetime(2026, 10, 23, 12, 0)
    return KapDisclosure(
        disclosure_index=index,
        company_title=title,
        subject=subject,
        summary="Özet",
        published_at=published,
        published_date=published.date(),
        url=f"https://www.kap.org.tr/tr/Bildirim/{index}",
        disclosure_class="ODA",
    )


def test_kap_sync_stores_and_maps_without_duplicating(repo: MarketDataRepository) -> None:
    service = KapService(repo, fetch=lambda session: [_disclosure()], detail_fetch=lambda *a: None)

    first = service.sync()
    assert first == {"fetched": 1, "inserted": 1, "updated": 0, "mapped": 1, "unmapped": 0}

    second = service.sync()
    assert second["inserted"] == 0 and second["updated"] == 1

    rows = repo.list_kap_disclosures("THYAO.IS")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "THYAO.IS"
    assert rows[0]["published_date"] == "2026-10-23"
    assert repo.latest_kap_date() == date(2026, 10, 23)


def test_kap_sync_keeps_unmapped_rows_instead_of_guessing(repo: MarketDataRepository) -> None:
    service = KapService(
        repo,
        fetch=lambda session: [_disclosure(11, title="BİLİNMEYEN ŞİRKET A.Ş.")],
        detail_fetch=lambda *a: None,
    )
    result = service.sync()
    assert result["unmapped"] == 1
    with repo.manager.engine.begin() as conn:
        tickers = [
            row[0] for row in conn.execute(sa.text("SELECT ticker FROM kap_disclosures")).all()
        ]
    assert tickers == [None]


def test_detail_lookup_fills_the_symbol_and_is_reused(repo: MarketDataRepository) -> None:
    calls: list[int] = []

    def detail(index: int, session=None) -> str:
        calls.append(index)
        return "GARAN.IS"

    service = KapService(
        repo,
        fetch=lambda session: [_disclosure(12, title="GARANTİ FİNANSAL KİRALAMA A.Ş.")],
        detail_fetch=detail,
    )
    assert service.sync()["mapped"] == 1
    assert calls == [12]
    assert repo.kap_title_map() == {"GARANTİ FİNANSAL KİRALAMA A.Ş.": "GARAN.IS"}

    # A later run resolves the same title from the stored map: no extra page fetch.
    service2 = KapService(
        repo,
        fetch=lambda session: [_disclosure(13, title="GARANTİ FİNANSAL KİRALAMA A.Ş.")],
        detail_fetch=detail,
    )
    assert service2.sync()["mapped"] == 1
    assert calls == [12]


def test_detail_budget_is_respected(repo: MarketDataRepository) -> None:
    calls: list[int] = []

    def detail(index: int, session=None) -> str | None:
        calls.append(index)
        return None

    service = KapService(
        repo,
        fetch=lambda session: [
            _disclosure(20, title="X ŞİRKETİ A.Ş."),
            _disclosure(21, title="Y ŞİRKETİ A.Ş."),
            _disclosure(22, title="Z ŞİRKETİ A.Ş."),
        ],
        detail_fetch=detail,
    )
    result = service.sync(max_detail_lookups=2)
    assert len(calls) == 2
    assert result["unmapped"] == 3


def test_kap_sync_is_a_noop_when_fetch_returns_nothing(repo: MarketDataRepository) -> None:
    service = KapService(repo, fetch=lambda session: [], detail_fetch=lambda *a: None)
    assert service.sync() == {
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "mapped": 0,
        "unmapped": 0,
    }


def test_disclosures_for_unknown_symbol_is_none(repo: MarketDataRepository) -> None:
    assert KapService(repo, fetch=lambda s: []).disclosures("NOPE") is None


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------


def test_turkish_number_and_date_parsing() -> None:
    assert _tr_number("1.234,56") == pytest.approx(1234.56)
    assert _tr_number("0,8333") == pytest.approx(0.8333)
    assert _tr_number("83,33") == pytest.approx(83.33)
    assert _tr_number("") is None
    assert _tr_number("-") is None
    assert _tr_date("14.01.2026") == date(2026, 1, 14)
    assert _tr_date("14/01/2026") is None


def test_action_table_keeps_turkish_decimal_precision() -> None:
    html = """
    <table>
      <tr><td>Kod</td><td>Kapanış (TL)</td><td>Bölünme Sonrası Sermaye (TL)</td>
          <td>Tarih</td><td>Bedelli Oran (%)</td><td>Bedelli Nom. Tutar (TL)</td>
          <td>Diğer (*)</td><td>Bedelsiz IK Oran (%)</td><td>Bedelsiz Temettü Oran (%)</td>
          <td>Nakit Tem.Brüt (%)</td><td>Nakit Temettü (TL)</td><td>Hisse Başı Brüt (TL)</td></tr>
      <tr><td>ENKAI</td><td>74,50</td><td>6.000.000.000</td><td>08.04.2026</td>
          <td>0,00</td><td>0,00</td><td>0,00</td><td>0,00</td><td>0,00</td>
          <td>210,00</td><td>12.600.000.000</td><td>2,1000</td></tr>
      <tr><td>KAYSE</td><td>2,43</td><td>3.000.000.000</td><td>06.01.2026</td>
          <td>0,00</td><td>0,00</td><td>0,00</td><td>324,93</td><td>0,00</td>
          <td>0,00</td><td>0</td><td>0,0000</td></tr>
    </table>
    """
    rows = parse_corporate_action_rows(html)
    assert [row["Kod"] for row in rows] == ["ENKAI", "KAYSE"]
    assert _tr_number(rows[0]["Hisse Başı Brüt (TL)"]) == pytest.approx(2.1)
    assert _tr_number(rows[1]["Bedelsiz IK Oran (%)"]) == pytest.approx(324.93)
    assert _tr_date(rows[0]["Tarih"]) == date(2026, 4, 8)


def test_action_table_parser_returns_empty_without_the_table() -> None:
    assert parse_corporate_action_rows("<html><body><p>bakım</p></body></html>") == []


def test_corporate_action_upsert_is_idempotent(repo: MarketDataRepository) -> None:
    rows = [
        {
            "ticker": "THYAO.IS",
            "action_date": date(2026, 4, 8),
            "kind": "temettu",
            "cash_per_share_tl": 2.1,
            "cash_ratio_pct": 210.0,
            "source": "isyatirim",
        },
        {
            "ticker": "THYAO.IS",
            "action_date": date(2026, 4, 8),
            "kind": "bedelsiz",
            "bonus_ratio_pct": 50.0,
            "source": "isyatirim",
        },
    ]
    assert repo.upsert_corporate_actions(rows) == 2
    assert repo.upsert_corporate_actions(rows) == 2, "same key updates, never duplicates"
    stored = repo.list_corporate_actions("THYAO.IS")
    assert len(stored) == 2
    assert {row["kind"] for row in stored} == {"temettu", "bedelsiz"}


def test_trailing_dividend_yield_uses_the_last_close(repo: MarketDataRepository) -> None:
    today = date.today()
    repo.write_bars(
        "THYAO.IS",
        [DailyBar(date=today - timedelta(days=1), close=100.0)],
        source="isyatirim",
    )
    repo.upsert_corporate_actions(
        [
            {
                "ticker": "THYAO.IS",
                "action_date": today - timedelta(days=30),
                "kind": "temettu",
                "cash_per_share_tl": 5.0,
                "source": "isyatirim",
            },
            {
                "ticker": "THYAO.IS",
                "action_date": today - timedelta(days=500),
                "kind": "temettu",
                "cash_per_share_tl": 99.0,
                "source": "isyatirim",
            },
        ]
    )
    result = CorporateActionsService(repo).trailing_dividend("THYAO")
    assert result is not None
    assert result["cash_per_share_tl"] == pytest.approx(5.0)
    assert result["yield_pct"] == pytest.approx(5.0)


def test_trailing_dividend_is_none_without_cash(repo: MarketDataRepository) -> None:
    repo.write_bars(
        "THYAO.IS",
        [DailyBar(date=date.today() - timedelta(days=1), close=100.0)],
        source="isyatirim",
    )
    result = CorporateActionsService(repo).trailing_dividend("THYAO")
    assert result == {"cash_per_share_tl": None, "yield_pct": None, "window_days": 365.0}


def test_actions_are_labelled_and_unknown_symbol_is_none(repo: MarketDataRepository) -> None:
    repo.upsert_corporate_actions(
        [
            {
                "ticker": "THYAO.IS",
                "action_date": date(2026, 4, 8),
                "kind": "temettu",
                "cash_per_share_tl": 2.1,
                "source": "isyatirim",
            }
        ]
    )
    service = CorporateActionsService(repo)
    rows = service.actions("THYAO")
    assert rows is not None and rows[0]["kind_label"] == "Nakit temettü"
    assert service.actions("NOPE") is None


def test_sync_is_a_noop_when_the_vendor_returns_nothing(repo: MarketDataRepository) -> None:
    service = CorporateActionsService(repo, fetch=lambda session: [])
    assert service.sync() == {"fetched": 0, "written": 0}


def test_dividend_yield_scan_threshold() -> None:
    bars = [DailyBar(date=date(2026, 10, 23), close=100.0)]
    hit = scan_dividend_yield(bars, date(2026, 10, 23), FundamentalContext({}, 1_000.0, 4.5))
    assert hit is not None and hit.value == pytest.approx(4.5)
    assert (
        scan_dividend_yield(bars, date(2026, 10, 23), FundamentalContext({}, 1_000.0, 3.99)) is None
    )
    assert scan_dividend_yield(bars, date(2026, 10, 23), FundamentalContext({}, 1_000.0)) is None


def test_snapshot_row_carries_the_dividend_yield() -> None:
    bars = [DailyBar(date=date(2026, 10, 23), close=200.0, market_cap_tl=1e9)]
    row = snapshot_row("THYAO.IS", bars, {}, dividend_per_share=5.0)
    assert row is not None
    assert row["dividend_yield_pct"] == pytest.approx(2.5)
    plain = snapshot_row("THYAO.IS", bars, {})
    assert plain is not None and plain["dividend_yield_pct"] is None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path) -> Flask:
    db_path = str(tmp_path / "kap_api.db")
    with settings.override(
        DB_PATH=db_path,
        JWT_SECRET_KEY="test-secret-key-for-kap-api-123456",
        JWT_COOKIE_SECURE=False,
        BROKER_MODE="paper",
        BROKER_PROVIDER="paper",
        METRICS_PUBLIC=False,
        ALLOW_PUBLIC_REGISTRATION=True,
        STOCK_PAGES_PUBLIC=False,
        ADMIN_BOOTSTRAP_EMAIL="",
        ADMIN_BOOTSTRAP_PASSWORD_HASH="",
    ):
        manager = DatabaseManager(sqlite_path=db_path)
        manager.initialize()
        repository = MarketDataRepository(manager)
        repository.upsert_instruments(
            [Instrument(code="THYAO", ticker="THYAO.IS", name="Türk Hava Yolları", sector="Ulaşım")]
        )
        repository.write_bars(
            "THYAO.IS",
            [
                DailyBar(date=date(2026, 10, 22), close=250.0),
                DailyBar(date=date(2026, 10, 23), close=255.0),
            ],
            source="isyatirim",
        )
        repository.upsert_kap_disclosures(
            [
                {
                    "disclosure_index": 1687034,
                    "ticker": "THYAO.IS",
                    "company_title": "TÜRK HAVA YOLLARI A.O.",
                    "subject": "Özel Durum Açıklaması",
                    "summary": "Özet",
                    "disclosure_class": "ODA",
                    "published_at": datetime(2026, 10, 23, 19, 20, 42),
                    "published_date": date(2026, 10, 23),
                    "url": "https://www.kap.org.tr/tr/Bildirim/1687034",
                }
            ]
        )
        repository.upsert_corporate_actions(
            [
                {
                    "ticker": "THYAO.IS",
                    "action_date": datetime.now(UTC).date() - timedelta(days=20),
                    "kind": "temettu",
                    "cash_per_share_tl": 5.0,
                    "source": "isyatirim",
                }
            ]
        )
        application = create_dashboard_app(
            fetcher=MagicMock(),
            engine=MagicMock(),
            db=DataAccess(manager),
            broker=MagicMock(),
        )
        application.config["TESTING"] = True
        application.config["_test_manager"] = manager
        yield application


def _login(client: FlaskClient, email: str = "member@bistbot.local") -> str:
    client.post("/api/auth/register", json={"email": email, "password": "Str0ng-test-pass!"})
    return client.post(
        "/api/auth/login", json={"email": email, "password": "Str0ng-test-pass!"}
    ).get_json()["access_token"]


def _promote(app: Flask, email: str) -> None:
    manager = app.config["_test_manager"]
    with manager.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email}
        )


def test_member_cannot_read_kap_when_pages_are_private(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/stocks/THYAO/kap", headers=headers).status_code == 403
        assert client.get("/api/stocks/THYAO/corporate-actions", headers=headers).status_code == 403


def test_admin_reads_kap_and_actions(app: Flask) -> None:
    with app.test_client() as client:
        token = _login(client, "admin@bistbot.local")
        _promote(app, "admin@bistbot.local")
        headers = {"Authorization": f"Bearer {token}"}

        kap = client.get("/api/stocks/THYAO/kap", headers=headers)
        assert kap.status_code == 200
        rows = kap.get_json()["disclosures"]
        assert len(rows) == 1
        assert rows[0]["subject"] == "Özel Durum Açıklaması"
        assert rows[0]["url"].startswith("https://www.kap.org.tr/")

        actions = client.get("/api/stocks/THYAO/corporate-actions", headers=headers)
        assert actions.status_code == 200
        payload = actions.get_json()
        assert payload["actions"][0]["kind_label"] == "Nakit temettü"
        assert payload["trailing_dividend"]["yield_pct"] == pytest.approx(1.96, abs=0.01)

        assert client.get("/api/stocks/NOPE/kap", headers=headers).status_code == 404
        assert client.get("/api/stocks/NOPE/corporate-actions", headers=headers).status_code == 404
        assert client.get("/api/stocks/1!/kap", headers=headers).status_code == 400

        page = client.get("/ui/stock/THYAO")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "KAP Bildirimleri" in html
        assert "Temettü ve Sermaye Artırımı" in html
