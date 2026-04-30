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


def _format_confidence_label(confidence: str) -> str:
    confidence_key = str(confidence or "confidence.low")
    return get_message(confidence_key)


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

    stats = stats_response.json().get("stats", {}) if stats_response.ok else {}
    recent_signals = signals_response.json().get("signals", []) if signals_response.ok else []
    index_data = fetch_index_data()

    # Read latest_scan from both locations for backward compatibility
    raw_latest = stats.get("latest_scan") or stats_response.json().get("latest_scan")
    latest_scan = raw_latest if isinstance(raw_latest, dict) else {}
    scanned_assets = int(latest_scan.get("total_scanned", summary.get("total_analyzed", 0)) or 0)
    actionable_signals = int(
        latest_scan.get("actionable", latest_scan.get("signals_generated", 0)) or 0
    )
    profitable = int(stats.get("profitable", 0) or 0)
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    avg_profit = float(stats.get("avg_profit_pct", 0.0) or 0.0)
    active_signals = [s for s in signals if getattr(s.signal_type, "name", "") != "HOLD"]
    strong = sorted(
        [s for s in active_signals if s.score >= 40], key=lambda s: s.score, reverse=True
    )
    active_watch = (
        strong[:4] if strong else sorted(active_signals, key=lambda s: s.score, reverse=True)[:4]
    )
    summary_ready = int(summary.get("total_analyzed", 0) or 0) > 0
    index_ready = any(float(data.get("value", 0.0) or 0.0) > 0 for data in index_data.values())

    render_page_hero(
        "İşlem Paneli",
        "Canlı işlem akışı için premium BIST kontrol merkezi",
        "Panel ekranını mobil uyumlu bir kontrol merkezine dönüştürdük. Canlı performans, radar fırsatları ve son sinyaller tek koyu tema içinde sunuluyor.",
        badges=[
            f"{actionable_signals} pozitif sinyal",
            f"Kazanma oranı %{win_rate:.1f}",
            f"Ortalama kâr %{avg_profit:.1f}",
        ],
        accent="secondary",
    )

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
            radar_rows.append(
                "<div class='bb-list-row'>"
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
            f"Tarama kapsamı: {summary.get('total_analyzed', 0)} varlık"
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
        benchmark_html = (
            "<div class='bb-list'>" + "".join(index_rows) + "</div>"
            if index_ready
            else "<div class='bb-note'>Karşılaştırma verisi henüz hazır değil.</div>"
        )
        render_html_panel(benchmark_html + "<div style='height:14px;'></div>" + sentiment_html)

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
