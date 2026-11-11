"""tools/akkado_trial.py --server: the trial's requests through asset_generate.run. No key and no engine: the fakes
of asset_generate, and a measure of the test's own except where Node measures."""
import importlib.util
import io
import json
import shutil
import sys
import wave
from pathlib import Path

import pytest

import asset_api
import asset_generate as ag
import asset_jobs as aj
import asset_token
import studio_backend as sb
from asset_engine import nkido

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("akkado_trial", ROOT / "tools" / "akkado_trial.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
COIN = ("sfx", "coin", "A bright coin pickup, two quick high notes.", 0.5)
BROKEN = nkido.RenderError("compile", "unknown word", 2)


class Lint:
    """measure() for Deps: every sound measures as fine, and `issues` is what the lint finds in it."""

    def __init__(self, issues=()):
        self.issues = list(issues)

    def __call__(self, wav, kind="sfx", loop=False, loud=(-20, -16)):
        with wave.open(io.BytesIO(wav)) as w:
            rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
        return {"measure": {"seconds": frames / rate, "rate": rate, "channels": channels, "bits": 16, "clips": 0,
                            "sample_peak": -10.0, "peak": -10.0, "loud": -18.0, "lead": 0.0, "tail": 0.0, "dc": 0.0,
                            "seam": 0.0, "end": -80.0},
                "issues": list(self.issues)}


def deps(model=None, engine=(), lint=None):
    model = model or ag.FakeModel()
    return ag.Deps(model=lambda: model, engine=ag.FakeEngine(engine), measure=lint or Lint(), model_name="fake"), model


def test_first_call(tmp_path):
    made, _ = deps()
    row = trial.serve(made, *COIN, tmp_path)
    assert (row["passed"], row["first_try"], row["error"], row["calls"], row["repairs"]) == (True, True, "", 1, 0)
    assert (row["issues"], row["cost"], row["loop"]) == ([], 0.0, False)
    assert (tmp_path / "coin.wav").read_bytes()[:4] == b"RIFF"
    assert (tmp_path / "coin.0.akkado").read_text(encoding="utf-8") == (tmp_path / "coin.akkado").read_text(encoding="utf-8")
    assert trial.served(row).split() == ["sfx", "coin", "pass", "first", "calls=1", "$0.0000", f"{row['seconds']:g}s"]


def test_the_request_is_the_body_of_a_job(tmp_path):
    made, model = deps()
    row = trial.serve(made, "ambience", "wind", "A seamless loop of gentle wind over an open field.", 8.0, tmp_path)
    asked = ag.request_of(model.prompts[0])
    assert (asked["item"]["kind"], asked["item"]["loop"], asked["item"]["seconds"]) == ("amb", True, 8.0)
    assert (asked["item"]["name"], asked["item"]["description"]) == ("wind", "A seamless loop of gentle wind over an open field.")
    assert asked["project"]["loud"] == list(ag.PROFILES["mobile"])
    assert (row["kind"], row["loop"], row["passed"]) == ("ambience", True, True)
    made, model = deps()
    row = trial.serve(made, "music", "victory", "A short victory fanfare, 2 bars at 120 BPM. Stems: melody, bass.", 4.0, tmp_path)
    assert ag.request_of(model.prompts[0])["item"]["loop"] is False
    assert (row["passed"], row["stems"]) == (True, ["melody", "bass"])


def test_passed_after_a_repair(tmp_path):
    made, model = deps(ag.FakeModel(cost=0.002), engine=[BROKEN])
    row = trial.serve(made, *COIN, tmp_path)
    assert (row["passed"], row["first_try"], row["calls"], row["repairs"]) == (True, False, 2, 1)
    assert row["cost"] == pytest.approx(0.004)
    assert "unknown word" in model.prompts[1]
    assert (tmp_path / "coin.0.akkado").exists() and (tmp_path / "coin.1.akkado").exists()
    assert [(tmp_path / f"coin.{call}.prompt.txt").read_text(encoding="utf-8") for call in (0, 1)] == model.prompts
    assert "pass repaired" in trial.served(row)


def test_a_reply_that_cannot_be_read_is_a_call_without_a_source(tmp_path):
    made, _ = deps(ag.FakeModel([sb.ModelError("openrouter_cut")]))
    row = trial.serve(made, *COIN, tmp_path)
    assert (row["passed"], row["first_try"], row["calls"]) == (True, False, 2)
    assert not (tmp_path / "coin.0.akkado").exists() and (tmp_path / "coin.1.akkado").exists()
    assert (tmp_path / "coin.0.prompt.txt").exists() and (tmp_path / "coin.1.prompt.txt").exists()


def test_failed(tmp_path):
    made, _ = deps(ag.FakeModel(cost=0.002), engine=[BROKEN] * (ag.REPAIRS + 1))
    row = trial.serve(made, *COIN, tmp_path)
    assert (row["passed"], row["first_try"], row["error"], row["calls"]) == (False, False, "make_failed", ag.REPAIRS + 1)
    assert row["cost"] == pytest.approx(0.002 * (ag.REPAIRS + 1))
    assert not (tmp_path / "coin.wav").exists() and not (tmp_path / "coin.akkado").exists()
    assert len(list(tmp_path.glob("coin.*.akkado"))) == ag.REPAIRS + 1
    assert "FAIL make_failed" in trial.served(row)


def test_issues_left_in_a_result_are_listed(tmp_path):
    made, _ = deps(lint=Lint([{"id": "dc", "level": "warn", "value": 0.01, "limit": 0.002}]))
    row = trial.serve(made, *COIN, tmp_path)
    assert (row["passed"], row["first_try"]) == (True, True)
    assert [issue["id"] for issue in row["issues"]] == ["dc"]
    assert trial.served(row).endswith("| left: dc(warn)")


def test_a_draft_that_raises_failed_as_internal(tmp_path):
    def broken(wav, **flags):
        raise RuntimeError("no measuring")

    made, _ = deps(lint=broken)
    row = trial.serve(made, *COIN, tmp_path)
    assert (row["passed"], row["error"], row["calls"]) == (False, "internal", 1)
    assert row["raised"] == "RuntimeError: no measuring"


@needs_node
def test_server_deps_are_the_apis_and_open_nothing_of_a_server(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_api, "LOCAL_FILES", tmp_path / "none")
    monkeypatch.setattr(asset_api, "DATA", tmp_path / "data")                 # where a local ledger file would be made
    monkeypatch.setattr(asset_token, "SECRET_FILE", tmp_path / "token.key")  # where a missing token key would be made
    named = {"OLMUSE_GEN_DB": str(tmp_path / "named.db"), "OLMUSE_RENDERS": str(tmp_path / "renders"),
             "STRUDEL_LOCAL_LEDGER": "1"}
    made = trial.server_deps(env={**named, "OLMUSE_GEN_FAKE": "1"})
    assert made.model is ag.FakeModel and isinstance(made.engine, ag.FakeEngine) and isinstance(made.measure, ag.NodeLint)
    assert made.model_name == ag.FakeModel.name
    made = trial.server_deps(env={**named, "OLMUSE_GEN_KEY": "not-a-key"})
    assert (made.model_name, made.engine) == (sb.DEFAULT_CHOICE, nkido)
    assert made.call_usd == aj.GEN_CALL_USD.get(sb.DEFAULT_CHOICE, aj.GEN_CALL_USD_OTHER)
    model = made.model()
    assert (model.model, model.effort) == (sb.DEFAULT_CHOICE, ag.EFFORT)
    made = trial.server_deps("some/other-model", env={**named, "OLMUSE_GEN_KEY": "not-a-key"})
    assert (made.model_name, made.call_usd) == ("some/other-model", aj.GEN_CALL_USD_OTHER)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(SystemExit, match="no model key"):
        trial.server_deps(env=named)


@needs_node
def test_main_with_the_fake_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OLMUSE_GEN_FAKE", "1")
    monkeypatch.setattr(sys, "argv", ["akkado_trial.py", "--server", "--limit", "3", "--out", str(tmp_path)])
    trial.main()
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[:4] for line in lines[:3]] == [["sfx", name, "pass", "first"] for name in ("ui_click", "ui_confirm", "ui_error")]
    assert lines[3].endswith("first-try 100%, after repair 100%")
    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    summary = saved["summary"]
    assert (summary["model"], summary["path"], summary["requests"]) == ("fake", "server", 3)
    assert (summary["first_try"], summary["after_repair"], summary["calls"], summary["sfx"]) == (3, 3, 3, "3/3/3")
    assert (summary["cost_usd"], summary["issues_left"], summary["failed"]) == (0.0, 0, {})
    assert [row["name"] for row in saved["rows"]] == ["ui_click", "ui_confirm", "ui_error"]
    assert all((tmp_path / f"{row['name']}.wav").exists() for row in saved["rows"])


def test_effort_is_not_taken_with_server(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["akkado_trial.py", "--server", "--effort", "low", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as stopped:
        trial.main()
    assert stopped.value.code == 2
    assert list(tmp_path.iterdir()) == []
