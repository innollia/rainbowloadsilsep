"""Bakeoff tool (bakeoff/): recorded jobs, budget stop, codex parsing, blind-listening tally."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bakeoff"))

import core  # noqa: E402
import harness  # noqa: E402
import listen_store  # noqa: E402
import run  # noqa: E402
import studio_backend as sb  # noqa: E402
from test_studio_backend import Fake, drive  # noqa: E402

CONFIG = {
    "settings": {"rounds": 2, "effort": "medium", "lang": "ko", "auto": True},
    "tasks": [{"id": "1", "star": True, "text": "하우스"}, {"id": "2", "star": False, "text": "로파이"}],
    "models": [{"id": "fake/cheap", "via": "openrouter", "tier": "초저가", "tasks": "all", "reps": 1, "job_max_usd": 0.01},
               {"id": "fake/top", "via": "openrouter", "tier": "고가", "tasks": "star", "reps": 2, "job_max_usd": 1}],
    "budget": {"over_factor": 1.3, "openrouter_floor_usd": 0.2},
}


class PricedFake(Fake):
    """Every call costs 0.006, like an OpenRouter reply's usage.cost."""

    def edit(self, prompt):
        self.last_usage = {"cost": 0.006}
        return super().edit(prompt)

    def listen(self, data, prompt):
        self.last_usage = {"cost": 0.006}
        return super().listen(data, prompt)


@pytest.fixture
def bench(tmp_path, monkeypatch):
    control = tmp_path / "control.json"
    monkeypatch.setenv("BAKEOFF_CONTROL", str(control))
    monkeypatch.setattr(sb, "Progress", harness.Progress)
    monkeypatch.setattr(sb, "merge_candidate", harness.merge_candidate)
    monkeypatch.setattr(core, "build_engine", lambda model, effort="medium", system=None: PricedFake())
    jobs = harness.BakeoffJobs(daily_limit=100)
    monkeypatch.setattr(sb, "_bakeoff_jobs", jobs, raising=False)

    def run_job(model, task, owner):
        log = core.job_log(model["id"], task["id"], 1, tmp_path)
        control.write_text(json.dumps({"model": model, "log": str(log), "task": task["id"], "rep": 1}), encoding="utf-8")
        jobs.submit(owner, sb.validate_request({"text": task["text"], "tracks": [], "bpm": 120, "auto": True, "rounds": 2}))
        drive(jobs, owner)
        for _ in range(200):  # the end line is written as the job thread finishes
            if core.end_of(core.read_jsonl(log)):
                break
            import time
            time.sleep(0.01)
        return log

    return tmp_path, run_job


def test_two_fake_jobs_leave_logs_wavs_and_spend(bench):
    root, run_job = bench
    model = CONFIG["models"][0]
    logs = [run_job(model, task, f"o{n}") for n, task in enumerate(CONFIG["tasks"])]
    for log in logs:
        records = core.read_jsonl(log)
        kinds = [r["kind"] for r in records]
        assert kinds[0] == "start" and kinds[-1] == "end" and "edit" in kinds and "listen" in kinds
        end = core.end_of(records)
        assert core.outcome(records) == "success" and end["rounds_listened"] >= 1
        assert log.with_name(f"{log.stem}-r1.wav").read_bytes().startswith(b"RIFF")
        assert end["final_song"]["tracks"]
    assert core.model_spent(model["id"], root) == pytest.approx(sum(core.spent(core.read_jsonl(p)) for p in logs))
    assert core.model_spent(model["id"], root) > 0


def test_budget_stops_a_model_past_its_cap(bench, monkeypatch):
    root, run_job = bench
    monkeypatch.setattr(core, "openrouter_left", lambda key: 5.0)
    monkeypatch.setattr(core, "load_config", lambda path=None: CONFIG)
    model = CONFIG["models"][0]  # cap: 2 jobs x $0.01 x 1.3 = $0.026; one fake job spends at least $0.018
    budget = run.Budget(CONFIG, root)
    assert budget.allows(model)[0]
    run_job(model, CONFIG["tasks"][0], "a")
    run_job(model, CONFIG["tasks"][1], "b")
    allowed, why = budget.allows(model)
    assert not allowed and "model budget" in why
    assert budget.allows({"id": "x", "via": "codex"})[0]  # subscription CLIs are not metered


def test_budget_stops_everything_near_an_empty_account(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "openrouter_left", lambda key: 0.1)
    allowed, why = run.Budget(CONFIG, tmp_path).allows(CONFIG["models"][1])
    assert not allowed and "nearly empty" in why


def test_plan_and_resume(tmp_path):
    jobs = core.plan_jobs(CONFIG)
    assert len(jobs) == 2 + 2  # cheap: both tasks once; top: star task twice
    assert len(core.plan_jobs(CONFIG, models=["fake/top"], reps=1)) == 1
    model, task = CONFIG["models"][0], CONFIG["tasks"][0]
    log = core.job_log(model["id"], task["id"], 1, tmp_path)
    assert run.job_state(model, task, 1, tmp_path) == "todo"
    core.append_jsonl(log, {"kind": "end", "status": "failed", "error": "harness", "messages": []})
    assert run.job_state(model, task, 1, tmp_path) == "retry"
    run.set_aside(log)
    assert not log.exists() and run.job_state(model, task, 1, tmp_path) == "todo"
    core.append_jsonl(log, {"kind": "end", "status": "failed", "error": "harness", "messages": []})
    assert run.job_state(model, task, 1, tmp_path) == "done"  # one rerun only


def test_model_failure_is_not_infrastructure():
    records = [{"kind": "edit", "error": "openrouter_parse"},
               {"kind": "end", "status": "failed", "messages": [], "rounds_listened": 0}]
    assert core.outcome(records) == "fail"
    records[0]["error"] = "openrouter_quota"
    assert core.outcome(records) == "infra"


def test_codex_reads_answer_and_usage():
    cli = core.CodexCli("gpt-5.6-luna")
    out = b'{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3,"reasoning_output_tokens":1}}\n'
    usage = cli.usage_of(out)
    assert usage["input"] == 10 and usage["cost"] == 0 and usage["billing"] == "subscription"
    assert cli.parse('{"summary": "x"}') == {"summary": "x"}
    with pytest.raises(sb.ModelError) as err:
        cli.parse("", b'{"type":"turn.failed","error":"usage limit"}')
    assert core.error_key(err.value) == "codex_failed"


def test_listen_votes_and_tally(tmp_path):
    manifest = {"tasks": [{"id": "1", "clips": [
        {"clip": "a1", "model": "good"}, {"clip": "b1", "model": "bad"}, {"clip": "c1", "model": "mid"},
        {"clip": "d1", "model": "good", "dup_of": "a1"}]}]}
    votes = listen_store.Votes(tmp_path / "v.sqlite")
    for voter, scores in {"민지": {"a1": 9, "b1": 2, "c1": 5, "d1": 8}, "준": {"a1": 7, "b1": 3, "c1": 6}}.items():
        for clip, score in scores.items():
            votes.save(voter, "1", clip, score=score)
    votes.save("준", "1", "b1", mismatch=True)
    assert votes.mine("준")[("1", "b1")] == {"score": 3, "mismatch": True}  # a mismatch mark keeps the score
    result = listen_store.tally(manifest, votes.all())
    assert [r["model"] for r in result["models"]] == ["good", "mid", "bad"]
    assert result["models"][-1]["mismatch"] == 1 and result["voters"] == 2
    assert result["consistency"] == [{"voter": "민지", "task": "1", "gap": 1}]
    assert {p["voter"]: p["rated"] for p in listen_store.progress(manifest, votes.all())} == {"민지": 4, "준": 3}
    with pytest.raises(ValueError):
        votes.save("", "1", "a1", score=5)
    with pytest.raises(ValueError):
        votes.save("x", "1", "a1", score=11)


def test_each_listener_gets_a_stable_order_of_their_own():
    task = {"id": "1", "clips": [{"clip": str(n)} for n in range(6)]}
    first = [c["clip"] for c in listen_store.order_for("민지", task)]
    assert first == [c["clip"] for c in listen_store.order_for("민지", task)]
    assert any([c["clip"] for c in listen_store.order_for(name, task)] != first for name in ("준", "하나", "도윤"))
