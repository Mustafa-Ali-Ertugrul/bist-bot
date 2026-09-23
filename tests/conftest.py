import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def _freeze_market_hours_off(monkeypatch):
    """Keep scan orchestration tests independent of wall-clock market hours (B4).

    The freshness gate (``ScanService._apply_freshness_gate``) activates only
    while BIST is open; with its stale test fixtures that aborts scans. The
    gate's own behaviour is covered by ``tests/test_freshness_gate.py``, which
    re-patches ``bist_bot.scanner.is_bist_open`` to ``lambda: True`` per test.
    Other modules (scheduler, worker_http, market_calendar) import their own
    reference, so only the scanner module's name is patched here (call via
    ``import bist_bot.scanner as scanner_module`` — patch-where-used rule).
    """
    import bist_bot.scanner as scanner_module

    monkeypatch.setattr(scanner_module, "is_bist_open", lambda: False)


@pytest.fixture(autouse=True)
def _stub_default_outcome_tracker(monkeypatch):
    """Keep ScanService's default SignalOutcomeTracker out of the real results/ dir.

    ScanService builds ``SignalOutcomeTracker(settings=..., db=...)`` with the
    default CWD-relative ``results_dir="results"``. Tests that run ``scan_once``
    without injecting a tracker would otherwise write ``signal_outcome_open.json``
    / ``signal_outcomes.csv`` into the repository tree. The tracker's own unit
    tests construct the class directly with ``tmp_path`` and are unaffected.
    """
    import bist_bot.scanner as scanner_module

    monkeypatch.setattr(
        scanner_module,
        "SignalOutcomeTracker",
        lambda *args, **kwargs: MagicMock(),
    )


@pytest.fixture(autouse=True)
def _clear_dashboard_caches():
    """Reset module-level dashboard caches/throttles between tests.

    ``/api/stats`` now serves a short-TTL cached payload and the RBAC granted
    audit row is throttled per identity. Both live in module globals, so a
    value written by one test would otherwise leak into the next (e.g. an
    ``empty rejection_breakdown`` assertion seeing a previous test's payload,
    or a throttled ``rbac_access_granted`` INSERT breaking an audit-set
    assertion). Clearing per test keeps every test on a cold cache while still
    exercising the production paths.

    Also resets the overview page's 30s API-response memo (tests patch
    ``api_request`` with an exact ``side_effect`` list), the UI runtime's
    last-bar metrics memo (keyed on ``id(df)``, would otherwise serve a
    frame's metrics computed under a previous test's ``add_all`` patch), the
    analyze-page indicator memo (D4), signal-card chart memo (D5),
    dashboard /api/analyze indicator memo, and whale-radar indicator memo.
    Each import is independent so an optional dependency failure skips only
    that clearer instead of abandoning the rest.
    """
    clearers = []

    # Dashboard: /api/stats TTL cache + RBAC granted-audit throttle.
    try:
        from bist_bot import dashboard as dashboard_module
    except Exception:  # pragma: no cover - dashboard deps optional in unit tests
        dashboard_module = None
    for name in (
        "_clear_api_stats_cache",
        "_clear_rbac_granted_audit_throttle",
        "_clear_analyze_indicators_cache",
    ):
        clearer = getattr(dashboard_module, name, None)
        if callable(clearer):
            clearers.append(clearer)
            clearer()

    # Whale service: content-keyed indicator frame memo (whale radar page).
    try:
        from bist_bot.services import whale_alert_service as whale_module
    except Exception:  # pragma: no cover - deps optional in unit tests
        whale_module = None
    clearer = getattr(whale_module, "_clear_whale_indicators_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # Overview page: 30s TTL memo of /api/stats + /api/signals/history. Tests
    # patch ``api_request`` with an exact ``side_effect=[a, b]`` list, so a
    # payload surviving from a previous test would both under-consume the
    # side effects and assert against stale JSON.
    try:
        from bist_bot.ui.pages import overview_page as overview_module
    except Exception:  # pragma: no cover - streamlit deps optional in unit tests
        overview_module = None
    clearer = getattr(overview_module, "_clear_api_response_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # UI runtime: last-bar RSI/volume_ratio memo keyed on id(df); must not
    # leak a frame's metrics across tests (or into patched add_all tests).
    try:
        from bist_bot.ui import runtime_data as runtime_data_module
    except Exception:  # pragma: no cover - pandas/streamlit deps optional
        runtime_data_module = None
    clearer = getattr(runtime_data_module, "_clear_last_row_metrics_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # Analyze page: content-keyed indicator frame memo (D4).
    try:
        from bist_bot.ui.pages import analyze_page as analyze_module
    except Exception:  # pragma: no cover - streamlit deps optional in unit tests
        analyze_module = None
    clearer = getattr(analyze_module, "_clear_analyze_indicators_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # Signal card: content-keyed 60-bar chart frame memo (D5).
    try:
        from bist_bot.ui.components import signal_card as signal_card_module
    except Exception:  # pragma: no cover - streamlit deps optional in unit tests
        signal_card_module = None
    clearer = getattr(signal_card_module, "_clear_signal_chart_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # Shared add_all content memo (engine/regime enrichment hot path).
    try:
        from bist_bot import indicators as indicators_module
    except Exception:  # pragma: no cover - indicators deps optional in unit tests
        indicators_module = None
    clearer = getattr(indicators_module, "_clear_add_all_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # Trend-bias enriched-frame memo (regime.get_trend_bias hot path).
    try:
        from bist_bot.strategy import regime as regime_module
    except Exception:  # pragma: no cover - regime deps optional in unit tests
        regime_module = None
    clearer = getattr(regime_module, "_clear_trend_bias_enrich_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    # Macro-benchmark enriched-frame memo (engine._enrich_macro_benchmark).
    try:
        from bist_bot.strategy import engine as engine_module
    except Exception:  # pragma: no cover - engine deps optional in unit tests
        engine_module = None
    clearer = getattr(engine_module, "_clear_macro_benchmark_enrich_cache", None)
    if callable(clearer):
        clearers.append(clearer)
        clearer()

    yield
    for clearer in clearers:
        clearer()


@pytest.fixture(autouse=True)
def _stub_default_shadow_trade_service(monkeypatch):
    """Keep ScanService's default ShadowTradeService out of the real results/ dir.

    ScanService builds ``ShadowTradeService(...)`` with the default
    CWD-relative ``results_dir="results"``. Tests that run ``scan_once``
    without injecting a service would otherwise write ``shadow_open.json`` /
    ``shadow_pnl.csv`` / ``shadow_summary_state.json`` into the repository
    tree. The service's own unit tests construct the class directly with
    ``tmp_path`` and are unaffected.
    """
    import bist_bot.scanner as scanner_module

    monkeypatch.setattr(
        scanner_module,
        "ShadowTradeService",
        lambda *args, **kwargs: MagicMock(),
    )
