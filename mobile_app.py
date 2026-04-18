# mobile_app.py
# ─────────────────────────────────────────────
# Bu dosya artık kullanılmamaktadır.
# Tüm mobil ve masaüstü UI streamlit_app.py içinde birleştirilmiştir.
#
# Eğer bu dosyayı doğrudan çalıştırırsanız,
# otomatik olarak streamlit_app.py'ye yönlendirilirsiniz.
# ─────────────────────────────────────────────

import streamlit as st
from streamlit_app import (
    bootstrap_state,
    inject_styles,
    ensure_initial_data,
    filter_signals,
    get_market_summary,
    run_scan,
    render_top_shell,
    render_dashboard,
    render_signals,
    render_analysis,
    render_settings,
    render_navigation,
)
from datetime import datetime

st.set_page_config(
    page_title="BIST Sinyal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Re-use all state, styles and logic from streamlit_app
bootstrap_state()
inject_styles()
ensure_initial_data()

signals     = filter_signals(
    st.session_state.get("signals", []),
    st.session_state.get("all_data", {})
)
all_data     = st.session_state.get("all_data", {})
market_summary = get_market_summary(signals, all_data)

if st.session_state.auto_refresh and st.session_state.last_scan_time:
    elapsed = (datetime.now() - st.session_state.last_scan_time).total_seconds()
    if elapsed >= st.session_state.refresh_interval * 60:
        run_scan()
        st.rerun()

render_top_shell(signals, market_summary)

if not signals:
    st.warning("Sinyal bulunamadı. Tarama tekrarlandığında ekran otomatik dolacak.")
else:
    if st.session_state.current_view == "dashboard":
        render_dashboard(signals, market_summary)
    elif st.session_state.current_view == "signals":
        render_signals(signals, all_data)
    elif st.session_state.current_view == "analysis":
        render_analysis(all_data)
    else:
        render_settings(signals)

st.markdown(
    f"<div class='footer-note'>BIST Bot · "
    f"{datetime.now().strftime('%d.%m.%Y %H:%M')}</div>",
    unsafe_allow_html=True,
)
render_navigation()