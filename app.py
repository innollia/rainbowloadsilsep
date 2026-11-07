"""strudel 딸깍이 — Streamlit entry point."""
from pathlib import Path
import os
import hmac
import secrets
import runpy

import streamlit as st
import streamlit.components.v1 as components

from studio_backend import AgyCli, Jobs, Router, validate_request
from credits import FREE_CREDITS, LedgerError, LocalLedger, RemoteLedger, price_table

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

    gemini_key = secret("SCHOOL_GEMINI_API_KEY", "GEMINI_API_KEY")
    claude_key = secret("ANTHROPIC_API_KEY")
    provider = setting("AI_PROVIDER").strip().lower()
    if setting("STRUDEL_ENGINE") == "agy":
        return AgyCli()
    if provider == "gemini":
        claude_key = ""
    if provider == "claude":
        gemini_key = ""
    if gemini_key or claude_key:
        return Router(gemini_key, claude_key, setting("GEMINI_MODEL"), setting("GEMINI_BASE_URL"), setting("CLAUDE_MODEL"), provider)
    return AgyCli() if setting("STRUDEL_LOCAL_AI") == "1" else None


@st.cache_resource
def jobs():
    return Jobs(choose_model(), daily_limit=int(setting("STRUDEL_DAILY_CALLS", "200")), ledger=ledger())


@st.cache_resource
def ledger():
    """The Lambda ledger when configured; otherwise a local file that only this PC sees."""
    url = setting("STRUDEL_CREDITS_URL")
    token = setting("STRUDEL_CREDITS_TOKEN")
    if not token:
        try:
            token = (Path.home() / ".all-tomorrow" / "strudel-credits.token").read_text(encoding="ascii").strip()
        except OSError:
            token = ""
    if url and token:
        return RemoteLedger(url, token)
    folder = Path(__file__).with_name(".studio-data")
    folder.mkdir(exist_ok=True)
    return LocalLedger(str(folder / "credits.sqlite"), pepper=setting("STRUDEL_CREDITS_PEPPER", "local-only"))


def google_ready():
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def google_login():
    auth = st.secrets["auth"]
    st.login("google") if "google" in auth else st.login()


password = setting("STUDIO_PASSWORD")
google = google_ready()
teacher = bool(st.session_state.get("studio_authenticated"))
member = google and bool(st.user.is_logged_in)
if (password or google) and not (teacher or member):
    st.title("strudel 딸깍이")
    st.write("말로 음악을 만들고, 게임에 쓸 소리까지 뽑아 주는 작업실이야.")
    if google:
        st.button(f"구글 계정으로 시작하기 · 무료 {FREE_CREDITS} 크레딧", type="primary", on_click=google_login)
    if password:
        with st.expander("선생님 비밀번호로 열기", expanded=not google):
            with st.form("login"):
                entered = st.text_input("작업실 비밀번호", type="password")
                if st.form_submit_button("작업실 열기"):
                    if hmac.compare_digest(entered.encode(), password.encode()):
                        st.session_state.studio_authenticated = True
                        st.rerun()
                    else:
                        st.error("비밀번호를 확인해 줘.")
    st.stop()
email = str(st.user.get("email") or "").strip().lower() if member and not teacher else ""
if not email and not google and not teacher and setting("STRUDEL_LOCAL_AI") == "1":
    email = setting("STRUDEL_DEV_EMAIL").strip().lower()  # local testing of credits only; the public server never sets STRUDEL_LOCAL_AI


def account_view(refresh=False, history=False):
    """What the browser may know about the signed-in account. Never the ledger's keys."""
    if not email:
        return None
    if refresh or "studio_account" not in st.session_state:
        try:
            st.session_state.studio_account = ledger().account(email)
        except LedgerError as exc:
            st.session_state.studio_error = str(exc)
            return None
    view = dict(st.session_state.studio_account, email=email, prices=price_table(),
                buy_url=setting("STRUDEL_BUY_URL", "https://buymeacoffee.com/innollia"),
                per_usd=int(setting("STRUDEL_CREDITS_PER_USD", "20")))
    if history:
        try:
            st.session_state.studio_history = ledger().history(email)
        except LedgerError as exc:
            st.session_state.studio_error = str(exc)
    view["history"] = st.session_state.get("studio_history")
    return view

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
[data-testid="stVerticalBlock"]:has(iframe) {gap:0}
</style>""", unsafe_allow_html=True)
studio = components.declare_component("studio", path=str(Path(__file__).parent / "studio_frontend"))
owner = st.session_state.studio_owner
# A public URL must never be able to spend the key, so AI needs a password or an explicit local flag.
ai_ready = jobs().model is not None and (teacher or bool(email) or setting("STRUDEL_LOCAL_AI") == "1")


@st.fragment(run_every=1)
def render():
    manager = jobs()
    choices = manager.model.choices() if hasattr(manager.model, "choices") else None
    snap = manager.snapshot(owner)
    if snap and "credits" in snap and "studio_account" in st.session_state:
        st.session_state.studio_account["credits"] = snap["credits"]
    result = studio(ai_enabled=ai_ready, engine=manager.model.name if manager.model else "", choices=choices, job=snap,
                    account=account_view(), signed_in=bool(email),
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
            req = validate_request(result["payload"])
            req["model"] = req["model"] or (choices or {}).get("model", "")
            if email:
                req["account"] = email
            manager.submit(owner, req)
        elif action == "account":
            account_view(refresh=True, history=True)
        elif action == "logout":
            manager.cancel(owner)
            st.session_state.pop("studio_account", None)
            st.logout()
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
