from __future__ import annotations

import html

import streamlit as st

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
    recent_signals = signals_response.json().get("signals", []) if signals_response.ok else []
    index_data = fetch_index_data()

    # total signals from DB: int(stats.get("total_signals", len(signals)) or 0)
    profitable = int(stats.get("profitable", 0) or 0)
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    avg_profit = float(stats.get("avg_profit_pct", 0.0) or 0.0)
    positive_flow = len([s for s in signals if s.score >= 10])
    strong = sorted([s for s in signals if s.score >= 40], key=lambda s: s.score, reverse=True)
    active_watch = (
        strong[:4] if strong else sorted(signals, key=lambda s: s.score, reverse=True)[:4]
    )

    render_page_hero(
        "Trading Dashboard",
        "Premium BIST control center for live execution flow",
        "Dashboard ekranini mobil-first bir command deck yapisina tasidim. Canli performans, radar firsatlari ve son sinyal hareketleri tek koyu tema yuzeyde toplandi.",
        badges=[
            f"{positive_flow} positive signals",
            f"Win rate %{win_rate:.1f}",
            f"Avg profit %{avg_profit:.1f}",
        ],
        accent="secondary",
    )

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        scanned = latest_scan.get("total_scanned", summary.get("total_analyzed", 0))
        render_metric_block("Scanned assets", str(scanned), "Total assets analyzed")
    with k2:
        actionable = latest_scan.get(
            "actionable",
            int(latest_scan.get("buy_signals", 0) or 0)
            + int(latest_scan.get("sell_signals", 0) or 0),
        )
        render_metric_block("Actionable signals", str(actionable), "Signals requiring attention")
    with k3:
        render_metric_block(
            "Profitable closes",
            str(profitable),
            "Sessions finished in green",
            accent="positive",
        )
    with k4:
        render_metric_block(
            "Win rate",
            f"%{win_rate:.1f}",
            f"Avg profit %{avg_profit:.1f}",
            accent="positive" if win_rate >= 50 else "danger",
        )

    left, right = st.columns([1.35, 1], gap="large")
    with left:
        render_section_title("Market pulse", "Top conviction ideas")
        radar_rows = []
        for signal in active_watch:
            radar_rows.append(
                "<div class='bb-list-row'>"
                "<div>"
                f"<div class='bb-list-row-title'>{html.escape(signal.ticker.replace('.IS', ''))}</div>"
                f"<div class='bb-list-row-subtitle'>{html.escape(signal.signal_type.display)} • Confidence {html.escape(str(signal.confidence).replace('confidence.', '').upper())}</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<div class='bb-note-strong'>TL{signal.price:.2f}</div>"
                f"<div class='bb-list-row-subtitle'>Score {signal.score:+.0f}</div>"
                "</div>"
                "</div>"
            )
        radar_html = "".join(radar_rows) or "<div class='bb-note'>Scan data not ready yet.</div>"
        render_html_panel(
            (
                f"<div class='bb-section-caption'>Scan coverage {summary.get('total_analyzed', 0)} assets</div>"
                "<div style='display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0 18px;'>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Average RSI</div><div class='bb-note-strong'>{summary.get('avg_rsi', 50):.1f}</div></div></div>"
                f"<div class='bb-list-row'><div><div class='bb-label'>Volume ratio</div><div class='bb-note-strong'>{summary.get('avg_vol_ratio', 1.0):.2f}x</div></div></div>"
                "</div>"
                f"<div class='bb-list'>{radar_html}</div>"
            ),
            accent="positive",
        )

    with right:
        render_section_title("Benchmarks", "Market context")
        index_rows = []
        for name, data in index_data.items():
            change = float(data.get("change_pct", 0.0) or 0.0)
            index_rows.append(
                "<div class='bb-list-row'>"
                "<div>"
                f"<div class='bb-list-row-title'>{html.escape(name)}</div>"
                f"<div class='bb-list-row-subtitle'>Live reference basket</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<div class='bb-note-strong'>{float(data.get('value', 0.0) or 0.0):,.2f}</div>"
                f"<div class='{'bb-text-positive' if change >= 0 else 'bb-text-danger'}'>{change:+.2f}%</div>"
                "</div>"
                "</div>"
            )
        tone = summary.get("sector_dist", {})
        render_html_panel(
            "<div class='bb-list'>"
            + "".join(index_rows)
            + "</div>"
            + "<div style='height:14px;'></div>"
            + "<div class='bb-list-row'>"
            + "<div><div class='bb-label'>Sentiment map</div><div class='bb-list-row-subtitle'>Oversold / neutral / overbought split</div></div>"
            + "<div style='display:flex;gap:8px;flex-wrap:wrap;'>"
            + _badge(f"OS {tone.get('Asiri Satim', 0)}")
            + _badge(f"NTR {tone.get('Notr', 0)}", positive=False)
            + _badge(f"OB {tone.get('Asiri Alim', 0)}")
            + "</div></div>"
        )

    render_section_title("Recent flow", "Last 10 recorded signals")
    if not recent_signals:
        st.info(get_message("ui.no_signals_yet"))
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
