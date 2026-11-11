"""Tokens for the asset room's generation API, and what the Streamlit page does with them.

The page (app.py) signs a short-lived token for a session that may use AI and hands it to the asset iframe; the
API process (asset_api.py) checks it with the same secret. Standard library only and no streamlit import, so both
processes and the tests can load this file.

Token: b64url(JSON payload) + "." + b64url(HMAC-SHA256(secret, the payload part as it is sent)). Both parts are
base64url (the alphabet with - and _) without padding.
Payload: {v: 1, aud: "asset", kind: "acct"|"pw", sub, email (acct only), lang, iat, exp = iat + 900}."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

VERSION = 1
AUD = "asset"
KINDS = ("acct", "pw")
TTL = 900  # seconds a token lives: exp = iat + TTL
RENEW_BELOW = 300  # session_token signs a new one when fewer seconds than this are left
TTL_STEP = 30  # session_token reports the seconds left rounded down to this
MAX_TOKEN = 4096  # ours are a few hundred characters; nothing longer is looked at
SECRET_ENV = "OLMUSE_ASSET_TOKEN_SECRET"
SECRET_FILE = Path(__file__).resolve().parent / ".studio-data" / "asset_token.key"
PORT_ENV = "OLMUSE_API_PORT"
API_PORT = 8502  # the API's port when the environment names none; the public API's always
TOKEN_STATE = "asset_token"  # session-state key of the session's token
SEEN_STATE = "asset_credits_seen"  # session-state key of what adopt_credits remembers


class TokenError(ValueError):
    """A token the API answers with 401. code is no_token, bad_token or token_expired."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ---------- secret ----------
def load_secret(path=None, env=None) -> bytes:
    """OLMUSE_ASSET_TOKEN_SECRET, else the key file: 32 random bytes that whichever process comes first creates.
    Raises OSError when the file can be neither read nor made; the API must not start then.
    The page and the API both take the secret from here and from nowhere else (no ~/.all-tomorrow file, no
    st.secrets), so the two cannot end up with different ones."""
    value = str((os.environ if env is None else env).get(SECRET_ENV) or "").strip()
    if value:
        return value.encode("utf-8")
    path = Path(path or SECRET_FILE)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600), "wb") as out:
            out.write(secrets.token_bytes(32))
        try:
            os.link(tmp, path)  # exclusive and whole: a process that lost the race reads the winner's 32 bytes
        except FileExistsError:
            pass
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
    key = path.read_bytes()
    if len(key) < 32:
        raise OSError(f"{path.name} holds fewer than 32 bytes")
    return key


def _key(secret) -> bytes:
    key = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret or b"")
    if not key:
        raise ValueError("empty token secret")
    return key


# ---------- the port ----------
def api_port(env=None) -> int:
    """The port of the API on this PC: OLMUSE_API_PORT, else 8502. The page reads it for the address it hands a
    local run's iframe (app.py; the public page says /api/asset whatever this is), and the API for the Hosts it
    answers to. Both take it from here, so the two cannot end up with different ones. run_local.ps1 sets the
    variable to a free port, since 8502 is the public API's; run_public.ps1 removes it."""
    value = str((os.environ if env is None else env).get(PORT_ENV) or "").strip()
    return int(value) if value.isascii() and value.isdigit() and len(value) <= 5 and 0 < int(value) < 65536 else API_PORT


# ---------- sign and verify ----------
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(key: bytes, part: str) -> str:
    return _b64(hmac.new(key, part.encode("ascii"), hashlib.sha256).digest())


def payload_for(kind: str, sub: str, email: str, lang: str, now: float) -> dict:
    """The payload of a token issued at now. sub is "acct:<account key>" or "pw:<session>". An account token
    carries the email, because the ledger charges by email; a password token never does."""
    if kind not in KINDS or not str(sub).startswith(kind + ":") or (kind == "acct" and not email):
        raise ValueError("bad token subject")
    iat = int(now)
    payload = {"v": VERSION, "aud": AUD, "kind": kind, "sub": str(sub), "lang": str(lang), "iat": iat, "exp": iat + TTL}
    if kind == "acct":
        payload["email"] = str(email)
    return payload


def sign(payload: dict, secret) -> str:
    """The token for payload. The JSON is ASCII and the part is base64url without padding, so a browser reads it
    with JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/"))). atob alone throws on a part with - or _."""
    part = _b64(json.dumps(payload, separators=(",", ":")).encode("ascii"))
    return part + "." + _mac(_key(secret), part)


def _well_formed(p) -> bool:
    if not isinstance(p, dict) or p.get("v") != VERSION or p.get("aud") != AUD or p.get("kind") not in KINDS:
        return False
    if type(p.get("iat")) is not int or type(p.get("exp")) is not int or not isinstance(p.get("lang"), str):
        return False
    if not isinstance(p.get("sub"), str) or not p["sub"].startswith(p["kind"] + ":"):
        return False
    email = p.get("email")
    return (isinstance(email, str) and bool(email)) if p["kind"] == "acct" else email is None


def verify(token, secret, now: float | None = None) -> dict:
    """The payload of a token we signed that has not run out. Raises TokenError (no_token, bad_token, token_expired)."""
    key = _key(secret)
    if not token or not isinstance(token, str):
        raise TokenError("no_token")
    part, _, mac = token.partition(".")
    try:
        # The signature is compared as text, so no second spelling of the same bytes passes.
        signed = len(token) <= MAX_TOKEN and hmac.compare_digest(mac.encode("ascii"), _mac(key, part).encode("ascii"))
        payload = json.loads(_unb64(part)) if signed else None
    except ValueError:  # not ASCII, not base64 or not JSON
        payload = None
    if not _well_formed(payload):
        raise TokenError("bad_token")
    if (time.time() if now is None else now) >= payload["exp"]:
        raise TokenError("token_expired")
    return payload


def owner_of(payload: dict, secret, ip: str) -> str:
    """Whose jobs a verified token's requests are. An account is its sub. A password session gets a new sub on
    every reload (app.py makes it for each Streamlit session), so those are grouped by the caller's address
    instead: one classroom is one owner, and its jobs, daily counts, dollars, request ids and cancel marks go by
    that. Only the API's requests a minute are counted by the sub itself (asset_api.Api.counted)."""
    if payload["kind"] == "acct":
        return payload["sub"]
    return "pwip:" + hmac.new(_key(secret), str(ip).encode("utf-8"), hashlib.sha256).hexdigest()[:16]


# ---------- host (Streamlit page) helpers ----------
def _ours(token, key: bytes) -> bool:
    """Whether a token this module made earlier carries key's signature."""
    part, _, mac = token.partition(".") if isinstance(token, str) and token.isascii() else ("", "", "")
    return bool(part) and hmac.compare_digest(mac, _mac(key, part))


def session_token(state, kind: str, sub: str, email: str, lang: str, now: float, secret=None) -> dict:
    """{"token", "ttl"} for this session. state is st.session_state (any mapping): the token stays there and is
    signed again when fewer than RENEW_BELOW seconds are left, when kind, sub or lang changed (the API words its
    messages in the token's language), or when the secret is no longer the one that signed it.

    ttl is the seconds left by this server's clock, rounded down to TTL_STEP. The page passes it to the browser on
    every run, and a number that changed each second would send the whole set of arguments each second.
    secret defaults to load_secret(), read on every call."""
    key = _key(load_secret() if secret is None else secret)
    held = state.get(TOKEN_STATE)
    if not (isinstance(held, dict) and (held.get("kind"), held.get("sub"), held.get("lang")) == (kind, sub, lang)
            and held.get("exp", 0) - now >= RENEW_BELOW and _ours(held.get("token"), key)):
        payload = payload_for(kind, sub, email, lang, now)
        held = {"token": sign(payload, key), "kind": kind, "sub": sub, "lang": lang, "exp": payload["exp"]}
        state[TOKEN_STATE] = held
    return {"token": held["token"], "ttl": int(held["exp"] - now) // TTL_STEP * TTL_STEP}


def account_read(state) -> None:
    """The page calls this each time it has read the account from the ledger. adopt_credits then knows that the
    balance shown may be newer than a view whose charge came before that read."""
    seen = dict(state.get(SEEN_STATE) or {})
    seen["shown"] = seen.get("shown", 0) + 1
    state[SEEN_STATE] = seen


def adopt_credits(state, job_snap, agent_view) -> bool:
    """Takes the balance a job view or an agent view reports into state["studio_account"], once per view.

    A view keeps showing the balance of its last charge or refund. Copied on every run it would undo a newer
    balance read by the page's `account` action, so each view is taken once and remembered in state: a job by
    (id, calls, credits), an agent answer by (n, credits). A view seen before the account is loaded is remembered
    too, since the account read that follows is newer than it.

    A view can also be old the first time it is seen. An agent answer carries the balance of the charge made
    before its model call and comes out only after it; a job's charge reaches the page a run later. So state
    counts how often the shown balance was replaced (`shown`: a ledger read told by account_read, or a balance
    taken here), and a view's balance is taken only when that count has not moved since its charge could first
    have happened: the run before this one for a job, the run before the call was first seen for an agent.
    Otherwise the balance is left as it is and True is returned: the page reads the ledger again."""
    before = state.get(SEEN_STATE) or {}
    seen = dict(before)
    shown = seen.get("shown", 0)
    looked = seen.get("looked", shown)  # what the count was when the last run was here
    call = seen.get("call")
    if agent_view and not (call and call[0] == agent_view.get("n")):
        call = seen["call"] = (agent_view.get("n"), looked)
    account, reread = state.get("studio_account"), False
    for name, view, mark, since in (
            ("job", job_snap, job_snap and (job_snap.get("id"), job_snap.get("calls"), job_snap.get("credits")), looked),
            ("agent", agent_view, agent_view and (agent_view.get("n"), agent_view.get("credits")), call and call[1])):
        if not view or view.get("credits") is None or seen.get(name) == mark:
            continue
        seen[name] = mark
        if not isinstance(account, dict):
            continue
        if since == shown:
            account["credits"] = view["credits"]
            shown += 1
        else:
            reread = True
    seen["shown"] = seen["looked"] = shown
    if seen != before:
        state[SEEN_STATE] = seen
    return reread
