"""Tests for notification dispatch: detail labels, diagnosis block,
robust-watchlist-based group routing, and CSV consistency."""

from __future__ import annotations

import csv
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from bist_bot.config.settings import settings  # noqa: E402
from bist_bot.config.watchlist import load_watchlist  # noqa: E402
from bist_bot.notifier import TelegramNotifier  # noqa: E402
from bist_bot.services.notification_service import (  # noqa: E402
    NotificationDispatchService,
)
from bist_bot.strategy.signal_models import Signal, SignalType  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    ticker: str = "THYAO.IS",
    signal_type: SignalType = SignalType.BUY,
    score: float = 30.0,
    price: float = 100.0,
    reasons: list[str] | None = None,
    stop_loss: float = 95.0,
    target_price: float = 110.0,
    confidence: str = "confidence.medium",
    agreement_ratio: float | None = None,
    is_actionable: bool = False,
) -> Signal:
    # Far-future timestamp so is_expired() naturally returns False for the
    # duration of the test (avoids TTL-bound false-skip).
    return Signal(
        ticker=ticker,
        signal_type=signal_type,
        score=score,
        price=price,
        reasons=reasons or [],
        stop_loss=stop_loss,
        target_price=target_price,
        confidence=confidence,
        agreement_ratio=agreement_ratio,
        timestamp=datetime(2099, 1, 1, 10, 0, 0, tzinfo=UTC),
        is_actionable=is_actionable,
    )


def _make_notifier_with_fake_sender() -> tuple[TelegramNotifier, list[str]]:
    captured: list[str] = []

    def fake_sender(base_url, chat_id, text, **kwargs) -> bool:
        captured.append(text)
        return True

    notifier = TelegramNotifier(
        token="mock-token",
        chat_id="mock-chat",
        sender=fake_sender,
    )
    assert notifier.enabled
    return notifier, captured


def test_scan_summary_distinguishes_actionable_buys_from_radars():
    notifier, captured = _make_notifier_with_fake_sender()
    actionable = _make_signal(ticker="ASTOR.IS", score=30.0, price=120.0, is_actionable=True)
    radar = _make_signal(ticker="ODAS.IS", score=11.0, price=8.66)

    assert notifier.send_scan_summary([actionable, radar], total_scanned=2)

    assert len(captured) == 1
    summary = captured[0]
    assert "Alım Sinyali: 1" in summary
    assert "Radar / İzle: 1" in summary
    assert "🟢 Astor Enerji" in summary
    assert "(Skor: +30) — AL" in summary
    assert "🟡 Odas" in summary
    assert "(Skor: +11) — RADAR" in summary


# H6-ON robust list (source: results/robust_watchlist.csv).
ROBUST_SET = {
    "ASTOR.IS",
    "TUPRS.IS",
    "PETKM.IS",
    "SISE.IS",
    "GUBRF.IS",
    "ENKAI.IS",
    "ODAS.IS",
    "EKGYO.IS",
}

# Overfit-prone names that should NOT be in the H6-ON robust set.
OVERFIT_NAMES = {"ASELS.IS", "GARAN.IS", "SAHOL.IS", "THYAO.IS", "BIMAS.IS", "ISCTR.IS"}


def _make_service(
    notifier: TelegramNotifier,
) -> NotificationDispatchService:
    """Build a service with group settings enabled.

    Faz 0b: group mirroring is gone, so these settings must not change
    behaviour — every message goes to the operator chat only.
    """
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=True):
        return NotificationDispatchService(notifier, sleeper=lambda _: None)


# ============================================================================
# Faz 0b: the customer group never receives signal content
# ============================================================================


def test_no_message_is_sent_to_the_group():
    """Group settings enabled + robust tickers still route nothing to the group."""
    sent: list[tuple[str, str]] = []

    def sender(base_url, chat_id, text, **kwargs) -> bool:
        sent.append((chat_id, text))
        return True

    notifier = TelegramNotifier(token="mock-token", chat_id="mock-chat", sender=sender)
    svc = _make_service(notifier)
    signal = _make_signal(ticker="TUPRS.IS", score=30.0, is_actionable=True)
    svc.notify_scan_results([signal], [signal], total_scanned=1)

    assert sent, "operator must still receive the scan summary"
    assert all(chat_id == "mock-chat" for chat_id, _ in sent)
    assert all("AL SİNYALİ" not in text or chat_id == "mock-chat" for chat_id, text in sent)


def test_group_settings_no_longer_change_message_count():
    notifier, captured = _make_notifier_with_fake_sender()
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=False):
        svc_disabled = NotificationDispatchService(notifier, sleeper=lambda _: None)
    signal = _make_signal(ticker="TUPRS.IS", score=30.0, is_actionable=True)
    svc_disabled.notify_scan_results([signal], [signal], total_scanned=1)

    notifier2, captured2 = _make_notifier_with_fake_sender()
    svc_enabled = _make_service(notifier2)
    svc_enabled.notify_scan_results([signal], [signal], total_scanned=1)

    assert len(captured) == len(captured2) == 2  # summary + detail, operator only


def test_notifier_group_chat_id_gated_by_flag():
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=False):
        notifier = TelegramNotifier(
            token="mock-token", chat_id="mock-chat", sender=lambda **k: True
        )
        assert notifier.group_chat_id is None
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=True):
        notifier = TelegramNotifier(
            token="mock-token", chat_id="mock-chat", sender=lambda **k: True
        )
        assert notifier.group_chat_id == "mock-group"


# ============================================================================
# CSV consistency: load_watchlist("robust") must mirror results/robust_watchlist.csv
# ============================================================================


def test_load_watchlist_matches_csv_file_contents():
    """load_watchlist('robust') must equal the parsed CSV ticker column.

    Including fallback for missing or empty file (returns []).
    """
    csv_path = Path(__file__).resolve().parents[1] / "results" / "robust_watchlist.csv"
    assert csv_path.exists(), f"Missing CSV at {csv_path}"

    csv_tickers: list[str] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        assert header is not None
        for row in reader:
            if row:
                csv_tickers.append(row[0].strip())

    loaded = load_watchlist("robust")
    assert loaded == csv_tickers, f"load_watchlist returned {loaded}, CSV has {csv_tickers}"


def test_load_watchlist_handles_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHLIST_ROBUST_PATH", str(tmp_path / "does_not_exist.csv"))
    assert load_watchlist("robust") == []


def test_load_watchlist_returns_h6_on_list():
    """Sanity check: the loaded list IS the H6-ON robust set."""
    loaded = set(load_watchlist("robust"))
    assert loaded == ROBUST_SET, f"got {loaded}"


def test_overfit_names_excluded_from_h6_on_robust_set():
    """Hard guard: ASELS / GARAN / SAHOL etc. MUST NOT be in the robust set.

    These names failed H6-ON stress test (overfit). If they reappear, group
    dispatch would route overfit names to the public channel again.
    """
    loaded = set(load_watchlist("robust"))
    leaked = loaded & OVERFIT_NAMES
    assert not leaked, f"Overfit names leaked into robust set: {leaked}"


# ============================================================================
# (a) Actionable signal → owner gets AL SİNYALİ; group gets nothing
# ============================================================================


def test_actionable_signal_goes_to_owner_only():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="ASTOR.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        is_actionable=True,
    )
    assert signal.ticker in ROBUST_SET

    svc.notify_scan_results([signal], [signal], 10)

    assert len(captured) == 2, f"Expected summary + detail; got {len(captured)}"
    assert "BIST TARAMA RAPORU" in captured[0]
    detail_msg = captured[1]
    assert "AL SİNYALİ" in detail_msg
    assert "actionable" in detail_msg


# ============================================================================
# (b) Radar signal → owner gets RADAR / İZLE; group gets nothing
# ============================================================================


def test_radar_signal_goes_to_owner_only():
    """Positive RADAR signals get detail messages (with 'RADAR / İZLE' label)."""
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="PETKM.IS",
        signal_type=SignalType.WEAK_BUY,
        score=10.0,
    )
    assert signal.ticker in ROBUST_SET

    svc.notify_scan_results([signal], [], 10)

    assert len(captured) == 2
    assert "BIST TARAMA RAPORU" in captured[0]
    assert "RADAR / İZLE" in captured[1]


# ============================================================================
# (c) Radar signal outside the robust watchlist → owner detail only
# ============================================================================


def test_radar_signal_outside_robust_goes_to_owner_only():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="TAVHL.IS",  # not in H6-ON robust
        signal_type=SignalType.WEAK_BUY,
        score=10.0,
    )
    assert signal.ticker not in ROBUST_SET

    svc.notify_scan_results([signal], [], 10)

    assert len(captured) == 2
    assert "BIST TARAMA RAPORU" in captured[0]
    assert "RADAR / İZLE" in captured[1]


# ============================================================================
# (c2) Overfit names: owner detail only, nothing leaves the operator chat
# ============================================================================


def test_overfit_names_stay_with_the_operator():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signals = [
        _make_signal(ticker="ASELS.IS", signal_type=SignalType.BUY, score=50.0),
        _make_signal(ticker="GARAN.IS", signal_type=SignalType.BUY, score=50.0),
        _make_signal(ticker="SAHOL.IS", signal_type=SignalType.BUY, score=50.0),
    ]
    assert all(s.ticker in OVERFIT_NAMES for s in signals)
    svc.notify_scan_results(signals, signals, 10)

    assert len(captured) == 4  # summary + 3 details, all to the operator
    assert sum("AL SİNYALİ" in msg for msg in captured) == 3


# ============================================================================
# (c3) Many actionable signals → one summary + one detail each, no batch copy
# ============================================================================


def test_many_signals_do_not_trigger_a_group_batch_message():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    robust_tickers = ["ASTOR.IS", "TUPRS.IS", "PETKM.IS", "SISE.IS", "GUBRF.IS", "ENKAI.IS"]
    signals = [
        _make_signal(ticker=t, signal_type=SignalType.BUY, score=30.0) for t in robust_tickers
    ]
    assert all(s.ticker in ROBUST_SET for s in signals)

    svc.notify_scan_results(signals, signals, 10)

    assert len(captured) == 7  # summary + 6 details
    assert not any("Grup Özet" in msg for msg in captured)


# ============================================================================
# (d) Negative score → summary only (no owner detail)
# ============================================================================


def test_negative_score_skipped_everywhere():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="GUBRF.IS",
        signal_type=SignalType.SELL,
        score=-15.0,
    )

    svc.notify_scan_results([signal], [], 10)

    assert len(captured) == 1, f"Expected only the operator summary, got {len(captured)}"
    assert "BIST TARAMA RAPORU" in captured[0]


# ============================================================================
# (e) agreement_ratio in diagnosis block; gates reasons under 🛡️
# ============================================================================


def test_diagnosis_shows_agreement_ratio_and_gates():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="ASTOR.IS",
        signal_type=SignalType.BUY,
        score=30.0,
        agreement_ratio=0.75,
        confidence="confidence.high",
        reasons=[
            "Momentum: +8 (trend teyitli)",
            "Karşıt-trend bastırma: MTF trend zayıf, skor 20'ye düştü",
            "MTF çelişki → nötr: güçlü trend yok, pozisyon açılmıyor",
        ],
    )

    svc.notify_scan_results([signal], [signal], 10)

    msg = captured[1]

    assert "Bileşen uyumu: 3/4" in msg

    assert "🛡️ Uygulanan korumalar:" in msg
    assert "Karşıt-trend bastırma" in msg
    assert "MTF çelişki" in msg


# ============================================================================
# (f) Multiple robust signals → each group message uses full detail format
# ============================================================================


def test_multiple_signals_send_one_detail_each_to_the_operator():
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signals = [
        _make_signal(ticker="ASTOR.IS", signal_type=SignalType.BUY, score=30.0),
        _make_signal(ticker="TUPRS.IS", signal_type=SignalType.BUY, score=28.0),
        _make_signal(ticker="PETKM.IS", signal_type=SignalType.WEAK_BUY, score=15.0),
    ]
    actionable = [s for s in signals if s.score >= 20]
    assert all(s.ticker in ROBUST_SET for s in signals)

    svc.notify_scan_results(signals, actionable, 10)

    # 3 signals: 2 AL + 1 positive RADAR — all get detail messages, operator only
    assert len(captured) == 4
    assert "BIST TARAMA RAPORU" in captured[0]
    details = captured[1:4]
    assert all("📋 <b>Nedenler:</b>" in message for message in details)
    assert all("🔍 <b>Teşhis:</b>" in message for message in details)


# ============================================================================
# (g) confidence.single-source: agreement-based, not score-based
# ============================================================================


def test_header_uses_agreement_not_score_for_confidence() -> None:
    """score-based (risk_levels.confidence) must not drive the header.

    score=41 >= buy_threshold(40) would have previously produced
    confidence.high via score eşiği. With agreement_ratio=0.5 (2/4)
    the signal must show confidence.medium. Both header and Teşhis
    must use signal.confidence (agreement-based, single source).
    """
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="ASTOR.IS",
        signal_type=SignalType.BUY,
        score=41.0,
        agreement_ratio=0.5,
        confidence="confidence.medium",
    )
    svc.notify_scan_results([signal], [signal], 10)

    detail_msg = captured[1]
    assert "confidence.medium" in detail_msg, (
        "Header must use signal.confidence (agreement-based MEDIUM), not score-based HIGH"
    )
    assert "confidence.high" not in detail_msg, (
        "score >= buy_threshold must never make the header show HIGH "
        "when agreement_ratio is only 2/4"
    )
