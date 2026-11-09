import time

import asset_agent as aa
from studio_backend import ModelError

STATE = {"cats": [{"id": "ui"}, {"id": "bgm"}], "assets": [{"id": "sfx_ui_click"}, {"id": "bgm_garden"}]}


def act(**kw):
    base = {"op": "", "target": "", "assets": [], "cat": "", "name": "", "kind": "", "parent": "", "text": "", "url": ""}
    return {**base, **kw}


def test_clean_keeps_only_actions_on_the_board():
    reply = {"reply": "done", "questions": [], "actions": [
        act(op="move", assets=["sfx_ui_click", "ghost"], cat="bgm"),
        act(op="move", assets=["sfx_ui_click"], cat="nowhere"),
        act(op="add_cat", cat="forest", name="Forest", kind="music", parent="bgm"),
        act(op="move", assets=["bgm_garden"], cat="forest"),
        act(op="add_ref", target="cat:ui", kind="text", text="soft"),
        act(op="add_ref", target="asset:ghost", kind="text", text="x"),
        act(op="explode"),
    ]}
    out = aa.clean(reply, STATE)
    assert [a["op"] for a in out["actions"]] == ["move", "add_cat", "move", "add_ref"]
    assert out["actions"][0]["assets"] == ["sfx_ui_click"]


class FakeEngine:
    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.prompts = reply, fail, []

    def ask(self, prompt, schema, name):
        self.prompts.append(prompt)
        if self.fail:
            raise ModelError("openrouter_conn", detail="down")
        return self.reply


class FakeModel:
    def __init__(self, engine):
        self.e = engine

    def engine(self, model, effort, system=None):
        assert system == aa.SYSTEM
        return self.e


class FakeJobs:
    def __init__(self, limit=False):
        self.limit = limit

    def count_call(self, account, owner, lang, **kw):
        if self.limit:
            raise ValueError("daily limit")


class FakeLedger:
    def __init__(self):
        self.credits, self.log = 10, []

    def charge(self, email, cost, ref):
        self.credits -= cost; self.log.append(("charge", ref)); return True, self.credits

    def refund(self, email, cost, ref):
        self.credits += cost; self.log.append(("refund", ref)); return self.credits


def wait(agents, owner):
    for _ in range(200):
        v = agents.view(owner)
        if v and v["status"] != "working":
            return v
        time.sleep(0.01)
    raise AssertionError("no answer")


def test_agent_answers_and_charges_once():
    eng = FakeEngine({"reply": "ok", "questions": [], "actions": [act(op="set_brief", text="warm")]})
    agents, ledger = aa.Agents(), FakeLedger()
    agents.start("o1", {"n": "1", "text": "make it warm", "state": STATE, "lang": "en", "account": "a@b.c"}, FakeModel(eng), FakeJobs(), ledger)
    v = wait(agents, "o1")
    assert v["status"] == "done" and v["reply"] == "ok" and v["actions"][0]["op"] == "set_brief"
    assert [k for k, _ in ledger.log] == ["charge"] and "make it warm" in eng.prompts[0]


def test_failed_call_is_refunded_and_reported():
    agents, ledger = aa.Agents(), FakeLedger()
    agents.start("o2", {"n": "2", "text": "x", "state": STATE, "lang": "ko", "account": "a@b.c"}, FakeModel(FakeEngine(fail=True)), FakeJobs(), ledger)
    v = wait(agents, "o2")
    assert v["status"] == "failed" and v["error"]
    assert [k for k, _ in ledger.log] == ["charge", "refund"] and ledger.credits == 10


def test_daily_limit_fails_without_a_call():
    eng = FakeEngine({"reply": "", "questions": [], "actions": []})
    agents = aa.Agents()
    agents.start("o3", {"n": "3", "text": "x", "state": STATE, "lang": "en"}, FakeModel(eng), FakeJobs(limit=True))
    assert agents.view("o3") == {"n": "3", "status": "failed", "error": "daily limit"} and not eng.prompts


def test_prompt_carries_words_and_language():
    p = aa.prompt_for(STATE, "make it softer", "ko")
    assert "make it softer" in p and "Korean" in p
