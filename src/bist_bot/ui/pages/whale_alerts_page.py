from __future__ import annotations

import streamlit as st

from bist_bot.services.whale_alert_service import WhaleAlert, build_whale_alerts


def _render_alert(alert: WhaleAlert) -> None:
    with st.container(border=True):
        title_col, score_col = st.columns([3, 1])
        with title_col:
            st.subheader(alert.ticker.replace(".IS", ""))
            st.caption(f"{alert.direction} - {alert.severity}")
        with score_col:
            st.metric("Radar skoru", f"{alert.score}/100")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fiyat", f"TL{alert.price:.2f}")
        c2.metric("Değişim", f"{alert.change_pct:+.1f}%")
        c3.metric("Hacim", f"{alert.volume_ratio:.1f}x")
        c4.metric("Model", f"{alert.signal_score:+.0f}")

        if alert.reasons:
            st.markdown("**Nedenler**")
            for reason in alert.reasons:
                st.markdown(f"- {reason}")
        st.caption(alert.action_note)


def render_whale_alerts_page() -> None:
    all_data = st.session_state.get("all_data", {})
    signals = st.session_state.get("signals", [])
    alerts = build_whale_alerts(all_data, signals)
    high_count = sum(1 for alert in alerts if alert.score >= 80)
    medium_count = sum(1 for alert in alerts if 60 <= alert.score < 80)

    st.title("Balina Radar")
    st.caption(
        "Mevcut BIST100 taramasından hacim, fiyat ayrışması, trend ve model skorunu "
        "birleştirerek olağandışı hareket adaylarını sıralar."
    )
    st.info(
        "Yatırım tavsiyesi değildir. Bu ekran gerçek aracı kurum dağılımı veya emir "
        "defteri sahipliğini görmez; sadece mevcut teknik veriden izleme adayı üretir."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Aday", len(alerts))
    c2.metric("Yüksek", high_count)
    c3.metric("Orta", medium_count)

    if st.session_state.get("scan_in_progress"):
        phase = st.session_state.get("scan_phase") or "Tarama başlatılıyor"
        st.warning(f"Arka plan taraması sürüyor: {phase}")

    if not alerts:
        st.info(
            "Şu an eşiği geçen balina sinyal adayı yok. Yeni tarama tamamlanınca tekrar hesaplanır."
        )
        return

    for alert in alerts:
        _render_alert(alert)
