"""The fixes from docs/TECH_REVIEW.md: closed ledger, operator spend cap, password tries, refunds on any failure,
hashed emails on disk, logs and backups."""
import logging
import sqlite3
import sys
import time
from pathlib import Path

import pytest

import asset_agent as aa
import server_ops
import studio_backend as sb
from credits import LocalLedger, RemoteLedger, email_key, open_ledger, worst_usd

ROOT = Path(__file__).resolve().parents[1]
TRACKS = [{"id": "drums", "name": "drums", "role": "drums", "code": 's("bd*4")'}]


def request(**kw):
    return sb.validate_request({"text": "bass", "tracks": TRACKS, "bpm": 120, "lang": "en", **kw})


def member(email, **kw):
    return {**request(**kw), "account": email}


def wait(jobs, owner):
    for _ in range(500):
        snap = jobs.snapshot(owner)
        if snap and snap["status"] != "running":
            return snap
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class Talk:
    def __init__(self):
        self.calls = 0

    def edit(self, prompt):
        self.calls += 1
        return {"intent": "talk", "reply": "hi", "summary": "", "bpm": 120, "changes": []}


class Broken:
    def edit(self, prompt):
        raise RuntimeError("bug with secret sk-or-abcdefghijklmnop and me@example.com")


# ---------- 2. the ledger fails closed ----------
def test_no_remote_ledger_and_no_local_mode_means_no_ledger(tmp_path):
    led, problem = open_ledger("", "", "", False, str(tmp_path / "credits.sqlite"))
    assert led is None and "STRUDEL_CREDITS_URL" in problem and not (tmp_path / "credits.sqlite").exists()
    led, problem = open_ledger("https://x", "token", "", False, str(tmp_path / "credits.sqlite"))
    assert led is None and "pepper" in problem


def test_local_ledger_only_when_chosen_and_remote_when_configured(tmp_path):
    led, problem = open_ledger("", "", "", True, str(tmp_path / "credits.sqlite"))
    assert isinstance(led, LocalLedger) and not problem
    led, problem = open_ledger("https://x", "token", "pep", False, "")
    assert isinstance(led, RemoteLedger) and not problem and led.key_of("A@b.c ") == email_key("pep", "a@b.c")


def test_signed_in_job_without_ledger_never_calls_the_model():
    model = Talk()
    jobs = sb.Jobs(model, ledger=None)
    jobs.submit("acct:x", member("a@b.c"))
    snap = wait(jobs, "acct:x")
    assert snap["status"] == "failed" and snap["messages"][-1]["text"] == sb.msg("en", "no_ledger") and model.calls == 0


def test_signed_in_agent_without_ledger_never_calls_the_model():
    class Engine:
        prompts = []

        def ask(self, prompt, schema, name):
            self.prompts.append(prompt)
            return {"reply": "", "actions": [], "questions": []}

    class Model:
        def engine(self, model, effort, system=None):
            return Engine()

    agents = aa.Agents()
    agents.start("o", {"n": "1", "text": "x", "state": {}, "lang": "en", "account": "a@b.c"}, Model(), sb.Jobs(None), None)
    view = _agent_wait(agents, "o")
    assert view["status"] == "failed" and view["error"] == sb.msg("en", "no_ledger") and not Engine.prompts


# ---------- 1. the password sessions' daily dollar cap ----------
def test_operator_cap_stops_password_sessions_but_not_members():
    model = Talk()
    cap = worst_usd("", "") * 2.5  # room for two calls of the dearest model
    jobs = sb.Jobs(model, operator_usd=cap, ledger=LocalLedger())
    for i in range(2):
        jobs.submit(f"s{i}", request())
        assert wait(jobs, f"s{i}")["status"] == "done"
    jobs.submit("s9", request(lang="ko"))
    snap = wait(jobs, "s9")
    assert snap["status"] == "limit" and snap["messages"][-1]["text"] == sb.msg("ko", "operator_limit") and model.calls == 2
    jobs.submit("acct:m", member("m@b.c"))  # members pay with credits; the cap is not theirs
    assert wait(jobs, "acct:m")["status"] == "done"
    with pytest.raises(ValueError, match="budget"):
        jobs.count_call("", "s1", "en", model="", effort="")


def test_operator_cap_survives_restart_and_counts_cheap_models_cheaply(tmp_path):
    db = str(tmp_path / "jobs.sqlite3")
    jobs = sb.Jobs(Talk(), operator_usd=0.01, store=sb.job_store(db))
    for _ in range(3):  # 3 × 0.0032
        jobs.count_call("", "s", "en", model="deepseek/deepseek-v4.1-flash", effort="")
    again = sb.Jobs(Talk(), operator_usd=0.01, store=sb.job_store(db))
    with pytest.raises(ValueError):
        again.count_call("", "s", "en", model="deepseek/deepseek-v4.1-flash", effort="")


# ---------- 10. refunds on any failure, 5. logged tracebacks ----------
def test_unexpected_engine_error_refunds_and_logs_traceback(caplog):
    ledger = LocalLedger()
    start = ledger.account("a@b.c")["credits"]
    jobs = sb.Jobs(Broken(), ledger=ledger)
    with caplog.at_level(logging.ERROR, logger="olmuse"):
        jobs.submit("acct:a", member("a@b.c"))
        snap = wait(jobs, "acct:a")
    assert snap["status"] == "failed" and snap["messages"][-1]["text"] == sb.msg("en", "internal")
    assert ledger.account("a@b.c")["credits"] == start
    assert any(r.exc_info and r.exc_info[0] is RuntimeError for r in caplog.records)


def _agent_wait(agents, owner):
    for _ in range(300):
        v = agents.view(owner)
        if v and v["status"] != "working":
            return v
        time.sleep(0.01)
    raise AssertionError("agent stuck at working")


def test_agent_unexpected_error_fails_refunds_and_hides_the_text(caplog):
    class Model:
        def engine(self, model, effort, system=None):
            class E:
                def ask(self, *a):
                    raise KeyError("internal detail")
            return E()

    class Jobs:
        def count_call(self, *a, **kw):
            pass

    ledger = LocalLedger()
    start = ledger.account("a@b.c")["credits"]
    agents = aa.Agents(sb.job_store(":memory:"), ledger)
    with caplog.at_level(logging.ERROR, logger="olmuse"):
        agents.start("o", {"n": "1", "text": "x", "state": {}, "lang": "ko", "account": "a@b.c"}, Model(), Jobs(), ledger)
        view = _agent_wait(agents, "o")
    assert view["status"] == "failed" and view["error"] == sb.msg("ko", "internal") and "detail" not in view["error"]
    assert ledger.account("a@b.c")["credits"] == start and view["credits"] == start
    assert agents.store.db.execute("select count(*) from charges").fetchone()[0] == 0
    assert any(r.exc_info for r in caplog.records)


# ---------- 6. no plain emails in jobs.sqlite3 ----------
def test_store_keeps_account_keys_not_emails(tmp_path):
    db, ledger = tmp_path / "jobs.sqlite3", LocalLedger(pepper="p")
    store = sb.job_store(str(db), hasher=ledger.key_of)
    jobs = sb.Jobs(Talk(), ledger=ledger, account_limit=5, store=store)
    owner = store.owner("A@B.c")
    assert owner == "acct:" + ledger.key_of("a@b.c")
    jobs.submit(owner, member("a@b.c"))
    wait(jobs, owner)
    store.charged("studio", owner, "a@b.c", 2, "ref-1")
    dump = "\n".join(sqlite3.connect(db).iterdump())
    assert "a@b.c" not in dump.lower() and ledger.key_of("a@b.c") in dump


def test_old_plain_rows_are_hashed_and_still_refunded(tmp_path):
    db, ledger = str(tmp_path / "jobs.sqlite3"), LocalLedger(pepper="p")
    start = ledger.account("a@b.c")["credits"]
    old = sb.job_store(db)  # before hashing: emails in plain
    old.save("studio", "acct:a@b.c", {"id": "j", "status": "running", "messages": []}, "en")
    ledger.charge("a@b.c", 3, "j:0")
    old.charged("studio", "acct:a@b.c", "a@b.c", 3, "j:0")
    old.count("2026-01-01", ["acct:a@b.c"])
    old.db.close()

    jobs = sb.Jobs(Talk(), ledger=ledger, store=sb.job_store(db, hasher=ledger.key_of))
    owner = "acct:" + ledger.key_of("a@b.c")
    assert jobs.snapshot(owner)["status"] == "failed"
    assert ledger.account("a@b.c")["credits"] == start  # refunded by account key
    dump = "\n".join(sqlite3.connect(db).iterdump())
    assert "a@b.c" not in dump


def test_finished_results_are_deleted_after_30_days(tmp_path):
    db = str(tmp_path / "jobs.sqlite3")
    store = sb.job_store(db)
    store.save("studio", "old", {"status": "done"}, "en")
    store.save("studio", "new", {"status": "done"}, "en")
    store.db.execute("update views set at=? where owner='old'", (time.time() - 31 * 86400,))
    store.db.commit()
    store.db.close()
    owners = [r[0] for r in sb.job_store(db).db.execute("select owner from views")]
    assert owners == ["new"]


# ---------- 1. password tries ----------
def test_password_gate_locks_a_session_then_everyone():
    now = [1000.0]
    gate = server_ops.PasswordGate(session_tries=3, hourly_tries=5, lock_seconds=60, clock=lambda: now[0])
    assert gate.check("a", "x", "pw") == "wrong"
    assert gate.check("a", "pw", "pw") == "ok"
    gate.check("a", "x", "pw"), gate.check("a", "x", "pw")
    assert gate.check("a", "pw", "pw") == "locked"  # 3 wrong in this session: even the right one is refused
    assert gate.check("b", "pw", "pw") == "ok"
    gate.check("b", "x", "pw"), gate.check("c", "x", "pw")
    assert gate.check("d", "pw", "pw") == "locked"  # 5 wrong in the hour, from any session
    now[0] += 3601
    assert gate.check("a", "pw", "pw") == "ok"


def test_password_gate_refuses_empty_password():
    assert server_ops.PasswordGate().check("a", "", "") == "wrong"


# ---------- 5. logs ----------
def test_log_file_rotates_daily_and_hides_secrets(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = server_ops.setup_logging(tmp_path / "logs")
        assert server_ops.setup_logging(tmp_path / "logs") == path  # a second call adds nothing
        assert len(root.handlers) == len(before) + 1
        try:
            raise RuntimeError("token " + "ab" * 32 + " for me@example.com with sk-ant-api03-abcdefghijkl")
        except RuntimeError:
            logging.getLogger("olmuse.test").exception("failed for %s", "you@example.com")
        for h in root.handlers:
            h.flush()
        text = path.read_text(encoding="utf-8")
        assert "Traceback" in text and "RuntimeError" in text
        assert "example.com" not in text and "sk-ant" not in text and "ab" * 32 not in text
        handler = next(h for h in root.handlers if getattr(h, "olmuse", False))
        assert handler.backupCount == 7 and handler.when == "MIDNIGHT"
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()


def test_redact_hides_emails_and_bearer_tokens():
    text = sb.redact("Authorization: Bearer abcdefghijklmnop from a@b.co")
    assert "abcdefghijklmnop" not in text and "a@b.co" not in text


# ---------- 4. backups ----------
def test_backup_copies_wal_databases_and_keeps_the_newest_days(tmp_path):
    data, dest = tmp_path / "data", tmp_path / "backups"
    data.mkdir()
    live = sqlite3.connect(data / "jobs.sqlite3")
    live.execute("pragma journal_mode=wal")
    live.execute("create table t (x)")
    live.execute("insert into t values (42)")
    live.commit()  # still in the -wal file while the connection is open
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        server_ops.backup_sqlite(data, dest, keep=2, day=day)
    live.close()
    assert sorted(p.name for p in dest.iterdir()) == ["2026-01-02", "2026-01-03"]
    copied = dest / "2026-01-03" / "jobs.sqlite3"
    assert not list((dest / "2026-01-03").glob("*-wal"))
    check = sqlite3.connect(copied)
    assert check.execute("select x from t").fetchone() == (42,)
    check.close()


# ---------- 3. coupons need the admin token ----------
def test_coupon_tool_uses_only_the_admin_token(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import coupon
    monkeypatch.setenv("STRUDEL_CREDITS_URL", "https://ledger.example")
    monkeypatch.delenv("STRUDEL_CREDITS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("STRUDEL_LOCAL_LEDGER", raising=False)
    monkeypatch.setenv("STRUDEL_CREDITS_TOKEN", "the-app-token")  # must not be used
    monkeypatch.setattr(coupon, "ADMIN_TOKEN_FILE", tmp_path / "missing.token")
    with pytest.raises(SystemExit):
        coupon.ledger()
    (tmp_path / "admin.token").write_text("the-admin-token", encoding="ascii")
    monkeypatch.setattr(coupon, "ADMIN_TOKEN_FILE", tmp_path / "admin.token")
    led, where = coupon.ledger()
    assert where == "remote" and led.token == "the-admin-token"
