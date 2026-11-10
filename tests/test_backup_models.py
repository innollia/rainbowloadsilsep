"""The default model's safety net: a transient failure is retried once, a lasting one or repeated broken edits hand the
job to a stronger model once (operator-paid, capped per day), and the user is told a better model answered."""
import time

import pytest

import studio_backend as sb
from credits import LocalLedger

TRACKS = [{"id": "drums", "name": "drums", "role": "drums", "code": 's("bd*4")'}]
GOOD = {"intent": "edit", "reply": "", "summary": "more drums", "bpm": 120,
        "changes": [{"id": "drums", "name": "drums", "role": "drums", "code": 's("bd*8")'}]}
BROKEN = {"intent": "edit", "reply": "", "summary": "x", "bpm": 120,
          "changes": [{"id": "BAD ID", "name": "x", "role": "x", "code": 's("bd")'}]}


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(sb.Backed, "RETRY_PAUSE", 0)


class Engine:
    def __init__(self, name, replies):
        self.model, self.replies, self.calls = name, list(replies), 0

    def edit(self, prompt):
        self.calls += 1
        r = self.replies.pop(0) if self.replies else GOOD
        if isinstance(r, Exception):
            raise r
        return r


def backed(primary, backup=None, budget=None):
    return sb.Backed(primary, [("Haiku 5.5", 0.0015, lambda: backup)] if backup else [], budget)


def test_transient_failure_is_retried_once_on_the_same_model():
    primary = Engine(sb.DEFAULT_CHOICE, [sb.ModelError("openrouter_http", code=503, detail="x"), GOOD])
    b = backed(primary, Engine("haiku", []))
    assert b.edit("p") == GOOD and primary.calls == 2 and b.upgraded == ""


def test_a_lasting_failure_goes_to_the_stronger_model():
    primary = Engine(sb.DEFAULT_CHOICE, [sb.ModelError("openrouter_conn", detail="x")] * 2)
    backup = Engine("haiku", [GOOD])
    b = backed(primary, backup)
    assert b.edit("p") == GOOD and primary.calls == 2 and backup.calls == 1 and b.upgraded == "Haiku 5.5"


def test_a_key_failure_is_not_retried_but_handed_over():
    primary = Engine(sb.DEFAULT_CHOICE, [sb.ModelError("openrouter_key")])
    b = backed(primary, Engine("haiku", [GOOD]))
    assert b.edit("p") == GOOD and primary.calls == 1


def test_without_backups_the_error_carries_its_code():
    b = backed(Engine("claude-opus-5-5", [sb.ModelError("claude_quota")] * 2))
    with pytest.raises(sb.ModelError) as err:
        b.edit("p")
    assert err.value.text("en").endswith("(CL-429)")


def test_backups_stop_at_the_daily_budget():
    budget = sb.DailyUsd(0.001)
    b = backed(Engine(sb.DEFAULT_CHOICE, [sb.ModelError("openrouter_key")]), Engine("haiku", [GOOD]), budget)
    with pytest.raises(sb.ModelError):
        b.edit("p")


def test_router_backs_only_the_default_model():
    router = sb.Router("g", "c", openrouter_key="o")
    assert [label for label, _, _ in router.backed(sb.DEFAULT_CHOICE).backups] == ["Haiku 5.5", "Gemini 3.8 Flash"]
    assert router.backed("claude-sonnet-5-5").backups == []


def request():
    req = sb.validate_request({"text": "more drums", "tracks": TRACKS, "bpm": 120, "lang": "en"})
    req["account"], req["model"] = "a@b.c", sb.DEFAULT_CHOICE
    return req


class Model:
    """Stands in for the Router: the default model keeps breaking, its backup answers."""

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup

    def backed(self, model, effort):
        return backed(self.primary, self.backup)


def run(jobs, owner="acct:a@b.c"):
    jobs.submit(owner, request())
    job = jobs.jobs[owner]
    for _ in range(500):
        c = job.view.get("candidate")
        if c and job.view.get("accepted") != c["seq"] and job.running:
            jobs.feedback(owner, {"job_id": job.id, "seq": c["seq"], "ok": True})
        if not job.running:
            return job.view
        time.sleep(0.01)
    raise AssertionError("job did not end")


def test_broken_edits_hand_the_job_to_the_stronger_model_and_say_so():
    primary = Engine(sb.DEFAULT_CHOICE, [BROKEN] * 3)
    backup = Engine("haiku", [GOOD])
    ledger = LocalLedger()
    view = run(sb.Jobs(Model(primary, backup), ledger=ledger))
    kinds = [m["kind"] for m in view["messages"]]
    assert view["status"] == "done" and "upgrade" in kinds and backup.calls == 1
    assert any(m["text"] == sb.msg("en", "upgraded", model="Haiku 5.5") for m in view["messages"])
    assert ledger.account("a@b.c")["credits"] == 20 - 4  # four calls at the chosen model's price, the backup's is ours
