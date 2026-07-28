from __future__ import annotations

import html
from collections.abc import Callable

import streamlit as st

from bist_bot.ui.components.app_shell import (
    render_html_panel,
    render_page_hero,
    render_section_title,
)
from bist_bot.ui.components.metric_block import render_metric_block
from bist_bot.ui.pages.overview_page import (
    _candidate_rejection_count,
    _rejection_label,
    _stage_label,
    _to_int,
)
from bist_bot.ui.runtime import api_request


def _top_summary_item(rows: object, key_name: str) -> tuple[str, int]:
    if not isinstance(rows, list) or not rows:
        return "", 0
    first = rows[0]
    if not isinstance(first, dict):
        return "", 0
    raw_key = str(first.get(key_name, "") or "")
    count = _to_int(first.get("count", 0))
    if not raw_key or count <= 0:
        return "", 0
    return raw_key, count


def _format_rejection_rate(total_rejections: int, total_scanned: int) -> str:
    if total_scanned <= 0:
        return "%0.0"
    return f"%{(total_rejections / total_scanned) * 100:.1f}"


def _to_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return default
    try:
        return default if value is None else float(str(value))
    except (TypeError, ValueError):
        return default


def _render_scan_summary_chips(
    *, rejection_breakdown: dict[str, object], total_scanned: int
) -> str:
    reason_key, reason_count = _top_summary_item(
        rejection_breakdown.get("by_reason", []), "reason_code"
    )
    stage_key, stage_count = _top_summary_item(rejection_breakdown.get("by_stage", []), "stage")
    total_rejections = _to_int(rejection_breakdown.get("total_rejections", 0))
    top_blocker_label = _rejection_label(reason_key) if reason_key else "Nötr"
    top_stage_label = _stage_label(stage_key) if stage_key else "Nötr"
    rejection_rate = _format_rejection_rate(total_rejections, total_scanned)
    candidate_rejections = _candidate_rejection_count(total_scanned, 0)
    return (
        "<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0 18px;'>"
        "<div class='bb-list-row'><div><div class='bb-label'>En çok engelleyen</div>"
        f"<div class='bb-note-strong'>{html.escape(top_blocker_label)}</div>"
        f"<div class='bb-list-row-subtitle'>{html.escape(reason_key or 'neden yok')} • {reason_count}</div></div></div>"
        "<div class='bb-list-row'><div><div class='bb-label'>En çok eleyen aşama</div>"
        f"<div class='bb-note-strong'>{html.escape(top_stage_label)}</div>"
        f"<div class='bb-list-row-subtitle'>{html.escape(stage_key or 'aşama yok')} • {stage_count}</div></div></div>"
        "<div class='bb-list-row'><div><div class='bb-label'>Filtre kaydı oranı</div>"
        f"<div class='bb-note-strong'>{html.escape(rejection_rate)}</div>"
        f"<div class='bb-list-row-subtitle'>{total_rejections} filtre kaydı • en fazla {candidate_rejections} tekil aday</div></div></div>"
        "</div>"
    )


def _render_breakdown_list(
    *,
    title: str,
    subtitle: str,
    rows: object,
    key_name: str,
    label_fn: Callable[[str], str],
    empty_message: str,
    limit: int = 5,
) -> str:
    if not isinstance(rows, list) or not rows:
        return f"<div class='bb-note'>{html.escape(empty_message)}</div>"

    items: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        raw_key = str(row.get(key_name, "") or "")
        count = _to_int(row.get("count", 0))
        if not raw_key or count <= 0:
            continue
        items.append(
            "<div class='bb-list-row'>"
            f"<div><div class='bb-label'>{html.escape(label_fn(raw_key))}</div>"
            f"<div class='bb-list-row-subtitle'>{html.escape(raw_key)}</div></div>"
            f"<div class='bb-note-strong'>{count}</div>"
            "</div>"
        )

    if not items:
        return f"<div class='bb-note'>{html.escape(empty_message)}</div>"

    return (
        "<div class='bb-list-row'>"
        f"<div><div class='bb-label'>{html.escape(title)}</div>"
        f"<div class='bb-list-row-subtitle'>{html.escape(subtitle)}</div></div>"
        "</div>"
        f"<div class='bb-list'>{''.join(items)}</div>"
    )


def _render_history_summary_chips(history: dict[str, object]) -> str:
    reason_key, reason_count = _top_summary_item(history.get("by_reason", []), "reason_code")
    stage_key, stage_count = _top_summary_item(history.get("by_stage", []), "stage")
    avg_rate = _to_float(history.get("average_rejection_rate", 0.0))
    returned_scans = _to_int(history.get("returned_scans", 0))
    window_size = _to_int(history.get("window_size", 20))
    return (
        "<div style='display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0 18px;'>"
        "<div class='bb-list-row'><div><div class='bb-label'>Son N tarama</div>"
        f"<div class='bb-note-strong'>{returned_scans}/{max(window_size, 0)}</div>"
        "<div class='bb-list-row-subtitle'>Trend penceresi</div></div></div>"
        "<div class='bb-list-row'><div><div class='bb-label'>En sık engelleyen</div>"
        f"<div class='bb-note-strong'>{html.escape(_rejection_label(reason_key) if reason_key else 'Nötr')}</div>"
        f"<div class='bb-list-row-subtitle'>{html.escape(reason_key or 'neden yok')} • {reason_count}</div></div></div>"
        "<div class='bb-list-row'><div><div class='bb-label'>Ort. eleme oranı</div>"
        f"<div class='bb-note-strong'>%{avg_rate:.1f}</div>"
        f"<div class='bb-list-row-subtitle'>{html.escape(_stage_label(stage_key) if stage_key else 'Nötr')} • {stage_count}</div></div></div>"
        "</div>"
    )


def _render_rejection_rate_history(scans: object, limit: int = 6) -> str:
    if not isinstance(scans, list) or not scans:
        return "<div class='bb-note'>Henuz historical rejection rate verisi bulunmuyor.</div>"

    items: list[str] = []
    for row in scans[:limit]:
        if not isinstance(row, dict):
            continue
        scan_id = str(row.get("scan_id", "") or "")
        timestamp = str(row.get("timestamp", "") or "")
        rate = _to_float(row.get("rejection_rate", 0.0))
        total_rejections = _to_int(row.get("total_rejections", 0))
        total_scanned = _to_int(row.get("total_scanned", 0))
        top_reason = (
            row.get("top_reason", {}) if isinstance(row.get("top_reason", {}), dict) else {}
        )
        reason_key = str(top_reason.get("reason_code", "") or "")
        items.append(
            "<div class='bb-list-row'>"
            f"<div><div class='bb-label'>{html.escape(timestamp[:19] or 'Kayıt yok')}</div>"
            f"<div class='bb-list-row-subtitle'>{html.escape(scan_id or 'tarama id yok')} • {html.escape(reason_key or 'neden yok')}</div></div>"
            f"<div class='bb-note-strong'>%{rate:.1f}<div class='bb-list-row-subtitle'>{total_rejections}/{max(total_scanned, 0)}</div></div>"
            "</div>"
        )

    if not items:
        return "<div class='bb-note'>Henüz historical rejection rate verisi bulunmuyor.</div>"

    return (
        "<div class='bb-list-row'>"
        "<div><div class='bb-label'>Son eleme oranları</div>"
        "<div class='bb-list-row-subtitle'>Son taramalarda eleme yoğunluğu</div></div>"
        "</div>"
        f"<div class='bb-list'>{''.join(items)}</div>"
    )


def render_scan_detail_page() -> None:
    try:
        stats_response = api_request("GET", "/api/stats")
    except Exception as exc:
        st.warning(f"Tarama detay verisi alınamadı: {exc}")
        return

    try:
        history_response = api_request("GET", "/api/scans/history", params={"limit": 20})
    except Exception:
        history_response = None

    response_payload = stats_response.json() if stats_response.ok else {}
    stats = response_payload.get("stats", {}) if isinstance(response_payload, dict) else {}
    latest_scan = stats.get("latest_scan") or response_payload.get("latest_scan") or {}
    rejection_breakdown = (
        stats.get("rejection_breakdown") or response_payload.get("rejection_breakdown") or {}
    )
    history_payload = history_response.json() if history_response and history_response.ok else {}
    history = history_payload.get("history", {}) if isinstance(history_payload, dict) else {}

    if not isinstance(latest_scan, dict):
        latest_scan = {}
    if not isinstance(rejection_breakdown, dict):
        rejection_breakdown = {}
    if not isinstance(history, dict):
        history = {}

    scan_id = str(rejection_breakdown.get("scan_id", "") or "")
    scanned = _to_int(latest_scan.get("total_scanned", 0))
    generated = _to_int(latest_scan.get("signals_generated", 0))
    actionable = _to_int(latest_scan.get("actionable", 0))

    session_scanned = len(st.session_state.get("all_data", {}) or {})
    session_stats = st.session_state.get("scan_stats", {})
    if session_scanned > scanned and isinstance(session_stats, dict):
        scanned = session_scanned
        generated = _to_int(session_stats.get("generated", 0))
        actionable = _to_int(session_stats.get("actionable", 0))
        session_breakdown = st.session_state.get("rejection_breakdown", {})
        if isinstance(session_breakdown, dict):
            rejection_breakdown = session_breakdown
            scan_id = str(rejection_breakdown.get("scan_id", "") or "")

    total_rejections = _to_int(rejection_breakdown.get("total_rejections", 0))
    rejected_candidates = _candidate_rejection_count(scanned, generated)
    timestamp = str(latest_scan.get("timestamp", "") or "")
    if session_scanned > 0 and not timestamp:
        last_scan_time = st.session_state.get("last_scan_time")
        timestamp = last_scan_time.isoformat() if last_scan_time else ""

    render_page_hero(
        "Tarama Detayı",
        "Son scan tanısı ve eleme dağılımı",
        "Bu ekran son scan için kapsama, üretilen sinyal sayısı ve en sık elenen nedenleri tek yerde toplar.",
        badges=[
            f"Tarama {scan_id or 'hazır değil'}",
            f"Taranan {scanned}",
            f"Üretilen {generated}",
            f"Elenen {rejected_candidates}",
        ],
        accent="secondary",
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_metric_block("Tarama kimliği", scan_id or "Hazır değil", "Son tarama bağlamı")
    with m2:
        render_metric_block("Taranan varlık", str(scanned), "Toplam analiz edilen varlık")
    with m3:
        render_metric_block("Üretilen sinyal", str(generated), "Hold dahil toplam sinyal")
    with m4:
        render_metric_block(
            "Elenen aday",
            str(rejected_candidates),
            f"Aksiyon gerekli {actionable} • Filtre kaydı {total_rejections}",
            accent="danger" if rejected_candidates > 0 else "positive",
        )

    # Invariant check: scanned = generated + uniquely rejected candidates
    if scanned > 0:
        accounted = generated + rejected_candidates
        invariant_held = accounted == scanned
        invariant_color = "positive" if invariant_held else "danger"
        invariant_icon = "✓" if invariant_held else "✗"
        invariant_text = (
            f"{invariant_icon} {accounted}/{scanned} hesaplandı"
            if invariant_held
            else f"{invariant_icon} {accounted}/{scanned} hesaplandı (fark: {scanned - accounted})"
        )
        st.markdown(
            f"<div style='text-align:right;margin-bottom:8px;'>"
            f"<span class='bb-text-{invariant_color}' style='font-size:0.85em;'>{invariant_text}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    scan_meta = (
        "<div class='bb-list-row'>"
        f"<div><div class='bb-label'>Son tarama zamanı</div><div class='bb-list-row-subtitle'>{html.escape(timestamp or 'Kayıt yok')}</div></div>"
        f"<div class='bb-note-strong'>{html.escape(scan_id or 'tarama-id yok')}</div>"
        "</div>"
    )
    scan_summary_chips = _render_scan_summary_chips(
        rejection_breakdown=rejection_breakdown,
        total_scanned=scanned,
    )
    render_html_panel(scan_meta + scan_summary_chips)

    if scanned <= 0 and not scan_id:
        render_section_title("Scan durumu", "Bekleyen veri")
        render_html_panel(
            "<div class='bb-note'>Henüz tamamlanmış bir tarama kaydı bulunmuyor.</div>"
        )
        return

    left, right = st.columns(2, gap="large")
    with left:
        render_section_title("Eleme Nedenleri", "En sık blokaj nedenleri")
        reason_rows = rejection_breakdown.get("by_reason", [])
        if total_rejections > 0:
            reason_html = _render_breakdown_list(
                title="En Sık Eleme Nedenleri",
                subtitle=f"{total_rejections} aday elendi",
                rows=reason_rows,
                key_name="reason_code",
                label_fn=_rejection_label,
                empty_message="Bu tarama için neden dağılımı bulunmuyor.",
            )
        else:
            reason_html = (
                "<div class='bb-note-strong'>Bu taramada aday elemesi yok.</div>"
                "<div class='bb-note' style='margin-top:6px;'>Sinyal hattı en azından son tarama için temiz geçmiş görünüyor.</div>"
            )
        render_html_panel(reason_html, accent="positive" if total_rejections == 0 else "")

    with right:
        render_section_title("Eleme Aşamaları", "En çok eleme yapan katmanlar")
        stage_rows = rejection_breakdown.get("by_stage", [])
        if total_rejections > 0:
            stage_html = _render_breakdown_list(
                title="En Sık Eleme Aşamaları",
                subtitle="Pipeline dağılımı",
                rows=stage_rows,
                key_name="stage",
                label_fn=_stage_label,
                empty_message="Bu tarama için aşama dağılımı bulunmuyor.",
            )
        else:
            stage_html = "<div class='bb-note'>Eleme olmadığı için aşama özeti gösterilmiyor.</div>"
        render_html_panel(stage_html)

    render_section_title("Geçmiş Analizleri", "Son 20 tarama trendi")
    history_scans = history.get("scans", [])
    if isinstance(history_scans, list) and history_scans:
        render_html_panel(_render_history_summary_chips(history), accent="secondary")

        history_left, history_right = st.columns(2, gap="large")
        with history_left:
            blocker_history_html = _render_breakdown_list(
                title="En Sık Engelleyenler",
                subtitle="Son 20 tarama toplamı",
                rows=history.get("by_reason", []),
                key_name="reason_code",
                label_fn=_rejection_label,
                empty_message="Geçmiş engelleyici dağılımı bulunmuyor.",
            )
            render_html_panel(blocker_history_html)

        with history_right:
            stage_history_html = _render_breakdown_list(
                title="Aşama Trendi",
                subtitle="En çok eleme yapan katmanlar",
                rows=history.get("by_stage", []),
                key_name="stage",
                label_fn=_stage_label,
                empty_message="Geçmiş aşama dağılımı bulunmuyor.",
            )
            render_html_panel(stage_history_html)

        render_html_panel(_render_rejection_rate_history(history_scans), accent="secondary")
    else:
        render_html_panel(
            "<div class='bb-note'>Geçmiş analitiği için yeterli tarama geçmişi henüz birikmedi.</div>"
        )
