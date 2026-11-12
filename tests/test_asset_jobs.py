"""The asset room's generation jobs (asset_jobs.py): the charge when a draft is picked and every way it is
refunded, the queue and its ceilings, the sweeper and a restart. No key and no engine: FakeModel, FakeEngine, a
measure of the test's own, LocalLedger behind a wrapper that can hang or fail, and a clock the test moves."""
import collections
import datetime
import io
import json
import logging
import os
import sqlite3
import struct
import subprocess
import sys
import textwrap
import threading
import time
import wave

import pytest

import asset_generate as ag
import asset_jobs as aj
import asset_token
import server_ops
import studio_backend as sb
from asset_engine import nkido
from credits import LedgerError, LocalLedger

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = datetime.datetime(2026, 3, 10, 12, 0).timestamp()  # noon, so an hour later is still the same day
MODEL = "deepseek/deepseek-v4.1-flash"
EST = 27_000  # three calls at 0.009 dollars, in millionths
TOMORROW = 43_201  # retry_after of a daily count at T0: the seconds from noon to the next day, and one
PW = aj.Who("pw", "pwip:0123456789abcdef", "", "en")
BROKEN = lambda: nkido.RenderError("compile", "bad", 1)  # noqa: E731


def lint(wav, kind="sfx", loop=False, loud=(-20, -16)):
    """A measure that finds nothing wrong: the length from the file, every level in range."""
    with wave.open(io.BytesIO(wav)) as w:
        seconds = w.getnframes() / w.getframerate()
    return {"measure": {"seconds": seconds, "rate": 48000, "channels": 2, "bits": 16, "sample_peak": -10.0, "peak": -10.0,
                        "loud": -18.0, "clips": 0, "lead": 0.0, "tail": 0.0, "end": -70.0, "dc": 0.0, "seam": 0.0}, "issues": []}


class Ledger:
    """LocalLedger with every call written down. fail: calls that raise before they do anything. lose: calls that
    do their work and then raise (the answer was lost). gates: an Event a call waits on."""

    def __init__(self, path=":memory:", free=20):
        self.real = LocalLedger(path, pepper="p", free=free)
        self.calls, self.locked = [], []
        self.fail, self.lose, self.gates = set(), set(), {}
        self.entered = collections.defaultdict(threading.Event)
        self.hang_for = None  # only this email's `account` waits on the gate
        self.watch = None     # the store's lock: it must not be held while the ledger is called

    def key_of(self, email):
        return self.real.key_of(email)

    def _call(self, name, what, work, email=""):
        self.calls.append((name, what))
        if self.watch is not None:
            self.locked.append(self.watch.locked())
        self.entered[name].set()
        if name in self.gates and (name != "account" or self.hang_for in (None, email)):
            self.gates[name].wait(30)
        if name in self.fail:
            raise LedgerError("down")
        out = work()
        if name in self.lose:
            raise LedgerError("the answer was lost")
        return out

    def account(self, email):
        return self._call("account", email, lambda: self.real.account(email), email)

    def charge(self, email, amount, ref):
        return self._call("charge", ref, lambda: self.real.charge(email, amount, ref))

    def refund_key(self, key, amount, ref):
        return self._call("refund", ref, lambda: self.real.refund_key(key, amount, ref))

    def named(self, name):
        return [what for call, what in self.calls if call == name]

    def credits(self, email="a@b.c"):
        return self.real.account(email)["credits"]


class Bench:
    def __init__(self, folder, *, script=(), engine=(), limits=None, model_name=MODEL, cost=0.002, free=20, ledger=True,
                 store=None, model=True, autostart=False, workers=1, measure=lint):
        self.now, self.slept = [T0], []
        self.ledger = Ledger(free=free) if ledger is True else ledger
        self.model = ag.FakeModel(script, cost=cost)
        self.engine = ag.FakeEngine(engine) if isinstance(engine, (list, tuple)) else engine
        self.store = store or aj.GenStore()
        self.jobs = aj.GenJobs(self.store, ledger=self.ledger, model=(lambda: self.model) if model else None,
                               engine=self.engine, measure=measure, renders=folder / "renders", temp=folder / "temp",
                               limits=limits, model_name=model_name, clock=lambda: self.now[0], sleep=self.sleep,
                               free=lambda path: 100 * aj.GB, autostart=autostart, workers=workers)
        if self.ledger:
            self.ledger.watch = self.store.lock

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now[0] += seconds

    def later(self, seconds):
        self.now[0] += seconds

    def who(self, email="a@b.c", lang="en"):
        return aj.Who("acct", "acct:" + self.ledger.key_of(email), email, lang)

    def row(self, job_id):
        with self.store.lock:
            found = self.store.db.execute("select * from gen where id=?", (job_id,)).fetchone()
        return dict(found) if found else None

    def view(self, who, job_id):
        return self.jobs.status(who, [job_id])["jobs"][0]

    def send(self, who, **said):
        return [job["id"] for job in self.jobs.submit(who, body(**said))["jobs"]]

    def release(self):
        for gate in [self.model.gate, getattr(self.engine, "gate", None), *(self.ledger.gates.values() if self.ledger else ())]:
            if gate is not None:
                gate.set()


@pytest.fixture
def bench(tmp_path):
    made = []

    def make(**options):
        made.append(Bench(tmp_path / f"bench{len(made)}", **options))
        return made[-1]
    yield make
    for b in made:
        b.release()
        b.jobs.stop()


def body(rid="r1", items=1, drafts=1, credits=None, kind="sfx", free=False, **more):
    things = items if isinstance(items, list) else [{"ref": f"k{i}", "kind": kind, "name": f"sound{i}", "seconds": 0.2}
                                                     for i in range(items)]
    cost = 0 if free else len(things) * drafts
    return {"request_id": rid, "expect_credits": cost if credits is None else credits, "drafts": drafts,
            "project": {"game": "g"}, "items": things, **more}


def until(check, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("the wait ran out")


def refused(call, *args):
    with pytest.raises(aj.GenError) as caught:
        call(*args)
    return caught.value.status, caught.value.code, caught.value.extras


def put(store, job_id, owner, status, charge, **more):
    """A row written straight into the store, for states a test cannot reach by running jobs."""
    row = {"id": job_id, "owner": owner, "cls": "pw" if owner.startswith("pwip:") else "acct", "batch": "b", "request_id": "rq",
           "ref": "k0", "k": 1, "n": 1, "ord": 0, "status": status, "attempt": 0, "view": json.dumps({"lang": "en"}),
           "input": "{}", "cancel": 0, "charge": charge, "charge_at": T0 - 10, "est": 0, "usd": 0, "bytes": 0, "created": T0 - 20, **more}
    with store.lock:
        store.db.execute(f"insert into gen ({', '.join(row)}) values ({', '.join('?' * len(row))})", list(row.values()))


# ---------- the charge and the refund ----------
def test_a_draft_is_charged_when_it_is_picked_and_not_before(bench):
    b = bench()
    a = b.who()
    ids = b.send(a, items=2)
    assert b.ledger.named("charge") == [] and b.ledger.credits() == 20
    assert [b.row(i)["charge"] for i in ids] == ["none", "none"] and b.jobs.count("d:" + a.owner) == 0
    assert b.jobs.drain() == 2
    assert b.ledger.named("charge") == ["gen:" + ids[0], "gen:" + ids[1]] and b.ledger.named("refund") == []
    assert [(b.row(i)["status"], b.row(i)["charge"]) for i in ids] == [("done", "charged")] * 2
    status = b.jobs.status(a, ids)
    assert status["credits"] == 18 == b.ledger.credits() and [v["refund"] for v in status["jobs"]] == ["none", "none"]
    assert (b.jobs.count("d:" + a.owner), b.jobs.count("d:members"), b.jobs.count("d:teachers")) == (2, 2, 0)
    assert not any(b.ledger.locked)  # the lock was never held while the ledger was called


def test_a_password_session_pays_nothing(bench):
    b = bench()
    ids = b.send(PW, free=True)
    b.jobs.drain()
    assert b.row(ids[0])["status"] == "done" and b.row(ids[0])["charge"] == "none" and b.ledger.calls == []
    assert (b.jobs.count("d:" + PW.owner), b.jobs.count("d:teachers"), b.jobs.count("d:members")) == (1, 1, 0)
    assert b.jobs.status(PW, ids)["credits"] is None


def test_a_failed_draft_is_refunded_once(bench):
    b = bench(engine=[BROKEN(), BROKEN(), BROKEN()])
    a = b.who()
    ids = b.send(a)
    b.jobs.drain()
    view = b.view(a, ids[0])
    assert (view["status"], view["error"]["code"], view["refund"]) == ("failed", "make_failed", "done")
    assert view["error"]["message"] == aj.message("en", "make_failed") and "result" not in view
    assert b.ledger.named("refund") == ["gen:" + ids[0]] and b.ledger.credits() == 20 and len(b.model.prompts) == 3
    assert b.row(ids[0])["charge"] == "refunded" and b.row(ids[0])["input"] is None  # the request text is gone
    assert b.jobs.status(a, ids)["credits"] == 20
    b.later(500)
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 1 and not (b.jobs.renders / ids[0]).exists()


def test_a_received_result_is_never_refunded(bench):
    b = bench()
    a = b.who()
    ids = b.send(a)
    b.jobs.drain()
    sound = b.jobs.sound(a, ids[0])
    assert sound.read()[:4] == b"RIFF" and len(sound.read()) == sound.bytes and b.row(ids[0])["charge"] == "kept"
    assert b.view(a, ids[0])["expires"] == T0 + aj.RESULT_TTL
    assert b.jobs.sound(a, ids[0]).sha256 == sound.sha256  # again, until it expires
    b.later(aj.RESULT_TTL - 1)
    b.jobs.sweep()
    assert b.view(a, ids[0])["status"] == "done"
    b.later(2)
    b.jobs.sweep()
    assert b.view(a, ids[0]) == {"id": ids[0], "status": "gone", "refund": "none"}
    assert b.ledger.named("refund") == [] and b.ledger.credits() == 19 and not (b.jobs.renders / ids[0]).exists()
    assert refused(b.jobs.sound, a, ids[0])[:2] == (404, "not_found")
    row = b.row(ids[0])
    assert row["view"] is None and row["input"] is None and row["charge"] == "kept"


def test_a_result_nobody_received_is_refunded_and_deleted_after_an_hour(bench):
    b = bench()
    a = b.who()
    ids = b.send(a)
    b.jobs.drain()
    assert b.view(a, ids[0])["expires"] == T0 + aj.UNFETCHED_TTL == T0 + 3600 and (b.jobs.renders / ids[0] / "master.wav").is_file()
    b.later(3599)
    b.jobs.sweep()
    assert b.view(a, ids[0])["status"] == "done" and b.ledger.named("refund") == []
    b.later(1)
    b.jobs.sweep()
    assert b.view(a, ids[0]) == {"id": ids[0], "status": "gone", "refund": "done"}
    assert b.ledger.named("refund") == ["gen:" + ids[0]] and b.ledger.credits() == 20 and not (b.jobs.renders / ids[0]).exists()
    assert b.jobs.count("d:members") == 0 and b.jobs.count("d:" + a.owner) == 1 and b.jobs.count("rf:" + a.owner) == 1
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 1
    b.later(aj.TRACE_TTL + 1)  # the trace stays seven days
    b.jobs.sweep()
    assert b.view(a, ids[0]) == {"id": ids[0], "status": "unknown", "refund": "none"}


def test_receiving_and_the_unfetched_expiry_cannot_both_win(bench):
    b = bench()
    a = b.who()
    first, second = b.send(a, items=2)
    b.jobs.drain()
    b.later(aj.UNFETCHED_TTL)
    b.jobs.sound(a, first)  # received in the same second it would expire
    b.jobs.sweep()
    assert (b.row(first)["status"], b.row(first)["charge"]) == ("done", "kept")
    assert (b.row(second)["status"], b.row(second)["charge"]) == ("gone", "refunded")
    assert refused(b.jobs.sound, a, second)[:2] == (404, "not_found") and b.row(second)["delivered"] is None
    with b.store.lock, b.store.tx() as db:  # the expiry's own update finds nothing to take once the result was received
        assert b.jobs._gone(db, first, b.now[0], received=False) is False
    assert b.ledger.named("refund") == ["gen:" + second] and b.ledger.credits() == 19


def test_the_sweeper_tries_a_refund_again_after_a_ledger_error(bench):
    b = bench(engine=[BROKEN(), BROKEN(), BROKEN()])
    a = b.who()
    b.ledger.fail.add("refund")
    ids = b.send(a)
    b.jobs.drain()
    assert b.row(ids[0])["charge"] == "refund_due" and b.view(a, ids[0])["refund"] == "pending"
    assert len(b.ledger.named("refund")) == 1 and b.ledger.credits() == 19  # the worker's own try
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 1  # the charge is not 90 seconds old yet
    b.later(91)
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 2 and b.row(ids[0])["charge"] == "refund_due"
    b.ledger.fail.clear()
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 3 and b.row(ids[0])["charge"] == "refunded" and b.ledger.credits() == 20
    assert b.view(a, ids[0])["refund"] == "done"
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 3


def test_a_cancel_while_the_charge_is_out_never_refunds_before_the_charge_answers(bench):
    b = bench(autostart=True)
    a = b.who()
    b.ledger.gates["charge"] = threading.Event()
    ids = b.send(a)
    assert b.ledger.entered["charge"].wait(10)
    view = b.jobs.cancel(a, ids)["jobs"][0]
    assert (view["status"], view["refund"]) == ("cancelled", "pending") and b.row(ids[0])["status"] == "running"
    b.later(400)  # old enough for the sweeper on both counts, but a live worker holds the job
    b.jobs.sweep()
    assert b.ledger.named("refund") == [] and b.row(ids[0])["charge"] == "pending"
    b.ledger.gates["charge"].set()
    until(lambda: b.row(ids[0])["charge"] == "refunded")
    assert b.ledger.calls[-2:] == [("charge", "gen:" + ids[0]), ("refund", "gen:" + ids[0])]
    assert len(b.ledger.named("refund")) == 1 and b.ledger.credits() == 20 and b.model.prompts == []
    assert b.row(ids[0])["status"] == "cancelled" and b.view(a, ids[0])["refund"] == "done"
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 1


def test_three_failed_charges_leave_it_unknown_and_the_refund_waits_90_seconds(bench):
    b = bench()
    a = b.who()
    b.ledger.lose.add("charge")  # the ledger takes the credit and the answer never arrives
    ids = b.send(a)
    b.jobs.drain()
    row = b.row(ids[0])
    assert (row["status"], row["error"], row["charge"]) == ("failed", "no_ledger", "unknown")
    assert len(b.ledger.named("charge")) == 3 and b.slept == [3, 10] and row["charge_at"] == T0 + 13  # the last try
    assert b.view(a, ids[0])["refund"] == "pending" and b.ledger.credits() == 19 and b.model.prompts == []
    b.jobs.sweep()
    b.later(89)
    b.jobs.sweep()
    assert b.ledger.named("refund") == []
    b.later(2)
    b.jobs.sweep()
    assert b.ledger.named("refund") == ["gen:" + ids[0]] and b.row(ids[0])["charge"] == "refunded" and b.ledger.credits() == 20
    b.later(1000)
    b.jobs.sweep()
    assert len(b.ledger.named("refund")) == 1
    assert (b.jobs.count("d:members"), b.jobs.count("d:" + a.owner), b.jobs.count("rf:" + a.owner)) == (0, 0, 0)


def test_a_charge_that_answers_on_the_second_try_is_taken_once(bench):
    b = bench()
    a = b.who()
    real = b.ledger.real.charge
    b.ledger.real.charge = lambda *args: (_ for _ in ()).throw(LedgerError("down")) if len(b.ledger.named("charge")) < 2 else real(*args)
    ids = b.send(a)
    b.jobs.drain()
    assert b.row(ids[0])["status"] == "done" and b.row(ids[0])["charge"] == "charged" and b.slept == [3]
    assert b.ledger.named("charge") == ["gen:" + ids[0]] * 2 and b.ledger.credits() == 19


def test_a_cancel_during_a_render_that_hangs_ends_cancelled_with_no_file_and_one_refund(bench):
    b = bench(autostart=True, engine=ag.FakeEngine(gate=threading.Event()))
    a = b.who()
    ids = b.send(a)
    assert b.engine.entered.wait(10)
    running = b.view(a, ids[0])
    assert (running["status"], running["stage"], running["attempt"]) == ("running", "rendering", 1) and 0 < running["progress"] < 1
    assert b.jobs.cancel(a, ids)["jobs"][0]["status"] == "cancelled"
    assert b.jobs.cancel(a, ids)["jobs"][0]["status"] == "cancelled"  # asking again changes nothing
    assert b.row(ids[0])["status"] == "running" and b.ledger.named("refund") == []
    b.engine.gate.set()
    until(lambda: b.row(ids[0])["charge"] == "refunded")
    row = b.row(ids[0])
    assert (row["status"], row["error"]) == ("cancelled", None) and not (b.jobs.renders / ids[0]).exists()
    assert b.ledger.named("refund") == ["gen:" + ids[0]] and b.ledger.credits() == 20
    assert b.view(a, ids[0])["refund"] == "done" and b.jobs.count("rf:" + a.owner) == 1


def test_anything_but_a_render_error_fails_the_job_as_internal_and_the_worker_goes_on(bench):
    b = bench(autostart=True, engine=[ZeroDivisionError("boom")])
    a = b.who()
    first, second = b.send(a, items=2)
    until(lambda: b.row(second)["status"] == "done")
    row = b.row(first)
    assert (row["status"], row["error"], row["charge"]) == ("failed", "internal", "refunded")
    assert b.ledger.named("refund") == ["gen:" + first] and b.ledger.credits() == 19
    assert b.view(a, first)["error"] == {"code": "internal", "message": aj.message("en", "internal")}
    # Not the user's doing: it leaves both counts and is not held against the refund limits.
    assert (b.jobs.count("d:members"), b.jobs.count("d:" + a.owner), b.jobs.count("rf:" + a.owner)) == (1, 1, 0)


def test_a_job_that_runs_past_300_seconds_fails_as_timeout_and_is_refunded(bench):
    b = bench()
    b.model.script = [lambda prompt: b.later(301) or {"source": "sine(1) |> out(@)", "seconds": 0.2, "bpm": 0}]
    a = b.who()
    ids = b.send(a)
    b.jobs.drain()
    row = b.row(ids[0])
    assert (row["status"], row["error"], row["charge"]) == ("failed", "timeout", "refunded") and b.engine.calls == []
    assert b.jobs.count("rf:" + a.owner) == 1 and b.ledger.credits() == 20


# ---------- restart ----------
def test_a_restart_fails_what_was_in_flight_and_refunds_by_the_charge_column(bench, tmp_path):
    folder = tmp_path / "bench0"
    store, ledger = aj.GenStore(folder / "asset-gen.db"), Ledger()
    owner = "acct:" + ledger.key_of("a@b.c")
    put(store, "qpending", owner, "queued", "pending")           # no charge reached the ledger
    put(store, "qcharged", owner, "queued", "charged")
    put(store, "rpending", owner, "running", "pending", started=T0 - 10, est=EST)   # charged, the answer was lost
    put(store, "rcharged", owner, "running", "charged", started=T0 - 10, est=EST, usd=0.004)
    put(store, "waiting", owner, "queued", "none")
    put(store, "pwrun", PW.owner, "running", "none", started=T0 - 10, est=EST)
    put(store, "done1", owner, "done", "charged", finished=T0 - 10, bytes=4, view=json.dumps({"lang": "en", "result": {}}))
    put(store, "done2", owner, "done", "kept", finished=T0 - 10, delivered=T0 - 5, bytes=4)
    for ref in ("qcharged", "rpending", "rcharged", "done1", "done2"):
        ledger.real.charge("a@b.c", 1, "gen:" + ref)
    day = datetime.date.fromtimestamp(T0).isoformat()
    with store.lock:
        for name, n in (("d:" + owner, 4), ("d:members", 4), ("d:" + PW.owner, 1), ("d:teachers", 1), ("usd:all", 3 * EST), ("usd:pw", EST)):
            store.add(day, name, n)
    for name in ("done1", "rcharged", "nobody"):
        (folder / "renders" / name).mkdir(parents=True)
        (folder / "renders" / name / "master.wav").write_bytes(b"RIFF")
    for name, age in (("olmuse-nkido-old", 700), ("olmuse-nkido-new", 60), ("other-old", 700)):
        (folder / "temp" / name).mkdir(parents=True)
        os.utime(folder / "temp" / name, (time.time() - age, time.time() - age))
    ledger.calls.clear()

    b = bench(store=store, ledger=ledger)
    a = b.who()
    assert {i: (b.row(i)["status"], b.row(i)["error"], b.row(i)["charge"]) for i in ("qpending", "qcharged", "rpending", "rcharged", "waiting", "pwrun")} == {
        "qpending": ("failed", "restarted", "unknown"), "qcharged": ("failed", "restarted", "refund_due"),
        "rpending": ("failed", "restarted", "unknown"), "rcharged": ("failed", "restarted", "refund_due"),
        "waiting": ("failed", "restarted", "none"), "pwrun": ("failed", "restarted", "none")}
    assert (b.row("done1")["status"], b.row("done1")["charge"], b.row("done2")["status"]) == ("done", "charged", "done")
    view = b.view(a, "rcharged")
    assert (view["status"], view["refund"], view["error"]["message"]) == ("failed", "pending", sb.msg("en", "restarted"))
    assert b.jobs.waiting == {} and b.jobs.drain() == 0 and ledger.calls == []  # nothing is put back in the queue
    assert sorted(p.name for p in (folder / "renders").iterdir()) == ["done1"]
    assert sorted(p.name for p in (folder / "temp").iterdir()) == ["olmuse-nkido-new", "other-old"]
    # What was picked leaves the counts, and its estimate becomes what it really cost.
    assert (b.jobs.count("d:" + owner), b.jobs.count("d:members"), b.jobs.count("d:" + PW.owner), b.jobs.count("d:teachers")) == (2, 2, 0, 0)
    assert (b.jobs.count("usd:all"), b.jobs.count("usd:pw")) == (4000, 0)

    b.jobs.sweep()
    assert ledger.named("refund") == []  # the last charge try is 10 seconds old: the charge may still be running
    b.later(81)
    b.jobs.sweep()
    assert sorted(ledger.named("refund")) == ["gen:qcharged", "gen:qpending", "gen:rcharged", "gen:rpending"]
    assert [b.row(i)["charge"] for i in ("qpending", "qcharged", "rpending", "rcharged")] == ["refunded"] * 4
    assert ledger.credits() == 18  # the two results that stand are paid for; a ref the ledger never saw gives nothing
    b.jobs.sweep()
    assert len(ledger.named("refund")) == 4
    again = bench(store=store, ledger=ledger)
    again.now[0] = b.now[0] + 500
    again.jobs.sweep()
    assert len(ledger.named("refund")) == 4 and ledger.credits() == 18 and again.row("done1")["status"] == "done"


CHILD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, ROOT)
    import asset_generate as ag, asset_jobs as aj
    from credits import LocalLedger
    real = LocalLedger(D + "/credits.sqlite", pepper="p")
    class Ledger:
        key_of, account, refund_key = real.key_of, real.account, real.refund_key
        def charge(self, email, amount, ref):
            if WHEN == "after":
                real.charge(email, amount, ref)
            open(D + "/in_call", "w").write("x")
            time.sleep(600)
    jobs = aj.GenJobs(aj.GenStore(D + "/asset-gen.db"), ledger=Ledger(), model=lambda: ag.FakeModel(), engine=ag.FakeEngine(),
                      measure=lambda wav, **said: {"measure": {}, "issues": []}, renders=D + "/renders", temp=D + "/temp",
                      free=lambda path: 10 ** 12, workers=1)
    who = aj.Who("acct", "acct:" + real.key_of("a@b.c"), "a@b.c", "en")
    jobs.submit(who, {"request_id": "r1", "expect_credits": 1, "drafts": 1, "project": {}, "items": [{"ref": "k0", "kind": "sfx"}]})
    time.sleep(600)
""")


@pytest.mark.parametrize("when, left", [("before", 20), ("after", 19)])
def test_a_process_killed_around_the_charge_is_refunded_once_on_the_next_start(tmp_path, when, left):
    """before: killed between the pick's commit and the charge. after: between the charge and the next write."""
    code = f"ROOT={ROOT!r}\nD={str(tmp_path)!r}\nWHEN={when!r}\n" + CHILD
    child = subprocess.Popen([sys.executable, "-c", code])
    try:
        until(lambda: (tmp_path / "in_call").exists() or child.poll() is not None, 60)
        assert child.poll() is None, "the child stopped before it reached the charge"
    finally:
        child.kill()
        child.wait()
    ledger = Ledger(str(tmp_path / "credits.sqlite"))
    assert ledger.credits() == left
    with sqlite3.connect(tmp_path / "asset-gen.db") as db:
        job_id, status, charge = db.execute("select id, status, charge from gen").fetchone()
    assert (status, charge) == ("running", "pending")  # what the dead process left on disk
    db.close()
    ahead = [0.0]
    start = lambda: aj.GenJobs(aj.GenStore(tmp_path / "asset-gen.db"), ledger=ledger, model=lambda: ag.FakeModel(),  # noqa: E731
                               engine=ag.FakeEngine(), measure=lint, renders=tmp_path / "renders", temp=tmp_path / "temp",
                               clock=lambda: time.time() + ahead[0], free=lambda path: 10 ** 12, autostart=False)
    jobs = start()
    row = lambda: jobs.store.db.execute("select status, error, charge from gen where id=?", (job_id,)).fetchone()  # noqa: E731
    assert tuple(row()) == ("failed", "restarted", "unknown")
    jobs.sweep()
    assert ledger.named("refund") == []  # inside the 90 seconds the charge call could still be on its way
    ahead[0] = 100
    jobs.sweep()
    assert ledger.named("refund") == ["gen:" + job_id] and tuple(row()) == ("failed", "restarted", "refunded")
    assert ledger.credits() == 20
    jobs.store.close()
    jobs = start()
    jobs.sweep()
    assert len(ledger.named("refund")) == 1 and ledger.credits() == 20
    jobs.store.close()


# ---------- request ids ----------
def test_the_same_request_id_makes_nothing_new_and_charges_nothing_more(bench):
    b = bench()
    a = b.who()
    first = b.jobs.submit(a, body("r1", 2, 2))
    again = b.jobs.submit(a, body("r1", 2, 2))
    assert first["replayed"] is False and again == {**first, "replayed": True}
    assert [(j["ref"], j["k"], j["n"], j["status"]) for j in first["jobs"]] == [("k0", 1, 2, "queued"), ("k0", 2, 2, "queued"),
                                                                              ("k1", 1, 2, "queued"), ("k1", 2, 2, "queued")]
    assert first["quote"] == {"items": 2, "drafts": 2, "unit": 1, "credits": 4, "free": False}
    assert b.store.one("select count(*) from gen") == 4
    b.jobs.drain()
    assert b.jobs.submit(a, body("r1", 2, 2)) == again and len(b.ledger.named("charge")) == 4 and b.ledger.credits() == 16
    assert refused(b.jobs.submit, a, body("r1", 2, 1)) == (409, "request_mismatch", {})
    assert refused(b.jobs.submit, a, body("r1", 2, 2, lang="ko")) == (409, "request_mismatch", {})
    other = b.who("x@y.z")
    assert b.jobs.submit(other, body("r1", 2, 2))["replayed"] is False  # another owner's r1 is another request


def test_a_cancel_that_came_first_turns_the_late_request_away(bench):
    b = bench()
    a = b.who()
    assert b.jobs.status_request(a, "late") == {"known": False, "cancelled": False, "jobs": []}
    assert b.jobs.cancel_request(a, "late") == {"jobs": []}
    assert b.jobs.cancel_request(a, "late") == {"jobs": []}
    assert b.jobs.status_request(a, "late") == {"known": False, "cancelled": True, "jobs": []}
    assert refused(b.jobs.submit, a, body("late")) == (410, "request_cancelled", {})
    assert b.store.one("select count(*) from gen") == 0
    assert b.jobs.submit(b.who("x@y.z"), body("late"))["replayed"] is False  # the mark is the owner's own


def test_status_and_cancel_by_request_id(bench):
    b = bench()
    a = b.who()
    ids = b.send(a, rid="r7", items=2, drafts=2)
    known = b.jobs.status_request(a, "r7")
    assert known["known"] is True and known["cancelled"] is False and [v["id"] for v in known["jobs"]] == sorted(ids, key=ids.index)
    assert [v["position"] for v in known["jobs"]] == [1, 3, 2, 4]  # every sound's draft 1 comes before any draft 2
    assert b.jobs.status_request(b.who("x@y.z"), "r7")["known"] is False
    views = b.jobs.cancel_request(a, "r7")["jobs"]
    assert [(v["status"], v["refund"]) for v in views] == [("cancelled", "none")] * 4
    assert b.jobs.status_request(a, "r7")["cancelled"] is True and b.jobs.drain() == 0 and b.ledger.named("charge") == []
    # Sent again after its cancel, a request that was taken is turned away too: its first answer said "queued".
    assert refused(b.jobs.submit, a, body("r7", 2, 2)) == (410, "request_cancelled", {})
    assert refused(b.jobs.submit, a, body("r7", 1, 1)) == (410, "request_cancelled", {})  # the mark comes before the body
    assert b.store.one("select count(*) from gen") == 4 and b.jobs.status_request(a, "r7")["known"] is True
    assert refused(b.jobs.status_request, a, "") == (400, "bad_request", {"field": "request_id"})
    assert refused(b.jobs.status, a, "x") == (400, "bad_request", {"field": "ids"})
    assert refused(b.jobs.cancel, a, ["x"] * 257) == (400, "bad_request", {"field": "ids"})


def test_a_password_sessions_request_is_found_again_after_a_reload_by_its_address(bench):
    """A reload gives a password session another sub (Who.session) and leaves its address, and the page then looks
    for the request it had sent by its request id. So the request id and the cancel mark go by the owner, which is
    the address, and never by the session."""
    before = aj.Who("pw", PW.owner, "", "en", "pw:the-first-load")
    after = aj.Who("pw", PW.owner, "", "en", "pw:after-a-reload")
    moved = aj.Who("pw", "pwip:another-address", "", "en", "pw:the-first-load")
    b = bench()
    ids = b.send(before, rid="r1", free=True)
    assert b.jobs.status_request(after, "r1")["known"] is True and b.jobs.submit(after, body("r1", free=True))["replayed"] is True
    assert b.jobs.status_request(moved, "r1")["known"] is False  # the same session at another address does not find it
    assert [v["status"] for v in b.jobs.cancel_request(after, "r1")["jobs"]] == ["cancelled"] and b.row(ids[0])["status"] == "cancelled"
    assert refused(b.jobs.submit, before, body("r1", free=True)) == (410, "request_cancelled", {})
    assert b.store.one("select count(*) from gen") == 1


def test_request_marks_are_forgotten_after_48_hours(bench):
    b = bench()
    a = b.who()
    b.jobs.cancel_request(a, "late")
    b.later(aj.REQ_TTL + 1)
    b.jobs.sweep()
    assert b.jobs.status_request(a, "late") == {"known": False, "cancelled": False, "jobs": []}


# ---------- the lock ----------
def test_a_ledger_that_hangs_while_one_request_is_taken_holds_nobody_else_up(bench):
    b = bench()
    a, other = b.who(), b.who("x@y.z")
    waiting = b.send(other, rid="r0")
    b.ledger.gates["account"], b.ledger.hang_for = threading.Event(), "a@b.c"
    b.ledger.entered["account"].clear()
    answer = []
    stuck = threading.Thread(target=lambda: answer.append(b.jobs.submit(a, body("r1"))), daemon=True)
    stuck.start()
    assert b.ledger.entered["account"].wait(10)
    began = time.monotonic()
    assert b.jobs.status(other, waiting)["jobs"][0]["status"] == "queued"
    assert b.jobs.submit(other, body("r2"))["replayed"] is False
    assert b.jobs.submit(PW, body("r3", free=True))["replayed"] is False
    assert b.jobs.quote_for(other, 1, 1)["ok"] is True and b.jobs.cancel(other, waiting)["jobs"][0]["status"] == "cancelled"
    assert b.jobs.health()["queued"] == 2
    assert time.monotonic() - began < 3 and stuck.is_alive() and answer == []
    b.ledger.gates["account"].set()
    stuck.join(10)
    assert answer and answer[0]["replayed"] is False


def test_nothing_outside_is_called_with_the_lock_held(bench):
    seen = []
    watch = lambda b: seen.append(b.store.lock.locked())  # noqa: E731
    b = bench(measure=lambda wav, **said: watch(b) or lint(wav, **said))
    b.model.script = [lambda prompt: watch(b) or {"source": "sine(1) |> out(@)", "seconds": 0.2, "bpm": 0}]
    b.engine.script = [lambda source, seconds, bpm: watch(b) or ag.sine_render(source, seconds)]
    a = b.who()
    ids = b.send(a)
    b.jobs.drain()
    b.later(aj.UNFETCHED_TTL)
    b.jobs.sweep()
    assert b.row(ids[0])["charge"] == "refunded" and len(seen) == 4 and not any(seen)
    assert [name for name, _ in b.ledger.calls] == ["account", "charge", "refund"] and not any(b.ledger.locked)


# ---------- the queue's ceilings ----------
def test_64_sounds_times_4_drafts_are_turned_away_before_any_model_call(bench):
    b = bench()
    a = b.who()
    b.ledger.real.grant("a@b.c", 1000)
    status, code, extras = refused(b.jobs.submit, a, body("r1", 64, 4))
    # 256 drafts are over a day's 200. Every 429 says when asking again can have another answer.
    assert (status, code) == (429, "account_limit") and extras == {"left_today": 200, "retry_after": TOMORROW}
    b = bench(limits=aj.Limits(account_daily=10_000, daily=10_000))
    b.ledger.real.grant("a@b.c", 1000)
    assert refused(b.jobs.submit, a, body("r1", 64, 4)) == (429, "too_many_active", {"room": 64, "retry_after": 30})
    assert refused(b.jobs.submit, a, body("r1", 33, 2)) == (429, "too_many_active", {"room": 64, "retry_after": 30})
    assert b.store.one("select count(*) from gen") == 0 and b.store.one("select count(*) from req") == 0
    assert b.model.prompts == [] and b.ledger.named("charge") == []
    assert len(b.send(a, rid="r1", items=64)) == 64 == aj.OWNER_ACTIVE
    assert refused(b.jobs.submit, a, body("r2")) == (429, "too_many_active", {"room": 0, "retry_after": aj.ACTIVE_RETRY})
    assert b.jobs.quote_for(a, 1, 1)["reason"] == "too_many_active"


def test_an_owner_gets_a_quarter_of_the_seats_left_so_two_owners_cannot_fill_the_queue(bench):
    b = bench()
    b.jobs.queue_cap = 40
    a, other = b.who(), b.who("x@y.z")
    assert b.jobs.quote_for(a, 1, 1)["room"] == 10  # (40 - 0) // 4
    b.send(a, rid="a1", items=10)
    assert refused(b.jobs.submit, a, body("a2")) == (429, "too_many_active", {"room": 0, "retry_after": 30})
    assert b.jobs.quote_for(other, 1, 1)["room"] == 7  # (40 - 10) // 4
    assert refused(b.jobs.submit, other, body("o1", 8)) == (429, "too_many_active", {"room": 7, "retry_after": 30})
    b.send(other, rid="o1", items=7)
    assert (b.jobs.quote_for(a, 1, 1)["room"], b.jobs.quote_for(other, 1, 1)["room"]) == (0, 0)
    assert b.jobs.health()["queued"] == 17 < b.jobs.queue_cap
    assert b.jobs.quote_for(PW, 1, 1)["room"] == 5  # (40 - 17) // 4
    # With the real ceilings two owners hold at most 64 each of 400 seats.
    assert 2 * aj.OWNER_ACTIVE < aj.QUEUE_CAP and min(aj.OWNER_ACTIVE, (aj.QUEUE_CAP - aj.OWNER_ACTIVE) // 4) == 64


def test_a_full_queue_is_busy(bench):
    b = bench()
    b.jobs.queue_cap = 8
    for n in range(2):  # the floor of an owner's share is 4 seats
        b.send(aj.Who("pw", f"pwip:{n:016d}", "", "en"), rid=f"r{n}", items=4, free=True)
    assert refused(b.jobs.submit, b.who(), body("r9")) == (503, "busy", {})
    assert b.jobs.quote_for(b.who(), 1, 1)["reason"] == "busy"


def test_owners_take_turns_and_every_draft_1_comes_before_any_draft_2(bench):
    b = bench()
    a, other = b.who(), b.who("x@y.z")
    b.send(a, rid="a1", items=[{"ref": f"a{i}", "kind": "sfx", "name": f"a{i}", "seconds": 0.2} for i in range(4)])
    b.send(other, rid="o1", items=[{"ref": f"o{i}", "kind": "sfx", "name": f"o{i}", "seconds": 0.2} for i in range(2)])
    b.jobs.drain()
    assert [ag.request_of(p)["item"]["name"] for p in b.model.prompts] == ["a0", "o0", "a1", "o1", "a2", "a3"]
    b = bench()
    b.send(a, items=[{"ref": f"k{i}", "kind": "sfx", "name": f"s{i}", "seconds": 0.2} for i in range(2)], drafts=2)
    b.jobs.drain()
    option = lambda p: p.split("Option ")[1].split(";")[0]  # noqa: E731
    assert [(ag.request_of(p)["item"]["name"], option(p)) for p in b.model.prompts] == [
        ("s0", "1 of 2"), ("s1", "1 of 2"), ("s0", "2 of 2"), ("s1", "2 of 2")]


def test_a_busy_owner_waits_behind_one_with_less_running(bench):
    b = bench(autostart=True, workers=2, engine=ag.FakeEngine(gate=threading.Event()))
    a = b.who()
    mine = b.send(a, items=3)
    until(lambda: b.engine.running == 2)  # both workers are on this owner's jobs
    theirs = b.send(PW, rid="p1", free=True)
    b.engine.gate.set()
    until(lambda: all(b.row(i)["status"] == "done" for i in mine + theirs))
    assert b.row(theirs[0])["started"] <= b.row(mine[2])["started"]
    names = [ag.request_of(p)["item"]["name"] for p in b.model.prompts]
    assert len(names) == 4


def test_two_renders_at_once_and_no_more(bench):
    b = bench(autostart=True, workers=4, engine=ag.FakeEngine(gate=threading.Event()))
    ids = b.send(PW, items=4, free=True)
    until(lambda: b.engine.running == 2 and len(b.model.prompts) == 4)  # four were asked for, two wait for a slot
    time.sleep(0.5)
    assert b.engine.running == 2 == aj.RENDER_SLOTS and b.jobs.health()["running"] == 4
    b.engine.gate.set()
    until(lambda: all(b.row(i)["status"] == "done" for i in ids))
    assert b.engine.most == 2 and len(b.engine.calls) == 4


def test_a_402_at_the_pick_fails_the_rest_without_charging(bench):
    b = bench()
    a = b.who()
    assert b.jobs.quote_for(a, 3, 1)["balance"] == 20  # the cache now says 20
    b.ledger.real.charge("a@b.c", 19, "spent-elsewhere")
    ids = b.send(a, items=3)  # taken on the cached balance
    b.jobs.drain()
    assert [(b.row(i)["status"], b.row(i)["error"], b.row(i)["charge"]) for i in ids] == [
        ("done", None, "charged"), ("failed", "no_credits", "none"), ("failed", "no_credits", "none")]
    assert b.ledger.named("charge") == ["gen:" + ids[0], "gen:" + ids[1]] and b.ledger.named("refund") == []
    assert b.ledger.credits() == 0 and len(b.model.prompts) == 1
    assert [b.view(a, i)["refund"] for i in ids] == ["none"] * 3 and b.row(ids[2])["started"] is None
    assert b.view(a, ids[1])["error"] == {"code": "no_credits", "message": sb.msg("en", "no_credits")}
    assert (b.jobs.count("d:members"), b.jobs.count("d:" + a.owner), b.jobs.count("rf:" + a.owner)) == (1, 1, 0)
    assert refused(b.jobs.submit, a, body("r2")) == (402, "no_credits", {"balance": 0, "credits": 1})


# ---------- results waiting, and the disk ----------
def test_only_the_owner_whose_results_wait_is_told_to_fetch_first(bench):
    b = bench()
    b.jobs.unfetched_cap = 1000  # bytes; one result is larger
    a, other = b.who(), b.who("x@y.z")
    first, second = b.send(a, items=2)
    assert b.jobs.drain() == 1  # with a result waiting, the owner's next job is passed over
    assert (b.row(first)["status"], b.row(second)["status"]) == ("done", "queued") and b.row(first)["bytes"] > 1000
    status, code, extras = refused(b.jobs.submit, a, body("r2"))
    assert (status, code) == (429, "fetch_first") and extras == {"retry_after": 3601}
    assert b.jobs.quote_for(a, 1, 1)["reason"] == "fetch_first"
    theirs = b.send(other, rid="o1")
    assert b.jobs.drain() == 1 and b.row(theirs[0])["status"] == "done"
    b.jobs.sound(a, first)
    assert b.jobs.submit(a, body("r2"))["replayed"] is False
    assert b.jobs.drain() == 1 and b.row(second)["status"] == "done"


def test_password_sessions_share_one_ceiling_for_results_that_wait(bench):
    b = bench()
    b.jobs.pw_unfetched_cap = 1000
    other = aj.Who("pw", "pwip:ffffffffffffffff", "", "en")
    b.send(PW, free=True)
    b.jobs.drain()
    assert refused(b.jobs.submit, other, body("r2", free=True))[:2] == (429, "fetch_first")
    assert b.jobs.submit(b.who(), body("r3"))["replayed"] is False


def test_over_the_disk_cap_only_received_results_nobody_looked_at_for_600_seconds_go(bench):
    b = bench()
    a = b.who()
    old, fresh, waiting = b.send(a, items=3)
    b.jobs.drain()
    b.jobs.sound(a, old)
    b.jobs.sound(a, fresh)
    b.later(700)
    b.jobs.status(a, [fresh])  # somebody still looks at this one
    b.jobs.sweep()
    assert [b.row(i)["status"] for i in (old, fresh, waiting)] == ["done"] * 3 and b.jobs.disk_paused is False
    b.jobs.disk_cap = 1
    b.jobs.sweep()
    assert [b.row(i)["status"] for i in (old, fresh, waiting)] == ["gone", "done", "done"]
    assert b.view(a, old) == {"id": old, "status": "gone", "refund": "none"} and not (b.jobs.renders / old).exists()
    assert (b.jobs.renders / fresh).exists() and (b.jobs.renders / waiting).exists() and b.row(fresh)["seen"] == T0 + 700
    # Still over: picking rests and a new request is turned away.
    assert b.jobs.disk_paused is True and refused(b.jobs.submit, a, body("r2")) == (503, "busy", {})
    assert b.jobs.quote_for(a, 1, 1)["reason"] == "busy" and b.ledger.named("refund") == []
    b.jobs.disk_cap = aj.DISK_CAP
    b.jobs.sweep()
    assert b.jobs.disk_paused is False and b.jobs.submit(a, body("r2"))["replayed"] is False


def test_right_after_a_restart_every_result_counts_as_just_seen(bench):
    b = bench(store=aj.GenStore())
    a = b.who()
    ids = b.send(a)
    b.jobs.drain()
    b.jobs.sound(a, ids[0])
    b.jobs.sweep()  # writes `seen` down
    again = bench(store=b.store, ledger=b.ledger)
    again.jobs.renders = b.jobs.renders
    again.now[0] = T0 + 5000
    again.jobs.boot = T0 + 5000
    again.jobs.disk_cap = 1
    again.jobs.sweep()
    assert again.row(ids[0])["status"] == "done"
    again.later(601)
    again.jobs.sweep()
    assert again.row(ids[0])["status"] == "gone"


def test_a_nearly_full_volume_rests_generation(bench):
    b = bench()
    b.jobs.free = lambda path: aj.DISK_FREE_MIN - 1
    b.jobs.sweep()
    assert b.jobs.disk_paused and refused(b.jobs.submit, PW, body(free=True)) == (503, "busy", {})
    assert b.jobs.health()["disk_free_mb"] == 2047


# ---------- refund limits and the daily counts ----------
def test_refunds_the_user_caused_are_limited_and_leave_the_shared_count(bench):
    b = bench(engine=[BROKEN() for _ in range(9)])
    b.jobs.refund_hourly = 2
    a, other = b.who(), b.who("x@y.z")
    b.send(a, items=2)
    b.jobs.drain()
    assert (b.jobs.count("d:members"), b.jobs.count("d:" + a.owner), b.jobs.count("rf:" + a.owner)) == (0, 2, 2)
    assert b.ledger.credits() == 20 and len(b.ledger.named("refund")) == 2
    assert b.jobs.quote_for(a, 1, 1)["ok"] is True  # the limit is met, not passed
    b.later(100)
    b.send(a, rid="r2")
    b.jobs.drain()
    assert b.jobs.count("rf:" + a.owner) == 3 and len(b.ledger.named("refund")) == 3
    # Passed by one: asking helps again when the oldest of the three is an hour old.
    assert refused(b.jobs.submit, a, body("r3")) == (429, "refund_limit", {"retry_after": 3501})
    assert b.jobs.quote_for(a, 1, 1)["reason"] == "refund_limit" and b.jobs.quote_for(a, 1, 1)["left_today"] == 197
    assert b.jobs.submit(other, body("o1"))["replayed"] is False
    b.later(3499)
    assert refused(b.jobs.submit, a, body("r3")) == (429, "refund_limit", {"retry_after": 2})
    b.later(2)
    assert b.jobs.submit(a, body("r3"))["replayed"] is False
    b.jobs.refund_daily = 3
    assert b.jobs.quote_for(a, 1, 1)["ok"] is True  # three today: met, not passed
    b.jobs.refund_daily = 2
    assert refused(b.jobs.submit, a, body("r4")) == (429, "refund_limit", {"retry_after": TOMORROW - 3601})
    assert aj.REFUND_HOURLY == 12 and aj.REFUND_DAILY == 24


def test_the_daily_counts_refuse_what_would_pass_them(bench):
    b = bench(limits=aj.Limits(account_daily=3, daily=4))
    a, other = b.who(), b.who("x@y.z")
    assert refused(b.jobs.submit, a, body("r1", 4)) == (429, "account_limit", {"left_today": 3, "retry_after": TOMORROW})
    b.send(a, rid="r1", items=2)
    assert b.jobs.quote_for(a, 1, 1)["left_today"] == 1  # what waits is counted with what was used
    b.jobs.drain()
    assert refused(b.jobs.submit, a, body("r2", 2)) == (429, "account_limit", {"left_today": 1, "retry_after": TOMORROW})
    assert refused(b.jobs.submit, other, body("o1", 3)) == (429, "daily_limit", {"left_today": 2, "retry_after": TOMORROW})
    error = pytest.raises(aj.GenError, b.jobs.submit, a, body("r2", 2)).value
    assert aj.message("en", error) == sb.msg("en", "account_limit", n=3)
    b.later(86400)  # tomorrow the counts start again
    assert b.jobs.submit(a, body("r2", 3))["replayed"] is False
    b.jobs.sweep()
    assert b.store.one("select count(*) from counts where day<?", (datetime.date.fromtimestamp(b.now[0]).isoformat(),)) == 0


def test_two_password_tokens_from_one_address_share_one_count(bench):
    secret = b"s" * 32
    one = asset_token.payload_for("pw", "pw:first-session", "", "en", T0)
    two = asset_token.payload_for("pw", "pw:second-session", "", "en", T0)
    same = [aj.Who("pw", asset_token.owner_of(p, secret, "10.0.0.7"), "", "en") for p in (one, two)]
    elsewhere = aj.Who("pw", asset_token.owner_of(two, secret, "10.0.0.8"), "", "en")
    assert same[0].owner == same[1].owner != elsewhere.owner and same[0].owner.startswith("pwip:")
    b = bench(limits=aj.Limits(pw_daily=3, pw_all_daily=5))
    ids = b.send(same[0], rid="r1", items=2, free=True)
    assert refused(b.jobs.submit, same[1], body("r2", 2, free=True)) == (429, "session_limit", {"left_today": 1, "retry_after": TOMORROW})
    more = b.send(same[1], rid="r2", free=True)
    assert b.jobs.status(same[1], ids)["jobs"][0]["status"] == "queued"  # a password job is any password token's
    assert b.jobs.status(elsewhere, ids)["jobs"][0]["status"] == "queued"
    assert b.jobs.status(b.who(), ids)["jobs"][0] == {"id": ids[0], "status": "forbidden", "refund": "none"}
    b.send(elsewhere, rid="r1", items=2, free=True)
    assert refused(b.jobs.submit, elsewhere, body("r2", free=True)) == (429, "daily_limit", {"left_today": 0, "retry_after": TOMORROW})
    b.jobs.drain()
    assert (b.jobs.count("d:" + same[0].owner), b.jobs.count("d:" + elsewhere.owner), b.jobs.count("d:teachers")) == (3, 2, 5)
    assert b.ledger.calls == [] and len(ids + more) == 3


def test_the_dollar_count_starts_as_an_estimate_and_ends_as_the_real_cost(bench):
    b = bench(cost=0.002)
    during = []
    b.model.script = [lambda prompt: during.append((b.jobs.count("usd:pw"), b.jobs.count("usd:all"))) or
                      {"source": "sine(1) |> out(@)", "seconds": 0.2, "bpm": 0}]
    ids = b.send(PW, free=True)
    b.jobs.drain()
    assert during == [(EST, EST)] and (b.jobs.count("usd:pw"), b.jobs.count("usd:all")) == (2000, 2000)
    assert b.row(ids[0])["est"] == EST and b.row(ids[0])["usd"] == pytest.approx(0.002)
    b.send(b.who(), rid="r2")
    b.jobs.drain()
    assert (b.jobs.count("usd:pw"), b.jobs.count("usd:all")) == (2000, 4000)  # an account's draft is not in usd:pw
    other = bench(model_name="some/other-model", cost=0.0)
    assert other.jobs.est == 90_000 and aj.GEN_CALL_USD == {MODEL: 0.009}


def test_a_failed_draft_counts_the_calls_it_made(bench):
    b = bench(cost=0.004, engine=[BROKEN(), BROKEN(), BROKEN()])
    b.send(PW, free=True)
    b.jobs.drain()
    assert (b.jobs.count("usd:pw"), b.jobs.count("usd:all")) == (12_000, 12_000)
    assert (b.jobs.count("d:teachers"), b.jobs.count("d:" + PW.owner), b.jobs.count("rf:" + PW.owner)) == (0, 1, 1)


def test_a_provider_that_names_no_cost_still_fills_the_dollar_counts(bench):
    # cost=None: the answers carry no usage.cost at all, as from a proxy. Each answered call stays at its estimate.
    b = bench(cost=None, limits=aj.Limits(pw_daily_usd=0.06), engine=[BROKEN(), BROKEN(), BROKEN()])
    first = b.send(PW, free=True)
    b.jobs.drain()
    assert b.row(first[0])["error"] == "make_failed" and len(b.model.prompts) == 3
    assert (b.jobs.count("usd:pw"), b.jobs.count("usd:all")) == (EST, EST) and b.row(first[0])["usd"] == pytest.approx(0.027)
    second = b.send(PW, rid="r2", free=True)
    b.jobs.drain()
    assert b.row(second[0])["status"] == "done" and b.row(second[0])["usd"] == pytest.approx(0.009)  # one call
    assert (b.jobs.count("usd:pw"), b.jobs.count("usd:all")) == (36_000, 36_000)
    # 36 000 used and a draft may take 27 000 more: over the 60 000 of password sessions.
    assert refused(b.jobs.submit, PW, body("r3", free=True))[:2] == (429, "operator_limit")
    assert b.jobs.submit(b.who(), body("r4"))["replayed"] is False


def test_a_call_that_was_never_answered_and_a_model_that_says_it_is_free_cost_nothing(bench):
    b = bench(cost=None, script=[sb.ModelError("openrouter_conn", detail="x"), sb.ModelError("openrouter_conn", detail="x")])
    b.send(PW, free=True)
    b.jobs.drain()
    assert (b.jobs.count("usd:pw"), b.jobs.count("usd:all")) == (0, 0)  # the whole estimate goes back
    free = bench(cost=0.0)  # the fake's own default: it says so, and is believed
    free.send(PW, free=True)
    free.jobs.drain()
    assert (free.jobs.count("usd:pw"), free.jobs.count("usd:all")) == (0, 0) and len(free.model.prompts) == 1


def test_at_the_dollar_ceiling_for_everything_picking_rests(bench):
    b = bench(cost=0.02, limits=aj.Limits(daily_usd=0.03))
    a = b.who()
    first, second = b.send(a, items=2)
    assert b.jobs.drain() == 1  # 20 000 used and 27 000 more would pass 30 000
    assert (b.row(first)["status"], b.row(second)["status"]) == ("done", "queued") and b.jobs.count("usd:all") == 20_000
    assert refused(b.jobs.submit, a, body("r2")) == (429, "operator_limit", {"left_today": 198, "retry_after": TOMORROW})
    assert b.jobs.quote_for(PW, 1, 1)["reason"] == "operator_limit"
    assert len(b.ledger.named("charge")) == 1
    b.later(aj.QUEUE_WAIT + 1)  # what waited two hours fails as busy, uncharged
    b.jobs.sweep()
    assert (b.row(second)["status"], b.row(second)["error"], b.row(second)["charge"]) == ("failed", "busy", "none")
    assert b.view(a, second)["refund"] == "none" and len(b.ledger.named("charge")) == 1


def test_at_the_dollar_ceiling_for_password_sessions_their_waiting_jobs_fail(bench):
    b = bench(cost=0.02, limits=aj.Limits(pw_daily_usd=0.03))
    a = b.who()
    first, second = b.send(PW, items=2, free=True)
    mine = b.send(a, rid="r2")
    b.jobs.drain()
    assert (b.row(first)["status"], b.row(second)["status"], b.row(second)["error"]) == ("done", "failed", "operator_limit")
    assert b.row(mine[0])["status"] == "done"  # accounts go on
    assert refused(b.jobs.submit, PW, body("r3", free=True)) == (429, "operator_limit", {"left_today": 119, "retry_after": TOMORROW})
    assert b.view(PW, second)["error"]["message"] == sb.msg("en", "operator_limit")
    assert b.jobs.submit(a, body("r4"))["replayed"] is False


def test_a_cancel_while_waiting_adds_no_dollars_and_no_counts(bench):
    b = bench()
    a = b.who()
    ids = b.send(a, items=2)
    views = b.jobs.cancel(a, ids)["jobs"]
    assert [(v["status"], v["refund"]) for v in views] == [("cancelled", "none")] * 2
    assert b.jobs.drain() == 0 and b.ledger.named("charge") == [] and b.model.prompts == []
    assert [b.jobs.count(n) for n in ("usd:all", "usd:pw", "d:members", "d:" + a.owner, "rf:" + a.owner)] == [0] * 5
    assert b.row(ids[0])["input"] is None and b.jobs.cancel(a, ids)["jobs"] == views


# ---------- the sweeper ----------
def test_a_running_row_no_worker_holds_fails_after_360_seconds_and_is_refunded(bench):
    b = bench()
    a = b.who()
    b.ledger.real.charge("a@b.c", 1, "gen:lost")
    b.ledger.real.charge("a@b.c", 1, "gen:young")
    put(b.store, "lost", a.owner, "running", "charged", started=T0 - 361, charge_at=T0 - 361, est=EST)
    put(b.store, "young", a.owner, "running", "charged", started=T0 - 100, charge_at=T0 - 100, est=EST)
    b.jobs.sweep()
    assert (b.row("lost")["status"], b.row("lost")["error"], b.row("lost")["charge"]) == ("failed", "timeout", "refunded")
    assert (b.row("young")["status"], b.row("young")["charge"]) == ("running", "charged")
    assert b.ledger.named("refund") == ["gen:lost"] and b.ledger.credits() == 19
    assert b.view(a, "lost")["refund"] == "done" and b.jobs.count("rf:" + a.owner) == 1


def test_a_charge_left_pending_by_a_dead_worker_is_refunded_after_90_seconds(bench):
    b = bench()
    a = b.who()
    b.ledger.real.charge("a@b.c", 1, "gen:orphan")
    put(b.store, "orphan", a.owner, "running", "pending", started=T0 - 50, charge_at=T0 - 50)
    b.jobs.sweep()
    assert b.ledger.named("refund") == []
    b.later(41)
    b.jobs.sweep()
    assert b.ledger.named("refund") == ["gen:orphan"] and b.row("orphan")["charge"] == "refunded" and b.ledger.credits() == 20
    b.later(300)
    b.jobs.sweep()
    assert (b.row("orphan")["status"], b.row("orphan")["error"], b.row("orphan")["charge"]) == ("failed", "timeout", "refunded")
    assert len(b.ledger.named("refund")) == 1


# ---------- a store that refuses a write ----------
def full_disk(store, times):
    """store.add raises `times` times, the way SQLite does when the disk is full."""
    real, hits = store.add, []

    def add(day, name, n):
        if len(hits) < times:
            hits.append(name)
            raise sqlite3.OperationalError("database or disk is full")
        return real(day, name, n)
    store.add = add
    return hits


def test_a_pick_the_store_refuses_leaves_the_job_queued_in_the_store_and_in_memory(bench):
    b = bench()
    ids = b.send(PW, items=2, free=True)
    hits = full_disk(b.store, 1)
    with pytest.raises(sqlite3.OperationalError):
        b.jobs.drain()
    assert len(hits) == 1 and [b.row(i)["status"] for i in ids] == ["queued", "queued"]
    assert [entry[3] for entry in b.jobs.waiting[PW.owner]] == ids and b.jobs.held == {} and b.jobs.count("usd:all") == 0
    assert not b.store.lock.locked() and b.jobs.drain() == 2  # the next pick finds both
    assert [b.row(i)["status"] for i in ids] == ["done", "done"] and b.jobs.count("d:teachers") == 2


def test_a_worker_outlives_a_pick_the_store_refuses(bench):
    b = bench(autostart=True, workers=2, ledger=None)
    b.jobs.pick_retry = 0.01
    hits = full_disk(b.store, 2)
    ids = b.send(PW, items=4, free=True)
    until(lambda: all(b.row(i)["status"] == "done" for i in ids))
    assert len(hits) == 2 and all(t.is_alive() for t in b.jobs.threads) and b.jobs.waiting == {}
    more = b.send(PW, rid="r2", free=True)
    until(lambda: b.row(more[0])["status"] == "done")
    assert b.jobs.health()["ok"] is True


def test_health_is_not_ok_when_no_worker_is_alive(bench):
    b = bench(ledger=None)
    assert b.jobs.health()["ok"] is True  # never started: the caller drains
    dead = [threading.Thread(target=lambda: None) for _ in range(3)]
    for thread in dead:
        thread.start()
        thread.join()
    b.jobs.threads = dead  # the sweeper and two workers, all ended
    assert b.jobs.health()["ok"] is False
    b = bench(ledger=None, autostart=True, workers=1)
    assert b.jobs.health()["ok"] is True


def test_a_cancel_or_a_failure_the_store_refuses_keeps_the_memory_queue(bench):
    b = bench(ledger=None)
    ids = b.send(PW, items=2, free=True)
    real = b.store.tx

    def broken():
        raise sqlite3.OperationalError("database or disk is full")
    b.store.tx = broken
    with pytest.raises(sqlite3.OperationalError):
        b.jobs.cancel(PW, ids)
    with pytest.raises(sqlite3.OperationalError), b.jobs.wake:
        b.jobs._fail_waiting([PW.owner], "no_engine")
    b.store.tx = real
    assert [entry[3] for entry in b.jobs.waiting[PW.owner]] == ids and [b.row(i)["status"] for i in ids] == ["queued"] * 2
    assert [v["status"] for v in b.jobs.cancel(PW, ids[:1])["jobs"]] == ["cancelled"]
    assert [entry[3] for entry in b.jobs.waiting[PW.owner]] == ids[1:]
    assert [v["status"] for v in b.jobs.cancel(PW, ids[1:])["jobs"]] == ["cancelled"] and b.jobs.waiting == {}


# ---------- the model and the engine going away ----------
def test_three_key_errors_in_a_row_rest_the_model_for_60_seconds(bench):
    b = bench(script=[sb.ModelError("openrouter_key"), sb.ModelError("openrouter_credits"), sb.ModelError("openrouter_key")])
    a = b.who()
    ids = b.send(a, items=4)
    assert b.jobs.drain() == 3
    assert [(b.row(i)["status"], b.row(i)["error"], b.row(i)["charge"]) for i in ids[:3]] == [("failed", "no_model", "refunded")] * 3
    assert b.row(ids[3])["status"] == "queued"  # what waits is left alone
    assert b.jobs.health()["model"] is False and b.jobs.health()["ok"] is False
    assert refused(b.jobs.submit, a, body("r2")) == (503, "no_model", {}) and b.jobs.quote_for(a, 1, 1)["reason"] == "no_model"
    assert (b.jobs.count("rf:" + a.owner), b.jobs.count("d:" + a.owner), b.jobs.count("d:members")) == (0, 0, 0)
    b.later(aj.BREAKER_SECONDS + 1)
    assert b.jobs.health()["model"] is True and b.jobs.drain() == 1 and b.row(ids[3])["status"] == "done"


@pytest.mark.parametrize("code", [400, 404, 408, 413])
def test_a_provider_that_turns_every_call_down_is_the_servers_trouble_not_the_users(bench, code):
    # A wrong model id or a parameter the provider does not take: every call is a 4xx.
    b = bench(script=[sb.ModelError("openrouter_http", code=code, detail="No endpoints found") for _ in range(20)])
    a = b.who()
    ids = b.send(a, items=4)
    assert b.jobs.drain() == 3  # the third in a row rests the model
    assert [(b.row(i)["status"], b.row(i)["error"], b.row(i)["charge"]) for i in ids[:3]] == [("failed", "no_model", "refunded")] * 3
    assert len(b.model.prompts) == 3 and b.engine.calls == []  # one call a draft, not three
    # Not held against the user: out of both counts, nothing on the refund limits, every credit back.
    assert (b.jobs.count("rf:" + a.owner), b.jobs.count("d:" + a.owner), b.jobs.count("d:members")) == (0, 0, 0)
    assert b.jobs.refunds == {} and b.ledger.credits() == 20 and b.jobs.count("usd:all") == 0
    assert b.jobs.health()["model"] is False and b.row(ids[3])["status"] == "queued"
    assert refused(b.jobs.submit, a, body("r2")) == (503, "no_model", {})


def test_an_answer_between_errors_resets_the_count(bench):
    b = bench(script=[sb.ModelError("openrouter_key"), sb.ModelError("openrouter_key"), None, sb.ModelError("openrouter_key")])
    b.model.script[2] = {"source": "sine(1) |> out(@)", "seconds": 0.2, "bpm": 0}
    b.send(b.who(), items=4)
    b.jobs.drain()
    assert b.jobs.health()["model"] is True


def test_a_missing_engine_fails_what_waits_uncharged_and_turns_requests_away(bench):
    b = bench(engine=[nkido.RenderError("missing-engine", "nkido is not installed on this server")])
    a = b.who()
    first, second = b.send(a, items=2)
    b.jobs.drain()
    assert [(b.row(i)["status"], b.row(i)["error"], b.row(i)["charge"]) for i in (first, second)] == [
        ("failed", "no_engine", "refunded"), ("failed", "no_engine", "none")]
    assert len(b.ledger.named("charge")) == 1 and b.ledger.credits() == 20
    assert b.jobs.health()["engine"] is False and refused(b.jobs.submit, a, body("r2")) == (503, "no_engine", {})


class Meter:
    """A measure with NodeLint's `ok` and `check`. works: whether Node can be started."""

    def __init__(self, works=True):
        self.ok, self.works, self.checks = True, works, 0

    def __call__(self, wav, **said):
        if not self.works:
            self.ok = False
            raise ag.MeasureError("node cannot be started")
        self.ok = True
        return lint(wav, **said)

    def check(self):
        self.checks += 1
        try:
            self(ag.tone(0.1))
        except ag.MeasureError:
            self.ok = False
        return self.ok


def test_when_sounds_cannot_be_measured_no_request_is_taken_and_nothing_is_picked(bench):
    meter = Meter()
    b = bench(measure=meter)
    a = b.who()
    ids = b.send(a)
    meter.works = False
    b.jobs.sweep()  # the sweeper asks the measure
    assert meter.checks == 1 and b.jobs.health()["node"] is False and b.jobs.health()["ok"] is False
    assert b.jobs.drain() == 0 and b.row(ids[0])["status"] == "queued"  # what waits is left alone, unpaid
    assert b.model.prompts == [] and b.ledger.named("charge") == [] and b.jobs.count("usd:all") == 0
    assert refused(b.jobs.submit, a, body("r2")) == (503, "no_measure", {}) and refused(b.jobs.submit, PW, body("r3", free=True)) == (503, "no_measure", {})
    quote = b.jobs.quote_for(a, 1, 1)
    assert (quote["ok"], quote["reason"]) == (False, "no_measure")
    meter.works = True
    b.jobs.sweep()  # Node is back
    assert b.jobs.health()["node"] is True and b.jobs.drain() == 1 and b.row(ids[0])["status"] == "done"
    assert b.jobs.submit(a, body("r2"))["replayed"] is False


def test_a_measure_that_breaks_under_a_job_costs_one_draft_and_then_requests_are_turned_away(bench):
    meter = Meter()
    b = bench(measure=meter, cost=0.004)
    a = b.who()
    first, second = b.send(a, items=2)
    meter.works = False
    assert b.jobs.drain() == 1  # the second is not picked any more
    assert (b.row(first)["status"], b.row(first)["error"], b.row(first)["charge"]) == ("failed", "internal", "refunded")
    assert b.row(second)["status"] == "queued" and len(b.model.prompts) == 1 and b.ledger.credits() == 20
    assert refused(b.jobs.submit, a, body("r2")) == (503, "no_measure", {})


def test_the_measure_is_asked_before_the_first_pick(bench):
    meter = Meter(works=False)
    b = bench(measure=meter, autostart=True)
    assert meter.checks >= 1 and b.jobs.health()["node"] is False
    assert refused(b.jobs.submit, PW, body(free=True)) == (503, "no_measure", {}) and b.model.prompts == []
    b = bench(autostart=True)  # a measure without check, as the tests' own, is left alone
    assert b.jobs.health()["node"] is True


def test_what_is_not_there_is_named(bench):
    assert refused(bench(model=False).jobs.submit, PW, body(free=True)) == (503, "no_model", {})
    assert refused(bench(engine=None).jobs.submit, PW, body(free=True)) == (503, "no_engine", {})
    b = bench(ledger=None)
    account = aj.Who("acct", "acct:" + "0" * 64, "a@b.c", "en")
    assert refused(b.jobs.submit, account, body()) == (503, "no_ledger", {})
    assert refused(b.jobs.quote_for, account, 1, 1) == (503, "no_ledger", {})
    assert b.jobs.health()["ledger"] is False and b.jobs.submit(PW, body(free=True))["replayed"] is False
    assert b.jobs.health() == {"ok": True, "model": True, "engine": True, "node": True, "ledger": False, "queued": 1,
                               "running": 0, "disk_free_mb": 100 * 1024}
    missing = type("Engine", (), {"EXE": "no-such-engine.exe", "render_mended": None})()
    assert bench(engine=missing).jobs.health()["engine"] is False


# ---------- price and balance ----------
def test_the_quote_and_the_request_use_one_price(bench):
    b = bench()
    a = b.who()
    assert b.jobs.quote_for(a, 3, 2) == {"items": 3, "drafts": 2, "unit": 1, "credits": 6, "free": False, "balance": 20,
                                         "left_today": 200, "room": 64, "ok": True, "reason": None}
    assert b.jobs.quote_for(PW, 3, 2) == {"items": 3, "drafts": 2, "unit": 0, "credits": 0, "free": True, "balance": None,
                                          "left_today": 120, "room": 64, "ok": True, "reason": None}
    assert aj.quote(3, 2, False)["credits"] == 6 == 3 * 2 * aj.DRAFT_CREDITS and aj.DRAFT_CREDITS == 1
    assert refused(b.jobs.submit, a, body("r1", 3, 2, credits=5)) == (409, "quote_changed", {"quote": aj.quote(3, 2, False)})
    assert refused(b.jobs.submit, a, body("r1", 3, 2, credits=0)) == (409, "quote_changed", {"quote": aj.quote(3, 2, False)})
    assert refused(b.jobs.submit, PW, body("r1", 3, 2, credits=6)) == (409, "quote_changed", {"quote": aj.quote(3, 2, True)})
    assert b.jobs.submit(a, body("r1", 3, 2, credits=6))["quote"]["credits"] == 6
    for wrong in ((0, 1), (65, 1), (1, 0), (1, 5), ("1", 1), (True, 1)):
        assert refused(b.jobs.quote_for, a, *wrong)[:2] == (400, "bad_request")


def test_credits_that_waiting_drafts_will_take_are_reserved(bench):
    b = bench()
    a = b.who()
    b.send(a, rid="r1", items=15)
    assert b.jobs.quote_for(a, 5, 1)["ok"] is True
    quote = b.jobs.quote_for(a, 6, 1)
    assert (quote["ok"], quote["reason"], quote["balance"]) == (False, "no_credits", 20)
    assert refused(b.jobs.submit, a, body("r2", 6)) == (402, "no_credits", {"balance": 20, "credits": 6})
    assert refused(b.jobs.submit, a, body("r2", 21)) == (402, "no_credits", {"balance": 20, "credits": 21})
    assert b.jobs.submit(a, body("r2", 5))["replayed"] is False


def test_the_balance_is_asked_at_most_once_a_minute_and_status_never_asks(bench):
    b = bench()
    a = b.who()
    assert b.jobs.status(a, [])["credits"] is None and b.ledger.calls == []
    b.jobs.quote_for(a, 1, 1)
    ids = b.send(a)
    b.jobs.quote_for(a, 1, 1)
    assert b.ledger.named("account") == ["a@b.c"]
    b.jobs.drain()
    before = len(b.ledger.calls)
    for _ in range(5):
        assert b.jobs.status(a, ids)["credits"] == 19  # the charge's answer, from the cache
    assert len(b.ledger.calls) == before
    b.later(aj.BALANCE_TTL + 1)
    b.jobs.quote_for(a, 1, 1)
    assert b.ledger.named("account") == ["a@b.c"] * 2
    b.later(aj.BALANCE_TTL + 1)
    b.ledger.fail.add("account")
    assert refused(b.jobs.quote_for, a, 1, 1) == (503, "no_ledger", {})
    assert refused(b.jobs.submit, a, body("r2")) == (503, "no_ledger", {})
    assert b.jobs.submit(a, body("r1"))["replayed"] is True  # a request already taken still answers


def test_a_balance_read_the_ledger_left_unanswered_is_not_asked_again_for_five_seconds(bench):
    """A ledger that is down answers after its timeout. Without this every request of the account would wait
    that long again."""
    b = bench()
    a, other = b.who(), b.who("x@y.z")
    b.ledger.fail.add("account")
    assert aj.LEDGER_REST == 5 and refused(b.jobs.quote_for, a, 1, 1) == (503, "no_ledger", {})
    assert refused(b.jobs.quote_for, a, 1, 1) == refused(b.jobs.submit, a, body()) == (503, "no_ledger", {})
    assert b.ledger.named("account") == ["a@b.c"]  # the two that followed were told at once
    assert refused(b.jobs.quote_for, other, 1, 1) == (503, "no_ledger", {})
    assert b.ledger.named("account") == ["a@b.c", "x@y.z"]  # another account's first read is still asked
    b.later(aj.LEDGER_REST - 1)
    assert refused(b.jobs.quote_for, a, 1, 1)[1] == "no_ledger" and len(b.ledger.named("account")) == 2
    b.later(1)
    assert refused(b.jobs.quote_for, a, 1, 1)[1] == "no_ledger" and b.ledger.named("account") == ["a@b.c", "x@y.z", "a@b.c"]
    assert list(b.jobs.unread) == [a.owner]  # the other account's mark was over and is not kept
    b.later(aj.LEDGER_REST - 1)  # the rest counts from the last read that failed
    assert refused(b.jobs.submit, a, body())[1] == "no_ledger" and len(b.ledger.named("account")) == 3
    b.later(1)
    b.ledger.fail.clear()  # the ledger is back
    assert b.jobs.quote_for(a, 1, 1)["balance"] == 20 and b.jobs.unread == {} and len(b.ledger.named("account")) == 4
    assert b.jobs.status(a, [])["credits"] == 20 and b.ledger.locked == [False] * 4  # never asked with the lock held


def test_any_balance_the_ledger_gives_ends_the_rest_after_a_failed_read(bench):
    b = bench()
    a = b.who()
    b.send(a)  # the balance is read and a draft waits
    b.later(aj.BALANCE_TTL + 1)
    b.ledger.fail.add("account")  # reads fail; a charge is still answered
    assert refused(b.jobs.quote_for, a, 1, 1) == (503, "no_ledger", {}) and list(b.jobs.unread) == [a.owner]
    assert b.jobs.drain() == 1 and b.jobs.unread == {}  # the charge's answer is a balance
    assert b.jobs.quote_for(a, 1, 1)["balance"] == 19 and b.ledger.named("account") == ["a@b.c"] * 2


# ---------- views ----------
def test_a_result_shows_its_source_only_after_it_was_received(bench):
    b = bench(measure=ag.NodeLint())
    a = b.who("a@b.c", "ko")
    ids = b.send(a, items=[{"ref": "k0", "kind": "music", "loop": True, "name": "theme", "seconds": 1.0}])
    b.jobs.drain()
    view = b.view(a, ids[0])
    assert view["status"] == "done" and view["progress"] == 1.0 and (view["ref"], view["k"], view["n"]) == ("k0", 1, 1)
    result = view["result"]
    assert sorted(result) == ["bits", "bytes", "channels", "rate", "seconds", "sha256", "stems"]
    assert (result["rate"], result["channels"], result["bits"], result["seconds"]) == (48000, 2, 16, 1.0)
    assert [sorted(s) for s in result["stems"]] == [["bytes", "n", "sha256"]] * 2 and [s["n"] for s in result["stems"]] == [1, 2]
    stem = b.jobs.stem(a, ids[0], 2)  # one stem alone marks the result received
    assert stem.path.name == "stem-2.wav" and stem.sha256 == result["stems"][1]["sha256"] and b.row(ids[0])["charge"] == "kept"
    assert refused(b.jobs.stem, a, ids[0], 3)[:2] == (404, "not_found")
    after = b.view(a, ids[0])["result"]
    assert after["engine"] == "nkido" and after["model"] == MODEL and after["repairs"] == 0 and after["issues"] == []
    assert after["source"].startswith("// loop") and after["prompt"].startswith("Write one Akkado patch") and after["bpm"] is None
    assert [s["label"] for s in after["stems"]] == ["melody", "bass"] and -20 <= after["measure"]["loud"] <= -16
    assert after["sources"] == [{"name": "nkido (Akkado, Cedar)", "license": "MIT", "holder": "Moritz Laass", "use": "소리 합성 엔진"}]
    sound = b.jobs.sound(a, ids[0])
    assert sound.sha256 == result["sha256"] and sound.bytes == result["bytes"] == sound.path.stat().st_size
    assert b.row(ids[0])["bytes"] == result["bytes"] + sum(s["bytes"] for s in result["stems"])


def test_a_result_names_the_db_its_stems_were_kept_under_the_masters_gain(bench):
    def quiet(wav, kind="sfx", loop=False, loud=(-20, -16)):
        said = lint(wav, kind, loop, loud)
        if kind == "music":
            said["measure"].update(peak=-13.98, sample_peak=-13.98, loud=-30.0)  # 12 dB under the middle of its range
        return said

    # Two stems that cancel: the master is at 0.2 and one stem at 0.8, which the master's +12 dB would write at 3.2.
    made = nkido.Rendered(ag.tone(1.0, 440, 0.2), {"drums": ag.tone(1.0, 220, 0.8), "pad": ag.tone(1.0, 330, 0.2)}, 48000, 2, 1.0)
    b = bench(engine=[made], measure=quiet)
    a = b.who()
    ids = b.send(a, items=[{"ref": "k0", "kind": "music", "loop": True, "name": "theme", "seconds": 1.0}, {"ref": "k1", "kind": "sfx", "name": "tap"}])
    assert b.jobs.drain() == 2
    result = b.view(a, ids[0])["result"]
    assert result["stems_lowered_db"] == pytest.approx(11.06, abs=0.02) and len(result["stems"]) == 2  # before it is received too
    with wave.open(str(b.jobs.stem(a, ids[0], 1).path)) as w:
        data = w.readframes(w.getnframes())
    loudest = max(abs(sample) for sample in struct.unpack(f"<{len(data) // 2}h", data))
    assert len(data) == 4 * 48000 and loudest == pytest.approx(32768 * 10 ** (-1 / 20), abs=2)  # the stem at 0.8: at -1 dBFS
    assert "stems_lowered_db" not in b.view(a, ids[1])["result"]  # a sound whose stems got the master's gain says nothing


def test_who_may_see_a_job(bench):
    b = bench()
    a, other = b.who(), b.who("x@y.z")
    mine, theirs = b.send(a)[0], b.send(PW, free=True)[0]
    assert b.view(other, mine) == {"id": mine, "status": "forbidden", "refund": "none"}
    assert b.view(PW, mine) == {"id": mine, "status": "forbidden", "refund": "none"}
    assert b.view(a, theirs) == {"id": theirs, "status": "forbidden", "refund": "none"}
    assert b.view(a, "0" * 32) == {"id": "0" * 32, "status": "unknown", "refund": "none"}
    assert b.jobs.cancel(other, [mine])["jobs"][0]["status"] == "forbidden" and b.row(mine)["status"] == "queued"
    b.jobs.drain()
    assert refused(b.jobs.sound, other, mine) == (403, "forbidden", {}) and refused(b.jobs.sound, a, "0" * 32) == (404, "not_found", {})
    assert b.row(mine)["delivered"] is None
    assert b.jobs.sound(aj.Who("pw", "pwip:another", "", "en"), theirs).bytes > 0


def test_a_sound_that_is_not_ready_says_so(bench):
    b = bench(engine=[BROKEN(), BROKEN(), BROKEN()])
    a = b.who()
    ids = b.send(a)
    assert refused(b.jobs.sound, a, ids[0]) == (409, "not_ready", {})
    b.jobs.drain()
    assert refused(b.jobs.sound, a, ids[0]) == (404, "not_found", {})  # it failed: there will be no sound


def test_every_code_has_a_sentence_in_both_languages(bench):
    codes = ["make_failed", "timeout", "busy", "no_model", "no_engine", "no_measure", "no_ledger", "no_credits", "operator_limit", "restarted",
             "internal", "cancelled", "daily_limit", "too_many_active", "fetch_first", "refund_limit", "rate", "quote_changed",
             "request_mismatch", "request_cancelled", "bad_request", "too_large", "not_ready", "not_found", "forbidden",
             "no_token", "bad_token", "token_expired", "bad_host", "bad_origin"]
    for lang in ("en", "ko"):
        for code in codes:
            text = aj.message(lang, code)
            assert text and text != code and "{" not in text
    assert aj.message("ko", "busy") != sb.msg("ko", "busy") and aj.message("ko", "no_credits") == sb.msg("ko", "no_credits")
    assert aj.message("xx", "busy") == aj.message("en", "busy") and aj.message("en", "never-heard-of") == "never-heard-of"
    assert aj.message("en", aj.GenError(429, "too_many_active", room=3)) == aj.TEXT["en"]["too_many_active"]


# ---------- the store and the settings ----------
def test_the_store_is_its_own_file_that_the_backup_passes_over(tmp_path):
    store = aj.GenStore(tmp_path / "data" / "asset-gen.db")
    assert store.db.execute("pragma journal_mode").fetchone()[0] == "wal" and store.db.execute("pragma busy_timeout").fetchone()[0] == 10000
    columns = lambda table: [r[1] for r in store.db.execute(f"pragma table_info({table})")]  # noqa: E731
    assert columns("gen") == ["id", "owner", "cls", "batch", "request_id", "ref", "k", "n", "ord", "status", "stage", "attempt",
                              "error", "view", "input", "cancel", "charge", "charge_at", "est", "usd", "bytes", "created",
                              "started", "finished", "delivered", "seen", "expires", "sess"]
    assert columns("req") == ["owner", "request_id", "body_sha", "batch", "response", "cancelled", "created"]
    assert columns("counts") == ["day", "name", "n"]
    indexed = {tuple(c[2] for c in store.db.execute(f"pragma index_info({r[1]})")) for r in store.db.execute("pragma index_list(gen)")}
    assert {("owner", "status"), ("request_id",)} <= indexed
    assert server_ops.data_files(tmp_path / "data") == [] and aj.DEFAULT_DB.name == "asset-gen.db"
    assert not issubclass(aj.GenStore, sb.JobStore)
    store.close()


def test_a_file_has_one_store_so_a_second_owner_cannot_fail_the_firsts_jobs(bench, tmp_path):
    path = tmp_path / "data" / "asset-gen.db"
    b = bench(store=aj.GenStore(path), engine=ag.FakeEngine(gate=threading.Event()), autostart=True, workers=1)
    a = b.who()
    ids = b.send(a, items=2)
    assert b.engine.entered.wait(10)
    before = [(b.row(i)["status"], b.row(i)["error"]) for i in ids]
    assert before == [("running", None), ("queued", None)]
    # A second process (an import of the API module, a check script, a test run) opens the same file.
    with pytest.raises(aj.StoreTaken):
        aj.GenStore(path)
    assert [(b.row(i)["status"], b.row(i)["error"]) for i in ids] == before  # nothing was failed as `restarted`
    b.engine.gate.set()
    until(lambda: all(b.row(i)["status"] == "done" for i in ids))
    assert b.ledger.named("refund") == [] and server_ops.data_files(tmp_path / "data") == []
    b.jobs.stop()
    b.store.close()
    again = aj.GenStore(path)  # the file is free once its store is closed
    assert again.one("select count(*) from gen where status='done'") == 2
    again.close()
    assert aj.GenStore().held is None and aj.GenStore().held is None  # stores in memory are each their own


def test_a_body_that_cannot_be_stored_is_a_400_and_makes_nothing(bench):
    b = bench()
    a = b.who()
    lone = json.loads('{"ref": "k0", "kind": "sfx", "description": "x\\ud800y"}')  # valid JSON, not valid text
    assert refused(b.jobs.submit, a, body("r1", [lone])) == (400, "bad_request", {"field": "items[0].description"})
    huge = json.loads('{"ref": "k0", "kind": "sfx", "seconds": 1' + "0" * 400 + "}")
    assert refused(b.jobs.submit, a, body("r1", [huge])) == (400, "bad_request", {"field": "items[0].seconds"})
    assert b.store.one("select count(*) from gen") == 0 and b.store.one("select count(*) from req") == 0
    # The same for an id in a lookup or a cancel: it never reaches the store.
    for call in (b.jobs.status, b.jobs.cancel):
        assert refused(call, a, ["x\ud800"]) == (400, "bad_request", {"field": "ids"})
    for call in (b.jobs.status_request, b.jobs.cancel_request):
        assert refused(call, a, "r\udfff") == (400, "bad_request", {"field": "request_id"})
    assert refused(b.jobs.sound, a, "\ud800") == (404, "not_found", {}) and b.store.one("select count(*) from req") == 0
    assert not b.store.lock.locked() and b.jobs.submit(a, body("r1"))["replayed"] is False


def test_the_limits_come_from_the_environment():
    assert aj.Limits() == aj.Limits.from_env({})
    assert (aj.Limits().account_daily, aj.Limits().daily, aj.Limits().pw_daily, aj.Limits().pw_all_daily) == (200, 1000, 120, 240)
    assert (aj.Limits().usd_pw, aj.Limits().usd_all) == (600_000, 5_000_000)
    assert aj.Limits.from_env({"OLMUSE_GEN_PW_REFUND_HOURLY": "7", "OLMUSE_GEN_PW_REFUND_DAILY": "9"}) == aj.Limits(pw_refund_hourly=7, pw_refund_daily=9)
    got = aj.Limits.from_env({"OLMUSE_GEN_ACCOUNT_DAILY": "5", "OLMUSE_GEN_DAILY": "6", "OLMUSE_GEN_PW_DAILY": "7",
                              "OLMUSE_GEN_PW_ALL_DAILY": "8", "OLMUSE_GEN_PW_DAILY_USD": "0.25", "OLMUSE_GEN_DAILY_USD": "x"})
    assert got == aj.Limits(5, 6, 7, 8, 0.25, 5.00)
    for wrong in ("nan", "inf", "-1", "1e999"):  # a number no ceiling can be leaves the default
        odd = aj.Limits.from_env({"OLMUSE_GEN_DAILY_USD": wrong, "OLMUSE_GEN_PW_DAILY_USD": wrong, "OLMUSE_GEN_DAILY": "-3"})
        assert odd == aj.Limits() and odd.usd_all == 5_000_000
    assert (aj.GEN_WORKERS, aj.RENDER_SLOTS, aj.QUEUE_CAP, aj.OWNER_ACTIVE) == (6, 2, 400, 64)
    assert (aj.OWNER_UNFETCHED_BYTES, aj.PW_UNFETCHED_BYTES, aj.DISK_CAP) == (512 * 2 ** 20, 2 ** 30, 4 * 2 ** 30)


def test_the_engine_runs_below_normal_priority(monkeypatch, tmp_path):
    seen = {}

    class Done:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

    monkeypatch.setattr(nkido.subprocess, "Popen", lambda cmd, **options: seen.update(options) or Done())
    monkeypatch.setattr(nkido, "cage", lambda proc, limit: None)
    assert nkido.run_caged(["x"], str(tmp_path), 1, 1) == (0, "")
    assert seen["creationflags"] & getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) == getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    if sys.platform == "win32":
        assert seen["creationflags"] == subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS


# ---------- one address, many sessions ----------
def session(name, owner=PW.owner):
    """A password session: the address is the owner, the token's sub is the session."""
    return aj.Who("pw", owner, "", "en", "pw:" + name)


def test_a_password_sessions_refunds_are_its_own_and_the_address_has_a_wider_count(bench):
    """A classroom is one address and so one owner. What one session stopped or let fail is counted against that
    session. The address has a count of its own, several times as wide, because a reload is a new session."""
    b = bench(limits=aj.Limits(pw_refund_hourly=4, pw_refund_daily=5))
    b.jobs.refund_hourly = 2
    one, two, three = session("one"), session("two"), session("three")

    def fail(who, rid, items=1):
        b.engine.script += [BROKEN() for _ in range(3 * items)]
        ids = b.send(who, rid=rid, items=items, free=True)
        b.jobs.drain()
        assert [b.row(i)["error"] for i in ids] == ["make_failed"] * items

    fail(one, "a1", 3)
    assert refused(b.jobs.submit, one, body("a2", free=True)) == (429, "refund_limit", {"retry_after": 3601})
    assert b.jobs.quote_for(one, 1, 1)["reason"] == "refund_limit"
    assert b.jobs.quote_for(two, 1, 1)["ok"] is True  # the same address, another session
    fail(two, "b1")
    assert b.jobs.quote_for(three, 1, 1)["ok"] is True  # four at this address in the hour: met, not passed
    fail(three, "c1")
    assert b.jobs.count("rf:" + PW.owner) == 5 and b.jobs.count("d:" + PW.owner) == 5 and b.jobs.count("d:teachers") == 0
    # Passed by one. Nobody at this address is taken now, a session that just came by a reload included.
    assert refused(b.jobs.submit, three, body("c2", free=True)) == (429, "refund_limit", {"retry_after": 3601})
    assert refused(b.jobs.submit, session("reloaded"), body("d1", free=True))[1] == "refund_limit"
    assert b.jobs.submit(session("one", "pwip:ffffffffffffffff"), body("e1", free=True))["replayed"] is False  # another address
    assert b.jobs.drain() == 1
    b.later(3601)
    assert b.jobs.quote_for(three, 1, 1)["ok"] is True  # five today at this address: met, not passed
    fail(three, "c2")
    assert refused(b.jobs.submit, two, body("b2", free=True)) == (429, "refund_limit", {"retry_after": TOMORROW - 3601})
    # A token without a session (none is made that way) is counted by its owner alone, with the narrow limits.
    b = bench(engine=[BROKEN() for _ in range(9)])
    b.jobs.refund_hourly = 2
    b.send(PW, items=3, free=True)
    b.jobs.drain()
    assert refused(b.jobs.submit, PW, body("r2", free=True))[1] == "refund_limit" and b.jobs.count("rf:" + PW.owner) == 3
    assert (aj.Limits().pw_refund_hourly, aj.Limits().pw_refund_daily) == (36, 72)
    assert aj.TEXT["en"]["refund_limit"] == "Too many sounds were stopped or returned." and "today" not in aj.message("en", "refund_limit")


def test_the_sessions_of_one_address_take_turns(bench):
    """Inside an owner the order was the order of asking, so a session that asked for many sounds made everybody
    else at its address wait for all of them."""
    named = lambda letter, count: [{"ref": f"{letter}{i}", "kind": "sfx", "name": f"{letter}{i}", "seconds": 0.2}  # noqa: E731
                                   for i in range(count)]
    b = bench()
    one, two, other = session("one"), session("two"), b.who()
    first = b.send(one, rid="a1", items=named("a", 4), free=True)
    late = b.send(two, rid="b1", items=named("b", 2), free=True)
    assert [b.view(two, i)["position"] for i in late] == [2, 4] and [b.view(one, i)["position"] for i in first] == [2, 4, 5, 6]
    b.send(other, rid="o1", items=named("o", 1))
    assert b.view(two, late[0])["position"] == 3  # the account's one sound goes between
    b.jobs.drain()
    assert [ag.request_of(p)["item"]["name"] for p in b.model.prompts] == ["a0", "o0", "b0", "a1", "b1", "a2", "a3"]
    # A session's own order stays: every sound's draft 1 before any draft 2.
    b = bench()
    b.send(one, rid="a1", items=named("a", 2), drafts=2, free=True)
    b.send(two, rid="b1", items=named("b", 1), drafts=2, free=True)
    b.jobs.drain()
    option = lambda p: ag.request_of(p)["item"]["name"] + p.split("Option ")[1].split(" of")[0]  # noqa: E731
    assert [option(p) for p in b.model.prompts] == ["a01", "b01", "a11", "b02", "a02", "a12"]
    assert b.jobs.lane_active == {} and set(b.jobs.lane_served) <= {(PW.owner, aj.lane_of(one)), (PW.owner, aj.lane_of(two))}
    b.jobs.sweep()
    assert b.jobs.lane_served == {}  # nothing waits and nothing runs: the turns are forgotten


def test_credits_bought_on_the_page_count_before_a_request_is_turned_away(bench):
    """A coupon or a purchase goes from the page to the ledger and never passes the API, whose remembered balance
    would turn the account away for up to a minute after it paid."""
    b = bench(free=0)
    a = b.who()
    assert refused(b.jobs.submit, a, body()) == (402, "no_credits", {"balance": 0, "credits": 1})
    b.ledger.real.grant("a@b.c", 5)
    b.later(aj.BALANCE_RECHECK - 1)
    assert refused(b.jobs.submit, a, body())[1] == "no_credits" and b.jobs.quote_for(a, 1, 1)["reason"] == "no_credits"
    assert b.ledger.named("account") == ["a@b.c"]  # read a moment ago: not asked again yet
    b.later(1)
    quote = b.jobs.quote_for(a, 1, 1)
    assert (quote["ok"], quote["balance"]) == (True, 5) and b.ledger.named("account") == ["a@b.c"] * 2
    assert b.jobs.submit(a, body())["replayed"] is False and len(b.ledger.named("account")) == 2
    # Enough is never asked about again inside the minute, and too little is asked about once every few seconds.
    b.later(aj.BALANCE_RECHECK)
    assert b.jobs.quote_for(a, 4, 1)["ok"] is True and len(b.ledger.named("account")) == 2
    for _ in range(3):
        assert refused(b.jobs.submit, a, body("r2", 5)) == (402, "no_credits", {"balance": 5, "credits": 5})
    assert len(b.ledger.named("account")) == 3
    # A ledger that does not answer the second look leaves the remembered balance to decide.
    b.later(aj.BALANCE_RECHECK)
    b.ledger.fail.add("account")
    assert refused(b.jobs.submit, a, body("r2", 5)) == (402, "no_credits", {"balance": 5, "credits": 5})
    assert b.jobs.quote_for(a, 1, 1)["ok"] is True and aj.BALANCE_RECHECK == 5 and b.ledger.locked == [False] * len(b.ledger.calls)


def test_refunds_the_ledger_keeps_turning_down_are_said_in_the_log(bench, caplog):
    b = bench(engine=[BROKEN() for _ in range(3)])
    a = b.who()
    b.ledger.fail.add("refund")
    ids = b.send(a)
    b.jobs.drain()
    assert (b.row(ids[0])["error"], b.row(ids[0])["charge"]) == ("make_failed", "refund_due")
    alerts = lambda: [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR and "refund" in r.getMessage()]  # noqa: E731
    with caplog.at_level(logging.INFO, logger="olmuse.asset.jobs"):
        for _ in range(11):  # the sweeper's first try is at 120 seconds, 90 after the charge
            b.later(60)
            b.jobs.sweep()
        assert alerts() == [] and b.row(ids[0])["charge"] == "refund_due"
        b.later(60)
        b.jobs.sweep()  # ten minutes of nothing but refusals
        assert len(alerts()) == 1 and alerts()[0].startswith("ALERT ") and alerts()[0].endswith("for 10 minutes; credits still to go back: 1")
        assert "a@b.c" not in alerts()[0] and a.owner not in alerts()[0] and ids[0] not in alerts()[0]
        for _ in range(3 * 60):
            b.later(60)
            b.jobs.sweep()
        assert len(alerts()) == 4  # once an hour from then on
        assert len(b.ledger.named("refund")) == 1 + 11 + 3 * 60 and b.ledger.credits() == 19
        b.ledger.fail.clear()
        b.later(60)
        b.jobs.sweep()
        assert b.row(ids[0])["charge"] == "refunded" and b.ledger.credits() == 20
        for _ in range(2 * 60):
            b.later(60)
            b.jobs.sweep()
        assert len(alerts()) == 4
    assert b.jobs.health()["ok"] is True  # the page and the API go on as they were


def test_health_tells_a_full_disk_and_an_engine_that_went_and_came_back(bench, tmp_path):
    b = bench(ledger=None)
    b.jobs.free = lambda path: aj.DISK_FREE_MIN - 1
    b.jobs.sweep()
    assert b.jobs.health()["ok"] is False and refused(b.jobs.submit, PW, body(free=True)) == (503, "busy", {})
    b.jobs.free = lambda path: 100 * aj.GB
    b.jobs.sweep()
    assert b.jobs.health()["ok"] is True
    # The engine's program is looked for again at every sweep, not only when the process starts.
    exe = tmp_path / "nkido.exe"
    exe.write_bytes(b"x")
    engine = ag.FakeEngine()
    engine.EXE = str(exe)
    b = bench(engine=engine)
    a = b.who()
    ids = b.send(a) + b.send(PW, free=True)
    exe.unlink()
    b.jobs.sweep()
    assert (b.jobs.health()["engine"], b.jobs.health()["ok"]) == (False, False)
    assert [(b.row(i)["status"], b.row(i)["error"], b.row(i)["charge"]) for i in ids] == [("failed", "no_engine", "none")] * 2
    assert refused(b.jobs.submit, PW, body("r2", free=True)) == (503, "no_engine", {}) and b.ledger.named("charge") == []
    exe.write_bytes(b"x")
    b.jobs.sweep()
    assert (b.jobs.health()["engine"], b.jobs.health()["ok"]) == (True, True)
    assert b.jobs.submit(PW, body("r2", free=True))["replayed"] is False and b.jobs.drain() == 1
    # An engine that names no file is left as the last render found it.
    b = bench(engine=[nkido.RenderError("missing-engine", "nkido is not installed on this server")])
    b.send(PW, free=True)
    b.jobs.drain()
    b.jobs.sweep()
    assert b.jobs.health()["engine"] is False


def test_a_store_made_before_sessions_were_written_down_gets_the_column(tmp_path):
    path = tmp_path / "asset-gen.db"
    old = sqlite3.connect(path)
    old.executescript(aj.SCHEMA.replace(", sess text", ""))
    assert "sess" not in [row[1] for row in old.execute("pragma table_info(gen)")]
    old.execute("insert into gen (id, owner, cls, status, charge) values ('j1', 'pwip:x', 'pw', 'done', 'none')")
    old.commit()
    old.close()
    store = aj.GenStore(path)
    try:
        with store.lock:
            assert "sess" in [row["name"] for row in store.db.execute("pragma table_info(gen)")]
            assert store.one("select sess from gen where id='j1'") is None
    finally:
        store.close()
    aj.GenStore(path).close()  # and a store that has it is opened as it is


def test_one_session_cannot_pass_the_refund_limits_of_its_address_alone(bench):
    """One request holds up to 64 drafts and each of them that fails, or is never received, is a refund. All of
    them went into the address's count, so 37 from one session turned everybody at the address away for an hour.
    Of one session the address counts no more than what closes that session's own door: 13 in an hour, 25 a day."""
    one, two = session("one"), session("two")
    address, own = "rf:" + PW.owner, "rf:" + PW.owner + "/" + aj.lane_of(one)
    hour = lambda b: len(b.jobs.refunds.get(PW.owner, ()))  # noqa: E731 - the address's refunds of the last hour
    b = bench(engine=[BROKEN() for _ in range(3 * 40)])
    ids = b.send(one, rid="a1", items=40, free=True)  # forty drafts of one request, and none passes the checks
    b.jobs.drain()
    assert {b.row(i)["error"] for i in ids} == {"make_failed"}
    assert (b.jobs.count(own), b.jobs.count(address), hour(b)) == (40, 25, 13)
    assert refused(b.jobs.submit, one, body("a2", free=True)) == (429, "refund_limit", {"retry_after": 3601})
    assert b.jobs.quote_for(two, 1, 1)["ok"] is True and b.jobs.submit(two, body("b1", free=True))["replayed"] is False
    # Forty that nobody received (the tab was closed): an hour later one sweep ends them all.
    b = bench()
    ids = b.send(one, rid="a1", items=40, free=True)
    b.jobs.drain()
    b.later(aj.UNFETCHED_TTL + 1)
    b.jobs.sweep()
    assert {b.row(i)["status"] for i in ids} == {"gone"} and (b.jobs.count(own), b.jobs.count(address), hour(b)) == (40, 25, 13)
    assert refused(b.jobs.submit, one, body("a2", free=True))[1] == "refund_limit"
    assert b.jobs.submit(two, body("b1", free=True))["replayed"] is False
    assert b.jobs.submit(session("reloaded"), body("c1", free=True))["replayed"] is False
    # The address's own count is still there for sessions that keep changing: the third one passes it.
    b = bench(engine=[BROKEN() for _ in range(3 * 42)])
    for n, name in enumerate(("one", "two", "three")):
        assert hour(b) == 13 * n and b.jobs.quote_for(session("next"), 1, 1)["ok"] is True
        b.send(session(name), rid=name, items=14, free=True)
        b.jobs.drain()
    assert (hour(b), b.jobs.count(address)) == (39, 42)
    assert refused(b.jobs.submit, session("next"), body("d1", free=True)) == (429, "refund_limit", {"retry_after": 3601})
    # And the day's: of one session the address takes one more than the session's own limit for the day.
    b = bench(engine=[BROKEN() for _ in range(3 * 10)], limits=aj.Limits(pw_refund_hourly=100, pw_refund_daily=5))
    b.jobs.refund_hourly, b.jobs.refund_daily = 100, 2
    b.send(one, rid="a1", items=5, free=True)
    b.jobs.drain()
    assert (b.jobs.count(own), b.jobs.count(address)) == (5, 3)
    assert refused(b.jobs.submit, one, body("a2", free=True)) == (429, "refund_limit", {"retry_after": TOMORROW})
    b.send(two, rid="b1", items=5, free=True)
    b.jobs.drain()
    assert b.jobs.count(address) == 6
    assert refused(b.jobs.submit, session("next"), body("d1", free=True)) == (429, "refund_limit", {"retry_after": TOMORROW})


def test_a_second_outage_of_refunds_is_said_after_its_own_ten_minutes(bench, caplog):
    """The hour between two ALERTs is for one outage that goes on. It also held back the first ALERT of the next
    outage, which was said 57 minutes late, or never when the ledger was back before that."""
    b = bench(engine=[BROKEN() for _ in range(6)])
    a = b.who()
    alerts = lambda: [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR and "refund" in r.getMessage()]  # noqa: E731

    def owed(rid):
        b.ledger.fail.add("refund")
        ids = b.send(a, rid=rid)
        b.jobs.drain()
        assert b.row(ids[0])["charge"] == "refund_due"
        return ids[0]

    def sweeps(count):
        for _ in range(count):
            b.later(60)
            b.jobs.sweep()

    with caplog.at_level(logging.INFO, logger="olmuse.asset.jobs"):
        first = owed("r1")
        sweeps(12)  # the first refusal is at 120 seconds, the ALERT ten minutes after it
        assert len(alerts()) == 1
        b.ledger.fail.clear()
        sweeps(1)
        assert b.row(first)["charge"] == "refunded"
        second = owed("r2")
        sweeps(11)
        assert len(alerts()) == 1 and b.row(second)["charge"] == "refund_due"
        sweeps(1)  # ten minutes of refusals again, 13 minutes after the first ALERT
        assert len(alerts()) == 2 and alerts()[1].endswith("for 10 minutes; credits still to go back: 1")
        sweeps(59)
        assert len(alerts()) == 2  # and from there once an hour, as in the first outage
        sweeps(1)
        assert len(alerts()) == 3 and alerts()[2].endswith("for 70 minutes; credits still to go back: 1")


def test_whoever_just_came_stands_behind_the_ones_already_waiting(bench):
    """A session that was never picked counted as the one picked longest ago, so each new one (a reload, another
    tab) went ahead of a session that had been picked once, for as long as new ones kept coming. Owners the same."""
    named = lambda letter, count: [{"ref": f"{letter}{i}", "kind": "sfx", "name": f"{letter}{i}", "seconds": 0.2}  # noqa: E731
                                   for i in range(count)]

    def picked(b):
        job = b.jobs._next(block=False)
        b.jobs._serve(job)
        return job["ref"]

    for comer in (lambda n: session(f"new{n}"),                       # sessions of one address
                  lambda n: session("s", f"pwip:{n:016x}")):          # and owners: other addresses
        b = bench()
        home = session("home")
        late = b.send(home, rid="h1", items=named("h", 2), free=True)[1]
        assert picked(b) == "h0"
        order, told = [], []
        for n in range(4):  # one newcomer asks before every pick
            b.send(comer(n), rid=f"x{n}", items=named(f"x{n}", 1), free=True)
            told.append(b.view(home, late).get("position"))
            order.append(picked(b))
        assert order == ["x00", "h1", "x10", "x20"] and told[0] == 2  # one newcomer was there first; the rest wait
        assert b.jobs.drain() == 1
    # A newcomer stands behind the ones that waited before it, and ahead only of the one that was picked last.
    b = bench()
    b.send(session("a"), rid="a1", items=named("a", 3), free=True)
    b.send(session("b"), rid="b1", items=named("b", 3), free=True)
    assert [picked(b) for _ in range(3)] == ["a0", "b0", "a1"]
    b.send(session("c"), rid="c1", items=named("c", 2), free=True)
    assert [picked(b) for _ in range(5)] == ["b1", "c0", "a2", "b2", "c1"]
    # Whoever came while nothing had been picked since is in line as before: thirty sessions, one sound each first.
    b = bench()
    b.send(session("a"), rid="a1", items=named("a", 2), free=True)
    assert picked(b) == "a0"
    for n in range(29):
        b.send(session(f"s{n}"), rid=f"s{n}", items=named(f"s{n}x", 2), free=True)
    assert [picked(b) for _ in range(30)] == [f"s{n}x0" for n in range(29)] + ["a1"]


def test_a_balance_read_that_comes_back_after_a_charge_does_not_undo_it(bench):
    """A read of the balance and a worker's charge cross: the ledger made the read first and its answer arrived
    last. The read's balance was remembered over the charge's, one credit too many, so a request that had to be
    a 402 was taken and its draft failed as no_credits when it was picked."""
    b = bench(free=2)
    a = b.who()
    b.send(a, items=2)  # two credits and two drafts waiting: the balance is read and remembered
    b.later(aj.BALANCE_RECHECK + 1)
    ask, read, back, out = b.ledger.account, threading.Event(), threading.Event(), {}

    def slow(email):
        got = ask(email)  # the ledger reads at once; its answer is on the way back until `back`
        read.set()
        back.wait(10)
        return got

    b.ledger.account = slow
    asker = threading.Thread(target=lambda: out.update(quote=b.jobs.quote_for(a, 1, 1)))
    asker.start()  # short of credits and six seconds old: the ledger is asked once more, and says 2
    try:
        assert read.wait(10)
        b.jobs._serve(b.jobs._next(block=False))  # meanwhile one draft is picked and its charge answers: 1 left
        assert b.jobs.status(a, [])["credits"] == 1
    finally:
        back.set()
        asker.join(10)
        b.ledger.account = ask
    assert b.jobs.status(a, [])["credits"] == 1 == b.ledger.credits()
    assert (out["quote"]["ok"], out["quote"]["reason"], out["quote"]["balance"]) == (False, "no_credits", 1)
    assert refused(b.jobs.submit, a, body("r2")) == (402, "no_credits", {"balance": 1, "credits": 1})
    assert b.jobs.drain() == 1 and b.ledger.credits() == 0 and len(b.ledger.named("charge")) == 2
    # A read nothing crossed is remembered as before.
    b.ledger.real.grant("a@b.c", 3)
    b.later(aj.BALANCE_RECHECK)
    assert b.jobs.quote_for(a, 3, 1)["balance"] == 3 and b.jobs.status(a, [])["credits"] == 3


# ---------- accounts on the Claude CLI list (the owner's subscription, no credits) ----------
class Claude:
    """A stand-in for asset_generate.ClaudeCli: a FakeModel per call, ok and size like the real one."""

    def __init__(self, script=(), size=2, gate=None):
        self.model, self.ok, self.size, self.checks = ag.FakeModel(script, cost=0.0, gate=gate), True, size, 0
        self.name = "sonnet"

    def __call__(self):
        return self.model

    def check(self):
        self.checks += 1
        return self.ok


LISTED = "jam@b.c"


def claude_bench(bench, claude=None, accounts=(LISTED,), **options):
    b = bench(**options)
    b.claude = claude or Claude()
    b.jobs.stop()
    b.jobs = aj.GenJobs(b.store, ledger=b.ledger, model=b.jobs.model, engine=b.engine, measure=lint, renders=b.jobs.renders,
                        temp=b.jobs.temp, limits=b.jobs.limits, model_name=MODEL, clock=lambda: b.now[0], sleep=b.sleep,
                        free=lambda path: 100 * aj.GB, autostart=options.get("autostart", False), workers=options.get("workers", 1),
                        claude=b.claude, claude_accounts=accounts)
    return b


def test_a_listed_account_is_made_by_the_claude_cli_and_never_reaches_the_ledger(bench):
    b = claude_bench(bench, accounts=(" JAM@b.c ", "other@x.y"))
    jam = b.who(LISTED)
    quote = b.jobs.quote_for(jam, 2, 1)
    assert (quote["unit"], quote["credits"], quote["free"], quote["balance"], quote["ok"]) == (0, 0, True, None, True)
    ids = b.send(jam, rid="j", items=2, free=True)
    assert b.jobs.drain() == 2
    assert [(b.row(i)["status"], b.row(i)["charge"], b.row(i)["cls"]) for i in ids] == [("done", "none", "cc")] * 2
    assert b.ledger.calls == [] and len(b.claude.model.prompts) == 2 and b.model.prompts == []
    assert (b.jobs.count("d:" + jam.owner), b.jobs.count("d:members"), b.jobs.count("usd:all")) == (2, 0, 0)
    assert b.jobs.status(jam, ids)["credits"] is None and [v["refund"] for v in b.jobs.status(jam, ids)["jobs"]] == ["none"] * 2
    assert refused(b.jobs.submit, jam, body(rid="paid", items=1))[:2] == (409, "quote_changed")  # it is priced 0


def test_an_account_not_on_the_list_is_charged_and_made_by_the_paid_model_as_before(bench):
    b = claude_bench(bench)
    a = b.who()
    assert b.jobs.quote_for(a, 1, 1)["credits"] == 1
    ids = b.send(a)
    b.jobs.drain()
    assert (b.row(ids[0])["status"], b.row(ids[0])["charge"], b.row(ids[0])["cls"]) == ("done", "charged", "acct")
    assert b.ledger.named("charge") == ["gen:" + ids[0]] and len(b.model.prompts) == 1 and b.claude.model.prompts == []
    assert b.jobs.count("d:members") == 1 and b.jobs.count("usd:all") > 0
    # A password session is not an account, so the list never reaches it.
    pw = b.send(PW, rid="pw", free=True)
    b.jobs.drain()
    assert b.row(pw[0])["cls"] == "pw" and len(b.model.prompts) == 2


def test_a_listed_accounts_failed_draft_asks_the_ledger_nothing(bench):
    b = claude_bench(bench, engine=[BROKEN(), BROKEN(), BROKEN()])
    jam = b.who(LISTED)
    ids = b.send(jam, free=True)
    b.jobs.drain()
    view = b.view(jam, ids[0])
    assert (view["status"], view["error"]["code"], view["refund"]) == ("failed", "make_failed", "none")
    assert b.ledger.calls == [] and b.row(ids[0])["charge"] == "none" and b.jobs.count("rf:" + jam.owner) == 0
    assert b.jobs.count("d:" + jam.owner) == 1  # the subscription was spent on it
    b.later(aj.UNFETCHED_TTL + 1)
    b.jobs.sweep()
    assert b.ledger.calls == []


def test_a_listed_account_has_its_own_daily_cap(bench, monkeypatch):
    assert aj.Limits().claude_daily == 300
    assert aj.Limits.from_env({"OLMUSE_GEN_CLAUDE_DAILY": "5"}).claude_daily == 5
    b = claude_bench(bench, limits=aj.Limits(claude_daily=3, account_daily=1))
    jam = b.who(LISTED)
    b.send(jam, rid="a", items=2, free=True)
    b.jobs.drain()
    assert b.jobs.quote_for(jam, 2, 1)["reason"] == "account_limit"
    status, code, extras = refused(b.jobs.submit, jam, body(rid="b", items=2, free=True))
    assert (status, code, extras["left_today"]) == (429, "account_limit", 1)
    assert len(b.send(jam, rid="c", items=1, free=True)) == 1
    # The paid lane's caps are not the list's: account_daily is 1 and the members' count is untouched.
    assert b.jobs.count("d:members") == 0 and len(b.send(b.who(), rid="d")) == 1


def test_a_listed_account_works_without_the_paid_model_and_ledger(bench):
    b = claude_bench(bench, model=False, ledger=None)
    jam, a = aj.Who("acct", "acct:jam", LISTED, "en"), aj.Who("acct", "acct:a", "a@b.c", "en")
    ids = b.send(jam, free=True)
    assert b.jobs.drain() == 1 and b.row(ids[0])["status"] == "done"
    assert refused(b.jobs.submit, a, body(rid="x"))[:2] == (503, "no_model")


def test_when_the_claude_cli_is_down_only_the_listed_accounts_are_turned_away(bench, caplog):
    claude = Claude()
    b = claude_bench(bench, claude=claude)
    jam, a = b.who(LISTED), b.who()
    claude.ok = False
    assert refused(b.jobs.submit, jam, body(rid="j", free=True))[:2] == (503, "no_model")
    assert b.jobs.quote_for(jam, 1, 1)["reason"] == "no_model"
    assert b.jobs.quote_for(a, 1, 1)["ok"] is True and len(b.send(a)) == 1
    assert b.jobs.drain() == 1 and b.jobs.health()["ok"] is True and b.jobs.health()["claude"] is False
    claude.ok = True
    assert b.jobs.health()["claude"] is True and len(b.send(jam, rid="j2", free=True)) == 1


def test_a_claude_cli_that_signs_out_mid_draft_fails_the_listed_queue_with_an_alert(bench, caplog):
    claude = Claude()

    def signed_out(prompt):
        claude.ok = False
        return sb.ModelError("claudecli_auth")
    claude.model.script = [signed_out]
    b = claude_bench(bench, claude=claude)
    jam, a = b.who(LISTED), b.who()
    ids = b.send(jam, rid="j", items=3, free=True)
    paid = b.send(a)
    with caplog.at_level("ERROR"):
        b.jobs.drain()
    assert [b.row(i)["error"] for i in ids] == ["no_model"] * 3 and b.ledger.named("refund") == []
    assert b.row(paid[0])["status"] == "done" and "ALERT" in caplog.text and "Claude" in caplog.text
    assert b.jobs.count("d:" + jam.owner) == 0  # not the user's doing: nothing stays counted
    claude.ok = True  # signed in again: the sweeper's check takes it back
    b.jobs.sweep()
    assert claude.checks >= 1 and len(b.send(jam, rid="j2", free=True)) == 1


def test_the_claude_lane_rests_on_its_own_after_three_refusals_in_a_row(bench, caplog):
    claude = Claude([sb.ModelError("claudecli_failed")] * 3)
    b = claude_bench(bench, claude=claude)
    jam, a = b.who(LISTED), b.who()
    b.send(jam, rid="j", items=3, free=True)
    with caplog.at_level("ERROR"):
        b.jobs.drain()
    assert "ALERT" in caplog.text
    assert refused(b.jobs.submit, jam, body(rid="j2", free=True))[:2] == (503, "no_model")
    assert len(b.send(a)) == 1 and b.jobs.drain() == 1  # the paid lane does not rest with it
    b.later(aj.BREAKER_SECONDS)
    assert len(b.send(jam, rid="j3", free=True)) == 1


def test_no_more_listed_drafts_run_at_once_than_the_cli_has_slots(bench):
    gate = threading.Event()
    claude = Claude(size=1, gate=gate)
    b = claude_bench(bench, claude=claude, autostart=True, workers=3)
    jam, a = b.who(LISTED), b.who()
    ids = b.send(jam, rid="j", items=2, free=True)
    until(lambda: claude.model.entered.is_set())
    paid = b.send(a)
    until(lambda: b.row(paid[0])["status"] == "done")  # the paid lane is not held up by it
    assert sorted(b.row(i)["status"] for i in ids) == ["queued", "running"]
    gate.set()
    until(lambda: all(b.row(i)["status"] == "done" for i in ids))
