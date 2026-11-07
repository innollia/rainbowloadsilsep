"""strudel 딸깍이 — Streamlit entry point."""
from pathlib import Path
import os
import hmac
import secrets
import runpy

import streamlit as st
import streamlit.components.v1 as components

from studio_backend import AgyCli, Claude, Gemini, Jobs, validate_request

st.set_page_config(page_title="strudel 딸깍이", page_icon="◉", layout="wide", initial_sidebar_state="collapsed")


def setting(name, default=""):
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default


def key_pool():
    """Local-only key file. Absent on Cloud, where Streamlit Secrets are used."""
    try:
        lines = (Path.home() / ".all-tomorrow" / "key-pool.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    pairs = (line.removeprefix("export ").split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))
    return {name.strip(): value.strip().strip("'\"") for name, value in pairs}


def choose_model():
    """AI_PROVIDER picks one engine outright. Unset: school Gemini, Gemini, Claude, then local agy."""
    pool = key_pool()

    def secret(*names):
        return next((value for name in names if (value := setting(name) or pool.get(name, ""))), "")

    def gemini():
        key = secret("SCHOOL_GEMINI_API_KEY", "GEMINI_API_KEY")
        return Gemini(key, setting("GEMINI_MODEL"), setting("GEMINI_BASE_URL")) if key else None

    def claude():
        key = secret("ANTHROPIC_API_KEY")
        return Claude(key, setting("CLAUDE_MODEL")) if key else None

    provider = setting("AI_PROVIDER").strip().lower()
    if setting("STRUDEL_ENGINE") == "agy":
        return AgyCli()
    if provider == "gemini":
        return gemini()
    if provider == "claude":
        return claude()
    return gemini() or claude() or (AgyCli() if setting("STRUDEL_LOCAL_AI") == "1" else None)


@st.cache_resource
def jobs():
    return Jobs(choose_model(), daily_limit=int(setting("STRUDEL_DAILY_CALLS", "200")))


password = setting("STUDIO_PASSWORD")
if password and not st.session_state.get("studio_authenticated"):
    st.title("strudel 딸깍이")
    with st.form("login"):
        entered = st.text_input("작업실 비밀번호", type="password")
        if st.form_submit_button("작업실 열기"):
            if hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state.studio_authenticated = True
                st.rerun()
            else:
                st.error("비밀번호를 확인해 줘.")
    st.stop()

st.session_state.setdefault("studio_owner", secrets.token_urlsafe(24))
st.session_state.setdefault("studio_page", "music")

if st.session_state.studio_page != "music":
    left, right = st.columns([3, 1])
    if left.button("← 음악 작업실로 돌아가기"):
        st.session_state.studio_page = "music"
        st.rerun()
    if right.button("아케이드 / BLACK BOX 전환"):
        st.session_state.studio_page = "blackbox" if st.session_state.studio_page == "arcade" else "arcade"
        st.rerun()
    runpy.run_path(str(Path(__file__).with_name("arcade_page.py" if st.session_state.studio_page == "arcade" else "blackbox_page.py")))
    st.stop()

st.markdown("""<style>
[data-testid="stHeader"] {display:none}
[data-testid="stMainBlockContainer"] {max-width:none;padding:0}
html,body,[data-testid="stApp"] {background:#0f0f0f}
iframe {display:block}
</style>""", unsafe_allow_html=True)
studio = components.declare_component("studio", path=str(Path(__file__).parent / "studio_frontend"))
owner = st.session_state.studio_owner
# A public URL must never be able to spend the key, so AI needs a password or an explicit local flag.
ai_ready = jobs().model is not None and (bool(password) or setting("STRUDEL_LOCAL_AI") == "1")


@st.fragment(run_every=1)
def render():
    manager = jobs()
    result = studio(ai_enabled=ai_ready, engine=manager.model.name if manager.model else "", job=manager.snapshot(owner),
                    server_error=st.session_state.get("studio_error", ""), key="studio", default=None)
    if not isinstance(result, dict):
        return
    event_id = result.get("event_id")
    if not event_id or event_id == st.session_state.get("studio_event"):
        return
    st.session_state.studio_event = event_id
    st.session_state.studio_error = ""
    try:
        action = result.get("action")
        if action == "generate":
            if not ai_ready:
                raise ValueError("AI가 연결되지 않았어. 설정에서 연결 상태를 확인해 줘.")
            manager.submit(owner, validate_request(result["payload"]))
        elif action == "cancel":
            manager.cancel(owner)
        elif action == "feedback":
            manager.feedback(owner, result.get("payload", {}))
        elif action == "game":
            manager.cancel(owner)
            st.session_state.studio_page = "arcade"
            st.rerun(scope="app")
    except (ValueError, KeyError, TypeError) as exc:
        st.session_state.studio_error = str(exc)


render()
