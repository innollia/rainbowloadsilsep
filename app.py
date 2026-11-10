"""olmuse (구 strudel 딸깍이) — Streamlit entry point."""
from pathlib import Path
import os
import html
import json
import logging
import secrets
import runpy
import urllib.parse

import streamlit as st
import streamlit.components.v1 as components

from studio_backend import AgyCli, DailyUsd, Jobs, Router, in_app_browser, job_store, validate_request
from asset_agent import Agents
from asset_classify import classify as classify_files
from skill_router import ask_jev, read_key
from credits import FREE_CREDITS, LedgerError, open_ledger, price_table
from server_ops import PasswordGate, setup_logging, start_daily_backup

st.set_page_config(page_title="olmuse", page_icon="◉", layout="wide", initial_sidebar_state="collapsed")

HERE = Path(__file__).parent
DATA = HERE / ".studio-data"
LOCAL_SECRETS = Path.home() / ".all-tomorrow"  # this PC only; Cloud uses Streamlit Secrets
log = logging.getLogger("olmuse.app")


@st.cache_resource
def server_ops():
    """Once per process: the rotating log file under .studio-data/logs and a daily copy of the SQLite files."""
    setup_logging(DATA / "logs")
    start_daily_backup(DATA, os.environ.get("OLMUSE_BACKUP_DIR") or DATA / "backups")
    return True


server_ops()


# ---------- settings ----------
def setting(name, default=""):
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default


def local_file(name, encoding="utf-8"):
    try:
        return (LOCAL_SECRETS / name).read_text(encoding=encoding)
    except OSError:
        return ""


def key_pool():
    lines = local_file("key-pool.env").splitlines()
    pairs = (line.removeprefix("export ").split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))
    return {name.strip(): value.strip().strip("'\"") for name, value in pairs}


def secret(*names):
    """The first of names that is set, in settings first and then the local key pool."""
    pool = key_pool()
    return next((value for name in names if (value := setting(name) or pool.get(name, ""))), "")


# The public server never sets this, so it alone must not unlock anything that spends a key on a public URL.
LOCAL_AI = setting("STRUDEL_LOCAL_AI") == "1"
# Only run_local.ps1 sets this. Without it a missing remote ledger shuts paid AI instead of opening a local file.
LOCAL_LEDGER = setting("STRUDEL_LOCAL_LEDGER") == "1"


# ---------- AI engine and credit ledger ----------
def choose_model():
    """STRUDEL_ENGINE=agy forces the local CLI. AI_PROVIDER picks one API outright; unset, Gemini comes before Claude."""
    if setting("STRUDEL_ENGINE") == "agy":
        return AgyCli()
    provider = setting("AI_PROVIDER").strip().lower()
    gemini_key = "" if provider == "claude" else secret("SCHOOL_GEMINI_API_KEY", "GEMINI_API_KEY")
    claude_key = "" if provider == "gemini" else secret("ANTHROPIC_API_KEY")
    # The public server spends it only on MODEL_CHOICES (DeepSeek); bakeoff models join only when LOCAL_AI.
    openrouter_key = "" if provider in ("claude", "gemini") else secret("OPENROUTER_API_KEY")
    if gemini_key or claude_key or openrouter_key:
        router = Router(gemini_key, claude_key, setting("GEMINI_MODEL"), setting("GEMINI_BASE_URL"), setting("CLAUDE_MODEL"),
                        provider, openrouter_key=openrouter_key)
        # The default model's backups are paid by the operator: STRUDEL_BACKUP_DAILY_USD caps them per day at worst cost.
        backup_usd = float(setting("STRUDEL_BACKUP_DAILY_USD", "0.20") or 0)
        router.backup_budget = DailyUsd(backup_usd if backup_usd > 0 else None)
        return router
    return AgyCli() if LOCAL_AI else None


def limit_setting(name, default):
    """A call limit; 0 or below means none."""
    value = int(setting(name, default) or 0)
    return value if value > 0 else None


@st.cache_resource
def jobs():
    # STRUDEL_DAILY_CALLS is the safety ceiling for all signed-in accounts together; each account also has its own.
    # Password (teacher) sessions are a separate pool with a per-session cap, so a leaked password cannot drain it in one go.
    # Password sessions spend the operator's key without credits: STRUDEL_OPERATOR_DAILY_USD caps their worst-case
    # spend per day (0.60 USD: even 30 such days stay under the 30,000 KRW monthly budget). 0 or below means no cap.
    operator_usd = float(setting("STRUDEL_OPERATOR_DAILY_USD", "0.60") or 0)
    led = ledger()
    return Jobs(choose_model(), daily_limit=limit_setting("STRUDEL_DAILY_CALLS", "200"), ledger=led,
                account_limit=limit_setting("STRUDEL_ACCOUNT_DAILY_CALLS", "60"),
                teacher_limit=limit_setting("STRUDEL_TEACHER_DAILY_CALLS", "200"),
                session_limit=limit_setting("STRUDEL_TEACHER_SESSION_CALLS", "60"),
                operator_usd=operator_usd if operator_usd > 0 else None,
                store=job_store(setting("OLMUSE_JOBS_DB"), hasher=email_hasher(led)))


def email_hasher(led):
    """How jobs.sqlite3 stores an email: the ledger's own account key, or an HMAC with a pepper of this PC."""
    if led is not None:
        return led.key_of
    from credits import email_key
    return lambda email: email_key(ledger_pepper() or local_pepper(), email)


def local_pepper():
    path = DATA / "jobs.pepper"
    if not path.exists():
        DATA.mkdir(exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="ascii")
    return path.read_text(encoding="ascii").strip()


def ledger_pepper():
    return setting("STRUDEL_CREDITS_PEPPER") or local_file("strudel-credits.pepper", "ascii").strip()


@st.cache_resource
def agents():
    return Agents(jobs().store, ledger())


@st.cache_resource
def ledger_state():
    """(ledger, problem). The Lambda ledger when configured; the local file only when STRUDEL_LOCAL_LEDGER=1.
    Otherwise None: paid AI stays shut and the page says why."""
    url = setting("STRUDEL_CREDITS_URL")
    token = setting("STRUDEL_CREDITS_TOKEN") or local_file("strudel-credits.token", "ascii").strip()
    if LOCAL_LEDGER:
        DATA.mkdir(exist_ok=True)
    found, problem = open_ledger(url, token, ledger_pepper(), LOCAL_LEDGER, str(DATA / "credits.sqlite"))
    if problem:
        log.error("ALERT %s; signed-in AI is off", problem)
    return found, problem


def ledger():
    return ledger_state()[0]


@st.cache_resource
def password_gate():
    return PasswordGate(session_tries=int(setting("STUDIO_PASSWORD_SESSION_TRIES", "5")),
                        hourly_tries=int(setting("STUDIO_PASSWORD_HOURLY_TRIES", "20")))


# ---------- page text ----------
st.markdown("""<style>
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
[data-testid="InputInstructions"], footer, #MainMenu {display:none !important}
/* primaryColor is near-white, so primary buttons need dark text */
[data-testid="stBaseButton-primary"], [data-testid="stBaseLinkButton-primary"],
[data-testid="stBaseButton-primary"] *, [data-testid="stBaseLinkButton-primary"] * {color:#111 !important}
</style>""", unsafe_allow_html=True)

TEXT = {
    "en": {"google": "Continue with Google · {n} free credits", "password": "Password", "enter": "Enter", "wrong": "Wrong password.",
           "locked": "Too many wrong passwords. Try again later.",
           "no_ledger": "The credit ledger is not connected, so AI for signed-in accounts is off. Please try again later.",
           "server_error": "Something went wrong on our side. Please try again in a moment.",
           "back": "← Back to the music studio", "switch": "Switch Arcade / BLACK BOX",
           "no_ai": "AI isn't connected. Check the connection in Settings.",
           "in_app": "Google sign-in is blocked inside in-app browsers ({app}). Please open this page in your default browser (Chrome, Safari).",
           "in_app_how": "Tap ⋮ or ··· in the corner and choose \"Open in browser\", or copy the address and paste it into your browser.",
           "open_browser": "Open in browser", "copy": "Copy address", "copied": "Copied",
           "moved": "olmuse's address is {url}. Songs are saved per address, so export them here first if you made any."},
    "ko": {"google": "구글 계정으로 시작하기 · 무료 {n} 크레딧", "password": "비밀번호", "enter": "입장하기", "wrong": "비밀번호도 틀렸잖아~ 바보♡",
           "locked": "비밀번호를 너무 많이 틀렸잖아~ 좀 있다가 다시 해 봐♡",
           "no_ledger": "크레딧 장부가 안 연결돼서 로그인 계정 AI 막아 놨어~ 좀 있다 다시 해 봐.",
           "server_error": "서버에 문제가 생겼나 봐~ 좀 있다가 다시 해 봐.",
           "back": "← 음악 작업실로 돌아가기", "switch": "아케이드 / BLACK BOX 전환",
           "no_ai": "AI가 안 연결됐잖아~ 설정에서 연결 상태부터 확인해 봐♡",
           "in_app": "구글 로그인은 인앱 브라우저({app})에선 막히거든? 기본 브라우저(크롬, 사파리)로 열어 봐~",
           "in_app_how": "모서리의 ⋮ 나 ··· 눌러서 '다른 브라우저로 열기'를 고르든가, 주소 복사해서 브라우저에 붙여 넣어 봐~",
           "open_browser": "기본 브라우저로 열기", "copy": "주소 복사", "copied": "복사했어요",
           "moved": "olmuse 주소는 {url} 이야~ 곡은 주소마다 따로 저장되니까, 여기서 만든 곡 있으면 먼저 내보내 두라고♡"},
}
lang = st.query_params.get("lang", st.session_state.get("lang", "en"))
lang = lang if lang in TEXT else "en"
st.session_state.lang = lang
T = TEXT[lang]


def switch_lang(chosen, scope="app"):
    st.session_state.lang = chosen
    st.query_params["lang"] = chosen
    st.rerun(scope=scope)


# ---------- address and browser checks ----------
CANONICAL = setting("STRUDEL_CANONICAL_URL", "https://olmuse.app").rstrip("/")


def page_url():
    try:
        return str(st.context.url or CANONICAL)
    except Exception:
        return CANONICAL


def other_address_notice():
    """www.olmuse.app or the *.streamlit.app address keeps its own browser storage, so point to the real one."""
    host = str(st.context.headers.get("Host") or "").split(":")[0].lower()
    canonical = urllib.parse.urlsplit(CANONICAL).hostname or ""
    if canonical and host and host != canonical and (host == "www." + canonical or host.endswith(".streamlit.app")):
        st.warning(T["moved"].format(url=CANONICAL), icon=":material/open_in_new:")
        st.link_button(CANONICAL.removeprefix("https://"), CANONICAL)


def in_app_notice():
    """Google answers disallowed_useragent inside chat and social apps' web views. Say so before the button."""
    app = in_app_browser(st.context.headers.get("User-Agent"))
    if not app:
        return False
    url = page_url()
    st.warning(T["in_app"].format(app=app), icon=":material/open_in_browser:")
    st.caption(T["in_app_how"])
    if app == "KakaoTalk":  # KakaoTalk opens this scheme in the phone's default browser
        st.link_button(T["open_browser"], "kakaotalk://web/openExternal?url=" + urllib.parse.quote(url, safe=""),
                       type="primary", use_container_width=True)
    elif "Android" in str(st.context.headers.get("User-Agent")):
        rest = url.split("://", 1)[-1]
        st.link_button(T["open_browser"], f"intent://{rest}#Intent;scheme=https;action=android.intent.action.VIEW;end",
                       type="primary", use_container_width=True)
    components.html(f"""<div style="display:flex;gap:8px;font:14px sans-serif">
<input id="u" readonly value="{html.escape(url, quote=True)}" style="flex:1;padding:8px;border:1px solid #555;border-radius:8px;background:#1b1b1b;color:#eee">
<button id="b" style="padding:8px 14px;border:0;border-radius:8px;background:#e8e8e8;color:#111;font-weight:600">{html.escape(T["copy"])}</button></div>
<script>
const u=document.getElementById("u"), b=document.getElementById("b");
b.onclick=async()=>{{let ok=false;try{{await navigator.clipboard.writeText(u.value);ok=true}}catch(e){{}}
if(!ok){{u.select();u.setSelectionRange(0,9999);try{{ok=document.execCommand("copy")}}catch(e){{}}}}
if(ok)b.textContent={json.dumps(T["copied"])};}};
</script>""", height=52)
    return True


# ---------- sign-in ----------
def google_ready():
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def google_login():
    auth = st.secrets["auth"]
    st.login("google") if "google" in auth else st.login()


def login_screen(password, google):
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        head, pick = st.columns([3, 2], vertical_alignment="center")
        head.title("olmuse")
        chosen = pick.segmented_control("lang", ["en", "ko"], default=lang, format_func={"en": "English", "ko": "한국어"}.get,
                                        label_visibility="collapsed", key="lang_pick")
        if chosen and chosen != lang:
            switch_lang(chosen)
        other_address_notice()
        if google and in_app_notice():
            st.divider()
        if google:
            st.button(T["google"].format(n=FREE_CREDITS), type="primary", on_click=google_login, icon=":material/login:", use_container_width=True)
        if password:
            with st.form("login", border=False):
                entered = st.text_input(T["password"], type="password")
                if st.form_submit_button(T["enter"], icon=":material/arrow_forward:", use_container_width=True):
                    tries = st.session_state.setdefault("studio_gate", secrets.token_urlsafe(12))
                    answer = password_gate().check(tries, entered, password)
                    if answer == "ok":
                        st.session_state.studio_authenticated = True
                        st.rerun()
                    st.error(T["locked" if answer == "locked" else "wrong"])
    st.stop()


password = setting("STUDIO_PASSWORD")
google = google_ready()
teacher = bool(st.session_state.get("studio_authenticated"))  # password holders use the owner's key without credits
member = google and bool(st.user.is_logged_in)
if (password or google) and not (teacher or member):
    login_screen(password, google)
email = str(st.user.get("email") or "").strip().lower() if member and not teacher else ""
if not email and not google and not teacher and LOCAL_AI:
    email = setting("STRUDEL_DEV_EMAIL").strip().lower()  # lets credits be tried locally


def account_view(refresh=False, history=False):
    """What the browser may know about the signed-in account. Never the ledger's keys."""
    if not email or ledger() is None:
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
    view["daily_left"] = jobs().calls_left(email)
    view["find"] = st.session_state.get("studio_find")
    view["coupon"] = st.session_state.get("studio_coupon")
    return view


# ---------- game pages ----------
st.session_state.setdefault("studio_owner", secrets.token_urlsafe(24))
st.session_state.setdefault("studio_page", "music")

if st.session_state.studio_page != "music":
    left, right = st.columns([3, 1])
    if left.button(T["back"]):
        st.session_state.studio_page = "music"
        st.rerun()
    if right.button(T["switch"]):
        st.session_state.studio_page = "blackbox" if st.session_state.studio_page == "arcade" else "arcade"
        st.rerun()
    runpy.run_path(str(HERE / ("arcade_page.py" if st.session_state.studio_page == "arcade" else "blackbox_page.py")))
    st.stop()


# ---------- music studio ----------
st.markdown("""<style>
[data-testid="stMainBlockContainer"] {max-width:none;padding:0}
html,body,[data-testid="stApp"] {background:#0f0f0f}
iframe {display:block}
[data-testid="stVerticalBlock"]:has(iframe) {gap:0}
</style>""", unsafe_allow_html=True)
studio = components.declare_component("studio", path=str(HERE / "studio_frontend"))
# A signed-in account owns its job, so a reload or another device under the same account picks up the running job
# (and a result that finished while no page was open). Password and local sessions keep a per-session owner.
# The account part is the ledger's HMAC of the email, so jobs.sqlite3 never holds an email in plain.
owner = jobs().store.owner(email) if email else st.session_state.studio_owner
# A public URL must never be able to spend the key, so AI needs a password, a signed-in account or the local flag.
# A signed-in account's calls are paid, so they also need the ledger.
ai_ready = jobs().model is not None and (teacher or bool(email) or LOCAL_AI) and not (email and ledger() is None)


def handle(action, payload, manager, choices):
    if action == "generate":
        if not ai_ready:
            raise ValueError(T["no_ai"])
        req = validate_request({"lang": lang, **payload} if isinstance(payload, dict) else payload)
        req["model"] = req["model"] or (choices or {}).get("model", "")
        if email:
            req["account"] = email
        manager.submit(owner, req)
    elif action == "account":
        account_view(refresh=True, history=True)
    elif action == "find_payment":
        # {payer_email, amount, date: YYYY-MM-DD} → account.find = {found, added, credits, too_many}
        if not email or ledger() is None:
            return
        p = payload if isinstance(payload, dict) else {}
        try:
            found = ledger().find_payment(email, str(p.get("payer_email") or "")[:254],
                                                                 str(p.get("amount") or "")[:20], str(p.get("date") or "")[:10])
        except LedgerError as exc:
            raise ValueError(str(exc)) from None
        # n tells the page this is a new answer, even when it reads the same as the last one
        st.session_state.studio_find = {**found, "n": (st.session_state.get("studio_find") or {}).get("n", 0) + 1}
        account_view(refresh=True, history=True)
    elif action == "coupon":
        # {code} → account.coupon = {status: ok|none|used|empty|too_many, added, credits, n}
        if not email or ledger() is None:
            return
        try:
            got = ledger().redeem(email, str((payload or {}).get("code") or "")[:60])
        except LedgerError as exc:
            raise ValueError(str(exc)) from None
        st.session_state.studio_coupon = {**got, "n": (st.session_state.get("studio_coupon") or {}).get("n", 0) + 1}
        account_view(refresh=True, history=True)
    elif action == "logout":
        manager.cancel(owner)
        st.session_state.pop("studio_account", None)
        st.logout()
    elif action == "cancel":
        manager.cancel(owner)
    elif action == "feedback":
        manager.feedback(owner, payload)
    elif action == "classify":
        # The asset studio's imported files, sorted into groups by Jev; the page falls back to its own guess on ok=False.
        p = payload if isinstance(payload, dict) else {}
        files = [{"path": str(f.get("path") or "")[:300], "secs": f.get("secs") if isinstance(f.get("secs"), (int, float)) else 0}
                 for f in (p.get("files") or [])[:300] if isinstance(f, dict) and f.get("path")]
        answer = {"n": p.get("n"), "ok": False, "groups": {}}
        key = read_key() if ai_ready else ""
        if key and files:
            try:
                answer.update(ok=True, groups=classify_files(files, lambda q: ask_jev(key, {"task": "sort game sound files"}, q, timeout=15.0)))
            except (RuntimeError, OSError, ValueError):
                pass
        st.session_state.studio_classify = answer
    elif action == "asset_agent":
        # The asset board's resident agent: one model call in the background, the answer comes back as args.asset_agent.
        p = payload if isinstance(payload, dict) else {}
        if not ai_ready:
            agents().fail(owner, p.get("n"), T["no_ai"])
            return
        if len(json.dumps(p.get("state") or {}, ensure_ascii=False)) > 400000:
            raise ValueError("board too large")
        known = {m["id"] for m in (choices or {}).get("models", [])}
        req = {"n": p.get("n"), "text": str(p.get("text") or "")[:4000],
               "state": p.get("state") if isinstance(p.get("state"), dict) else {}, "lang": lang,
               "model": p.get("model") if p.get("model") in known else (choices or {}).get("model", ""),
               "effort": str(p.get("effort") or (choices or {}).get("effort", ""))[:20], "account": email or ""}
        if email and ledger() is None:
            agents().fail(owner, p.get("n"), T["no_ledger"])
            return
        agents().start(owner, req, manager.model, manager, ledger() if email else None)
    elif action == "lang":
        chosen = (payload or {}).get("lang")
        if chosen in TEXT and chosen != lang:
            switch_lang(chosen)
    elif action == "game":
        manager.cancel(owner)
        st.session_state.studio_page = "arcade"
        st.rerun(scope="app")


@st.fragment(run_every=1)
def render():
    manager = jobs()
    choices = manager.model.choices(lang=lang) if hasattr(manager.model, "choices") else None
    snap = manager.snapshot(owner)
    if snap and "credits" in snap and "studio_account" in st.session_state:
        st.session_state.studio_account["credits"] = snap["credits"]
    agent_view = agents().view(owner)
    if agent_view and "credits" in agent_view and "studio_account" in st.session_state:
        st.session_state.studio_account["credits"] = agent_view["credits"]
    result = studio(lang=lang, ai_enabled=ai_ready, engine=manager.model.name if manager.model else "", choices=choices, job=snap,
                    account=account_view(), signed_in=bool(email), classify=st.session_state.get("studio_classify"), asset_agent=agents().view(owner),
                    server_error=st.session_state.get("studio_error", ""), key="studio", default=None)
    if not isinstance(result, dict):
        return
    event_id = result.get("event_id")
    if not event_id or event_id == st.session_state.get("studio_event"):
        return
    st.session_state.studio_event = event_id
    st.session_state.studio_error = ""
    try:
        handle(result.get("action"), result.get("payload"), manager, choices)
    except ValueError as exc:  # our own words for the user
        st.session_state.studio_error = str(exc)
    except Exception:
        log.exception("action %s failed", str(result.get("action"))[:40])
        st.session_state.studio_error = T["server_error"]


if email and ledger_state()[1]:
    st.error(T["no_ledger"], icon=":material/error:")
render()
