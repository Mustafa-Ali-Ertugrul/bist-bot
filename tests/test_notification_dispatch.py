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
    """Build a service whose group chat_id is test-controlled.

    ``_make_signal`` already uses a far-future timestamp so the real
    ``is_expired`` returns False without patching.
    """
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=True):
        svc = NotificationDispatchService(notifier, sleeper=lambda _: None)
    assert svc._group_chat_id == "mock-group"
    return svc


# ============================================================================
# TELEGRAM_GROUP_ENABLED flag gating
# ============================================================================


def test_group_mirroring_skipped_when_flag_disabled():
    """TELEGRAM_GROUP_ENABLED=false iken chat id dolu olsa bile grup kopyasi gitmez."""
    notifier, captured = _make_notifier_with_fake_sender()
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=False):
        svc = NotificationDispatchService(notifier, sleeper=lambda _: None)
        assert svc._group_chat_id is None

        signal = _make_signal(ticker="TUPRS.IS", score=30.0, is_actionable=True)
        svc.notify_scan_results([signal], [signal], total_scanned=1)

    summaries = [t for t in captured if "TARAMA RAPORU" in t]
    assert len(summaries) == 1  # sadece ozel sohbet; grup kopyasi yok


def test_group_mirroring_sends_when_flag_enabled():
    notifier, captured = _make_notifier_with_fake_sender()
    with settings.override(TELEGRAM_GROUP_CHAT_ID="mock-group", TELEGRAM_GROUP_ENABLED=True):
        svc = NotificationDispatchService(notifier, sleeper=lambda _: None)
        signal = _make_signal(ticker="TUPRS.IS", score=30.0, is_actionable=True)
        svc.notify_scan_results([signal], [signal], total_scanned=1)

    summaries = [t for t in captured if "TARAMA RAPORU" in t]
    assert len(summaries) == 2  # ozel + grup


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
# (a) Actionable signal → owner gets AL SİNYALİ; robust member gets group
# ============================================================================


def test_actionable_signal_to_owner_and_group():
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

    assert len(captured) >= 2, f"Expected scan summary + detail; got {len(captured)}"

    detail_msg = captured[1]
    assert "AL SİNYALİ" in detail_msg
    assert "actionable" in detail_msg

    assert captured[2] == captured[0]
    assert captured[3] == detail_msg
    assert "AL SİNYALİ" in captured[3]


# ============================================================================
# (b) Radar signal → owner gets RADAR / İZLE; robust member gets group İZLE
# ============================================================================


def test_radar_signal_to_owner_and_group_if_robust():
    """Positive RADAR signals now get detail messages (with 'RADAR / İZLE' label)."""
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="PETKM.IS",
        signal_type=SignalType.WEAK_BUY,
        score=10.0,
    )
    assert signal.ticker in ROBUST_SET

    svc.notify_scan_results([signal], [], 10)

    # Owner: summary + detail with RADAR / İZLE label
    # Group:  summary + detail (mirrored)
    assert len(captured) == 4
    assert "BIST TARAMA RAPORU" in captured[0]
    assert "RADAR / İZLE" in captured[1]
    assert captured[2] == captured[0]  # group summary == owner summary
    assert captured[3] == captured[1]  # group detail == owner detail


# ============================================================================
# (c) Radar signal outside robust watchlist → owner detail only, no group detail
# ============================================================================


def test_radar_signal_outside_robust_not_sent_to_group():
    """Positive RADAR outside robust watchlist gets owner detail but NOT group detail.

    Group detail routing is protected by the robust watchlist so overfit names
    never reach the public channel.
    """
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signal = _make_signal(
        ticker="TAVHL.IS",  # not in H6-ON robust
        signal_type=SignalType.WEAK_BUY,
        score=10.0,
    )
    assert signal.ticker not in ROBUST_SET

    svc.notify_scan_results([signal], [], 10)

    # Owner: summary + detail; Group: summary only (no detail for non-robust)
    assert len(captured) == 3
    assert "BIST TARAMA RAPORU" in captured[0]
    assert "RADAR / İZLE" in captured[1]
    assert captured[2] == captured[0]  # group summary == owner summary


# ============================================================================
# (c2) Overfit names get owner detail but are blocked from the group
# ============================================================================


def test_overfit_names_do_not_reach_group():
    """Overfit names (failed H6-ON stress) get owner detail but NOT group detail."""
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    signals = [
        _make_signal(ticker="ASELS.IS", signal_type=SignalType.BUY, score=50.0),
        _make_signal(ticker="GARAN.IS", signal_type=SignalType.BUY, score=50.0),
        _make_signal(ticker="SAHOL.IS", signal_type=SignalType.BUY, score=50.0),
    ]
    assert all(s.ticker in OVERFIT_NAMES for s in signals)
    svc.notify_scan_results(signals, signals, 10)

    # Owner: summary + 3 details; Group: summary only (all overfit, none robust)
    assert len(captured) == 5
    assert captured[4] == captured[0]  # group summary == owner summary
    # No group detail messages for overfit names
    assert all("AL SİNYALİ" not in msg for msg in captured[4:])


# ============================================================================
# (c3) Batch protection: many robust signals → single compact group summary
# ============================================================================


def test_batch_protection_sends_single_summary_when_many_robust_signals():
    """When robust detail signals exceed the batch threshold, send one summary."""
    notifier, captured = _make_notifier_with_fake_sender()
    svc = _make_service(notifier)

    robust_tickers = ["ASTOR.IS", "TUPRS.IS", "PETKM.IS", "SISE.IS", "GUBRF.IS", "ENKAI.IS"]
    signals = [
        _make_signal(ticker=t, signal_type=SignalType.BUY, score=30.0) for t in robust_tickers
    ]
    assert all(s.ticker in ROBUST_SET for s in signals)
    assert len(signals) > svc._batch_threshold

    svc.notify_scan_results(signals, signals, 10)

    # Owner: summary + 6 details (indices 0-6); Group: summary + 1 batch (7-8)
    assert len(captured) == 9
    assert captured[7] == captured[0]  # group summary == owner summary
    batch_msg = captured[8]
    assert "Grup Özet" in batch_msg
    assert "6 robust sinyal" in batch_msg


# ============================================================================
# (d) Negative score → neither owner detail nor group
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

    assert len(captured) == 2, f"Expected owner and group summaries, got {len(captured)}"
    assert "BIST TARAMA RAPORU" in captured[0]
    assert captured[1] == captured[0]


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


def test_multiple_robust_signals_send_full_details_to_group():
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

    # 3 signals: 2 AL + 1 positive RADAR — all get detail messages
    # captured order:
    # 0: summary (owner)
    # 1: ASTOR detail (owner) — AL
    # 2: TUPRS detail (owner) — AL
    # 3: PETKM detail (owner) — RADAR / İZLE
    # 4: summary (group)
    # 5: ASTOR detail (group)
    # 6: TUPRS detail (group)
    # 7: PETKM detail (group)
    owner_details = captured[1:4]
    assert captured[4] == captured[0]
    group_details = captured[5:8]
    assert group_details == owner_details
    assert all("📋 <b>Nedenler:</b>" in message for message in group_details)
    assert all("🔍 <b>Teşhis:</b>" in message for message in group_details)


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
