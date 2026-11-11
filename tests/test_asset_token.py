import ast
import base64
import hashlib
import hmac
import json
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import asset_token as at
from credits import LedgerError, LocalLedger

ROOT = Path(__file__).resolve().parent.parent
SECRET = b"k" * 32
NOW = 1_800_000_000


def acct(now=NOW, **over):
    return {**at.payload_for("acct", "acct:abc", "kid@example.com", "ko", now), **over}


def pw(now=NOW, **over):
    return {**at.payload_for("pw", "pw:session-one", "", "en", now), **over}


def refused(token, secret=SECRET, now=NOW):
    with pytest.raises(at.TokenError) as err:
        at.verify(token, secret, now)
    return err.value.code


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# ---------- sign and verify ----------
def test_token_is_payload_dot_hmac_of_the_payload_part():
    token = at.sign(acct(), SECRET)
    part, mac = token.split(".")
    assert "=" not in token
    assert json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) == {
        "v": 1, "aud": "asset", "kind": "acct", "sub": "acct:abc", "email": "kid@example.com", "lang": "ko",
        "iat": NOW, "exp": NOW + 900}
    assert mac == b64(hmac.new(SECRET, part.encode("ascii"), hashlib.sha256).digest())


def test_a_browser_reads_the_payload_once_the_url_alphabet_is_put_back():
    token = at.sign(acct(email="a~b@example.com", sub="acct:abcde"), SECRET)  # this one has a _ in its payload part
    part = token.split(".")[0]
    assert "_" in part or "-" in part
    code = ("const part = " + json.dumps(part) + "; let plain = 'read'; try { atob(part); } catch { plain = 'threw'; }"
            "console.log(JSON.stringify([plain, JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/'))).email]));")
    done = subprocess.run(["node", "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["threw", "a~b@example.com"]  # atob alone fails; sign()'s recipe reads it


def test_verify_returns_what_was_signed():
    assert at.verify(at.sign(acct(), SECRET), SECRET, NOW) == acct()
    got = at.verify(at.sign(pw(), SECRET), SECRET, NOW + 899)
    assert got["kind"] == "pw" and got["sub"] == "pw:session-one" and got["lang"] == "en" and "email" not in got
    assert at.verify(at.sign(pw(), "text secret"), "text secret", NOW) == pw()  # an env secret is text


def test_a_changed_token_is_refused():
    token = at.sign(acct(), SECRET)
    part, mac = token.split(".")
    other = at.sign(acct(sub="acct:someone-else"), SECRET).split(".")[0]
    flip = lambda s, i: s[:i] + ("A" if s[i] != "A" else "B") + s[i + 1:]
    changed = [flip(part, 5) + "." + mac, part + "." + flip(mac, 5), other + "." + mac, part, part + ".", "." + mac,
               token + ".x", token + "=", token + "\n", " " + token, part + "." + mac + "é", "한글.한글", "a.b", "x" * 5000]
    assert [refused(t) for t in changed] == ["bad_token"] * len(changed)
    assert refused(token, secret=b"z" * 32) == "bad_token"
    assert refused(at.sign(acct(), b"z" * 32)) == "bad_token"
    assert at.verify(token, SECRET, NOW)  # the untouched one still passes


def test_a_missing_token_is_no_token():
    assert [refused(t) for t in ("", None)] == ["no_token", "no_token"]


def test_token_expires_900_seconds_after_it_was_issued():
    token = at.sign(acct(), SECRET)
    assert at.verify(token, SECRET, NOW + 899.9)["exp"] == NOW + 900
    assert refused(token, now=NOW + 900) == "token_expired"
    assert refused(token, now=NOW + 5000) == "token_expired"
    assert refused(token[:-1] + ("A" if token[-1] != "A" else "B"), now=NOW + 5000) == "bad_token"  # forged comes first


def test_verify_uses_the_clock_when_no_time_is_given():
    assert at.verify(at.sign(pw(now=time.time()), SECRET), SECRET)["kind"] == "pw"
    assert refused(at.sign(pw(now=time.time() - 901), SECRET), now=None) == "token_expired"


def test_other_audience_version_or_kind_is_refused_even_when_signed():
    wrong = [acct(aud="music"), acct(aud=None), acct(v=2), acct(kind="admin"), acct(kind=""), pw(kind="acct"),
             acct(email=""), {k: v for k, v in acct().items() if k != "email"}, pw(email="kid@example.com"),
             acct(sub="pw:abc"), pw(sub="acct:abc"), pw(sub=""), pw(sub=7), acct(exp=str(NOW + 900)), acct(exp=NOW + 900.5),
             acct(iat=None), acct(lang=None), {k: v for k, v in pw().items() if k != "exp"}]
    assert [refused(at.sign(p, SECRET)) for p in wrong] == ["bad_token"] * len(wrong)
    for not_an_object in ([1, 2], "text", 5, None):
        assert refused(at.sign(not_an_object, SECRET)) == "bad_token"


def test_payload_for_refuses_a_subject_that_does_not_fit_its_kind():
    for kind, sub, email in (("admin", "admin:x", ""), ("acct", "acct:abc", ""), ("acct", "abc", "kid@example.com"),
                             ("pw", "session-one", ""), ("pw", "acct:abc", "")):
        with pytest.raises(ValueError):
            at.payload_for(kind, sub, email, "ko", NOW)
    assert "email" not in at.payload_for("pw", "pw:x", "kid@example.com", "ko", NOW)  # a password token never carries one
    assert at.payload_for("pw", "pw:x", "", "ko", NOW + 0.9)["iat"] == NOW


def test_an_empty_secret_never_signs_or_checks():
    for empty in ("", b"", None):
        with pytest.raises(ValueError):
            at.sign(pw(), empty)
        with pytest.raises(ValueError) as err:
            at.verify(at.sign(pw(), SECRET), empty, NOW)
        assert not isinstance(err.value, at.TokenError)


# ---------- owner ----------
def test_owner_is_the_account_or_the_password_callers_address():
    assert at.owner_of(acct(), SECRET, "203.0.113.5") == "acct:abc"
    one = at.owner_of(pw(), SECRET, "203.0.113.5")
    assert one == "pwip:" + hmac.new(SECRET, b"203.0.113.5", hashlib.sha256).hexdigest()[:16]
    assert at.owner_of(pw(sub="pw:another-reload"), SECRET, "203.0.113.5") == one  # one classroom, one owner
    assert at.owner_of(pw(), SECRET, "203.0.113.6") != one
    assert at.owner_of(pw(), b"z" * 32, "203.0.113.5") != one


def test_a_password_sessions_sub_is_made_for_one_streamlit_session_and_a_reload_has_another():
    """The sub of a password token is "pw:" and studio_owner: 24 random bytes that app.py puts in a session state
    that has none, and writes nowhere else. A reload starts a new session state, so its tokens carry another sub.
    That is why the API counts nothing but requests a minute by it: what must be found again after a reload (jobs,
    request ids, cancel marks, the day's counts) goes by owner_of."""
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    uses = [line.strip() for line in source.splitlines() if "studio_owner" in line]
    made = 'st.session_state.setdefault("studio_owner", secrets.token_urlsafe(24))'
    assert uses.count(made) == 1 and 'kind, sub = ("acct", owner) if email else ("pw", "pw:" + st.session_state.studio_owner)' in uses
    assert not any("studio_owner =" in line or "studio_owner\"] =" in line or "studio_owner'] =" in line for line in uses)
    world = {"st": types.SimpleNamespace(session_state=None), "secrets": __import__("secrets")}
    subs = []
    for _ in range(2):  # two loads of the page
        world["st"].session_state = State()
        exec(made, world)
        subs.append("pw:" + world["st"].session_state.studio_owner)
        exec(made, world)  # a rerun inside the same session keeps it
        assert subs[-1] == "pw:" + world["st"].session_state.studio_owner
    assert subs[0] != subs[1] and all(len(sub) == 3 + 32 for sub in subs)
    assert at.owner_of(pw(sub=subs[0]), SECRET, "203.0.113.5") == at.owner_of(pw(sub=subs[1]), SECRET, "203.0.113.5")


# ---------- the port ----------
def test_the_api_port_is_8502_unless_the_environment_names_another(monkeypatch):
    assert at.API_PORT == 8502 and at.PORT_ENV == "OLMUSE_API_PORT"
    assert [at.api_port({"OLMUSE_API_PORT": said}) for said in ("50123", " 8600 ", "1", "65535")] == [50123, 8600, 1, 65535]
    for said in ("", "0", "65536", "123456", "-1", "85.02", "port", "٨٥٠٢"):  # nothing a server can listen on
        assert at.api_port({"OLMUSE_API_PORT": said}) == 8502
    monkeypatch.delenv("OLMUSE_API_PORT", raising=False)
    assert at.api_port() == at.api_port({}) == 8502
    monkeypatch.setenv("OLMUSE_API_PORT", "50123")  # read on every call, from the process's own environment
    assert at.api_port() == 50123


# ---------- secret ----------
def test_secret_comes_from_the_environment_first(tmp_path):
    path = tmp_path / "data" / "asset_token.key"
    assert at.load_secret(path, env={at.SECRET_ENV: " from-env \n"}) == b"from-env"
    assert not path.parent.exists()
    assert at.SECRET_ENV == "OLMUSE_ASSET_TOKEN_SECRET"
    assert at.SECRET_FILE == ROOT / ".studio-data" / "asset_token.key"


def test_secret_file_is_made_once_with_32_random_bytes(tmp_path):
    path = tmp_path / "data" / "asset_token.key"
    key = at.load_secret(path, env={})
    assert len(key) == 32 and path.read_bytes() == key
    assert at.load_secret(path, env={at.SECRET_ENV: ""}) == key  # an empty variable is no secret
    assert [p.name for p in path.parent.iterdir()] == ["asset_token.key"]  # nothing left beside it
    assert at.load_secret(tmp_path / "other.key", env={}) != key


def test_threads_starting_together_end_with_one_secret(tmp_path):
    path, got, go = tmp_path / "asset_token.key", [], threading.Event()

    def start():
        go.wait()
        got.append(at.load_secret(path, env={}))

    threads = [threading.Thread(target=start) for _ in range(16)]
    for t in threads:
        t.start()
    go.set()
    for t in threads:
        t.join()
    assert len(got) == 16 and set(got) == {path.read_bytes()}
    assert [p.name for p in tmp_path.iterdir()] == ["asset_token.key"]


def test_processes_starting_together_end_with_one_secret(tmp_path):
    """The page and the API are two processes. Each child waits for the go file, then all make or read the key at once."""
    path, go, count = tmp_path / "data" / "asset_token.key", tmp_path / "go", 6
    code = ("import hashlib, os, sys, time, asset_token\n"
            "open(sys.argv[2] + '.' + str(os.getpid()), 'w').close()\n"
            "while not os.path.exists(sys.argv[2]): time.sleep(0.001)\n"
            "print(hashlib.sha256(asset_token.load_secret(sys.argv[1], env={})).hexdigest())")
    children = [subprocess.Popen([sys.executable, "-c", code, str(path), str(go)], cwd=ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8") for _ in range(count)]
    try:
        until = time.monotonic() + 60
        while len(list(tmp_path.glob("go.*"))) < count and time.monotonic() < until:
            time.sleep(0.01)
        go.write_text("go", encoding="ascii")
        ended = [child.communicate(timeout=60) + (child.returncode,) for child in children]
    finally:
        for child in children:
            child.kill()
    assert [(status, err) for _, err, status in ended] == [(0, "")] * count
    assert {out.strip() for out, _, _ in ended} == {hashlib.sha256(path.read_bytes()).hexdigest()}
    assert [p.name for p in path.parent.iterdir()] == ["asset_token.key"]


def test_a_secret_that_can_be_neither_read_nor_made_raises(tmp_path):
    short = tmp_path / "short.key"
    short.write_bytes(b"too short")
    with pytest.raises(OSError):
        at.load_secret(short, env={})
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="ascii")
    with pytest.raises(OSError):
        at.load_secret(blocker / "asset_token.key", env={})


# ---------- session_token ----------
def test_session_token_signs_again_only_for_time_subject_language_or_another_secret():
    state = {}
    first = at.session_token(state, "pw", "pw:one", "", "ko", NOW, secret=SECRET)
    assert first["ttl"] == 900 and at.verify(first["token"], SECRET, NOW)["sub"] == "pw:one"
    assert state[at.TOKEN_STATE]["token"] == first["token"]
    assert at.session_token(state, "pw", "pw:one", "", "ko", NOW + 1.5, secret=SECRET)["token"] == first["token"]
    assert at.session_token(state, "pw", "pw:one", "", "ko", NOW + 600, secret=SECRET) == {"token": first["token"], "ttl": 300}

    renewed = at.session_token(state, "pw", "pw:one", "", "ko", NOW + 601, secret=SECRET)  # 299 seconds were left
    assert renewed["token"] != first["token"] and renewed["ttl"] == 900
    assert at.verify(renewed["token"], SECRET, NOW + 601)["iat"] == NOW + 601
    assert at.session_token(state, "pw", "pw:one", "", "ko", NOW + 700, secret=SECRET)["token"] == renewed["token"]

    reloaded = at.session_token(state, "pw", "pw:two", "", "ko", NOW + 701, secret=SECRET)  # sub changed
    assert reloaded["token"] != renewed["token"] and at.verify(reloaded["token"], SECRET, NOW + 701)["sub"] == "pw:two"

    member = at.session_token(state, "acct", "acct:abc", "kid@example.com", "ko", NOW + 702, secret=SECRET)  # kind changed
    payload = at.verify(member["token"], SECRET, NOW + 702)
    assert (payload["kind"], payload["sub"], payload["email"], payload["exp"]) == ("acct", "acct:abc", "kid@example.com", NOW + 702 + 900)
    assert at.session_token(state, "acct", "acct:abc", "kid@example.com", "ko", NOW + 703, secret=SECRET)["token"] == member["token"]
    other = at.session_token(state, "acct", "acct:xyz", "other@example.com", "ko", NOW + 704, secret=SECRET)
    assert at.verify(other["token"], SECRET, NOW + 704)["email"] == "other@example.com"

    english = at.session_token(state, "acct", "acct:xyz", "other@example.com", "en", NOW + 705, secret=SECRET)  # language changed
    assert english["token"] != other["token"] and at.verify(english["token"], SECRET, NOW + 705)["lang"] == "en"  # the API answers in it
    assert at.session_token(state, "acct", "acct:xyz", "other@example.com", "en", NOW + 706, secret=SECRET)["token"] == english["token"]

    replaced = b"z" * 32  # the operator put another key in place: the old signature is worth nothing at the API
    moved = at.session_token(state, "acct", "acct:xyz", "other@example.com", "en", NOW + 707, secret=replaced)
    assert moved["token"] != english["token"] and at.verify(moved["token"], replaced, NOW + 707)["sub"] == "acct:xyz"
    assert at.session_token(state, "acct", "acct:xyz", "other@example.com", "en", NOW + 708, secret=replaced)["token"] == moved["token"]


def test_ttl_goes_down_in_steps_of_30_and_never_says_more_than_is_left():
    state, seen = {}, []
    first = at.session_token(state, "pw", "pw:one", "", "ko", NOW, secret=SECRET)
    assert at.session_token(state, "pw", "pw:one", "", "ko", NOW + 1.5, secret=SECRET) == {"token": first["token"], "ttl": 870}
    for second in range(601):  # one run of the page each second until the token is signed again
        got = at.session_token(state, "pw", "pw:one", "", "ko", NOW + second, secret=SECRET)
        left = 900 - second
        assert got["token"] == first["token"] and got["ttl"] % at.TTL_STEP == 0 and left - at.TTL_STEP < got["ttl"] <= left
        seen.append(got["ttl"])
    assert at.TTL_STEP == 30 and sorted(set(seen)) == list(range(300, 901, 30))  # 21 values in 601 runs, not 601


def test_session_token_reads_the_shared_secret_when_none_is_given(monkeypatch):
    monkeypatch.setenv(at.SECRET_ENV, "shared-with-the-api")
    got = at.session_token({}, "pw", "pw:one", "", "ko", NOW)
    assert at.verify(got["token"], at.load_secret(), NOW)["sub"] == "pw:one"
    assert at.load_secret() == b"shared-with-the-api"


# ---------- adopt_credits ----------
def ledger_read(state, credits):
    """What app.py's account_view does when it reads the ledger: a fresh account, and adopt_credits is told."""
    state["studio_account"] = {"credits": credits}
    at.account_read(state)


def test_an_agent_views_balance_is_taken_once_so_a_newer_account_read_stays():
    state = {}
    ledger_read(state, 30)
    answer = {"n": "7", "status": "done", "credits": 20}
    assert at.adopt_credits(state, None, answer) is False
    assert state["studio_account"]["credits"] == 20
    ledger_read(state, 8)  # the `account` action read the ledger again
    for _ in range(3):
        assert at.adopt_credits(state, None, answer) is False
        assert state["studio_account"]["credits"] == 8
    assert at.adopt_credits(state, None, {"n": "8", "status": "done", "credits": 5}) is False  # a new answer
    assert state["studio_account"]["credits"] == 5


def test_a_job_views_balance_is_taken_once_per_charge_or_refund():
    state = {}
    ledger_read(state, 30)
    at.adopt_credits(state, {"id": "j1", "calls": 1, "credits": 29}, None)
    assert state["studio_account"]["credits"] == 29
    ledger_read(state, 12)
    at.adopt_credits(state, {"id": "j1", "calls": 1, "credits": 29, "stage": "listening"}, None)
    assert state["studio_account"]["credits"] == 12
    at.adopt_credits(state, {"id": "j1", "calls": 2, "credits": 11}, None)  # the next call was charged
    assert state["studio_account"]["credits"] == 11
    at.adopt_credits(state, {"id": "j1", "calls": 2, "credits": 12}, None)  # Jobs._refund changes credits, not calls
    assert state["studio_account"]["credits"] == 12
    ledger_read(state, 40)
    at.adopt_credits(state, {"id": "j1", "calls": 2, "credits": 12}, None)
    assert state["studio_account"]["credits"] == 40
    at.adopt_credits(state, {"id": "j2", "calls": 2, "credits": 12}, None)  # another job, same numbers
    assert state["studio_account"]["credits"] == 12


def test_views_without_a_balance_change_no_balance():
    state = {"studio_account": {"credits": 30}}
    assert at.adopt_credits(state, None, None) is False
    assert at.adopt_credits(state, {"id": "j1", "status": "running"}, {"n": "7", "status": "working"}) is False
    assert at.adopt_credits(state, {"id": "j1", "calls": 0, "credits": None}, {"n": "7", "credits": None}) is False
    assert state["studio_account"] == {"credits": 30}
    assert at.adopt_credits(state, None, {"n": "7", "status": "done", "credits": 28}) is False  # the same n, once it has a balance
    assert state["studio_account"]["credits"] == 28


def test_a_view_seen_before_the_account_loads_does_not_undo_the_load():
    state = {}
    job, answer = {"id": "j1", "calls": 3, "credits": 20}, {"n": "4", "status": "done", "credits": 21}
    assert at.adopt_credits(state, job, answer) is False
    assert "studio_account" not in state
    ledger_read(state, 8)  # read from the ledger after those views
    assert at.adopt_credits(state, job, answer) is False
    assert state["studio_account"]["credits"] == 8


def test_an_agent_answer_that_comes_after_a_newer_ledger_read_is_not_taken():
    """The answer carries the balance of the charge made before its model call, and comes out after the call."""
    state = {}
    ledger_read(state, 20)
    at.adopt_credits(state, None, None)
    working, answer = {"n": "9", "status": "working"}, {"n": "9", "status": "done", "credits": 18}  # charged 20 -> 18 at the start
    assert at.adopt_credits(state, None, working) is False
    ledger_read(state, 17)  # meanwhile a draft was charged and the frame's asset:account read the ledger
    assert at.adopt_credits(state, None, working) is False
    assert at.adopt_credits(state, None, answer) is True  # may be older than what is shown: the page reads the ledger
    assert state["studio_account"]["credits"] == 17
    ledger_read(state, 17)
    for _ in range(3):
        assert at.adopt_credits(state, None, answer) is False
        assert state["studio_account"]["credits"] == 17

    at.adopt_credits(state, None, {"n": "10", "status": "working"})  # a call with no read in between is taken as before
    assert at.adopt_credits(state, None, {"n": "10", "status": "done", "credits": 15}) is False
    assert state["studio_account"]["credits"] == 15

    ledger_read(state, 14)  # a read after the last run, then the next call is first seen: its charge may be either side of it
    at.adopt_credits(state, None, {"n": "11", "status": "working"})
    at.adopt_credits(state, None, {"n": "11", "status": "working"})
    assert at.adopt_credits(state, None, {"n": "11", "status": "failed", "credits": 15, "error": "x"}) is True
    assert state["studio_account"]["credits"] == 14


def test_a_job_charge_first_seen_right_after_a_ledger_read_is_not_taken():
    state = {}
    ledger_read(state, 30)
    at.adopt_credits(state, None, None)
    ledger_read(state, 18)  # read after the last run looked at the job
    assert at.adopt_credits(state, {"id": "j1", "calls": 1, "credits": 19}, None) is True  # charged before or after that read
    assert state["studio_account"]["credits"] == 18
    ledger_read(state, 18)
    assert at.adopt_credits(state, {"id": "j1", "calls": 1, "credits": 19}, None) is False
    assert at.adopt_credits(state, {"id": "j1", "calls": 2, "credits": 17}, None) is False  # a run later: newer than the read
    assert state["studio_account"]["credits"] == 17


def test_job_and_agent_new_in_one_run_take_one_and_ask_for_the_ledger():
    state = {}
    ledger_read(state, 30)
    at.adopt_credits(state, None, None)
    job, answer = {"id": "j1", "calls": 1, "credits": 29}, {"n": "7", "credits": 27}
    assert at.adopt_credits(state, job, answer) is True  # which of the two charges came last cannot be told
    ledger_read(state, 27)
    assert at.adopt_credits(state, job, answer) is False
    assert state["studio_account"]["credits"] == 27
    assert at.adopt_credits(state, {"id": "j1", "calls": 2, "credits": 26}, answer) is False  # remembered apart
    assert state["studio_account"]["credits"] == 26


def test_an_agent_call_that_overlaps_a_draft_charge_ends_on_the_ledgers_balance():
    """The real Agents._run and a real LocalLedger; only the model is a stand-in."""
    from asset_agent import Agents

    email, owner = "kid@example.com", "acct:abc"
    ledger, agents, state = LocalLedger(":memory:"), Agents(), {}

    def read():  # app.py account_view: a ledger read
        state["studio_account"] = ledger.account(email)
        at.account_read(state)

    def run():  # app.py render: the views first, then the ledger again when a view may be old
        if at.adopt_credits(state, None, agents.view(owner)):
            read()
        return state["studio_account"]["credits"]

    class Engine:
        def ask(self, prompt, schema, name):  # while the model works, a draft is charged and the frame asks for the balance
            run()
            ledger.charge(email, 1, "gen:job1")
            read()
            run()
            return {"reply": "ok", "actions": [], "questions": []}

    class Model:
        def engine(self, model, effort, system=""):
            return Engine()

    read()
    start = run()
    agents.views[owner] = {"n": "1:1", "status": "working"}
    agents._run(owner, "1:1", {"account": email, "model": "", "effort": "", "text": "hi", "state": {}}, Model(), ledger, "ko")
    view, truth = agents.view(owner), ledger.account(email)["credits"]
    assert view["status"] == "done" and truth < view["credits"] < start  # the answer's balance is the older one
    assert [run() for _ in range(5)] == [truth] * 5


# ---------- where it is wired: app.py ----------
class State(dict):
    """st.session_state for the page's functions: every key is an attribute too."""
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Ledger:
    """A ledger that lists its calls and can be made to fail."""

    def __init__(self, credits):
        self.credits, self.calls, self.down = credits, [], False

    def _answer(self, name, value):
        self.calls.append(name)
        if self.down:
            raise LedgerError("ledger down")
        return value

    def account(self, email):
        return self._answer("account", {"credits": self.credits})

    def history(self, email):
        return self._answer("history", [{"kind": "use"}])


def app_tree():
    return ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))


def page(*names, **world):
    """The named top-level functions and assignments of app.py, run alone over a made-up world: app.py is a Streamlit
    script and cannot be imported. Decorators are dropped. Returns the globals those functions run in."""
    picked = [n for n in app_tree().body if (isinstance(n, ast.FunctionDef) and n.name in names)
              or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))]
    assert len(picked) == len(names)
    for node in picked:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    exec(compile(ast.Module(picked, type_ignores=[]), "app.py", "exec"), world)
    return world


def studio_page(ledger, state, views, events):
    """render, handle and account_view of app.py over a counting ledger. views holds the job and agent views of the
    moment, events what the browser sends next; the returned list collects what each run hands to the browser."""
    shown = []

    def studio(**args):
        shown.append(json.loads(json.dumps(args)))  # as the browser gets it
        return events.pop(0) if events else None

    manager = types.SimpleNamespace(model=types.SimpleNamespace(name="model"), snapshot=lambda owner: views.get("job"),
                                    calls_left=lambda email: 5)
    world = page("render", "handle", "account_view", jobs=lambda: manager, owner="acct:abc", email="kid@example.com",
                 agents=lambda: types.SimpleNamespace(view=lambda owner: views.get("agent")), ledger=lambda: ledger,
                 st=types.SimpleNamespace(session_state=state), LedgerError=LedgerError, asset_token=at, studio=studio,
                 price_table=lambda: {}, setting=lambda name, default="": default, lang="ko", ai_ready=True,
                 asset_session=lambda: {"token": "signed", "ttl": 870, "api": "/api/asset"}, T={"server_error": "our side"},
                 log=types.SimpleNamespace(exception=lambda *a: None))
    return world["render"], shown


def test_page_passes_the_token_to_the_component_and_no_longer_overwrites_the_balance():
    render = next(n for n in app_tree().body if isinstance(n, ast.FunctionDef) and n.name == "render")
    assert "studio_account" not in ast.unparse(render) and "asset_token.adopt_credits" in ast.unparse(render)
    ledger, state, views = Ledger(20), State(), {"job": {"id": "j1", "calls": 1, "credits": 19}}
    run, shown = studio_page(ledger, state, views, [])
    run()
    run()
    assert shown[-1]["asset_token"] == {"token": "signed", "ttl": 870, "api": "/api/asset"}
    assert shown[-1]["account"]["credits"] == 20 and ledger.calls == ["account"]  # a view older than the first read is not taken
    views["job"] = {"id": "j1", "calls": 2, "credits": 18}
    run()
    assert shown[-1]["account"]["credits"] == 18 and ledger.calls == ["account"]  # a charge is taken from the view, no ledger call


def test_page_reads_the_ledger_again_when_an_agent_answer_may_be_older_than_the_balance_shown():
    ledger, state, views, events = Ledger(20), State(), {}, []
    run, shown = studio_page(ledger, state, views, events)
    run()
    run()
    views["agent"], ledger.credits = {"n": "1:1", "status": "working"}, 18  # the agent call was charged; its view says nothing yet
    run()
    assert shown[-1]["account"]["credits"] == 20
    ledger.credits = 17  # the generation API charged a draft, and the frame's asset:account reaches the page
    events.append({"event_id": "e1", "action": "account", "payload": {"quiet": True}})
    run()
    run()
    assert shown[-1]["account"]["credits"] == 17 and ledger.calls == ["account", "account"]  # the quiet read skips the history
    views["agent"] = {"n": "1:1", "status": "done", "credits": 18, "reply": "ok"}
    for _ in range(3):
        run()
        assert shown[-1]["account"]["credits"] == 17  # not back to 18
    assert ledger.calls == ["account"] * 3  # one more read for that answer, none after it

    views["agent"], ledger.credits = {"n": "1:2", "status": "working"}, 15  # the same again, but the ledger stops answering
    run()
    events.append({"event_id": "e2", "action": "account", "payload": {"quiet": True}})
    run()
    ledger.down = True
    views["agent"] = {"n": "1:2", "status": "done", "credits": 16, "reply": "ok"}
    for _ in range(3):
        run()
        assert shown[-1]["account"]["credits"] == 15 and shown[-1]["server_error"] == ""  # the balance stays, the chat hears nothing
    assert ledger.calls == ["account"] * 5 and not state.get("studio_error")


def test_the_credits_window_still_reads_the_history_and_says_when_the_ledger_fails():
    ledger, state, events = Ledger(20), State(), []
    run, shown = studio_page(ledger, state, {}, events)
    events.append({"event_id": "e1", "action": "account", "payload": {}})
    run()
    run()
    assert ledger.calls == ["account", "account", "history"] and shown[-1]["account"]["history"] == [{"kind": "use"}]
    ledger.down = True
    events.append({"event_id": "e2", "action": "account", "payload": {"quiet": "yes"}})  # only a real true is quiet
    run()
    run()
    assert shown[-1]["server_error"] == "ledger down"
    events.append({"event_id": "e3", "action": "account", "payload": {"quiet": True}})
    run()
    run()
    assert shown[-1]["server_error"] == ""


def test_only_a_session_that_may_use_ai_gets_a_token_and_it_names_the_api(monkeypatch):
    monkeypatch.delenv("OLMUSE_API_PORT", raising=False)
    state = State(studio_owner="session-one")
    world = page("asset_session", "ASSET_API", ai_ready=False, asset_secret=lambda: SECRET, asset_token=at, LOCAL_AI=False,
                 st=types.SimpleNamespace(session_state=state), email="", owner="session-one", lang="en",
                 time=types.SimpleNamespace(time=lambda: NOW))
    assert world["asset_session"]() is None and at.TOKEN_STATE not in state  # no AI, no token

    world["ai_ready"] = True
    got = world["asset_session"]()
    assert {k: got[k] for k in ("ttl", "api")} == {"ttl": 900, "api": "/api/asset"} and set(got) == {"token", "ttl", "api"}
    payload = at.verify(got["token"], SECRET, NOW)
    assert (payload["kind"], payload["sub"], payload["lang"]) == ("pw", "pw:session-one", "en") and "email" not in payload

    world.update(email="kid@example.com", owner="acct:abc")
    payload = at.verify(world["asset_session"]()["token"], SECRET, NOW)
    assert (payload["kind"], payload["sub"], payload["email"]) == ("acct", "acct:abc", "kid@example.com")

    world["asset_secret"] = lambda: None  # the key can be neither read nor made
    assert world["asset_session"]() is None
    # run_local.ps1 has no tunnel in front, so the page names the API's own port: OLMUSE_API_PORT, else 8502.
    assert page("ASSET_API", LOCAL_AI=True, asset_token=at)["ASSET_API"] == "http://127.0.0.1:8502/api/asset"
    monkeypatch.setenv("OLMUSE_API_PORT", "50123")
    assert page("ASSET_API", LOCAL_AI=True, asset_token=at)["ASSET_API"] == "http://127.0.0.1:50123/api/asset"
    assert page("ASSET_API", LOCAL_AI=False, asset_token=at)["ASSET_API"] == "/api/asset"  # the public page's address stays


def test_the_pages_secret_is_kept_a_minute_at_most_so_a_failed_read_is_tried_again():
    fn = next(n for n in app_tree().body if isinstance(n, ast.FunctionDef) and n.name == "asset_secret")
    (cached,) = fn.decorator_list
    assert ast.unparse(cached.func) == "st.cache_resource"
    assert 0 < {k.arg: ast.literal_eval(k.value) for k in cached.keywords}["ttl"] <= 60  # not for the life of the process

    alerts = []

    def locked():
        raise OSError("locked")

    world = page("asset_secret", asset_token=types.SimpleNamespace(load_secret=locked),
                 log=types.SimpleNamespace(error=lambda *a: alerts.append(a)))
    assert world["asset_secret"]() is None and len(alerts) == 1
    world["asset_token"] = types.SimpleNamespace(load_secret=lambda: SECRET)
    assert world["asset_secret"]() == SECRET


def test_module_loads_without_streamlit():
    code = "import sys, asset_token; print(sorted(m for m in sys.modules if m.split('.')[0] in ('streamlit', 'fastapi')))"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert (done.returncode, done.stdout.strip()) == (0, "[]"), done.stderr


# ---------- where it is wired: the host page (studio_frontend/app.js) ----------
HOST_JS = """
(() => {
  let now = 0, account = { credits: 5 }, aiEnabled = true, listener = null;
  const posts = [], sends = [], timers = [];
  const frame = { src: 'asset_studio/index.html', getAttribute: () => frame.src,
                  contentWindow: { postMessage: (m, origin) => posts.push({ ...m, origin }) } };
  const performance = { now: () => now };
  const location = { origin: 'https://olmuse.example' };
  const setTimeout = (fn, ms) => timers.push({ fn, ms });
  const send = (action, payload) => sends.push([action, payload]);
  const addEventListener = (type, fn) => { listener = fn; };
__TOKEN_BLOCK__
__MESSAGE_BLOCK__
  const at = (seconds) => { now = seconds * 1000; };
  const render = (token, ttl) => takeToken(token && { token, ttl, api: '/api/asset' });
  const fromFrame = (type) => listener({ data: { type }, source: frame.contentWindow });
  const fromElsewhere = (type) => listener({ data: { type }, source: {} });
  const tokens = () => posts.splice(0).filter((p) => p.type === 'asset:token').map((p) => [p.token, p.ttl]);
  const fire = () => timers.splice(0).forEach((t) => t.fn());
  const out = {};
__SCRIPT__
  console.log(JSON.stringify(out));
})();
"""


def host_source():
    return (ROOT / "studio_frontend" / "app.js").read_text(encoding="utf-8")


def host(script):
    """Runs the host page's own token code and its message listener in Node, over a made-up frame, clock and timer."""
    source = host_source()
    start = source.index("  /* ---------- asset room token and balance ---------- */")
    token_block = source[start:source.index("  function onRender(args) {", start)]
    start = source.index("  addEventListener('message', (e) => {\n    if (e.data?.type === 'asset:back')")
    message_block = source[start:source.index("\n  });", start) + len("\n  });")]
    js = HOST_JS.replace("__TOKEN_BLOCK__", token_block).replace("__MESSAGE_BLOCK__", message_block).replace("__SCRIPT__", script)
    done = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_host_page_sends_the_token_to_its_own_origin_only():
    source = host_source()
    lines = [line for line in source.splitlines() if "asset:token" in line]
    sends = [line for line in lines if "postMessage" in line]
    assert len(sends) == 1 and "type: 'asset:token', token" in sends[0] and sends[0].rstrip().endswith("}, location.origin);")
    assert not any("'*'" in line or '"*"' in line for line in lines)
    on_render = source[source.index("  function onRender(args) {"):source.index("  let aiEnabled = false")]
    assert on_render.count("takeToken(args.asset_token);") == 1  # every render: a new token string goes to the frame


def test_host_sends_the_token_on_ready_on_a_new_token_and_when_asked():
    got = host("""
      render('A', 900); out.first = posts.splice(0);
      at(10); render('A', 870); out.same = tokens();
      at(20); fromFrame('asset:ready'); out.ready = posts.splice(0).map((p) => [p.type, p.origin, p.ttl]);
      at(30); fromFrame('asset:token?'); out.asked = tokens();
      fromElsewhere('asset:token?'); fromElsewhere('asset:ready'); out.stranger = posts.splice(0);
      at(40); render('B', 900); out.changed = tokens();
      render(null); fromFrame('asset:ready'); fromFrame('asset:token?'); out.none = tokens();
      render('B', 870); out.back = tokens();
      frame.src = ''; render('C', 900); out.closed = tokens();
      frame.src = 'asset_studio/index.html'; fromFrame('asset:ready'); out.opened = tokens();
    """)
    assert got["first"] == [{"type": "asset:token", "token": "A", "ttl": 900, "api": "/api/asset", "origin": "https://olmuse.example"}]
    assert got["same"] == []  # the string did not change
    assert got["ready"] == [["asset:ai", "https://olmuse.example", None], ["asset:token", "https://olmuse.example", 860]]
    assert got["asked"] == [["A", 850]] and got["stranger"] == []
    assert got["changed"] == [["B", 900]]
    assert got["none"] == [] and got["closed"] == []  # no AI, or the asset room was never opened
    assert got["back"] == [["B", 870]]  # the frame loaded while there was none, so it does not hold B: the same string is sent
    assert got["opened"] == [["C", 900]]


def test_host_tells_the_frame_whether_an_account_is_signed_in_on_its_own_origin_only():
    """The asset room picks its board by `signed` (docs/ASSET_SYNC_SPEC.md E5): a signed-in account's board is kept
    apart and synced, and a sign-out shows the board without an account. It comes with asset:ai, which goes to this
    page's own origin, on the frame's ready and on every render that changes either value."""
    got = host("""
      fromFrame('asset:ready'); out.out = posts.splice(0).filter((p) => p.type === 'asset:ai');
      signedIn = true; fromFrame('asset:ready'); out.in = posts.splice(0).filter((p) => p.type === 'asset:ai');
    """)
    assert got["out"] == [{"type": "asset:ai", "on": True, "signed": False, "origin": "https://olmuse.example"}]
    assert got["in"] == [{"type": "asset:ai", "on": True, "signed": True, "origin": "https://olmuse.example"}]
    source = host_source()
    sends = [line for line in source.splitlines() if "'asset:ai'" in line]
    assert sends and all(line.rstrip().endswith("}, location.origin);") for line in sends)
    on_render = source[source.index("  function onRender(args) {"):source.index("  let aiEnabled = false")]
    assert "signedIn = !!args.signed_in;" in on_render
    assert "if (`${aiEnabled}:${signedIn}` !== aiSent && frame.getAttribute('src')) sendAi();" in on_render
    render = next(n for n in app_tree().body if isinstance(n, ast.FunctionDef) and n.name == "render")
    assert "signed_in=bool(email)" in ast.unparse(render)  # what app.py hands the host for it


def test_host_keeps_the_tokens_clock_and_sends_no_token_that_only_makes_the_frame_ask_again():
    got = host("""
      render('A', 900); tokens();
      at(839); fromFrame('asset:token?'); out.early = tokens();
      at(840); fromFrame('asset:token?'); out.lastMinute = tokens();
      at(880); render('A', 900); fromFrame('asset:ready'); out.resent = tokens();
      for (let ms = 880000; ms < 905000; ms += 50) { now = ms; fromFrame('asset:token?'); }
      out.loop = tokens();
      at(900); fromFrame('asset:ready'); out.dead = tokens();
      at(1000); fromFrame('asset:ready'); fromFrame('asset:token?'); out.long = tokens();
      render('B', 900); out.next = tokens();
    """)
    assert got["early"] == [["A", 61]]
    assert got["lastMinute"] == []  # the frame holds this one already: an answer would make it ask again at once
    assert got["resent"] == [["A", 20]]  # Streamlit sent the same args again 880 s on: a reloaded frame hears 20, not 900
    assert got["loop"] == [] and got["dead"] == [] and got["long"] == []  # renders stopped: nothing to give
    assert got["next"] == [["B", 900]]  # Streamlit is back with a new token


def test_host_gathers_asset_account_into_one_quiet_read():
    got = host("""
      for (let i = 0; i < 24; i++) fromFrame('asset:account');
      out.waits = timers.map((t) => t.ms); out.before = sends.slice();
      fire(); out.sent = sends.splice(0);
      fromFrame('asset:account'); out.again = timers.length; fire(); out.second = sends.splice(0);
      fromElsewhere('asset:account'); out.stranger = timers.length;
      fromFrame('asset:account'); account = null; fire(); out.signedOut = sends.splice(0);
      fromFrame('asset:account'); out.noAccount = timers.length;
    """)
    assert got == {"waits": [2000], "before": [], "sent": [["account", {"quiet": True}]], "again": 1,
                   "second": [["account", {"quiet": True}]], "stranger": 0, "signedOut": [], "noAccount": 0}
