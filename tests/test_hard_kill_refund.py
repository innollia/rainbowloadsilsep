"""A server process killed outright during a paid model call (no finally blocks run) refunds that call on the next
start, once, for both the music screen jobs and the asset agent."""
import os
import subprocess
import sys
import textwrap
import time

import asset_agent as aa
import studio_backend as sb
from credits import LocalLedger

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, ROOT)
    import studio_backend as sb, asset_agent as aa
    from credits import LocalLedger
    ledger = LocalLedger(D + "/credits.sqlite", pepper="p")
    store = sb.job_store(D + "/jobs.sqlite3", hasher=ledger.key_of)
    def hang(*a, **k):
        open(D + "/in_call", "w").write("x")
        time.sleep(600)
    class Eng:
        def __getattr__(self, name):
            return hang
    class Model:
        edit = staticmethod(hang)
        def engine(self, *a, **k):
            return Eng()
    class NoLimit:
        def count_call(self, *a, **k):
            pass
    if KIND == "studio":
        req = sb.validate_request({"text": "bass", "tracks": [{"id": "d", "name": "d", "role": "drums",
                                   "code": 's("bd*4")'}], "bpm": 120, "lang": "ko"})
        req["account"] = "a@b.c"
        sb.Jobs(Model(), ledger=ledger, store=store).submit("acct:a@b.c", req)
    else:
        aa.Agents(store=store, ledger=ledger).start(OWNER, {"n": "1", "text": "x", "state": {}, "lang": "ko",
                                                   "account": "a@b.c"}, Model(), NoLimit(), ledger)
    time.sleep(600)
""")


def kill_during_call(d, kind, owner):
    code = f"ROOT={ROOT!r}\nD={str(d)!r}\nKIND={kind!r}\nOWNER={owner!r}\n" + CHILD
    p = subprocess.Popen([sys.executable, "-c", code])
    try:
        for _ in range(300):
            if (d / "in_call").exists():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("child never reached the model call")
    finally:
        p.kill()
        p.wait()


def test_studio_call_killed_mid_flight_is_refunded(tmp_path):
    kill_during_call(tmp_path, "studio", "acct:a@b.c")
    ledger = LocalLedger(str(tmp_path / "credits.sqlite"), pepper="p")
    assert ledger.account("a@b.c")["credits"] == 18
    store = lambda: sb.job_store(str(tmp_path / "jobs.sqlite3"), hasher=ledger.key_of)
    jobs = sb.Jobs(object(), ledger=ledger, store=store())
    snap = jobs.restored["acct:" + ledger.key_of("a@b.c")]
    assert snap["status"] == "failed" and snap["messages"][-1]["text"] == sb.msg("ko", "restarted_refund", n=2)
    assert ledger.account("a@b.c")["credits"] == 20
    sb.Jobs(object(), ledger=ledger, store=store())
    assert ledger.account("a@b.c")["credits"] == 20


def test_agent_call_killed_mid_flight_is_refunded(tmp_path):
    owner = "acct:" + LocalLedger(":memory:", pepper="p").key_of("a@b.c")
    kill_during_call(tmp_path, "agent", owner)
    ledger = LocalLedger(str(tmp_path / "credits.sqlite"), pepper="p")
    assert ledger.account("a@b.c")["credits"] == 18
    store = lambda: sb.job_store(str(tmp_path / "jobs.sqlite3"), hasher=ledger.key_of)
    view = aa.Agents(store=store(), ledger=ledger).view(owner)
    assert view["status"] == "failed" and view["error"] == sb.restart_message("ko", 2)
    assert ledger.account("a@b.c")["credits"] == 20
    aa.Agents(store=store(), ledger=ledger)
    assert ledger.account("a@b.c")["credits"] == 20
