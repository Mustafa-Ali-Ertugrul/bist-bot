"""End-to-end integration / regression tests for the Streamlit UI layer.

WARNING / UYARI
---------------
If you intentionally change user-facing copy (Turkish labels, empty states,
scan/timeout warnings), filter session keys (``min_score_filter``, RSI/volume
filters), overview/signals layout, or ``request_scan`` / cooldown behaviour,
you MUST consciously update the string and interaction assertions in this file.

Bu dosya UI katmanının dayanıklı ve kullanıcı dostu kaldığını garanti eder:

1. Overview / signals render paths (mock session + patched ``st``)
2. Empty / error / warning states (no crash, clear messaging)
3. Filtering (score / RSI / volume) and high-volume signal lists
4. Scan button / cooldown / timeout user feedback
5. HTML escaping for untrusted sidebar news payloads

Full browser ``AppTest`` of the entire Streamlit app is intentionally avoided
here: auth bootstrap + multi-page wiring is covered separately; this suite
locks the operator-facing pure render and interaction contracts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from bist_bot.strategy.signal_models import Signal, SignalType
from bist_bot.ui.components import app_shell, metric_block
from bist_bot.ui.pages import overview_page, signals_page
from bist_bot.ui.runtime_data import filter_signals
from bist_bot.ui.runtime_scan import check_scan_timeout, request_scan

TR = timezone(timedelta(hours=3))


def _signal(
    ticker: str,
    score: float,
    signal_type: SignalType = SignalType.BUY,
    price: float = 100.0,
) -> Signal:
    return Signal(
        ticker=ticker,
        signal_type=signal_type,
        score=score,
        price=price,
        reasons=[f"reason-{ticker}"],
        stop_loss=price * 0.95,
        target_price=price * 1.1,
        position_size=10,
        confidence="confidence.medium",
    )


def _ohlcv(ticker_seed: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [ticker_seed] * 30,
            "high": [ticker_seed + 1] * 30,
            "low": [ticker_seed - 1] * 30,
            "close": [ticker_seed] * 30,
            "volume": [1_000.0] * 30,
            "rsi": [50.0] * 30,
            "volume_ratio": [1.2] * 30,
        },
        index=pd.date_range("2025-01-01", periods=30),
    )


class SessionMap(dict):
    """dict-like session_state supporting attribute access used by Streamlit code."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


class DummyColumn:
    def __enter__(self) -> DummyColumn:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class DummyTab:
    def __enter__(self) -> DummyTab:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class DummyContainer:
    def __enter__(self) -> DummyContainer:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _patch_streamlit_layout(mock_st: MagicMock) -> None:
    mock_st.columns.side_effect = lambda *args, **kwargs: tuple(
        DummyColumn() for _ in range(max(args[0] if args and isinstance(args[0], int) else 2, 1))
    )
    mock_st.tabs.return_value = (DummyTab(), DummyTab(), DummyTab())
    mock_st.container.return_value = DummyContainer()
    mock_st.button.return_value = False
    mock_st.write = MagicMock()
    mock_st.info = MagicMock()
    mock_st.warning = MagicMock()
    mock_st.error = MagicMock()
    mock_st.markdown = MagicMock()
    mock_st.rerun = MagicMock()
    mock_st.query_params = {}


# ---------------------------------------------------------------------------
# Pure helpers (no Streamlit runtime required)
# ---------------------------------------------------------------------------


def test_filter_status_html_normal_and_filtered() -> None:
    """Normal + filtered status copy stays informative for operators."""
    with patch.object(signals_page, "st") as mock_st:
        mock_st.session_state = SessionMap(
            min_score_filter=10,
            rsi_min_filter=0,
            rsi_max_filter=100,
            vol_ratio_filter=0.0,
        )
        plain = signals_page._render_filter_status_html(
            generated_count=5, visible_count=5, filtered_out_count=0
        )
        filtered = signals_page._render_filter_status_html(
            generated_count=10, visible_count=3, filtered_out_count=7
        )

    assert "Tüm sinyaller görünür" in plain
    assert "Min Skor" in plain
    assert "gizlendi" in filtered
    assert "7 sinyal" in filtered


def test_sidebar_news_html_escapes_untrusted_payload() -> None:
    from bist_bot.streamlit_app import _render_sidebar_news_html

    html = _render_sidebar_news_html(
        [
            {
                "title": "<script>alert(1)</script>",
                "source": "Evil & Co",
                "published_at": "2025-01-01",
                "url": "https://example.com/?q='xss'",
            }
        ]
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Evil &amp; Co" in html
    assert "BIST100 Haberleri" in html


def test_response_message_maps_http_errors_for_users() -> None:
    from bist_bot.streamlit_app import _response_message

    r429 = SimpleNamespace(status_code=429, text="", json=lambda: (_ for _ in ()).throw(ValueError()))
    r500 = SimpleNamespace(status_code=503, text="boom", json=lambda: (_ for _ in ()).throw(ValueError()))
    r401 = SimpleNamespace(status_code=401, text="", json=lambda: {"message": "bad creds"})

    assert "Çok fazla" in _response_message(r429, "default")
    assert "HTTP 503" in _response_message(r500, "default") or "hata" in _response_message(
        r500, "default"
    ).lower()
    assert _response_message(r401, "default") == "bad creds"


def test_metric_block_escapes_html() -> None:
    with patch.object(metric_block, "st") as mock_st:
        metric_block.render_metric_block("<b>Title</b>", "<script>1</script>", "sub")
        html = mock_st.markdown.call_args[0][0]
    assert "<script>" not in html
    assert "&lt;b&gt;Title&lt;/b&gt;" in html


def test_shell_navigation_uses_query_params() -> None:
    source_set = open(app_shell.__file__, encoding="utf-8").read()
    assert "st.query_params" in source_set
    assert "PAGE_META" in source_set
    assert "render_sidebar_nav" not in source_set


# ---------------------------------------------------------------------------
# Filter interactions
# ---------------------------------------------------------------------------


def test_filter_signals_applies_min_score_threshold() -> None:
    with patch("bist_bot.ui.runtime_data.st") as mock_st:
        mock_st.session_state = SessionMap(
            min_score_filter=20,
            rsi_min_filter=0,
            rsi_max_filter=100,
            vol_ratio_filter=0.0,
        )
        base = [
            _signal("AAA.IS", 10.0, SignalType.WEAK_BUY),
            _signal("BBB.IS", 25.0, SignalType.BUY),
            _signal("CCC.IS", 55.0, SignalType.STRONG_BUY),
        ]
        out = filter_signals(base, {})
    assert [s.ticker for s in out] == ["BBB.IS", "CCC.IS"]


def test_filter_signals_high_volume_list_stays_bounded() -> None:
    """Yüksek veri: 200 sinyal filtre sonrası tutarlı ve crash yok."""
    with patch("bist_bot.ui.runtime_data.st") as mock_st:
        mock_st.session_state = SessionMap(
            min_score_filter=-100,
            rsi_min_filter=0,
            rsi_max_filter=100,
            vol_ratio_filter=0.0,
        )
        base = [
            _signal(
                f"T{i:03d}.IS",
                float(i % 60 - 10),
                SignalType.HOLD if i % 3 == 0 else SignalType.BUY,
            )
            for i in range(200)
        ]
        out = filter_signals(base, {})
    assert len(out) == 200
    assert all(isinstance(s, Signal) for s in out)


# ---------------------------------------------------------------------------
# Signals page render states
# ---------------------------------------------------------------------------


def test_signals_page_empty_state_shows_group_info_messages() -> None:
    """Boş durum: gruplar 'uygun sinyal yok' info mesajı basar, çökmez."""
    session = SessionMap(
        all_data={},
        signals=[],
        min_score_filter=-100,
        rsi_min_filter=0,
        rsi_max_filter=100,
        vol_ratio_filter=0.0,
    )
    with (
        patch.object(signals_page, "st") as mock_st,
        patch.object(signals_page, "render_page_hero") as mock_hero,
        patch.object(signals_page, "render_section_title"),
        patch.object(signals_page, "render_html_panel"),
        patch.object(signals_page, "filter_signals", return_value=[]),
    ):
        mock_st.session_state = session
        _patch_streamlit_layout(mock_st)
        signals_page.render_signals_page()

    mock_hero.assert_called_once()
    info_texts = " ".join(str(c.args[0]) for c in mock_st.info.call_args_list)
    assert "uygun sinyal yok" in info_texts


def test_signals_page_normal_view_renders_groups_with_signals() -> None:
    signals = [
        _signal("THYAO.IS", 55.0, SignalType.STRONG_BUY, 300.0),
        _signal("GARAN.IS", 25.0, SignalType.BUY, 120.0),
        _signal("EREGL.IS", 0.0, SignalType.HOLD, 50.0),
        _signal("SASA.IS", -25.0, SignalType.SELL, 40.0),
    ]
    all_data = {s.ticker: _ohlcv(s.price) for s in signals}
    session = SessionMap(
        all_data=all_data,
        signals=signals,
        min_score_filter=-100,
        rsi_min_filter=0,
        rsi_max_filter=100,
        vol_ratio_filter=0.0,
    )
    with (
        patch.object(signals_page, "st") as mock_st,
        patch.object(signals_page, "render_page_hero") as mock_hero,
        patch.object(signals_page, "render_section_title"),
        patch.object(signals_page, "render_html_panel"),
        patch.object(signals_page, "render_signal_card") as mock_card,
        patch.object(signals_page, "filter_signals", side_effect=lambda base, data: base),
    ):
        mock_st.session_state = session
        _patch_streamlit_layout(mock_st)
        signals_page.render_signals_page()

    hero_kwargs = mock_hero.call_args.kwargs if mock_hero.call_args.kwargs else {}
    badges = hero_kwargs.get("badges") or (
        mock_hero.call_args.args[3] if len(mock_hero.call_args.args) > 3 else []
    )
    badge_text = " ".join(badges) if badges else ""
    # At least one strong/buy and one sell-ish badge path exercised via groups.
    assert mock_card.call_count >= 3
    assert mock_hero.called
    assert "Görünür" in badge_text or mock_card.call_count == len(signals)


# ---------------------------------------------------------------------------
# Overview: error / warning / scan button
# ---------------------------------------------------------------------------


def test_overview_shows_scan_error_warning_not_crash() -> None:
    """Hata durumu: scan_error → st.warning, uygulama çökmez."""
    session = SessionMap(
        all_data={},
        signals=[],
        scan_stats={"generated": 0, "actionable": 0},
        scan_in_progress=False,
        scan_error="provider timeout",
        scan_phase="Veri alınıyor",
        scan_warning=None,
        skipped_tickers=[],
    )
    api_stats = SimpleNamespace(
        ok=True,
        json=lambda: {"stats": {"latest_scan": {}, "rejection_breakdown": {}}},
    )
    api_signals = SimpleNamespace(ok=True, json=lambda: {"signals": []})

    with (
        patch.object(overview_page, "st") as mock_st,
        patch.object(overview_page, "api_request", side_effect=[api_stats, api_signals]),
        patch.object(overview_page, "fetch_index_data", return_value={}),
        patch.object(overview_page, "get_market_summary", return_value={}),
        patch.object(overview_page, "filter_signals", return_value=[]),
        patch.object(overview_page, "render_page_hero"),
        patch.object(overview_page, "render_section_title"),
        patch.object(overview_page, "render_html_panel"),
        patch.object(overview_page, "render_metric_block"),
        patch.object(overview_page, "request_scan", return_value=False),
    ):
        mock_st.session_state = session
        _patch_streamlit_layout(mock_st)
        overview_page.render_overview_page()

    warning_text = " ".join(str(c.args[0]) for c in mock_st.warning.call_args_list)
    assert "Tarama tamamlanamadı" in warning_text
    assert "provider timeout" in warning_text


def test_overview_shows_skipped_tickers_warning() -> None:
    """Graceful degradation UI: skipped tickers → sarı uyarı."""
    session = SessionMap(
        all_data={"THYAO.IS": object()},
        signals=[_signal("THYAO.IS", 30.0)],
        scan_stats={"generated": 1, "actionable": 1},
        scan_in_progress=False,
        scan_error=None,
        scan_warning=None,
        skipped_tickers=["GARAN.IS", "SASA.IS"],
    )
    api_stats = SimpleNamespace(
        ok=True,
        json=lambda: {
            "stats": {
                "latest_scan": {"total_scanned": 1, "signals_generated": 1, "actionable": 1},
                "rejection_breakdown": {"total_rejections": 0, "by_reason": [], "by_stage": []},
            }
        },
    )
    api_signals = SimpleNamespace(ok=True, json=lambda: {"signals": []})

    with (
        patch.object(overview_page, "st") as mock_st,
        patch.object(overview_page, "api_request", side_effect=[api_stats, api_signals]),
        patch.object(overview_page, "fetch_index_data", return_value={}),
        patch.object(overview_page, "get_market_summary", return_value={"avg_rsi": 50.0, "avg_vol_ratio": 1.0}),
        patch.object(overview_page, "filter_signals", side_effect=lambda s, d: s),
        patch.object(overview_page, "render_page_hero"),
        patch.object(overview_page, "render_section_title"),
        patch.object(overview_page, "render_html_panel"),
        patch.object(overview_page, "render_metric_block"),
        patch.object(overview_page, "request_scan", return_value=False),
    ):
        mock_st.session_state = session
        _patch_streamlit_layout(mock_st)
        overview_page.render_overview_page()

    warning_text = " ".join(str(c.args[0]) for c in mock_st.warning.call_args_list)
    assert "Veri alınamadı, atlanıyor" in warning_text
    assert "GARAN.IS" in warning_text


def test_overview_scan_button_triggers_request_scan() -> None:
    """Buton tıklama: BIST100 taramasını başlat → request_scan + info."""
    session = SessionMap(
        all_data={},
        signals=[],
        scan_stats={"generated": 0, "actionable": 0},
        scan_in_progress=False,
        scan_error=None,
        scan_warning=None,
        skipped_tickers=[],
    )
    api_stats = SimpleNamespace(
        ok=True,
        json=lambda: {"stats": {"latest_scan": {}, "rejection_breakdown": {}}},
    )
    api_signals = SimpleNamespace(ok=True, json=lambda: {"signals": []})

    def button_side_effect(label, *args, **kwargs):
        return label == "BIST100 taramasını başlat"

    with (
        patch.object(overview_page, "st") as mock_st,
        patch.object(overview_page, "api_request", side_effect=[api_stats, api_signals]),
        patch.object(overview_page, "fetch_index_data", return_value={}),
        patch.object(overview_page, "get_market_summary", return_value={}),
        patch.object(overview_page, "filter_signals", return_value=[]),
        patch.object(overview_page, "render_page_hero"),
        patch.object(overview_page, "render_section_title"),
        patch.object(overview_page, "render_html_panel"),
        patch.object(overview_page, "render_metric_block"),
        patch.object(overview_page, "request_scan", return_value=True) as mock_request,
    ):
        mock_st.session_state = session
        _patch_streamlit_layout(mock_st)
        mock_st.button.side_effect = button_side_effect
        overview_page.render_overview_page()

    mock_request.assert_called_once_with(force_clear=True)
    info_text = " ".join(str(c.args[0]) for c in mock_st.info.call_args_list)
    assert "arka planda başlatıldı" in info_text
    mock_st.rerun.assert_called()


def test_request_scan_cooldown_shows_warning() -> None:
    """Cooldown aktifken request_scan False döner ve st.warning basar."""
    session = SessionMap(_scan_session_key="s1")
    with (
        patch("bist_bot.ui.runtime_scan.st") as mock_st,
        patch("bist_bot.ui.runtime_scan.consume_cooldown", return_value=(False, 3.5)),
        patch("bist_bot.ui.runtime_scan.start_background_scan") as mock_start,
    ):
        mock_st.session_state = session
        mock_st.warning = MagicMock()
        ok = request_scan(force_clear=True)

    assert ok is False
    mock_start.assert_not_called()
    assert "Çok sık istek" in mock_st.warning.call_args[0][0]


def test_check_scan_timeout_sets_user_facing_error() -> None:
    """Timeout: scan_in_progress reset + net Türkçe hata mesajı."""
    from bist_bot.ui import runtime_scan

    old = datetime.now(TR) - timedelta(seconds=500)

    class FakeSession:
        def __init__(self) -> None:
            self.scan_in_progress = True
            self.scan_started_at = old
            self.scan_error = None
            self.scan_phase = "analiz"
            self._scan_session_key = "timeout-key"

        def get(self, key, default=None):
            return getattr(self, key, default)

    fake = FakeSession()
    with (
        patch.object(runtime_scan.st, "session_state", fake),
        patch.object(runtime_scan, "settings") as mock_settings,
        patch.object(runtime_scan, "logger"),
    ):
        mock_settings.STREAMLIT_BACKGROUND_SCAN_TIMEOUT_SECONDS = 180
        hit = check_scan_timeout()

    assert hit is True
    assert fake.scan_in_progress is False
    assert fake.scan_error is not None
    assert "tamamlanamad" in fake.scan_error.casefold()
    assert "180" in fake.scan_error
    assert "Manuel tarama" in fake.scan_error


def test_overview_api_failure_shows_warning_and_returns() -> None:
    """API erişilemezse overview zarifçe uyarır ve devam etmez."""
    session = SessionMap(
        all_data={},
        signals=[],
        scan_stats={},
        min_score_filter=-100,
        rsi_min_filter=0,
        rsi_max_filter=100,
        vol_ratio_filter=0.0,
    )
    with (
        patch.object(overview_page, "st") as mock_st,
        patch.object(overview_page, "api_request", side_effect=RuntimeError("api down")),
        patch.object(overview_page, "filter_signals", return_value=[]),
        patch.object(overview_page, "render_page_hero") as mock_hero,
    ):
        mock_st.session_state = session
        mock_st.warning = MagicMock()
        overview_page.render_overview_page()

    mock_hero.assert_not_called()
    assert mock_st.warning.called
