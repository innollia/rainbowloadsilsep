"""The asset room's generation API (asset_api.py) through fastapi.testclient: the checks every request passes and
their order, the shape of an error, and the whole way from a request to its sound and its stems.

No key and no engine: a scripted model, sine waves, a measure of the test's own, LocalLedger behind a wrapper that
writes its calls down, and a clock the test moves. Nothing starts a thread unless a test says so:
create_app(Deps(..., autostart=False)) and drain()."""
import asyncio
import datetime
import hashlib
import importlib.metadata
import io
import json
import logging
import re
import shutil
import socket
import subprocess
import threading
import time
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from uvicorn.main import main as uvicorn_command

import asset_api
import asset_generate as ag
import asset_jobs as aj
import asset_token
import studio_backend as sb
from asset_engine import nkido
from credits import LocalLedger, RemoteLedger

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime.datetime(2026, 3, 10, 12, 0).timestamp()  # noon, so minutes later is still the same day
SECRET = b"s" * 32
BASE = "http://127.0.0.1:8502"   # a Host the API allows
API = "/api/asset"
HOME = "https://olmuse.app"
MODEL = "deepseek/deepseek-v4.1-flash"
QUOTE = "/quote?items=1&drafts=1"
MUSIC = [{"ref": "k0", "kind": "music", "loop": True, "name": "theme", "seconds": 1.0}]  # renders with two stems
MISSING = "f" * 32


def lint(wav, kind="sfx", loop=False, loud=(-20, -16)):
    """A measure that finds nothing wrong: the length from the file, every level in range."""
    with wave.open(io.BytesIO(wav)) as w:
        seconds = w.getnframes() / w.getframerate()
    return {"measure": {"seconds": seconds, "rate": 48000, "channels": 2, "bits": 16, "sample_peak": -10.0, "peak": -10.0,
                        "loud": -18.0, "clips": 0, "lead": 0.0, "tail": 0.0, "end": -70.0, "dc": 0.0, "seam": 0.0}, "issues": []}


class Ledger:
    """LocalLedger with the name of every call written down."""

    def __init__(self, free=20):
        self.real, self.calls = LocalLedger(":memory:", pepper="p", free=free), []

    def key_of(self, email):
        return self.real.key_of(email)

    def account(self, email):
        self.calls.append("account")
        return self.real.account(email)

    def charge(self, email, amount, ref):
        self.calls.append("charge")
        return self.real.charge(email, amount, ref)

    def refund_key(self, key, amount, ref):
        self.calls.append("refund")
        return self.real.refund_key(key, amount, ref)


def bearer(token):
    return {"Authorization": "Bearer " + token} if token else {}


def body(rid="r1", items=1, drafts=1, credits=None, kind="sfx", **more):
    things = items if isinstance(items, list) else [{"ref": f"k{i}", "kind": kind, "name": f"sound{i}", "seconds": 0.2}
                                                     for i in range(items)]
    return {"request_id": rid, "expect_credits": len(things) * drafts if credits is None else credits, "drafts": drafts,
            "project": {"game": "g"}, "items": things, **more}


def refused(response):
    """(status, code, extras) of an error answer, after a look at its shape."""
    said = response.json()
    assert list(said) == ["error"] and isinstance(said["error"]["message"], str) and said["error"]["message"]
    assert response.headers["cache-control"] == "no-store"
    return response.status_code, said["error"]["code"], {k: v for k, v in said["error"].items() if k not in ("code", "message")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def until(check, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("the wait ran out")


class Bench:
    """One API over fakes, with the time in the test's hands. web asks the way the tunnel does, from 127.0.0.1."""

    def __init__(self, folder, free=20, **deps):
        self.now = [T0]
        self.ledger = Ledger(free)
        self.model = ag.FakeModel(cost=0.002)
        self.app = asset_api.create_app(asset_api.Deps(
            secret=SECRET, renders=folder / "renders", temp=folder / "temp", ledger=self.ledger, model=lambda: self.model,
            engine=ag.FakeEngine(), measure=lint, model_name=MODEL, clock=lambda: self.now[0], sleep=lambda seconds: None,
            free=lambda path: 100 * aj.GB, autostart=False, **deps))
        self.api = self.app.state.api
        self.jobs = self.api.jobs
        self.web = self.client()

    def client(self, peer="127.0.0.1"):
        return TestClient(self.app, base_url=BASE, client=(peer, 50000))

    def token(self, email="a@b.c", lang="en", sub="", secret=SECRET):
        """An account's token, or with sub ("pw:...") a password session's."""
        kind = "pw" if sub else "acct"
        payload = asset_token.payload_for(kind, sub or "acct:" + self.ledger.key_of(email), "" if sub else email, lang, self.now[0])
        return asset_token.sign(payload, secret)

    def get(self, path, token="", headers=None, web=None):
        return (web or self.web).get(API + path, headers={**bearer(token), **(headers or {})})

    def post(self, path, said=None, token="", origin=HOME, headers=None, web=None, content=None):
        sent = {**bearer(token), **({"Origin": origin} if origin else {}), **(headers or {})}
        if content is not None:
            return (web or self.web).post(API + path, content=content, headers=sent)
        return (web or self.web).post(API + path, json=said, headers=sent)

    def make(self, token, headers=None, web=None, **said):
        made = self.post("/jobs", body(**said), token, headers=headers, web=web)
        assert made.status_code == 200, made.text
        return [job["id"] for job in made.json()["jobs"]]

    def views(self, token, ids, **more):
        return self.post("/jobs/status", {"ids": ids}, token, **more).json()["jobs"]

    def row(self, job_id):
        with self.jobs.store.lock:
            return dict(self.jobs.store.db.execute("select * from gen where id=?", (job_id,)).fetchone())


@pytest.fixture
def bench(tmp_path):
    made = []

    def make(**options):
        made.append(Bench(tmp_path / f"bench{len(made)}", **options))
        return made[-1]
    yield make
    for b in made:
        b.jobs.stop()
        b.jobs.store.close()
        b.api.close()


# ---------- health, and the app itself ----------
def test_health_takes_no_token_and_says_only_flags_and_counts(bench):
    b = bench()
    got = b.get("/health")
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    assert got.json() == {"ok": True, "model": True, "engine": True, "node": True, "ledger": True, "queued": 0, "running": 0,
                          "disk_free_mb": 100 * 1024}
    b.make(b.token(), items=2)
    assert b.get("/health").json()["queued"] == 2
    assert b.web.head(API + "/health").status_code == 200
    assert refused(b.get("/health", headers={"Host": "evil.example"})) == (403, "bad_host", {})
    assert b.ledger.calls == ["account"]  # the one balance the request needed; health asks nobody


def test_the_module_app_builds_nothing_until_the_server_starts_it():
    app = asset_api.app
    assert app.state.api is None  # no store opened, no thread, no log file: importing has no effect
    assert (app.docs_url, app.redoc_url, app.openapi_url) == (None, None, None)
    got = TestClient(app, base_url=BASE, raise_server_exceptions=False).get(API + "/health")
    assert refused(got) == (500, "internal", {})
    with pytest.raises(TypeError):
        asset_api.Deps(secret=SECRET)  # the renders folder has no default: GenJobs empties what its store does not know


def test_the_server_start_builds_the_jobs_and_its_stop_ends_them(tmp_path, monkeypatch):
    logged = []
    store = aj.GenStore(str(tmp_path / "gen.db"))
    monkeypatch.delenv("OLMUSE_API_ORIGINS", raising=False)
    monkeypatch.setattr(asset_api.server_ops, "setup_logging", logged.append)
    monkeypatch.setattr(asset_api, "real_deps", lambda log_to: log_to(asset_api.logs_beside(store.path)) or asset_api.Deps(
        secret=SECRET, renders=tmp_path / "renders", temp=tmp_path / "temp", store=store, model=ag.FakeModel,
        engine=ag.FakeEngine(), measure=lint, free=lambda path: 100 * aj.GB, workers=2))
    app = asset_api.create_app()
    assert app.state.api is None
    with TestClient(app, base_url=BASE, client=("127.0.0.1", 50000)) as web:
        jobs = app.state.api.jobs
        assert logged == [tmp_path / "logs" / "api"]  # beside its database: not the page's logs, nor another API's
        assert web.get(API + "/health").json()["ok"] is True and len(jobs.threads) == 3  # the sweeper and two workers
        token = asset_token.sign(asset_token.payload_for("pw", "pw:s", "", "en", time.time()), SECRET)
        made = web.post(API + "/jobs", json=body(credits=0), headers={**bearer(token), "Origin": HOME}).json()["jobs"]
        status = lambda: web.post(API + "/jobs/status", json={"ids": [made[0]["id"]]},  # noqa: E731
                                  headers={**bearer(token), "Origin": HOME}).json()["jobs"][0]["status"]
        until(lambda: status() == "done")  # a worker of the server's own made it
    assert jobs.threads == [] and store.held is None  # stopped, and the database let go


def test_the_api_does_not_start_without_its_token_key(monkeypatch):
    def no_key(log_to=None):
        raise OSError("the key can be neither read nor made")
    monkeypatch.delenv("OLMUSE_API_ORIGINS", raising=False)
    monkeypatch.setattr(asset_api.server_ops, "setup_logging", lambda folder: None)
    monkeypatch.setattr(asset_api, "real_deps", no_key)
    with pytest.raises(OSError):
        with TestClient(asset_api.create_app(), base_url=BASE):
            pass


# ---------- the checks and their order ----------
def test_everything_but_health_needs_a_token(bench):
    b = bench()
    for path in (QUOTE, f"/jobs/{MISSING}/sound", f"/jobs/{MISSING}/stems/1", "/nothing"):
        assert refused(b.get(path)) == (401, "no_token", {})
    for path in ("/jobs", "/jobs/status", "/jobs/cancel"):
        assert refused(b.post(path, {})) == (401, "no_token", {})
    for path in ("/", "/docs", "/redoc", "/openapi.json"):  # outside the prefix: the same door, and no docs behind it
        assert refused(b.web.get(path)) == (401, "no_token", {})
    assert b.get(QUOTE).json()["error"]["message"] == aj.message("en", "no_token")
    good = b.token()
    assert refused(b.web.get("/openapi.json", headers=bearer(good))) == (404, "not_found", {})
    assert refused(b.get("/jobs", good)) == (404, "not_found", {})  # a GET where only POST is
    for method in ("PUT", "DELETE", "TRACE", "BREW"):  # a method nothing takes: the same door
        assert refused(b.web.request(method, API + "/jobs")) == (401, "no_token", {})
        assert refused(b.web.request(method, API + "/jobs", headers=bearer(good))) == (404, "not_found", {})
        assert refused(b.web.request(method, API + "/health", headers={"Host": "evil.example"})) == (403, "bad_host", {})
    assert refused(b.get(QUOTE, headers={"Authorization": "Basic " + good})) == (401, "no_token", {})
    assert refused(b.get(QUOTE, "not-a-token")) == (401, "bad_token", {})
    assert refused(b.get(QUOTE, good[:-2])) == (401, "bad_token", {})
    assert refused(b.get(QUOTE, b.token(secret=b"x" * 32))) == (401, "bad_token", {})  # signed with another key
    b.now[0] += asset_token.TTL
    assert refused(b.get(QUOTE, good)) == (401, "token_expired", {})
    assert b.get(QUOTE, b.token()).status_code == 200


def test_host_comes_first_then_a_posts_origin_then_the_declared_length_then_the_token(bench):
    b = bench()
    good, big = b.token(), {"Content-Length": str(asset_api.MAX_BODY + 1)}
    assert refused(b.post("/jobs", {}, origin="https://evil.example", headers={"Host": "evil.example", **big})) == (403, "bad_host", {})
    assert refused(b.post("/jobs", {}, origin="https://evil.example", headers=big)) == (403, "bad_origin", {})
    assert refused(b.post("/jobs", {}, headers=big)) == (413, "too_large", {})  # no token, and the length is judged first
    assert refused(b.post("/jobs", {})) == (401, "no_token", {})
    assert refused(b.post("/jobs", {}, good)) == (400, "bad_request", {"field": "expect_credits"})
    # A good token does not open a wrong Host or a wrong Origin.
    for host in ("evil.example", "olmuse.app:8502", "127.0.0.1:8501", "olmuse.app.evil.example", ""):
        assert refused(b.get(QUOTE, good, headers={"Host": host})) == (403, "bad_host", {})
    for host in ("olmuse.app", "OLMUSE.APP", "localhost:8502", "127.0.0.1:8502"):
        assert b.get(QUOTE, good, headers={"Host": host}).status_code == 200
    for origin in ("https://evil.example", "http://olmuse.app", "https://olmuse.app.evil.example", "null", ""):
        assert refused(b.post("/jobs/status", {"ids": []}, good, origin=origin)) == (403, "bad_origin", {})  # "" sends none
    assert b.post("/jobs/status", {"ids": []}, good).status_code == 200
    assert b.get(QUOTE, good, headers={"Origin": "https://evil.example"}).status_code == 200  # only a POST's Origin is judged
    assert b.api.rates.times.get(("anon", "127.0.0.1")) is not None and len(b.api.rates.times[("anon", "127.0.0.1")]) == 1
    assert asset_api.BODY_SECONDS == 30 and asset_api.HEALTH_THREADS == 2 and asset_api.LEDGER_LANE == (8, 32)


def test_a_refusal_before_the_token_is_judged_is_still_worded_in_the_tokens_language(bench):
    b = bench()
    ko, big = b.token(lang="ko"), {"Content-Length": str(asset_api.MAX_BODY + 1)}
    for sent, code in ((b.post("/jobs", {}, ko, headers=big), "too_large"),            # the declared length
                       (b.post("/jobs", {}, ko, origin="https://evil.example"), "bad_origin"),
                       (b.get(QUOTE, ko, headers={"Host": "evil.example"}), "bad_host"),
                       (b.get("/health", ko, headers={"Host": "evil.example"}), "bad_host")):
        assert sent.json()["error"] == {"code": code, "message": aj.message("ko", code)}
    assert aj.message("ko", "too_large") != aj.message("en", "too_large")
    # The same refusals without a token of ours are in the default language, and looking counts nothing.
    for token in ("", "not-a-token", ko[:-2], b.token(lang="ko", secret=b"x" * 32)):
        sent = b.post("/jobs", {}, token, headers=big)
        assert sent.json()["error"] == {"code": "too_large", "message": aj.message("en", "too_large")}
    assert b.api.rates.times == {}  # no try was counted, by address or by owner
    b.now[0] += asset_token.TTL  # a token that ran out still says which language its holder reads
    assert b.get(QUOTE, ko).json()["error"] == {"code": "token_expired", "message": aj.message("ko", "token_expired")}
    assert b.post("/jobs", {}, ko, headers=big).json()["error"]["message"] == aj.message("ko", "too_large")
    assert list(b.api.rates.times) == [("anon", "127.0.0.1")] and len(b.api.rates.times[("anon", "127.0.0.1")]) == 1


def test_a_body_that_does_not_come_is_not_waited_for_without_end(bench, monkeypatch):
    b = bench()
    a = {**bearer(b.token(lang="ko")), "Origin": HOME}
    monkeypatch.setattr(asset_api, "BODY_SECONDS", 0.05)

    async def never():  # the headers came; the body does not
        await asyncio.Event().wait()
        yield b""

    async def ask():
        transport = httpx.ASGITransport(app=b.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as web:
            stalled = await asyncio.wait_for(web.post(API + "/jobs/status", content=never(), headers=a), 5)
            return stalled, await asyncio.wait_for(web.post(API + "/jobs/status", json={"ids": []}, headers=a), 5)
    stalled, after = asyncio.run(ask())
    assert refused(stalled) == (400, "bad_request", {"field": ""}) and stalled.headers["connection"] == "close"
    assert stalled.json()["error"]["message"] == aj.message("ko", "bad_request")
    assert after.status_code == 200 and "connection" not in after.headers
    assert len(b.api.rates.times[("status", "acct:" + b.ledger.key_of("a@b.c"))]) == 2  # it was counted before the wait


def test_a_body_over_the_cap_is_413_declared_or_not_and_the_rest_must_be_a_json_object(bench):
    b = bench()
    good = b.token()
    over = b"[" + b" " * asset_api.MAX_BODY
    assert asset_api.MAX_BODY == 1_600_000 and len(over) == asset_api.MAX_BODY + 1
    assert refused(b.post("/jobs", token=good, content=over)) == (413, "too_large", {})

    def pieces():  # no Content-Length: the cap is met while reading
        for _ in range(17):
            yield b" " * 100_000
    sent = b.post("/jobs", token=good, content=pieces())
    assert "content-length" not in sent.request.headers and refused(sent) == (413, "too_large", {})
    full = b" " * (asset_api.MAX_BODY - 2) + b"[]"  # as long as a body may be: read, and then not an object
    assert refused(b.post("/jobs", token=good, content=full)) == (400, "bad_request", {"field": ""})
    for raw in (b"", b"{", b"[1]", b'"x"', b"null", b"7", b"\xff\xfe{}", b"[" * 5000 + b"]" * 5000, b'{"a":' + b"9" * 5000 + b"}"):
        assert refused(b.post("/jobs/status", token=good, content=raw)) == (400, "bad_request", {"field": ""})
    assert b.post("/jobs/status", token=good, content=b' {"ids": []} ').status_code == 200


def test_the_61st_failed_try_of_an_address_is_429_and_a_good_token_is_never_counted_by_address(bench):
    b = bench()
    visitor = {"CF-Connecting-IP": "203.0.113.7"}
    for _ in range(asset_api.ANON_RATE):
        assert refused(b.get(QUOTE, "bad", headers=visitor)) == (401, "bad_token", {})
    late = b.get(QUOTE, "bad", headers=visitor)
    assert asset_api.ANON_RATE == 60 and refused(late) == (429, "rate", {"retry_after": 60}) and late.headers["retry-after"] == "60"
    assert refused(b.post("/jobs", {}, headers=visitor))[:2] == (429, "rate")  # no token at all is the same failure
    assert refused(b.get(QUOTE, "bad", headers={"CF-Connecting-IP": "203.0.113.8"})) == (401, "bad_token", {})  # another address
    good = b.token()
    for _ in range(asset_api.ANON_RATE + 5):  # from the address that is shut out, with a good token
        assert b.post("/jobs/status", {"ids": []}, good, headers=visitor).status_code == 200
    assert len(b.api.rates.times[("anon", "203.0.113.7")]) == 60
    b.now[0] += 59
    assert refused(b.get(QUOTE, "bad", headers=visitor)) == (429, "rate", {"retry_after": 1})
    b.now[0] += 1
    assert refused(b.get(QUOTE, "bad", headers=visitor)) == (401, "bad_token", {})


def test_each_owner_has_its_own_requests_a_minute(bench):
    b = bench()
    a, other = b.token("a@b.c", lang="ko"), b.token("z@b.c")
    assert asset_api.RATES == {"make": 10, "quote": 30, "status": 120, "sound": 600}
    for _ in range(5):  # making and cancelling are one count, and a refused request is counted too
        assert b.post("/jobs", {}, a).status_code == 400
        assert b.post("/jobs/cancel", {"ids": []}, a).status_code == 200
    late = b.post("/jobs", body(), a)
    assert refused(late) == (429, "rate", {"retry_after": 60}) and late.headers["retry-after"] == "60"
    assert late.json()["error"]["message"] == aj.message("ko", "rate")  # worded in the token's language
    assert refused(b.post("/jobs/cancel", {"ids": []}, a))[:2] == (429, "rate")
    assert b.post("/jobs", body(), other).status_code == 200  # another owner
    for path, limit in ((QUOTE, 30), (f"/jobs/{MISSING}/sound", 300), (f"/jobs/{MISSING}/stems/1", 300)):
        codes = {b.get(path, a).status_code for _ in range(limit)}
        assert codes <= {200, 404}
    assert refused(b.get(QUOTE, a))[:2] == (429, "rate")
    assert refused(b.get(f"/jobs/{MISSING}/sound", a))[:2] == refused(b.get(f"/jobs/{MISSING}/stems/1", a))[:2] == (429, "rate")
    for _ in range(120):
        assert b.post("/jobs/status", {"ids": []}, a).status_code == 200
    assert refused(b.post("/jobs/status", {"request_id": "r1"}, a))[:2] == (429, "rate")
    assert b.get(QUOTE, other).status_code == 200
    b.now[0] += 60
    assert b.post("/jobs", body(), a).status_code == 200 and b.get(QUOTE, a).status_code == 200


def test_request_counts_forget_the_keys_nobody_uses():
    now = [0.0]
    rates = asset_api.Rates(lambda: now[0])
    assert [rates.wait(("x", i), 1) for i in range(3)] == [0, 0, 0] and rates.wait(("x", 0), 1) == 60
    now[0] = 30.5
    assert rates.wait(("x", 0), 1) == 30 and len(rates.times[("x", 0)]) == 1  # a request turned away is not counted
    now[0] = 61.0
    assert rates.wait(("y", 0), 1) == 0 and list(rates.times) == [("y", 0)]


def test_a_request_counted_under_two_keys_is_counted_in_both_or_in_neither():
    now = [0.0]
    rates = asset_api.Rates(lambda: now[0])
    shared = (("address", 0), 2)
    assert rates.wait(("session", 1), 1, shared) == 0 and rates.wait(("session", 2), 1, shared) == 0
    now[0] = 10.0
    assert rates.wait(("session", 3), 1, shared) == 50 and ("session", 3) not in rates.times  # the shared count is full
    assert rates.wait(("session", 1), 1, (("other", 0), 2)) == 50 and ("other", 0) not in rates.times  # its own count is
    assert [len(times) for times in rates.times.values()] == [1, 2, 1]
    now[0] = 60.0
    assert rates.wait(("session", 3), 1, shared) == 0 and len(rates.times[("address", 0)]) == 1


def test_one_sessions_stopped_sounds_do_not_close_the_door_on_its_classroom(bench):
    """Through the API as the page uses it. Thirteen drafts of one session end with nothing to keep, which passes
    that session's refund limit. Another session at the same address is still taken: the session comes from the
    token's sub, and the address's own count is wider."""
    b = bench()
    room = {"CF-Connecting-IP": "198.51.100.4"}
    one, two = b.token(sub="pw:student-a"), b.token(sub="pw:student-b")
    b.jobs.engine.script += [nkido.RenderError("compile", "bad", 1) for _ in range(3 * 13)]
    ids = b.make(one, headers=room, items=13, credits=0)
    assert b.jobs.drain() == 13 and {view["status"] for view in b.views(one, ids, headers=room)} == {"failed"}
    turned = b.post("/jobs", body("r2", credits=0), one, headers=room)
    assert refused(turned) == (429, "refund_limit", {"retry_after": 3601}) and turned.headers["retry-after"] == "3601"
    assert turned.json()["error"]["message"] == "Too many sounds were stopped or returned."
    assert b.get(QUOTE, one, headers=room).json()["reason"] == "refund_limit"
    assert b.get(QUOTE, two, headers=room).json()["ok"] is True
    assert len(b.make(two, headers=room, rid="r3", credits=0)) == 1
    owner = asset_token.owner_of({"kind": "pw"}, SECRET, "198.51.100.4")
    assert b.jobs.count("rf:" + owner) == 13 and aj.REFUND_HOURLY == 12 < aj.Limits().pw_refund_hourly


def test_thirty_password_sessions_at_one_address_each_start_a_sound_in_the_same_minute(bench):
    """A classroom: one address, so one owner, and thirty sessions. Requests a minute are counted by the session
    (the token's sub) and, six times as many, by the owner. The daily count is the owner's alone."""
    b = bench(limits=aj.Limits(pw_daily=40))
    room, elsewhere = {"CF-Connecting-IP": "198.51.100.4"}, {"CF-Connecting-IP": "198.51.100.99"}
    owner = asset_token.owner_of({"kind": "pw"}, SECRET, "198.51.100.4")
    students, made = [b.token(sub=f"pw:student{i}") for i in range(30)], []
    for i, student in enumerate(students):
        b.now[0] += 1  # thirty seconds for all of them
        made += b.make(student, headers=room, rid=f"r{i}", credits=0)
        assert b.views(student, made[-1:], headers=room)[0]["status"] == "queued"
    assert len(set(made)) == 30 and {b.row(job_id)["owner"] for job_id in made} == {owner}
    counted = lambda bucket, key: len(b.api.rates.times[(bucket, key)])  # noqa: E731
    assert (counted("make", "pw:student0"), counted("make", owner)) == (1, 30)
    assert (counted("status", "pw:student0"), counted("status", owner)) == (1, 30)

    # A session has ten of its own a minute, whatever the others at its address have used.
    for _ in range(9):
        assert b.post("/jobs/cancel", {"ids": []}, students[0], headers=room).status_code == 200
    assert refused(b.post("/jobs/cancel", {"ids": []}, students[0], headers=room)) == (429, "rate", {"retry_after": 31})
    assert b.post("/jobs/cancel", {"ids": []}, students[1], headers=room).status_code == 200
    # The address has six times that for all its sessions together: a reload is a new session.
    assert asset_api.PW_ADDRESS_TIMES == 6 and counted("make", owner) == 40
    for i in range(20):
        assert b.post("/jobs/cancel", {"ids": []}, b.token(sub=f"pw:reload{i}"), headers=room).status_code == 200
    fresh = b.token(sub="pw:fresh")
    assert refused(b.post("/jobs", body("r-fresh", credits=0), fresh, headers=room)) == (429, "rate", {"retry_after": 31})
    assert ("make", "pw:fresh") not in b.api.rates.times and counted("make", owner) == 60  # turned away: counted nowhere
    assert b.post("/jobs/cancel", {"ids": []}, fresh, headers=elsewhere).status_code == 200  # the same session at another address
    assert b.post("/jobs/cancel", {"ids": []}, b.token(), headers=room).status_code == 200  # an account at that address: its own

    # The drafts of a day are still the address's: thirty were made, ten more fit, and a new session does not add any.
    assert b.jobs.drain() == 30 and (b.jobs.count("d:" + owner), b.jobs.count("d:teachers")) == (30, 30)
    b.now[0] += 60
    for i in range(10):
        b.make(students[i], headers=room, rid=f"again{i}", credits=0)
    late = b.post("/jobs", body("r-late", credits=0), b.token(sub="pw:late"), headers=room)
    assert refused(late)[:2] == (429, "session_limit") and late.json()["error"]["left_today"] == 0
    assert b.ledger.calls == []  # a password session pays nothing and the ledger is never asked


def test_quote_reads_two_counts_from_the_address(bench):
    b = bench()
    a = b.token(lang="ko")
    assert b.get("/quote?items=3&drafts=2", a).json() == {
        "items": 3, "drafts": 2, "unit": 1, "credits": 6, "free": False, "balance": 20, "left_today": 200, "room": 64,
        "ok": True, "reason": None}
    for query, field in (("", "items"), ("?items=3", "drafts"), ("?items=0&drafts=1", "items"), ("?items=65&drafts=1", "items"),
                         ("?items=1&drafts=5", "drafts"), ("?items=1.5&drafts=1", "items"), ("?items=-1&drafts=1", "items"),
                         ("?items=two&drafts=1", "items")):
        got = b.get("/quote" + query, a)
        assert refused(got) == (400, "bad_request", {"field": field})
        assert got.json()["error"]["message"] == aj.message("ko", "bad_request")
    free = b.get("/quote?items=64&drafts=4", b.token(sub="pw:s")).json()
    assert (free["free"], free["unit"], free["credits"], free["balance"]) == (True, 0, 0, None)
    assert (free["ok"], free["reason"]) == (False, "session_limit")  # 256 drafts are more than a day's 120


# ---------- from a request to its sound ----------
def test_from_a_request_to_its_sound_and_its_stems(bench):
    b = bench()
    a = b.token()
    sent = body(items=MUSIC, drafts=2)
    made = b.post("/jobs", sent, a)
    got = made.json()
    assert made.status_code == 200 and made.headers["cache-control"] == "no-store"
    assert sorted(got) == ["batch", "jobs", "quote", "replayed"] and got["replayed"] is False
    assert got["quote"] == {"items": 1, "drafts": 2, "unit": 1, "credits": 2, "free": False}
    assert [sorted(job) for job in got["jobs"]] == [["id", "k", "n", "ref", "status"]] * 2
    assert [(job["ref"], job["k"], job["n"], job["status"]) for job in got["jobs"]] == [("k0", 1, 2, "queued"), ("k0", 2, 2, "queued")]
    ids = [job["id"] for job in got["jobs"]]
    assert all(re.fullmatch("[0-9a-f]{32}", job_id) for job_id in ids)
    assert b.post("/jobs", sent, a).json() == {**got, "replayed": True}  # the same request again makes nothing
    assert b.get("/health").json()["queued"] == 2

    waiting = b.post("/jobs/status", {"ids": ids}, a).json()
    assert waiting["credits"] == 20 and [(v["status"], v["position"], v["progress"]) for v in waiting["jobs"]] == [
        ("queued", 1, 0.0), ("queued", 2, 0.0)]
    assert refused(b.get(f"/jobs/{ids[0]}/sound", a)) == (409, "not_ready", {})
    assert b.jobs.drain() == 2 and b.ledger.calls == ["account", "charge", "charge"]

    done = b.post("/jobs/status", {"ids": ids}, a).json()
    view = done["jobs"][0]
    assert done["credits"] == 18 and (view["status"], view["refund"], view["progress"], view["batch"]) == ("done", "none", 1.0, got["batch"])
    result = view["result"]
    assert sorted(result) == ["bits", "bytes", "channels", "rate", "seconds", "sha256", "stems"]  # no source, no prompt yet
    assert [sorted(stem) for stem in result["stems"]] == [["bytes", "n", "sha256"]] * 2 and result["rate"] == 48000

    heard = b.get(f"/jobs/{ids[0]}/sound", a, headers={"Range": "bytes=0-99"})  # a Range changes nothing
    assert heard.status_code == 200 and len(heard.content) == result["bytes"] and sha(heard.content) == result["sha256"]
    assert heard.headers["content-type"] == "audio/wav" and heard.headers["etag"] == result["sha256"]
    assert heard.headers["x-content-type-options"] == "nosniff" and heard.headers["cache-control"] == "no-store"
    assert heard.headers["content-length"] == str(result["bytes"])
    assert "accept-ranges" not in heard.headers and "content-range" not in heard.headers
    with wave.open(io.BytesIO(heard.content)) as w:
        assert w.getframerate() == 48000 and w.getnframes() == 48000
    assert b.row(ids[0])["charge"] == "kept" and b.row(ids[1])["charge"] == "charged"

    first, second = (v["result"] for v in b.views(a, ids))
    assert set(first) - set(result) == {"engine", "model", "prompt", "source", "bpm", "measure", "issues", "repairs", "sources"}
    assert first["engine"] == "nkido" and "bus(1" in first["source"] and ag.OPEN in first["prompt"]
    assert [stem["label"] for stem in first["stems"]] == ["melody", "bass"]
    assert "source" not in second and "prompt" not in second and "label" not in second["stems"][0]  # that one was not received

    for stem in result["stems"]:
        part = b.get(f"/jobs/{ids[0]}/stems/{stem['n']}", a, headers={"Range": "bytes=10-"})
        assert part.status_code == 200 and sha(part.content) == stem["sha256"] == part.headers["etag"]
        assert part.headers["content-type"] == "audio/wav" and len(part.content) == stem["bytes"]
        assert "accept-ranges" not in part.headers
    for n in ("3", "0", "one", "1.0", "-1", "100"):
        assert refused(b.get(f"/jobs/{ids[0]}/stems/{n}", a)) == (404, "not_found", {})
    assert b.get(f"/jobs/{ids[0]}/sound", a).content == heard.content  # received again, as often as wanted until it expires
    assert b.get(f"/jobs/{ids[0]}/sound?id={ids[1]}", a).content == heard.content  # the path names the job, not the query
    assert b.row(ids[1])["delivered"] is None and b.ledger.calls == ["account", "charge", "charge"]

    # A cancel that comes after the end changes nothing: both drafts stay, the received one and the other.
    out = b.post("/jobs/cancel", {"ids": ids}, a).json()["jobs"]
    assert [(v["id"], v["status"], v["refund"]) for v in out] == [(ids[0], "done", "none"), (ids[1], "done", "none")]
    assert "source" in out[0]["result"] and "source" not in out[1]["result"]
    assert [b.row(i)["charge"] for i in ids] == ["kept", "charged"] and "refund" not in b.ledger.calls


def test_a_cancel_while_a_draft_is_being_made_is_refunded_by_its_worker(bench):
    b = bench()
    a = b.token()
    ids = b.make(a)

    def cancelled_meanwhile(prompt):  # the cancel arrives while the model is writing
        seen.append(b.post("/jobs/cancel", {"ids": ids}, a).json()["jobs"][0])
        return ag.FakeModel.patch_for(prompt)
    seen = []
    b.model.script.append(cancelled_meanwhile)
    assert b.jobs.drain() == 1
    assert (seen[0]["status"], seen[0]["refund"]) == ("cancelled", "pending")  # shown as cancelled at once
    view = b.views(a, ids)[0]
    assert (view["status"], view["refund"]) == ("cancelled", "done") and "result" not in view
    assert b.ledger.calls == ["account", "charge", "refund"] and b.post("/jobs/status", {"ids": ids}, a).json()["credits"] == 20
    assert refused(b.get(f"/jobs/{ids[0]}/sound", a)) == (404, "not_found", {})
    b = bench()
    a = b.token()
    ids = b.make(a, items=MUSIC)
    b.jobs.drain()
    assert "source" not in b.views(a, ids)[0]["result"] and b.row(ids[0])["delivered"] is None
    for path in (f"/jobs/{ids[0]}/sound", f"/jobs/{ids[0]}/stems/2"):  # a HEAD gets no sound, so it receives nothing
        assert b.web.head(API + path, headers=bearer(a)).status_code == 404
    assert b.row(ids[0])["delivered"] is None and b.row(ids[0])["charge"] == "charged"
    assert b.get(f"/jobs/{ids[0]}/stems/2", a).status_code == 200
    assert b.row(ids[0])["delivered"] == T0 and b.row(ids[0])["charge"] == "kept"
    assert "bus(2" in b.views(a, ids)[0]["result"]["source"]


def test_the_result_is_marked_received_before_a_byte_of_it_is_read(bench, monkeypatch):
    b = bench()
    a = b.token()
    ids = b.make(a)
    b.jobs.drain()
    seen = []

    def read(sound):
        seen.append(b.row(ids[0])["delivered"])
        raise FileNotFoundError("the file went away")
    monkeypatch.setattr(aj.Sound, "read", read)
    assert refused(b.get(f"/jobs/{ids[0]}/sound", a)) == (404, "not_found", {})
    assert seen == [T0] and b.row(ids[0])["charge"] == "kept"  # no refund for a sound that started to go out


def test_a_result_file_that_cannot_be_read_right_now_is_a_503_to_try_again_not_a_404(bench, monkeypatch):
    b = bench()
    a = b.token(lang="ko")
    ids = b.make(a, items=MUSIC)
    b.jobs.drain()
    real, fails, slept = aj.Sound.read, [], []
    b.api.sleep = slept.append

    def held(sound):  # another program has the file for a moment (on Windows: a sharing violation)
        if fails:
            raise fails.pop()
        return real(sound)
    monkeypatch.setattr(aj.Sound, "read", held)
    for path in (f"/jobs/{ids[0]}/sound", f"/jobs/{ids[0]}/stems/1"):
        fails[:] = [PermissionError(13, "sharing violation"), PermissionError(13, "sharing violation")]
        late = b.get(path, a)
        assert refused(late) == (503, "busy", {"retry_after": asset_api.READ_RETRY}) and late.headers["retry-after"] == "2"
        assert late.json()["error"]["message"] == aj.message("ko", "busy") and fails == []
        row = b.row(ids[0])  # received as far as the charge goes, and still there to be received
        assert (row["status"], row["charge"], row["delivered"]) == ("done", "kept", T0)
        fails[:] = [PermissionError(13, "sharing violation")]  # once: the second read gets it
        assert b.get(path, a).status_code == 200 and fails == []
    assert slept == [asset_api.READ_PAUSE] * 4 and "refund" not in b.ledger.calls
    assert sha(b.get(f"/jobs/{ids[0]}/sound", a).content) == b.views(a, ids)[0]["result"]["sha256"]


def test_another_accounts_job_is_forbidden_and_a_missing_one_unknown(bench):
    b = bench()
    a, z, pw = b.token("a@b.c"), b.token("z@b.c"), b.token(sub="pw:s")
    ids = b.make(a, items=MUSIC)
    b.jobs.drain()
    for stranger in (z, pw):
        assert b.views(stranger, [ids[0], MISSING]) == [{"id": ids[0], "status": "forbidden", "refund": "none"},
                                                        {"id": MISSING, "status": "unknown", "refund": "none"}]
        assert refused(b.get(f"/jobs/{ids[0]}/sound", stranger)) == (403, "forbidden", {})
        assert refused(b.get(f"/jobs/{ids[0]}/stems/1", stranger)) == (403, "forbidden", {})
        assert refused(b.get(f"/jobs/{MISSING}/sound", stranger)) == (404, "not_found", {})
        assert b.post("/jobs/cancel", {"ids": ids}, stranger).json() == {"jobs": [{"id": ids[0], "status": "forbidden", "refund": "none"}]}
        assert b.post("/jobs/status", {"request_id": "r1"}, stranger).json() == {"known": False, "cancelled": False, "jobs": []}
    row = b.row(ids[0])
    assert (row["status"], row["delivered"], row["cancel"]) == ("done", None, 0)  # nothing of it was touched
    assert b.views(a, ids)[0]["status"] == "done"


def test_a_second_password_token_reaches_a_password_job(bench):
    b = bench()
    one, two = b.token(sub="pw:first"), b.token(sub="pw:second")
    room, elsewhere = {"CF-Connecting-IP": "198.51.100.4"}, {"CF-Connecting-IP": "198.51.100.99"}
    owner = asset_token.owner_of({"kind": "pw"}, SECRET, "198.51.100.4")
    ids = b.make(one, headers=room, items=MUSIC, credits=0)
    more = b.make(two, headers=room, rid="r2", credits=0)       # another session at the same address
    far = b.make(two, headers=elsewhere, rid="r3", credits=0)   # the same session at another address
    assert owner.startswith("pwip:") and b.row(ids[0])["owner"] == b.row(more[0])["owner"] == owner
    assert b.row(far[0])["owner"] == asset_token.owner_of({"kind": "pw"}, SECRET, "198.51.100.99") != owner
    assert b.jobs.drain() == 3 and b.jobs.count("d:" + owner) == 2  # one classroom, one count
    view = b.views(two, ids, headers=elsewhere)[0]  # whoever holds a password token and knows the id
    assert view["status"] == "done" and "source" not in view["result"]
    assert b.get(f"/jobs/{ids[0]}/sound", two, headers=elsewhere).status_code == 200
    assert "source" in b.views(one, ids, headers=room)[0]["result"]
    assert b.post("/jobs/cancel", {"ids": ids}, two, headers=elsewhere).json()["jobs"][0]["status"] == "done"
    assert b.views(b.token(), ids)[0]["status"] == "forbidden"  # an account is not a password session
    assert b.ledger.calls == []  # a password session pays nothing and the ledger is never asked


def test_the_visitor_header_is_believed_only_from_the_tunnel(bench):
    b = bench()
    token, told = b.token(sub="pw:s"), {"CF-Connecting-IP": "198.51.100.4"}
    owner = lambda ip: asset_token.owner_of({"kind": "pw"}, SECRET, ip)  # noqa: E731
    direct = b.client("10.0.0.9")
    assert b.row(b.make(token, headers=told, web=direct, credits=0)[0])["owner"] == owner("10.0.0.9")  # not the tunnel: not believed
    assert b.row(b.make(token, rid="r2", credits=0)[0])["owner"] == owner("127.0.0.1")  # a local run has no tunnel in front
    assert b.row(b.make(token, headers=told, rid="r3", credits=0)[0])["owner"] == owner("198.51.100.4")
    assert refused(b.get(QUOTE, "bad", headers=told, web=direct))[:2] == (401, "bad_token")
    assert list(b.api.rates.times) == [("make", "pw:s"), ("make", owner("10.0.0.9")), ("make", owner("127.0.0.1")),
                                       ("make", owner("198.51.100.4")), ("anon", "10.0.0.9")]


def test_an_ipv6_address_counts_as_its_64(bench):
    assert [asset_api.net(ip) for ip in ("203.0.113.7", "2001:db8:1:2::77", "2001:DB8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:3::77",
                                         "::ffff:203.0.113.7", "fe80::1%eth0", "", "not an address")] == [
        "203.0.113.7", "2001:db8:1:2::/64", "2001:db8:1:2::/64", "2001:db8:1:3::/64", "203.0.113.7", "fe80::/64", "", "not an address"]
    b = bench()
    owner = asset_token.owner_of({"kind": "pw"}, SECRET, "2001:db8:1:2::/64")
    made = [b.make(b.token(sub=f"pw:s{i}"), headers={"CF-Connecting-IP": f"2001:db8:1:2::{i:x}"}, rid=f"r{i}", credits=0)[0]
            for i in range(1, 61)]
    assert {b.row(job_id)["owner"] for job_id in made} == {owner}  # sixty addresses of one line: one owner, one count
    token = b.token(sub="pw:s61")  # a session that has asked nothing yet: what turns it away is the count of its line
    late = b.post("/jobs", body("r61", credits=0), token, headers={"CF-Connecting-IP": "2001:db8:1:2:aaaa::1"})
    assert refused(late)[:2] == (429, "rate")
    assert b.post("/jobs", body("r62", credits=0), token, headers={"CF-Connecting-IP": "2001:db8:1:3::1"}).status_code == 200
    for i in range(asset_api.ANON_RATE):  # and the failed tries of one line are one count as well
        assert refused(b.get(QUOTE, "bad", headers={"CF-Connecting-IP": f"2001:db8:9:9::{i:x}"}))[:2] == (401, "bad_token")
    assert refused(b.get(QUOTE, "bad", headers={"CF-Connecting-IP": "2001:db8:9:9:ffff::1"}))[:2] == (429, "rate")


# ---------- what a request is refused for ----------
def test_expect_credits_missing_is_400_and_another_number_is_409(bench):
    b = bench()
    a = b.token()
    sent = body(items=2)
    del sent["expect_credits"]
    assert refused(b.post("/jobs", sent, a)) == (400, "bad_request", {"field": "expect_credits"})
    price = {"items": 2, "drafts": 1, "unit": 1, "credits": 2, "free": False}
    assert refused(b.post("/jobs", body(items=2, credits=3), a)) == (409, "quote_changed", {"quote": price})
    assert refused(b.post("/jobs", body(items=2, credits=0), a)) == (409, "quote_changed", {"quote": price})  # 0 against a price
    pw = b.token(sub="pw:s")
    assert refused(b.post("/jobs", body(items=2), pw)) == (409, "quote_changed", {"quote": {**price, "unit": 0, "credits": 0, "free": True}})
    assert b.get("/health").json()["queued"] == 0 and b.ledger.calls == [] and b.model.prompts == []


def test_no_credits_is_402_and_nothing_is_made(bench):
    b = bench(free=1)
    a = b.token()
    assert refused(b.post("/jobs", body(items=2), a)) == (402, "no_credits", {"balance": 1, "credits": 2})
    quote = b.get("/quote?items=2&drafts=1", a).json()
    assert (quote["ok"], quote["reason"], quote["balance"], quote["credits"]) == (False, "no_credits", 1, 2)
    assert b.get("/health").json()["queued"] == 0 and b.ledger.calls == ["account"] and b.jobs.drain() == 0
    assert b.post("/jobs", body(items=1), a).status_code == 200  # all or nothing: one draft is within the balance


def test_a_daily_limit_is_a_429_with_its_retry_after_as_a_header_too(bench):
    b = bench(limits=aj.Limits(account_daily=1))
    a = b.token(lang="ko")
    late = b.post("/jobs", body(items=2), a)
    status, code, extras = refused(late)
    assert (status, code, extras) == (429, "account_limit", {"left_today": 1, "retry_after": 43_201})  # from noon to the next day
    assert late.headers["retry-after"] == "43201" and late.json()["error"]["message"] == aj.message("ko", "account_limit", n=1)
    assert b.post("/jobs", body(items=1), a).status_code == 200 and b.get("/health").json()["queued"] == 1


def test_a_slow_ledger_keeps_only_its_own_request_waiting(bench):
    b = bench()
    entered, gate, real = threading.Event(), threading.Event(), b.ledger.account

    def slow(email):
        if email == "a@b.c":
            entered.set()
            gate.wait(10)
        return real(email)
    b.ledger.account = slow
    a, z = {**bearer(b.token("a@b.c")), "Origin": HOME}, {**bearer(b.token("z@b.c")), "Origin": HOME}

    async def both():  # one event loop, as in the server: a request that waits must not hold the loop
        transport = httpx.ASGITransport(app=b.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as web:
            held = asyncio.create_task(web.post(API + "/jobs", json=body(), headers=a))
            assert await asyncio.to_thread(entered.wait, 5)  # the account's request is inside the ledger call now
            quick = [await asyncio.wait_for(web.post(API + "/jobs", json=body(), headers=z), 5),
                     await asyncio.wait_for(web.post(API + "/jobs/status", json={"request_id": "r1"}, headers=z), 5),
                     await asyncio.wait_for(web.get(API + "/health"), 5)]
            still_waiting = not held.done()
            gate.set()
            return still_waiting, await asyncio.wait_for(held, 5), quick
    try:
        still_waiting, held, quick = asyncio.run(both())
    finally:
        gate.set()
    assert still_waiting and held.status_code == 200 and [got.status_code for got in quick] == [200, 200, 200]
    assert quick[2].json()["queued"] == 1 and b.get("/health").json()["queued"] == 2


def test_requests_that_wait_for_the_ledger_leave_the_threads_of_everything_else_alone(bench):
    b = bench()
    fast, pw = b.token("fast@b.c"), b.token(sub="pw:s")
    ids = b.make(fast, items=MUSIC)
    b.jobs.drain()
    threads, waiting = asset_api.LEDGER_LANE
    slow = [b.token(f"slow{i}@b.c") for i in range(threads + waiting + 1)]  # more than the server's 40 shared threads
    gate, real, inside = threading.Event(), b.ledger.account, []

    def stuck(email):  # the ledger answers nobody until the gate opens
        if email.startswith("slow"):
            inside.append(email)
            gate.wait(20)
        return real(email)
    b.ledger.account = stuck
    post = {**bearer(fast), "Origin": HOME}

    async def ask():
        transport = httpx.ASGITransport(app=b.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as web:
            held = [asyncio.create_task(web.get(API + QUOTE, headers=bearer(token))) for token in slow[:-1]]
            await asyncio.to_thread(until, lambda: len(inside) == threads)  # every thread of the lane is in the ledger
            await asyncio.sleep(0.05)
            quick = [await asyncio.wait_for(call, 5) for call in (
                web.get(API + "/health"),
                web.post(API + "/jobs/status", json={"ids": ids}, headers=post),
                web.get(API + f"/jobs/{ids[0]}/sound", headers=bearer(fast)),
                web.get(API + f"/jobs/{ids[0]}/stems/1", headers=bearer(fast)),
                web.post(API + "/jobs/cancel", json={"ids": ids}, headers=post),
                web.get(API + QUOTE, headers=bearer(pw)),  # a password session's quote asks no ledger
                web.post(API + "/jobs", json=body("r2", credits=0), headers={**bearer(pw), "Origin": HOME}))]
            full = await asyncio.wait_for(web.get(API + QUOTE, headers=bearer(slow[-1])), 5)  # the line is full: at once
            none_done = not any(task.done() for task in held)
            gate.set()
            return quick, full, none_done, await asyncio.wait_for(asyncio.gather(*held), 20)
    try:
        quick, full, none_done, held = asyncio.run(ask())
    finally:
        gate.set()
    assert [got.status_code for got in quick] == [200] * 7 and none_done and len(inside) >= threads
    assert refused(full) == (503, "busy", {})
    assert {got.status_code for got in held} == {200} and len(held) == threads + waiting
    assert b.get(QUOTE, slow[-1]).status_code == 200  # and there is room again


def test_health_has_its_own_threads_and_its_line_has_no_end(bench):
    b = bench()
    a = {**bearer(b.token()), "Origin": HOME}
    gate, real = threading.Event(), b.jobs.health

    def stuck():
        gate.wait(20)
        return real()
    b.jobs.health = stuck

    async def ask():
        transport = httpx.ASGITransport(app=b.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as web:
            held = [asyncio.create_task(web.get(API + "/health")) for _ in range(60)]  # it takes no token: anybody can
            await asyncio.sleep(0.1)
            other = await asyncio.wait_for(web.post(API + "/jobs/status", json={"ids": []}, headers=a), 5)
            none_done = not any(task.done() for task in held)
            gate.set()
            return other, none_done, await asyncio.wait_for(asyncio.gather(*held), 20)
    try:
        other, none_done, held = asyncio.run(ask())
    finally:
        gate.set()
    # None was turned away for the length of the line: a 503 there would be what the server watch reads.
    assert other.status_code == 200 and none_done and {got.status_code for got in held} == {200}


def test_status_never_asks_the_ledger(bench):
    b = bench()
    a = b.token()
    ids = b.make(a)
    b.jobs.drain()
    assert b.ledger.calls == ["account", "charge"]
    b.now[0] += 2 * aj.BALANCE_TTL  # the balance in memory is old now: a quote would ask again
    for _ in range(5):
        assert b.post("/jobs/status", {"ids": ids + [MISSING]}, a).json()["credits"] == 19
        assert b.post("/jobs/status", {"request_id": "r1"}, a).json()["known"] is True
    assert b.ledger.calls == ["account", "charge"]
    assert b.get(QUOTE, a).json()["balance"] == 19 and b.ledger.calls == ["account", "charge", "account"]


def test_status_and_cancel_take_ids_or_a_request_id(bench):
    b = bench()
    a = b.token()
    assert b.post("/jobs/status", {"request_id": "never"}, a).json() == {"known": False, "cancelled": False, "jobs": []}
    ids = b.make(a, items=2)
    seen = b.post("/jobs/status", {"request_id": "r1"}, a).json()
    assert (seen["known"], seen["cancelled"], [v["id"] for v in seen["jobs"]]) == (True, False, ids)

    out = b.post("/jobs/cancel", {"ids": ids[:1]}, a).json()
    assert list(out) == ["jobs"] and [(v["id"], v["status"], v["refund"]) for v in out["jobs"]] == [(ids[0], "cancelled", "none")]
    assert b.post("/jobs/cancel", {"ids": ids[:1]}, a).json() == out  # asking again changes nothing
    out = b.post("/jobs/cancel", {"request_id": "r1"}, a).json()
    assert [(v["id"], v["status"]) for v in out["jobs"]] == [(ids[0], "cancelled"), (ids[1], "cancelled")]
    assert b.post("/jobs/status", {"request_id": "r1"}, a).json()["cancelled"] is True
    assert b.jobs.drain() == 0 and b.ledger.calls == ["account"]  # nothing was picked, so nothing was charged

    # A cancel that arrives before its request leaves a mark, and the request, arriving late, is turned away.
    assert b.post("/jobs/cancel", {"request_id": "late"}, a).json() == {"jobs": []}
    assert b.post("/jobs/status", {"request_id": "late"}, a).json() == {"known": False, "cancelled": True, "jobs": []}
    b.now[0] += 60
    assert refused(b.post("/jobs", body("late"), a)) == (410, "request_cancelled", {})
    assert refused(b.post("/jobs", body("r1", items=2), a)) == (410, "request_cancelled", {})
    b.make(a, rid="r5")
    assert refused(b.post("/jobs", body("r5", items=2), a)) == (409, "request_mismatch", {})  # the same id, another body

    for path in ("/jobs/status", "/jobs/cancel"):
        assert refused(b.post(path, {}, a)) == (400, "bad_request", {"field": "ids"})
        assert refused(b.post(path, {"ids": "abc"}, a)) == (400, "bad_request", {"field": "ids"})
        assert refused(b.post(path, {"ids": ["a"] * 257}, a)) == (400, "bad_request", {"field": "ids"})
        assert refused(b.post(path, {"request_id": 5}, a)) == (400, "bad_request", {"field": "request_id"})
        assert refused(b.post(path, {"request_id": "x" * 65}, a)) == (400, "bad_request", {"field": "request_id"})


def test_a_request_block_over_48000_characters_is_413_with_its_ref(bench):
    b = bench()
    a = b.token()
    long = {"ref": "k9", "kind": "sfx", "mode": "revise", "name": "big", "change": "louder", "base": {"source": "<" * 20000}}
    sent = body(items=[{"ref": "k0", "kind": "sfx", "name": "small"}, long])
    assert len(json.dumps(sent)) < asset_api.MAX_BODY and ag.MAX_REQUEST_CHARS == 48_000
    assert refused(b.post("/jobs", sent, a)) == (413, "too_large", {"ref": "k9"})
    assert b.get("/health").json()["queued"] == 0  # all or nothing: the small one was not made either


def test_a_crash_is_a_500_that_says_nothing_about_it(bench, monkeypatch, caplog):
    b = bench()
    a = b.token(lang="ko")
    hidden = "a zebra in the request of " + "a@b.c"  # an exception's own text may quote anything

    def broken(who, ids):
        raise RuntimeError(hidden)
    monkeypatch.setattr(b.jobs, "status", broken)
    with caplog.at_level(logging.ERROR, logger="olmuse.asset.api"):
        got = b.post("/jobs/status", {"ids": []}, a)
    assert refused(got) == (500, "internal", {}) and got.json()["error"]["message"] == aj.message("ko", "internal")
    assert "zebra" not in got.text and "Traceback" not in got.text and "RuntimeError" not in got.text
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged and "in status" in logged and "zebra" not in logged and "a@b.c" not in logged
    assert b.get(QUOTE, a).status_code == 200  # and the API goes on


# ---------- pages on another port (a local run) ----------
def test_cors_headers_only_when_a_page_is_not_the_sites_own(bench):
    ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}
    b = bench()
    plain = b.web.options(API + "/jobs", headers={"Origin": HOME, **ask})
    assert plain.status_code == 401 and "access-control-allow-origin" not in plain.headers
    assert "access-control-allow-origin" not in b.post("/jobs", body(), b.token()).headers

    page = "http://127.0.0.1:8501"
    local = bench(origins="http://127.0.0.1:8501,http://localhost:8501")
    first = local.web.options(API + "/jobs", headers={"Origin": page, **ask})
    assert first.status_code == 200 and first.headers["access-control-allow-origin"] == page
    assert "authorization" in first.headers["access-control-allow-headers"].lower() and first.headers["cache-control"] == "no-store"
    a = local.token()
    made = local.post("/jobs", body(), a, origin=page)
    assert made.status_code == 200 and made.headers["access-control-allow-origin"] == page
    assert {name.strip().lower() for name in made.headers["access-control-expose-headers"].split(",")} == {"etag", "retry-after"}
    late = local.post("/jobs", {}, origin=page)
    assert refused(late) == (401, "no_token", {}) and late.headers["access-control-allow-origin"] == page  # the page can read it
    assert refused(local.post("/jobs", body("r2"), a, origin="http://localhost:8501/"))[:2] == (403, "bad_origin")
    assert local.post("/jobs", body("r2"), a, origin="http://localhost:8501").status_code == 200
    assert refused(local.post("/jobs", body("r3"), a)) == (403, "bad_origin", {})  # the site itself is not on this list
    other = local.web.options(API + "/jobs", headers={"Origin": "https://evil.example", **ask})
    assert other.status_code == 400 and "access-control-allow-origin" not in other.headers
    # Host comes first here too: the preflight, which the CORS middleware would answer by itself, and the rest.
    for wrong in (local.web.options(API + "/jobs", headers={"Origin": page, "Host": "evil.example", **ask}),
                  local.post("/jobs", body("r4"), a, origin=page, headers={"Host": "evil.example"}),
                  local.get("/health", headers={"Host": "evil.example", "Origin": page})):
        assert refused(wrong) == (403, "bad_host", {}) and "access-control-allow-origin" not in wrong.headers
    ko = local.web.options(API + "/jobs", headers={"Origin": page, "Host": "evil.example", **bearer(local.token(lang="ko")), **ask})
    assert ko.json()["error"]["message"] == aj.message("ko", "bad_host")


# ---------- the server's own settings ----------
def test_real_deps_reads_the_environment_and_then_this_pcs_files(tmp_path, monkeypatch):
    home, made = tmp_path / "home", []
    home.mkdir()
    monkeypatch.setattr(asset_api, "LOCAL_FILES", home)
    monkeypatch.setattr(asset_api, "DATA", tmp_path / "data")
    monkeypatch.setattr(ag, "model_factory", lambda key, model, base_url: made.append((key, model, base_url)) or "a factory")
    base = {"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40, "OLMUSE_GEN_DB": str(tmp_path / "gen.db"), "OLMUSE_RENDERS": str(tmp_path / "renders")}

    def read(**env):
        deps = asset_api.real_deps({**base, **env})
        deps.store.close()
        return deps

    plain = read()
    assert plain.secret == b"x" * 40 and plain.store.path == str(tmp_path / "gen.db") and plain.renders == str(tmp_path / "renders")
    assert plain.model is None and plain.engine is nkido and plain.ledger is None and made == []  # no key, no ledger: both off
    assert plain.model_name == sb.DEFAULT_CHOICE and plain.measure.node == "node" and plain.limits == aj.Limits()
    assert asset_api.listed(plain.hosts) == ("olmuse.app", "127.0.0.1:8502", "localhost:8502")
    assert asset_api.listed(plain.origins) == ("https://olmuse.app",) and plain.autostart is True

    (home / "key-pool.env").write_text("# keys\nOTHER=1\nexport OPENROUTER_API_KEY='from-the-pool'\n", encoding="utf-8")
    assert read().model == "a factory" and made.pop() == ("from-the-pool", sb.DEFAULT_CHOICE, "")
    read(OPENROUTER_API_KEY="from-env", OLMUSE_GEN_MODEL="some/model", OLMUSE_GEN_BASE_URL="http://proxy.test/v1")
    assert made.pop() == ("from-env", "some/model", "http://proxy.test/v1")
    read(OPENROUTER_API_KEY="from-env", OLMUSE_GEN_KEY="its-own")
    assert made.pop() == ("its-own", sb.DEFAULT_CHOICE, "")
    (home / "key-pool.env").write_text("OLMUSE_GEN_KEY=its-own-from-the-pool\nOPENROUTER_API_KEY=from-the-pool\n", encoding="utf-8")
    read(OPENROUTER_API_KEY="from-env")  # the API's own key comes before the shared one, wherever each is kept
    assert made.pop() == ("its-own-from-the-pool", sb.DEFAULT_CHOICE, "")

    fake = read(OLMUSE_GEN_FAKE="1", OPENROUTER_API_KEY="from-env")
    assert fake.model is ag.FakeModel and isinstance(fake.engine, ag.FakeEngine) and fake.model_name == "fake" and made == []

    tuned = read(OLMUSE_API_HOSTS="a.example, B.example:1", OLMUSE_API_ORIGINS="http://127.0.0.1:8501,http://localhost:8501",
                 OLMUSE_GEN_PW_DAILY="7", OLMUSE_GEN_DAILY_USD="1.5", OLMUSE_NODE="node-x")
    assert asset_api.listed(tuned.hosts) == ("a.example", "b.example:1") and tuned.measure.node == "node-x"
    assert asset_api.listed(tuned.origins) == ("http://127.0.0.1:8501", "http://localhost:8501")
    assert (tuned.limits.pw_daily, tuned.limits.daily_usd, tuned.limits.daily) == (7, 1.5, 1000)
    # An API on a port of its own (run_local.ps1 beside the public one) answers the page that asks it there.
    assert asset_api.listed(read(OLMUSE_API_PORT="50123").hosts) == ("olmuse.app", "127.0.0.1:50123", "localhost:50123")
    assert asset_api.listed(read(OLMUSE_API_PORT="50123", OLMUSE_API_HOSTS="a.example").hosts) == ("a.example",)
    assert read(OLMUSE_API_PORT="not a port").hosts == asset_api.DEFAULT_HOSTS == "olmuse.app,127.0.0.1:8502,localhost:8502"

    # The ledger: the Lambda with its url, token and pepper; the local file only when that is chosen on purpose.
    (home / "strudel-credits.token").write_text("the-token\n", encoding="ascii")
    assert read(STRUDEL_CREDITS_URL="https://ledger.test").ledger is None  # no pepper
    (home / "strudel-credits.pepper").write_text("the-pepper\n", encoding="ascii")
    remote = read(STRUDEL_CREDITS_URL="https://ledger.test").ledger
    assert isinstance(remote, RemoteLedger) and (remote.url, remote.token, remote.pepper) == ("https://ledger.test", "the-token", "the-pepper")
    assert read(STRUDEL_CREDITS_URL="https://ledger.test", STRUDEL_CREDITS_TOKEN="env-token").ledger.token == "env-token"
    assert read().ledger is None and not (tmp_path / "data").exists()
    local = read(STRUDEL_LOCAL_LEDGER="1").ledger
    assert isinstance(local, LocalLedger) and (tmp_path / "data" / "credits.sqlite").exists()
    local.db.close()

    # Where the rows and the results are kept. The public API's database is opened by nothing but the public API:
    # a run on this PC's own ledger file or on the scripted model has its own, and the results go where the rows go.
    monkeypatch.setattr(aj, "DEFAULT_DB", tmp_path / "public" / "asset-gen.db")

    def kept(**env):
        deps = asset_api.real_deps({"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40, **env})
        deps.store.close()
        if isinstance(deps.ledger, LocalLedger):
            deps.ledger.db.close()
        return deps.store.path, deps.renders, type(deps.ledger)

    public, own, other = tmp_path / "public", tmp_path / "data" / "local", tmp_path / "other"
    assert kept() == (str(public / "asset-gen.db"), str(public / "asset-renders"), type(None))
    assert kept(STRUDEL_CREDITS_URL="https://ledger.test", STRUDEL_LOCAL_LEDGER="1") == (
        str(public / "asset-gen.db"), str(public / "asset-renders"), RemoteLedger)  # the real ledger: the real rows
    assert kept(STRUDEL_LOCAL_LEDGER="1") == (str(own / "asset-gen.db"), str(own / "asset-renders"), LocalLedger)
    assert kept(OLMUSE_GEN_FAKE="1") == (str(own / "asset-gen.db"), str(own / "asset-renders"), type(None))
    assert kept(OLMUSE_GEN_DB=str(other / "gen.db")) == (str(other / "gen.db"), str(other / "asset-renders"), type(None))
    assert kept(STRUDEL_LOCAL_LEDGER="1", OLMUSE_GEN_DB=str(other / "gen.db"), OLMUSE_RENDERS=str(other / "r")) == (
        str(other / "gen.db"), str(other / "r"), LocalLedger)
    assert aj.DEFAULT_RENDERS.name == "asset-renders" and aj.DEFAULT_RENDERS.parent == asset_api.ROOT / ".studio-data"


def test_a_local_run_never_touches_the_public_rows_or_their_results(tmp_path, monkeypatch):
    """What the separate database is for: a paid draft that waits to be received in the public database, and the
    start of an API with run_local.ps1's settings beside it."""
    public = tmp_path / "public"
    monkeypatch.setattr(asset_api, "LOCAL_FILES", tmp_path / "home")
    monkeypatch.setattr(asset_api, "DATA", tmp_path / "data")
    monkeypatch.setattr(aj, "DEFAULT_DB", public / "asset-gen.db")
    monkeypatch.setattr(aj, "DEFAULT_RENDERS", public / "asset-renders")
    paid = Bench(tmp_path / "bench", store=aj.GenStore(str(public / "asset-gen.db")))
    paid.jobs.renders = public / "asset-renders"  # where the public API keeps them: beside its database
    ids = paid.make(paid.token(), items=2)
    assert paid.jobs.drain(1) == 1  # one draft is done and not received yet, the other still waits
    master = public / "asset-renders" / ids[0] / "master.wav"
    assert master.is_file() and [paid.row(i)["status"] for i in ids] == ["done", "queued"]
    paid.jobs.store.close()  # the public API is down for a moment
    paid.api.close()

    deps = asset_api.real_deps({"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40, "STRUDEL_LOCAL_LEDGER": "1"})
    deps.autostart, deps.measure = False, lint
    deps.clock = lambda: T0 + 2 * aj.UNFETCHED_TTL  # late enough to expire what nobody received
    local = asset_api.Api(deps)  # its start fails what is queued or running in the database it opened
    local.jobs.sweep()
    local.jobs.store.close()
    deps.ledger.db.close()
    local.close()
    assert deps.store.path == str(tmp_path / "data" / "local" / "asset-gen.db") and master.is_file()
    assert deps.renders == str(tmp_path / "data" / "local" / "asset-renders")
    back = aj.GenStore(str(public / "asset-gen.db"))
    rows = {r["id"]: (r["status"], r["charge"]) for r in back.all("select id, status, charge from gen")}
    back.close()
    assert rows == {ids[0]: ("done", "charged"), ids[1]: ("queued", "none")}  # as the public API left them


def test_the_log_is_kept_beside_the_database(tmp_path, monkeypatch, caplog):
    """An API that is not the public one (run_local.ps1, the scripted model, a test with a database of its own)
    wrote into the public API's log file, and two processes on one log file lose lines at midnight."""
    assert asset_api.logs_beside(aj.DEFAULT_DB) == asset_api.LOGS == ROOT / ".studio-data" / "logs" / "api"
    data = tmp_path / "data"
    monkeypatch.setattr(asset_api, "LOCAL_FILES", tmp_path / "home")
    monkeypatch.setattr(asset_api, "DATA", data)
    monkeypatch.setattr(aj, "DEFAULT_DB", data / "asset-gen.db")

    def where(**env):
        told = []
        caplog.clear()
        deps = asset_api.real_deps({"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40, **env},
                                   log_to=lambda folder: told.append((folder, len(caplog.records))))
        deps.store.close()
        if isinstance(deps.ledger, LocalLedger):
            deps.ledger.db.close()
        assert len(told) == 1 and told[0][1] == 0 and len(caplog.records) > 0  # told before the first line was logged
        return told[0][0]

    assert where() == data / "logs" / "api"
    assert where(OLMUSE_GEN_FAKE="1") == where(STRUDEL_LOCAL_LEDGER="1") == data / "local" / "logs" / "api"
    assert where(OLMUSE_GEN_DB=str(tmp_path / "other" / "gen.db")) == tmp_path / "other" / "logs" / "api"
    # A database another process has: the folder is known before the start fails, so the line goes to that log.
    held, told = aj.GenStore(str(tmp_path / "other" / "gen.db")), []
    with pytest.raises(aj.StoreTaken):
        asset_api.real_deps({"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40, "OLMUSE_GEN_DB": held.path}, log_to=told.append)
    held.close()
    assert told == [tmp_path / "other" / "logs" / "api"]


def test_a_start_that_keeps_failing_writes_its_frames_once(tmp_path, monkeypatch, caplog):
    """run_api.ps1 starts the API again for as long as it fails. The log gets the frames of a failure once, and one
    line for every start that failed the same way after it."""
    fails, logs = [True], tmp_path / "logs"

    def deps(log_to=None):
        log_to(logs)
        if fails[0]:
            raise aj.StoreTaken("asset-gen.db is already open in a running process")
        return asset_api.Deps(secret=SECRET, renders=tmp_path / "renders", temp=tmp_path / "temp", model=ag.FakeModel,
                              engine=ag.FakeEngine(), measure=lint, free=lambda path: 100 * aj.GB, workers=1)

    monkeypatch.delenv("OLMUSE_API_ORIGINS", raising=False)
    monkeypatch.setattr(asset_api.server_ops, "setup_logging", lambda folder: None)
    monkeypatch.setattr(asset_api, "real_deps", deps)

    def start():
        caplog.clear()
        try:
            with TestClient(asset_api.create_app(), base_url=BASE):
                pass
        except aj.StoreTaken:
            pass
        return [r.getMessage() for r in caplog.records if "could not start" in r.getMessage()]

    first, second, third = start(), start(), start()
    assert len(first) == 1 and first[0].splitlines()[0] == "ALERT the asset api could not start: StoreTaken"
    assert len(first[0].splitlines()) > 3  # the class and the frames
    assert second == third == ["ALERT the asset api could not start: StoreTaken, as before"]
    assert (logs / asset_api.START_MARK).is_file()
    fails[0] = False
    assert start() == [] and not (logs / asset_api.START_MARK).exists()
    fails[0] = True
    assert len(start()[0].splitlines()) > 3  # after a start that worked, the frames are written again

    def early(log_to=None):
        raise OSError("failed before the database was known")
    monkeypatch.setattr(asset_api, "LOGS", tmp_path / "public-logs")
    monkeypatch.setattr(asset_api, "real_deps", early)
    for _ in range(2):
        caplog.clear()
        with pytest.raises(OSError):
            with TestClient(asset_api.create_app(), base_url=BASE):
                pass
        assert len([r for r in caplog.records if "could not start: OSError" in r.getMessage()][0].getMessage().splitlines()) > 3
    assert not (tmp_path / "public-logs").exists()  # without a folder of its own nothing is kept


def test_requirements_pin_what_is_installed():
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").split()
    for name in ("fastapi", "uvicorn", "numpy", "soundfile", "httpx"):
        assert f"{name}=={importlib.metadata.version(name)}" in lines


COMMAND = ("'-m', 'uvicorn', 'asset_api:app', '--host', '127.0.0.1', '--port', \"$port\", '--workers', '1', '--no-access-log',"
           " '--no-proxy-headers'")  # $port is 8502 unless OLMUSE_API_PORT names another
LISTENING = "Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue"
PORT_READ = ("$port = 8502", '$said = "$env:OLMUSE_API_PORT".Trim()',
             "if ($said -match '^[0-9]{1,5}$' -and [int]$said -ge 1 -and [int]$said -le 65535) { $port = [int]$said }")
PORT_PROBE = ("$probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)",
              "$probe.Start(); $port = $probe.LocalEndpoint.Port; $probe.Stop()",
              '$env:OLMUSE_API_PORT = "$port"')


def test_the_server_is_started_so_that_the_peer_is_the_sockets_and_never_a_forwarded_header():
    """uvicorn's default (--proxy-headers, trusting 127.0.0.1) puts the X-Forwarded-For of a request from the tunnel
    in the peer's place before the app sees it. address() would then never see 127.0.0.1 and never read
    CF-Connecting-IP. What the scripts start is read here by uvicorn's own command line."""
    default = COMMAND.replace('"$port"', "'8502'")
    args = re.findall(r"'([^']*)'", default)
    assert args[:2] == ["-m", "uvicorn"]
    read = uvicorn_command.make_context("uvicorn", args[2:]).params
    assert (read["app"], read["host"], read["port"], read["workers"]) == ("asset_api:app", "127.0.0.1", 8502, 1)
    assert read["proxy_headers"] is False and read["access_log"] is False
    assert uvicorn_command.make_context("uvicorn", ["asset_api:app"]).params["proxy_headers"] is True  # what it is without
    assert "--no-proxy-headers" in asset_api.__doc__ and default.replace("'", "").replace(",", "") in asset_api.__doc__
    for name in ("run_api.ps1", "run_local.ps1"):
        script = (ROOT / name).read_text(encoding="utf-8")
        assert script.count("'uvicorn'") == script.count(COMMAND) == 1  # started in this one way


def test_the_run_scripts_keep_the_api_up_and_only_apionly_stops_it():
    command, listening = COMMAND, LISTENING
    api = (ROOT / "run_api.ps1").read_text(encoding="utf-8")
    assert "while ($true) {" in api and command in api
    # Its port is 8502 unless OLMUSE_API_PORT names another, read once before the loop the way asset_token.api_port reads it.
    assert api.index("\n".join(PORT_READ) + "\n") < api.index("while ($true) {")
    wait = api[api.index("while ($true) {"):api.index("$api = Start-Process")]
    on_port = listening.replace("8502", "$port")
    assert f"$held = {on_port} | Select-Object -First 1" in wait and "if ($held) {" in wait and "Start-Sleep 5; continue" in wait
    # What listens there may not be the API. The loop still waits, and says so in the console file, once for each.
    assert "$owner.CommandLine -notmatch 'asset_api:app'" in wait and "$held.OwningProcess -ne $stranger" in wait
    assert "Add-Content (Join-Path $logs 'console.err.log')" in wait and "ALERT port $port is held by pid $stranger" in wait
    assert "Stop-Process" not in api  # the loop never stops anything
    assert api.index(command) < api.index("$api.WaitForExit()") < api.index("Start-Sleep $rest")
    assert "param([switch]$Public)\n" in api  # the word run_public.ps1 knows its own loop by
    assert "'.studio-data\\logs\\api'" in api and "'console.out.log'" in api and "'console.err.log'" in api

    public = (ROOT / "run_public.ps1").read_text(encoding="utf-8")
    assert "param([switch]$ServerOnly, [switch]$ApiOnly)" in public
    start = public[public.index("function Start-Api {"):public.index("$pool = ")]
    # The public API is never the scripted model's and never on another port than 8502, whatever the window was left with.
    assert start.index("Remove-Item Env:OLMUSE_GEN_FAKE, Env:OLMUSE_API_PORT") < start.index("Start-Process powershell")
    assert "-WindowStyle Hidden" in start and "'-NoProfile', '-File', \"`\"$apiLoop`\"\", '-Public'" in start
    # The loop is known by that start: this folder's run_api.ps1 as the -File and -Public after it, not by the file's name alone.
    assert "$apiLoop = Join-Path $PSScriptRoot 'run_api.ps1'\n" in public[:public.index("function Get-ApiLoop {")]
    assert "$mark = '-File\\s+\"?' + [regex]::Escape($apiLoop) + '\"?\\s+-Public(\\s|$)'" in public
    assert "$_.CommandLine -match $mark" in public and "-match 'run_api" not in public
    only = public[public.index("if ($ApiOnly) {"):public.index("if (-not $ServerOnly) {")]
    assert "Get-ApiLoop | ForEach-Object { Stop-Process" in only and listening in only
    assert only.index("Stop-Process") < only.index("Start-Api") < only.index("return")
    # -ApiOnly stops an API, known by its command line, and nothing else that happens to listen on the port: that is
    # looked at before anything is stopped, left running, and the script ends with an error after the loop is up.
    stops = [line for line in only.splitlines() if "Stop-Process" in line]
    assert len(stops) == 2 and all("Stop-Process -Id $_.ProcessId" in line for line in stops) and "$_.OwningProcess -Force" not in only
    assert "Where-Object { $_.CommandLine -match 'asset_api:app' } |" in only and "Name like 'python%'" in only
    assert only.index("$strangers = @(") < only.index("Stop-Process") and ".CommandLine -notmatch 'asset_api:app' })" in only
    assert only.index("Start-Api") < only.index('if ($strangers) { throw "Port 8502 is held by pid') < only.index("return")
    # Outside -ApiOnly nothing stops the API: its loop is started when there is none, and that is all.
    rest = public.replace(only, "")
    code = [line for line in rest.splitlines() if not line.lstrip().startswith("#")]
    assert not any("8502" in line or "asset_api" in line for line in code)
    assert [line.strip() for line in code if "Get-ApiLoop" in line and "function" not in line] == ["if (-not (Get-ApiLoop)) { Start-Api }"]
    full = rest[rest.index("if (-not $ServerOnly) {"):rest.index("python (Join-Path $PSScriptRoot 'tools\\stamp_assets.py')")]
    assert "if (-not (Get-ApiLoop)) { Start-Api }" in full  # a full run only; -ServerOnly restarts the page alone

    local = (ROOT / "run_local.ps1").read_text(encoding="utf-8")
    assert command in local and local.index(command) < local.index("streamlit run") and "$env:STRUDEL_LOCAL_AI = '1'" in local
    # The page's port is chosen here and told to Streamlit, which would otherwise move up from a taken 8501 to the
    # public API's 8502. It is 8501 when that is free, and the pages the API allows are the ones on the port chosen.
    lines = local.splitlines()
    port = lines.index("$page = 8501")
    assert lines[port + 1] == ("while ($page -eq 8502 -or (Get-NetTCPConnection -LocalPort $page -State Listen"
                               " -ErrorAction SilentlyContinue)) { $page++ }")
    assert '$env:OLMUSE_API_ORIGINS = "http://127.0.0.1:$page,http://localhost:$page"' in lines[port + 2:]
    assert "--server.address 127.0.0.1 --server.port $page --server.headless true" in local
    # Its rows and its results are not the public API's, and what it set does not stay behind in the window.
    for name in ("OLMUSE_GEN_DB", "OLMUSE_RENDERS"):
        assert local.index(f"$env:{name} = Join-Path $PSScriptRoot '.studio-data\\local\\") < local.index(command)
    end = local[local.index("finally {"):]
    assert "Remove-Item Env:OLMUSE_API_ORIGINS, Env:OLMUSE_GEN_DB, Env:OLMUSE_RENDERS, Env:OLMUSE_API_PORT" in end
    assert "Stop-Process -Id $api.Id" in end
    # The API's port here is a free one Windows names. app.py and the API read it from OLMUSE_API_PORT, so it is set
    # before either starts, and the public API's 8502 is in no line but the one where the page's port passes it over.
    probe = lines.index(PORT_PROBE[0])
    assert tuple(lines[probe:probe + 3]) == PORT_PROBE and probe + 3 <= next(i for i, line in enumerate(lines) if command in line)
    code = [line for line in lines if not line.lstrip().startswith("#")]
    assert [line for line in code if "8502" in line] == [lines[port + 1]] and "Write-Warning" not in local


def test_the_local_api_gets_a_free_port_that_no_streamlit_app_takes():
    """What run_local.ps1 does to choose the port, run by PowerShell itself: the port is free, it is far from the
    ports Streamlit counts up from 8501, and it is one app.py and the API read back from OLMUSE_API_PORT."""
    exe = shutil.which("powershell")
    if not exe:
        pytest.skip("no Windows PowerShell on this machine")
    assert all(line in (ROOT / "run_local.ps1").read_text(encoding="utf-8").splitlines() for line in PORT_PROBE)
    done = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", "; ".join(PORT_PROBE) + "; Write-Output $env:OLMUSE_API_PORT"],
                          capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    assert done.returncode == 0 and done.stdout.strip().isdigit(), done.stdout + done.stderr
    port = int(done.stdout.strip())
    assert port > 10000 and asset_token.api_port({"OLMUSE_API_PORT": done.stdout.strip()}) == port
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))  # nothing listens there


def test_the_loop_reads_the_port_the_way_the_api_and_the_page_do():
    """run_api.ps1 starts the server on a port and asset_token.api_port tells the API which Host that is and the
    page where to ask. One variable, read in two languages: the same answer for whatever it holds."""
    exe = shutil.which("powershell")
    if not exe:
        pytest.skip("no Windows PowerShell on this machine")
    assert "\n".join(PORT_READ) in (ROOT / "run_api.ps1").read_text(encoding="utf-8")
    said = ["", "50123", " 8600 ", "08600", "1", "65535", "0", "65536", "123456", "8502x", "-1", "85.02", "port"]
    script = ("foreach ($value in @(" + ", ".join(f"'{value}'" for value in said) + ")) { $env:OLMUSE_API_PORT = $value; "
              + "; ".join(PORT_READ) + "; Write-Output $port }")
    done = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, encoding="utf-8",
                          errors="replace", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert [int(line) for line in done.stdout.split()] == [asset_token.api_port({"OLMUSE_API_PORT": value}) for value in said]
    assert [asset_token.api_port({"OLMUSE_API_PORT": value}) for value in said] == [8502, 50123, 8600, 8600, 1, 65535] + [8502] * 7


REST = ("$quick = ((Get-Date) - $began).TotalSeconds -lt 30", "if (-not $quick) { $rest = 2 }", "Start-Sleep $rest",
        "if ($quick) { $rest = [Math]::Min(60, $rest * 2) }")


def test_the_loop_rests_longer_while_starts_keep_ending_at_once():
    """An API that cannot start ends within a second, and every such start writes to the log. The loop's rest of two
    seconds doubles up to a minute while that goes on, and is two seconds again after a start that held."""
    exe = shutil.which("powershell")
    if not exe:
        pytest.skip("no Windows PowerShell on this machine")
    lines = [line.strip() for line in (ROOT / "run_api.ps1").read_text(encoding="utf-8").splitlines()]
    assert "$rest = 2" in lines and "$began = Get-Date" in lines and REST[0] in lines
    assert lines.index("$rest = 2") < lines.index("while ($true) {") < lines.index("$began = Get-Date")
    ended, rest = lines.index("$api.WaitForExit()"), lines.index(REST[0])
    assert lines.index("$began = Get-Date") < ended < rest and tuple(lines[rest:rest + len(REST)]) == REST
    assert [line for line in lines if line.startswith("Start-Sleep")] == ["Start-Sleep 5; continue", "Start-Sleep $rest"]
    script = ("function Start-Sleep($seconds) { Write-Output $seconds }; $rest = 2; "
              "foreach ($ran in @(1, 1, 1, 1, 1, 1, 1, 45, 1, 1)) { $began = (Get-Date).AddSeconds(-$ran); " + "; ".join(REST) + " }")
    done = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, encoding="utf-8",
                          errors="replace", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert [int(line) for line in done.stdout.split()] == [2, 4, 8, 16, 32, 60, 60, 2, 2, 4]


def test_only_the_loop_run_public_started_is_taken_for_the_api_loop(tmp_path):
    """run_public.ps1 knew the loop by `run_api.ps1` anywhere in a powershell's command line. A window that only
    named the file kept a full run from starting the API, and -ApiOnly stopped that window. Its Get-ApiLoop is run
    here by PowerShell itself against three windows, with a stand-in for the file so that this PC's own loop is
    neither looked for nor mistaken."""
    exe = shutil.which("powershell")
    if not exe:
        pytest.skip("no Windows PowerShell on this machine")
    public = (ROOT / "run_public.ps1").read_text(encoding="utf-8")
    found = public[public.index("function Get-ApiLoop {"):public.index("function Start-Api {")]
    loop = tmp_path / "run_api.ps1"
    loop.write_text("param([switch]$Public)" + chr(10) + "Start-Sleep 120" + chr(10), encoding="ascii")
    windows = [subprocess.Popen([exe, "-NoProfile", "-File", str(loop), "-Public"]),  # the way Start-Api starts it
               subprocess.Popen([exe, "-NoProfile", "-File", str(loop)]),             # a loop somebody runs by hand
               subprocess.Popen([exe, "-NoProfile", "-Command", "Start-Sleep 120 # only reading " + str(loop) + " -Public"])]
    try:
        script = chr(10).join(["$apiLoop = '" + str(loop).replace("'", "''") + "'", found, "Get-ApiLoop | ForEach-Object { $_.ProcessId }"])
        done = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, encoding="utf-8",
                              errors="replace", timeout=60)
        assert done.returncode == 0, done.stdout + done.stderr
        assert [int(line) for line in done.stdout.split()] == [windows[0].pid]
    finally:
        for window in windows:
            window.kill()
            window.wait(10)


def test_the_run_scripts_are_powershell_that_parses():
    exe = shutil.which("powershell")
    if not exe:
        pytest.skip("no Windows PowerShell on this machine")
    paths = ", ".join("'" + str(ROOT / name).replace("'", "''") + "'" for name in ("run_api.ps1", "run_public.ps1", "run_local.ps1"))
    script = ("$bad = 0; foreach ($path in " + paths + ") { $errors = $null; "
              "[void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errors); "
              "foreach ($e in $errors) { $bad++; Write-Output ($path + ': ' + $e.Extent.StartLineNumber + ': ' + $e.Message) } }; exit $bad")
    done = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, encoding="utf-8",
                          errors="replace", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


# ---------- accounts on the Claude CLI list ----------
class Claude:
    def __init__(self):
        self.model, self.ok, self.size = ag.FakeModel(cost=0.0), True, 2

    def __call__(self):
        return self.model


def test_a_listed_account_is_quoted_nothing_and_its_sound_is_made_without_the_ledger(bench):
    claude = Claude()
    b = bench(claude=claude, claude_accounts="Jam@b.c, other@x.y")
    jam, a = b.token("jam@b.c"), b.token()
    quote = b.get("/quote?items=2&drafts=1", jam).json()
    assert (quote["unit"], quote["credits"], quote["free"], quote["ok"]) == (0, 0, True, True)
    ids = b.make(jam, items=2, credits=0)
    assert b.jobs.drain() == 2 and b.ledger.calls == [] and len(claude.model.prompts) == 2
    assert [v["status"] for v in b.views(jam, ids)] == ["done", "done"]
    assert b.get("/quote?items=1&drafts=1", a).json()["credits"] == 1  # everyone else pays as before
    health = b.get("/health").json()
    assert health["claude"] is True and set(health) == {"ok", "model", "engine", "node", "ledger", "queued", "running",
                                                         "disk_free_mb", "claude"}


def test_real_deps_reads_the_claude_list_and_its_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_api, "LOCAL_FILES", tmp_path / "home")
    monkeypatch.setattr(asset_api, "DATA", tmp_path / "data")
    base = {"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40, "OLMUSE_GEN_DB": str(tmp_path / "gen.db")}

    def read(**env):
        deps = asset_api.real_deps({**base, **env})
        deps.store.close()
        return deps

    plain = read()
    assert plain.claude is None and asset_api.listed(plain.claude_accounts) == ()
    on = read(OLMUSE_GEN_CLAUDE_ACCOUNTS="A@b.c,jam@b.c", OLMUSE_GEN_CLAUDE_MODEL="opus", OLMUSE_GEN_CLAUDE_SLOTS="3",
              OLMUSE_GEN_CLAUDE_DAILY="40", OLMUSE_GEN_CLAUDE_EXE="C:/tools/claude.exe")
    assert isinstance(on.claude, ag.ClaudeCli) and asset_api.listed(on.claude_accounts) == ("a@b.c", "jam@b.c")
    assert (on.claude.model, on.claude.size, on.claude.command, on.limits.claude_daily) == ("opus", 3, ["C:/tools/claude.exe"], 40)
    assert read(OLMUSE_GEN_CLAUDE_ACCOUNTS="a@b.c", OLMUSE_GEN_CLAUDE_MODEL="fable").claude.model == "sonnet"
    defaults = read(OLMUSE_GEN_CLAUDE_ACCOUNTS="a@b.c").claude
    assert (defaults.model, defaults.size, defaults.command) == ("sonnet", 2, ["claude"])
    assert read(OLMUSE_GEN_CLAUDE_ACCOUNTS="a@b.c", OLMUSE_GEN_FAKE="1").claude is ag.FakeModel
