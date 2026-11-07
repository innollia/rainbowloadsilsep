"""Streamlit game arcade: auto-discovers folders under static/games/."""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="ARCADE // 개인 게임 보관함",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = [
    st.Page("arcade_page.py", title="게임 아케이드", icon="🎮", default=True),
    st.Page("blackbox_page.py", title="BLACK BOX 09", icon="🧩"),
]
st.navigation(pages).run()
