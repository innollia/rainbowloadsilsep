"""Job state on disk: a restart is simulated by building new Jobs/Agents on the same database file."""
import time

import asset_agent as aa
import studio_backend as sb
from credits import LocalLedger

TRACKS = [{"id": "drums", "name": "drums", "role": "drums", "code": 's("bd*4")'}]


def request(**kw):
    return sb.validate_request({"text": "bass", "tracks": TRACKS, "bpm": 120, "lang": "en", **kw})


class Model:
    def edit(self, prompt):
        return {"intent": "talk", "reply": "sounds good", "summary": "", "bpm": 120, "changes": []}


def wait(jobs, owner):
    for _ in range(200):
        snap = jobs.snapshot(owner)
        if snap and snap["status"] != "running":
            return snap
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_finished_result_survives_restart(tmp_path):
    db = str(tmp_path / "jobs.sqlite3")
    jobs = sb.Jobs(Model(), store=sb.job_store(db))
    jobs.submit("acct:a@b.c", request())
    done = wait(jobs, "acct:a@b.c")
    assert done["status"] == "done" and done["messages"][-1]["text"] == "sounds good"
    again = sb.Jobs(Model(), store=sb.job_store(db))
    assert again.snapshot("acct:a@b.c") == done


def test_running_job_fails_and_is_refunded_once(tmp_path):
    db, ledger = str(tmp_path / "jobs.sqlite3"), LocalLedger()
    start = ledger.account("a@b.c")["credits"]
    store = sb.job_store(db)
    job = sb.Job(request(lang="ko"), "acct:a@b.c")
    job.store = store
    job._save()
    ok, _ = ledger.charge("a@b.c", 5, job.id + ":0")
    assert ok
    store.charged("studio", job.owner, "a@b.c", 5, job.id + ":0")  # the process dies during this call

    snap = sb.Jobs(Model(), ledger=ledger, store=sb.job_store(db)).snapshot("acct:a@b.c")
    assert snap["status"] == "failed" and snap["messages"][-1]["text"] == sb.msg("ko", "restarted_refund", n=5)
    assert ledger.account("a@b.c")["credits"] == start
    sb.Jobs(Model(), ledger=ledger, store=sb.job_store(db))  # a second restart refunds nothing more
    assert ledger.account("a@b.c")["credits"] == start


def test_daily_count_survives_restart(tmp_path):
    db = str(tmp_path / "jobs.sqlite3")
    jobs = sb.Jobs(Model(), account_limit=3, daily_limit=None, store=sb.job_store(db))
    jobs.count_call("a@b.c", "o")
    jobs.count_call("a@b.c", "o")
    again = sb.Jobs(Model(), account_limit=3, daily_limit=None, store=sb.job_store(db))
    assert again.calls_left("a@b.c", "o") == 1


def test_working_agent_call_fails_and_is_refunded_once(tmp_path):
    db, ledger = str(tmp_path / "jobs.sqlite3"), LocalLedger()
    start = ledger.account("a@b.c")["credits"]
    store = sb.job_store(db)
    store.save("agent", "o1", {"n": "1", "status": "working"}, "en")
    ledger.charge("a@b.c", 4, "agent:o1:x")
    store.charged("agent", "o1", "a@b.c", 4, "agent:o1:x")

    view = aa.Agents(sb.job_store(db), ledger).view("o1")
    assert view["status"] == "failed" and view["error"] == sb.msg("en", "restarted_refund", n=4)
    assert ledger.account("a@b.c")["credits"] == start
    aa.Agents(sb.job_store(db), ledger)
    assert ledger.account("a@b.c")["credits"] == start


def test_finished_agent_view_survives_restart(tmp_path):
    db = str(tmp_path / "jobs.sqlite3")
    agents = aa.Agents(sb.job_store(db))
    agents.fail("o2", "7", "nope")
    assert aa.Agents(sb.job_store(db)).view("o2") == {"n": "7", "status": "failed", "error": "nope"}
