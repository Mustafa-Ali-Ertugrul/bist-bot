from __future__ import annotations

import html

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.locales import get_message
from bist_bot.ui.components.metric_block import render_metric_block
from bist_bot.ui.runtime import api_request


def _badge(label: str, positive: bool = True) -> str:
    cls = "bb-badge bb-badge-positive" if positive else "bb-badge"
    return f"<span class='{cls}'>{html.escape(label)}</span>"


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        try:
            return int(value)
        except ValueError:
            return default
    try:
        return default if value is None else int(str(value))
    except (TypeError, ValueError):
        return default


def _resolve_scan_metrics(
    *,
    session_scan_stats: dict[str, int] | None,
    latest_scan: dict[str, object],
    all_data: dict[str, object],
) -> tuple[int, int]:
    scanned_assets = _to_int(latest_scan.get("total_scanned", 0))
    actionable_signals = _to_int(
        latest_scan.get("actionable", latest_scan.get("signals_generated", 0))
    )

    session_scanned = len(all_data) if isinstance(all_data, dict) else 0
    session_stats = session_scan_stats or {}
    if session_scanned > scanned_assets and isinstance(session_stats, dict):
        scanned_assets = session_scanned
        actionable_signals = _to_int(session_stats.get("actionable", 0))

    return scanned_assets, actionable_signals


def _rejection_label(reason_code: str) -> str:
    labels = {
        "insufficient_history": "Yetersiz veri",
        "adx_missing": "ADX eksik",
        "score_filtered_sideways": "Yatay piyasa filtresi",
        "score_filtered_momentum": "Momentum onayi yetersiz",
        "score_zero_after_penalty": "Skor sifirlandi",
        "sector_limit_blocked": "Sektor limiti",
        "portfolio_risk_blocked": "Portfoy risk limiti",
        "meta_model_blocked": "Meta-model elemesi",
        "mtf_confluence_blocked": "MTF uyumsuzlugu",
        "hold_neutral_zone": "Notr bolge",
    }
    return labels.get(reason_code, reason_code.replace("_", " ").title())


def _stage_label(stage: str) -> str:
    labels = {
        "data": "Veri",
        "indicators": "Gostergeler",
        "scoring": "Skorlama",
        "classification": "Siniflandirma",
        "risk": "Risk",
        "mtf": "MTF",
    }
    return labels.get(stage, stage)


def _render_rejection_stage_summary(breakdown: dict[str, object]) -> str:
    total_rejections = _to_int(breakdown.get("total_rejections", 0))
    if total_rejections <= 0:
        return ""
    raw_rows = breakdown.get("by_stage", [])
    rows = raw_rows if isinstance(raw_rows, list) else []
    top_rows = rows[:3]
    badges: list[str] = []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage", "") or "")
        count = _to_int(row.get("count", 0))
        if stage and count > 0:
            badges.append(_badge(f"{_stage_label(stage)} {count}", positive=False))
    if not badges:
        return ""
    return (
        "<div class='bb-list-row' style='margin-top:10px;'>"
        "<div><div class='bb-label'>Aşama dağılımı</div>"
        "<div class='bb-list-row-subtitle'>En cok eleme yapan katmanlar</div></div>"
        f"<div style='display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;'>{''.join(badges)}</div>"
        "</div>"
    )


def _render_rejection_breakdown(
    breakdown: dict[str, object],
    *,
    scanned: int = 0,
    generated: int = 0,
) -> str:
    total_rejections = _to_int(breakdown.get("total_rejections", 0))
    if total_rejections <= 0:
        return ""
    raw_rows = breakdown.get("by_reason", [])
    rows = raw_rows if isinstance(raw_rows, list) else []
    top_rows = rows[:3]
    items: list[str] = []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        reason_code = str(row.get("reason_code", "") or "")
        count = _to_int(row.get("count", 0))
        if not reason_code or count <= 0:
            continue
        items.append(
            "<div class='bb-list-row'>"
            f"<div><div class='bb-label'>{html.escape(_rejection_label(reason_code))}</div>"
            f"<div class='bb-list-row-subtitle'>{html.escape(reason_code)}</div></div>"
            f"<div class='bb-note-strong'>{count}</div>"
            "</div>"
        )
    if not items:
        return ""

    outcome_html = ""
    if scanned > 0:
        accounted = generated + total_rejections
        outcome_html = (
            "<div style='margin-top:8px;'>"
            f"<div class='bb-list-row-subtitle'>Uretilen: {generated} | Elenen: {total_rejections} | Hesaplanan: {accounted}/{scanned}</div>"
            "</div>"
        )

    return (
        "<div style='height:14px;'></div>"
        "<div class='bb-list-row'>"
        f"<div><div class='bb-label'>En yaygın blokajlar</div><div class='bb-list-row-subtitle'>{total_rejections} aday elendi</div></div>"
        "</div>"
        f"<div class='bb-list'>{''.join(items)}</div>"
        f"{_render_rejection_stage_summary(breakdown)}"
        f"{outcome_html}"
    )


def render_overview_page() -> None:
    st.title(get_message("ui.overview_title"))

    try:
        stats_response = api_request("GET", "/api/stats")
        signals_response = api_request("GET", "/api/signals/history", params={"limit": 20})
    except Exception as exc:
        st.warning(f"{get_message('ui.api_data_failed')}: {exc}")
        return

    stats = stats_response.json().get("stats", {}) if stats_response.ok else {}
    signals_payload = signals_response.json().get("signals", []) if signals_response.ok else []

    total_signals = stats.get("total_signals", 0)
    completed = stats.get("completed", 0)
    profitable = stats.get("profitable", 0)
    win_rate = stats.get("win_rate", 0.0)
    avg_profit = stats.get("avg_profit_pct", 0.0)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_block(
            get_message("ui.total_signals"), str(total_signals), get_message("ui.signals_over_time")
        )
    with c2:
        render_metric_block(
            get_message("ui.trades_completed"), str(completed), get_message("ui.trade_result_known")
        )
    with c3:
        render_metric_block(
            get_message("ui.profitable"), str(profitable), get_message("ui.profit_made")
        )
    with c4:
        render_metric_block(
            get_message("ui.win_rate"),
            f"%{win_rate:.1f}",
            f"{get_message('ui.avg_profit')}: %{avg_profit:.1f}",
        )

    st.subheader(get_message("ui.recent_signals"))
    if not signals_payload:
        st.info(get_message("ui.no_signals_yet"))
    else:
        cols = st.columns([1, 1, 1, 1, 1, 1, 1])
        headers = [
            get_message("ui.ticker"),
            get_message("ui.type"),
            get_message("ui.price"),
            get_message("ui.lot"),
            get_message("ui.score"),
            get_message("ui.status"),
            get_message("ui.date"),
        ]
        for col, header in zip(cols, headers, strict=True):
            col.markdown(f"**{header}**")

        for sig in signals_payload[:10]:
            cols = st.columns([1, 1, 1, 1, 1, 1, 1])
            cols[0].markdown(f"`{sig.get('ticker', '').replace('.IS', '')}`")
            cols[1].markdown(sig.get("signal_type", ""))
            cols[2].markdown(f"₺{sig.get('price', 0):.2f}")
            cols[3].markdown(str(sig.get("position_size", "-")))
            score = float(sig.get("score", 0) or 0)
            score_prefix = "Güçlü " if score >= settings.STRONG_BUY_THRESHOLD else ""
            cols[4].markdown(f"{score_prefix}{score:+.0f}")
            cols[5].markdown(sig.get("outcome", get_message("ui.pending")))
            cols[6].markdown(sig.get("timestamp", "")[:10])
