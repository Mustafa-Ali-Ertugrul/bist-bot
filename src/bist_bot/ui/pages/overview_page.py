from __future__ import annotations

import html

import streamlit as st

from bist_bot.config.settings import settings
from bist_bot.locales import get_message
from bist_bot.ui.components.app_shell import (
    render_html_panel,
    render_page_hero,
    render_section_title,
)
from bist_bot.ui.components.metric_block import render_metric_block
from bist_bot.ui.runtime import (
    api_request,
    fetch_index_data,
    filter_signals,
    get_market_summary,
)


def _badge(label: str, positive: bool = True) -> str:
    cls = "bb-badge bb-badge-positive" if positive else "bb-badge"
    return f"<span class='{cls}'>{html.escape(label)}</span>"


def _format_confidence_label(confidence: str) -> str:
    confidence_key = str(confidence or "confidence.low")
    return get_message(confidence_key)


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
    summary: dict[str, object],
) -> tuple[int, int]:
    session_scan_stats = session_scan_stats or {}
    session_scanned = _to_int(summary.get("total_analyzed", 0))
    session_generated = _to_int(session_scan_stats.get("generated", 0))
    session_actionable = _to_int(session_scan_stats.get("actionable", 0))

    if session_scanned > 0 or session_generated > 0:
        return session_scanned, session_actionable

    scanned_assets = _to_int(latest_scan.get("total_scanned", 0))
    actionable_signals = _to_int(
        latest_scan.get("actionable", latest_scan.get("signals_generated", 0))
    )
    return scanned_assets, actionable_signals


def _rejection_label(reason_code: str) -> str:
    labels = {
        "insufficient_history": "Yetersiz veri",
        "adx_missing": "ADX eksik",
        "score_filtered_sideways": "Yatay piyasa filtresi",
        "score_filtered_momentum": "Momentum onayı yetersiz",
        "score_zero_after_penalty": "Skor sıfırlandı",
        "sector_limit_blocked": "Sektör limiti",
        "portfolio_risk_blocked": "Portföy risk limiti",
        "meta_model_blocked": "Meta-model elemesi",
        "mtf_confluence_blocked": "MTF uyumsuzluğu",
        "hold_neutral_zone": "Nötr bölge (beklemede)",
    }
    return labels.get(reason_code, reason_code.replace("_", " ").title())


def _stage_label(stage: str) -> str:
    labels = {
        "data": "Veri",
        "indicators": "Göstergeler",
        "scoring": "Skorlama",
        "classification": "Sınıflandırma",
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
    if not top_rows:
        return ""
    badges: list[str] = []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage", "") or "")
        count = _to_int(row.get("count", 0))
        if not stage or count <= 0:
            continue
        badges.append(_badge(f"{_stage_label(stage)} {count}", positive=False))
    if not badges:
        return ""
    return (
        "<div class='bb-list-row' style='margin-top:10px;'>"
        "<div><div class='bb-label'>Aşama dağılımı</div>"
        "<div class='bb-list-row-subtitle'>En çok eleme yapan katmanlar</div></div>"
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
    if not top_rows:
        return ""
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
    stage_summary = _render_rejection_stage_summary(breakdown)

    # Outcome accounting
    outcome_html = ""
    if scanned > 0:
        accounted = generated + total_rejections
        invariant_held = accounted == scanned
        invariant_color = "positive" if invariant_held else "danger"
        invariant_icon = "✓" if invariant_held else "✗"
        invariant_text = (
            f"{invariant_icon} {accounted}/{scanned} hesaplandı"
            if invariant_held
            else f"{invariant_icon} {accounted}/{scanned} hesaplandı (fark: {scanned - accounted})"
        )
        outcome_html = (
            "<div style='margin-top:8px;'>"
            f"<div class='bb-text-{invariant_color}' style='font-size:0.85em;'>{invariant_text}</div>"
            f"<div class='bb-list-row-subtitle'>Üretilen: {generated} • Elenen: {total_rejections}</div>"
            "</div>"
        )

    return (
        "<div style='height:14px;'></div>"
        "<div class='bb-list-row'>"
        f"<div><div class='bb-label'>En yaygın blokajlar</div><div class='bb-list-row-subtitle'>{total_rejections} aday elendi</div></div>"
        "</div>"
        f"<div class='bb-list'>{''.join(items)}</div>"
        f"{stage_summary}"
        f"{outcome_html}"
    )


def render_overview_page() -> None:
    all_data = st.session_state.get("all_data", {})
    signals = filter_signals(st.session_state.get("signals", []), all_data)
    summary = get_market_summary(signals, all_data)

    try:
        stats_response = api_request("GET", "/api/stats")
        signals_response = api_request("GET", "/api/signals/history", params={"limit": 20})
    except Exception as exc:
        st.warning(f"{get_message('ui.api_data_failed')}: {exc}")
        return

    response_payload = stats_response.json() if stats_response.ok else {}
    stats = response_payload.get("stats", {})
    latest_scan = stats.get("latest_scan") or response_payload.get("latest_scan") or {}
    rejection_breakdown = (
        stats.get("rejection_breakdown") or response_payload.get("rejection_breakdown") or {}
    )
    recent_signals = signals_response.json().get("signals", []) if signals_response.ok else []
    index_data = fetch_index_data()
    session_scan_stats = st.session_state.get("scan_stats")

    # Read latest_scan from both locations for backward compatibility
    raw_latest = stats.get("latest_scan") or (
        response_payload.get("latest_scan") if stats_response.ok else None
    )
    latest_scan = raw_latest if isinstance(raw_latest, dict) else {}
    scanned_assets, actionable_signals = _resolve_scan_metrics(
        session_scan_stats=session_scan_stats if isinstance(session_scan_stats, dict) else None,
        latest_scan=latest_scan,
        summary=summary,
    )
    profitable = int(stats.get("profitable", 0) or 0)
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    avg_profit = float(stats.get("avg_profit_pct", 0.0) or 0.0)
    active_signals = [s for s in signals if getattr(s.signal_type, "name", "") != "HOLD"]
    strong = sorted(
        [s for s in active_signals if s.score >= settings.STRONG_BUY_THRESHOLD],
        key=lambda s: s.score,
        reverse=True,
    )
    active_watch = (
        strong[:4] if strong else sorted(active_signals, key=lambda s: s.score, reverse=True)[:4]
    )
    summary_ready = scanned_assets > 0
    index_ready = any(float(data.get("value", 0.0) or 0.0) > 0 for data in index_data.values())

    render_page_hero(
        "İşlem Paneli",
        "BIST kontrol merkezi",
        "Canlı performans, radar fırsatları ve son sinyaller.",
        badges=[
            f"{actionable_signals} pozitif sinyal",
            f"Kazanma oranı %{win_rate:.1f}",
            f"Ortalama kâr %{avg_profit:.1f}",
        ],
        accent="secondary",
    )
    if st.session_state.get("scan_in_progress"):
        phase = st.session_state.get("scan_phase") or "Tarama baslatiliyor"
        st.info(f"Arka plan taramasi suruyor: {phase}")
    elif st.session_state.get("scan_error"):
        phase = st.session_state.get("scan_phase")
        detail = f" Son asama: {phase}" if phase else ""
        st.warning(f"Tarama tamamlanamadi: {st.session_state.scan_error}.{detail}")

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        render_metric_block("Taranan varlıklar", str(scanned_assets), "Toplam analiz edilen varlık")
    with k2:
        render_metric_block(
            "İşleme uygun sinyaller",
            str(actionable_signals),
            "İzleme veya işlem gerektiren sinyaller",
        )
    with k3:
        render_metric_block(
            "Kârlı kapanışlar",
            str(profitable),
            "Kârla kapanan işlemler",
            accent="positive",
        )
    with k4:
        render_metric_block(
            "Kazanma oranı",
            f"%{win_rate:.1f}",
            f"Ort. kâr %{avg_profit:.1f}",
            accent="positive" if win_rate >= 50 else "danger",
        )

    left, right = st.columns([1.35, 1], gap="large")
    with left:
        render_section_title("Piyasa görünümü", "Öne çıkan fırsatlar")
        radar_rows = []
        for signal in active_watch:
            is_radar = getattr(signal.signal_type, "name", "") == "RADAR"
            row_class = "bb-list-row bb-radar-card" if is_radar else "bb-list-row"
            radar_rows.append(
                f"<div class='{row_class}'>"
                "<div>"
                f"<div class='bb-list-row-title'>{html.escape(signal.ticker.replace('.IS', ''))}</div>"
                f"<div class='bb-list-row-subtitle'>{html.escape(signal.signal_type.display)} • Güven: {html.escape(_format_confidence_label(signal.confidence).title())}</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<div class='bb-note-strong'>TL{signal.price:.2f}</div>"
                f"<div class='bb-list-row-subtitle'>Skor: {signal.score:+.0f}</div>"
                "</div>"
                "</div>"
            )
        if radar_rows:
            radar_html = "".join(radar_rows)
        elif scanned_assets > 0:
            radar_html = (
                "<div class='bb-note-strong'>İşleme uygun sinyal bulunamadı</div>"
                "<div class='bb-note' style='margin-top:6px;'>Son taramada güçlü fırsat oluşmadı. Şu an izleme modunda.</div>"
            )
        else:
            radar_html = "<div class='bb-note'>Veri henüz hazır değil.</div>"
        scan_caption = (
            f"Tarama kapsamı: {scanned_assets} varlık"
            if summary_ready
            else "Veri henüz hazır değil"
        )
        overview_metrics = (
            "<div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0 18px;'>"
            f"<div class='bb-list-row'><div><div class='bb-label'>Ortalama RSI</div><div class='bb-note-strong'>{summary.get('avg_rsi', 0.0):.1f}</div></div></div>"
            f"<div class='bb-list-row'><div><div class='bb-label'>Hacim oranı</div><div class='bb-note-strong'>{summary.get('avg_vol_ratio', 0.0):.2f}x</div></div></div>"
            "</div>"
            if summary_ready
            else "<div class='bb-note' style='margin:14px 0 18px;'>Veri henüz hazır değil.</div>"
        )
        render_html_panel(
            (
                f"<div class='bb-section-caption'>{scan_caption}</div>"
                f"{overview_metrics}"
                f"<div class='bb-list'>{radar_html}</div>"
            ),
            accent="positive",
        )

    with right:
        render_section_title("Karşılaştırma göstergeleri", "Piyasa özeti")
        index_rows = []
        for name, data in index_data.items():
            change = float(data.get("change_pct", 0.0) or 0.0)
            value = float(data.get("value", 0.0) or 0.0)
            if value <= 0:
                continue
            index_rows.append(
                "<div class='bb-list-row'>"
                "<div>"
                f"<div class='bb-list-row-title'>{html.escape(name)}</div>"
                f"<div class='bb-list-row-subtitle'>Canlı referans gösterge</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<div class='bb-note-strong'>{value:,.2f}</div>"
                f"<div class='{'bb-text-positive' if change >= 0 else 'bb-text-danger'}'>{change:+.2f}%</div>"
                "</div>"
                "</div>"
            )
        tone = summary.get("sector_dist", {})
        if summary_ready:
            sentiment_html = (
                "<div class='bb-list-row'>"
                "<div><div class='bb-label'>Piyasa dağılımı</div><div class='bb-list-row-subtitle'>Aşırı satım / nötr / aşırı alım dağılımı</div></div>"
                "<div style='display:flex;gap:8px;flex-wrap:wrap;'>"
                + _badge(f"Aşırı Satım {tone.get('Asiri Satim', 0)}")
                + _badge(f"Nötr {tone.get('Notr', 0)}", positive=False)
                + _badge(f"Aşırı Alım {tone.get('Asiri Alim', 0)}")
                + "</div></div>"
            )
        else:
            sentiment_html = (
                "<div class='bb-list-row'>"
                "<div><div class='bb-label'>Piyasa dağılımı</div><div class='bb-list-row-subtitle'>Veri henüz hazır değil.</div></div>"
                "</div>"
            )
        rejection_html = (
            _render_rejection_breakdown(
                rejection_breakdown,
                scanned=scanned_assets,
                generated=actionable_signals,
            )
            if isinstance(rejection_breakdown, dict)
            else ""
        )
        benchmark_html = (
            "<div class='bb-list'>" + "".join(index_rows) + "</div>"
            if index_ready
            else "<div class='bb-note'>Karşılaştırma verisi henüz hazır değil.</div>"
        )
        render_html_panel(
            benchmark_html + "<div style='height:14px;'></div>" + sentiment_html + rejection_html
        )

    render_section_title("Son akış", "Kaydedilen son 10 sinyal")

    # Fallback: if API history is empty but session has signals, use session data
    if not recent_signals and signals:
        recent_signals = [
            {
                "ticker": s.ticker,
                "signal_type": s.signal_type.value,
                "score": s.score,
                "price": s.price,
                "position_size": s.position_size,
                "outcome": "PENDING",
                "timestamp": s.timestamp.isoformat() if s.timestamp else "",
            }
            for s in signals[:10]
        ]

    if not recent_signals:
        if scanned_assets > 0:
            st.info(
                "Son taramada kaydedilecek yeni sinyal oluşmadı. "
                "Yeni sinyal oluştuğunda burada listelenecek."
            )
        else:
            st.info("Henüz kayıtlı sinyal yok.")
        return

    headers = [
        get_message("ui.ticker"),
        get_message("ui.type"),
        get_message("ui.price"),
        get_message("ui.lot"),
        get_message("ui.score"),
        get_message("ui.status"),
        get_message("ui.date"),
    ]
    rows: list[str] = []
    for sig in recent_signals[:10]:
        score = float(sig.get("score", 0) or 0)
        outcome = html.escape(str(sig.get("outcome", get_message("ui.pending"))))
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(sig.get('ticker', '')).replace('.IS', ''))}</code></td>"
            f"<td>{html.escape(str(sig.get('signal_type', '')))}</td>"
            f"<td>TL{float(sig.get('price', 0) or 0):.2f}</td>"
            f"<td>{html.escape(str(sig.get('position_size', '-')))}</td>"
            f"<td class='{'bb-text-positive' if score >= 0 else 'bb-text-danger'}'>{score:+.0f}</td>"
            f"<td>{outcome}</td>"
            f"<td>{html.escape(str(sig.get('timestamp', ''))[:10])}</td>"
            "</tr>"
        )
    st.markdown(
        "<table class='bb-table'><thead><tr>"
        + "".join(f"<th>{html.escape(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>",
        unsafe_allow_html=True,
    )
