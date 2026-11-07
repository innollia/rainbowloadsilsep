"""Shared pieces of the model bakeoff (docs/MODEL_BAKEOFF_PLAN.md): config, result files, engines, recorder.

Nothing here is used by the product. Keys are read from ~/.all-tomorrow/key-pool.env and never written anywhere.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import studio_backend as sb  # noqa: E402

CONFIG = HERE / "tasks.json"
RESULTS = HERE / "results"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Failures that are ours (network, rate limit, browser), not the model's: rerun once.
INFRA_ERRORS = ("openrouter_quota", "openrouter_conn", "agy_missing", "agy_timeout", "codex_missing", "codex_timeout",
                "no_browser", "harness", "bad_capture")


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def key_pool() -> dict:
    try:
        lines = (Path.home() / ".all-tomorrow" / "key-pool.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    pairs = (line.removeprefix("export ").split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))
    return {name.strip(): value.strip().strip("'\"") for name, value in pairs}


def openrouter_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY") or key_pool().get("OPENROUTER_API_KEY", "")


def slug(model_id: str) -> str:
    return model_id.replace("/", "__").replace(":", "_")


def job_name(task: str, rep: int) -> str:
    return f"{task}-{rep}"


def job_log(model_id: str, task: str, rep: int, root: Path = RESULTS) -> Path:
    return Path(root) / slug(model_id) / f"{job_name(task, rep)}.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass  # a line cut by a crash
    return out


def append_jsonl(path: Path, record: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def end_of(records: list[dict]) -> dict | None:
    return next((r for r in reversed(records) if r.get("kind") == "end"), None)


def spent(records: list[dict]) -> float:
    return sum(float((r.get("usage") or {}).get("cost") or 0) for r in records)


def model_spent(model_id: str, root: Path = RESULTS) -> float:
    folder = Path(root) / slug(model_id)
    return sum(spent(read_jsonl(p)) for p in folder.rglob("*.jsonl")) if folder.exists() else 0.0


def plan_jobs(config: dict, models=None, tasks=None, reps=None) -> list[dict]:
    """Every (model, task, rep) the config assigns, narrowed by the command line."""
    out = []
    for m in config["models"]:
        if models and m["id"] not in models and slug(m["id"]) not in models:
            continue
        mine = [t for t in config["tasks"] if m.get("tasks", "all") == "all" or t.get("star")]
        for t in mine:
            if tasks and t["id"] not in tasks:
                continue
            for rep in range(1, (reps or m.get("reps", 1)) + 1):
                out.append({"model": m, "task": t, "rep": rep})
    return out


def model_cap(model: dict, config: dict) -> float:
    """Most this model may spend: planned jobs x per-job maximum x the overrun factor (plan 8.4)."""
    jobs = len(plan_jobs(config, models=[model["id"]]))
    return jobs * float(model.get("job_max_usd", 0)) * float(config["budget"]["over_factor"])


def openrouter_left(key: str) -> float | None:
    """Credits left on the account, or None when the check itself failed."""
    import urllib.request

    try:
        req = urllib.request.Request(OPENROUTER_URL + "/credits", headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.load(res)["data"]
        return float(data["total_credits"]) - float(data["total_usage"])
    except Exception:
        return None


# ---------- engines ----------
def codex_command() -> list[str]:
    """Run codex.js with node directly: a .cmd shim would re-parse the TOML quotes in -c."""
    roots = [Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"]
    try:
        roots.append(Path(subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, shell=os.name == "nt",
                                         timeout=30).stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for root in roots:
        script = root / "@openai" / "codex" / "bin" / "codex.js"
        if script.exists():
            return [shutil.which("node") or "node", str(script)]
    found = shutil.which("codex")
    return [found] if found else []


class CodexCli:
    """GPT models through the logged-in OpenAI Codex CLI (subscription, so no per-call price).

    Runs tool-free in an empty read-only temp folder. No audio input: listening is measurement analysis."""

    name = "Codex CLI"
    hears = False
    TIMEOUT = 300

    def __init__(self, model: str, effort: str = "medium", system: str | None = None, command: list | None = None):
        self.model, self.effort = model, effort
        self.system = sb.SYSTEM if system is None else system
        self.command = command
        self.process = None
        self.last_usage: dict = {}

    def _run(self, prompt: str, schema_def: dict) -> dict:
        command = self.command or codex_command()
        if not command:
            raise sb.ModelError("codex_missing: Codex CLI not found")
        text = self.system + "\nDo not run any commands or use any tools. Reply only with the JSON object.\n\n" + prompt
        with tempfile.TemporaryDirectory(prefix="olmuse-codex-") as folder:
            schema, last = os.path.join(folder, "schema.json"), os.path.join(folder, "last.txt")
            with open(schema, "w", encoding="utf-8") as stream:
                json.dump(sb.strict_schema(sb.plain_schema(schema_def)), stream)
            args = command + ["exec", "-m", self.model, "-c", f'model_reasoning_effort="{self.effort}"', "-s", "read-only",
                              "--skip-git-repo-check", "--ephemeral", "--ignore-rules", "--color", "never",
                              "--output-schema", schema, "-o", last, "--json", "-"]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                self.process = subprocess.Popen(args, cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, creationflags=flags)
                out, err = self.process.communicate(text.encode("utf-8"), timeout=self.TIMEOUT)
            except OSError:
                raise sb.ModelError("codex_missing: Codex CLI could not start") from None
            except subprocess.TimeoutExpired:
                self.stop()
                raise sb.ModelError("codex_timeout: Codex CLI did not finish in time") from None
            self.last_usage = self.usage_of(out)
            try:
                answer = Path(last).read_text(encoding="utf-8")
            except OSError:
                answer = ""
        return self.parse(answer, out, err)

    def usage_of(self, out: bytes) -> dict:
        usage = {}
        for line in out.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "turn.completed":
                usage = event.get("usage") or {}
        return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
                "reasoning": usage.get("reasoning_output_tokens", 0), "cached": usage.get("cached_input_tokens", 0),
                "cost": 0.0, "billing": "subscription", "model": self.model, "provider": "codex"}

    @staticmethod
    def parse(answer: str, out: bytes = b"", err: bytes = b"") -> dict:
        try:
            reply = json.loads(answer)
        except ValueError:
            failure = ""
            for line in out.decode("utf-8", "replace").splitlines():
                if '"error"' in line or '"turn.failed"' in line:
                    failure = line
            detail = sb.redact(failure or err.decode("utf-8", "replace")[-300:])
            raise sb.ModelError(f"codex_failed: {detail}") from None
        if not isinstance(reply, dict):
            raise sb.ModelError("codex_failed: reply is not an object")
        return reply

    def stop(self):
        process = self.process
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
            else:
                process.kill()

    def edit(self, prompt: str) -> dict:
        return self._run(prompt, sb.EDIT_SCHEMA)

    def listen(self, wav: bytes, prompt: str) -> dict:
        return self._run(sb.measured_prompt(wav, prompt), sb.LISTEN_SCHEMA)


def build_engine(model: dict, effort: str = "medium", system: str | None = None):
    via = model["via"]
    if via == "openrouter":
        return sb.OpenRouter(openrouter_key(), model["id"], effort, system=system)
    if via == "agy":
        return sb.AgyCli(model=model.get("agy_model", ""), system=system)
    if via == "codex":
        return CodexCli(model["id"], effort, system=system)
    raise ValueError(f"unknown connection {via}")


def error_key(exc: Exception) -> str:
    key = getattr(exc, "key", "") or str(exc)
    return key.split(":", 1)[0]


class Recorder:
    """Wraps one job's engine. Every call leaves a line in the job log; every capture is kept as a WAV."""

    def __init__(self, inner, log: Path):
        self.inner, self.log = inner, Path(log)
        self.hears = getattr(inner, "hears", False)
        self.name = getattr(inner, "name", "")
        self.listens = 0

    def note(self, **record):
        append_jsonl(self.log, {"t": round(time.time(), 3), **record})

    def _call(self, kind: str, call, *args) -> dict:
        start = time.monotonic()
        try:
            reply = call(*args)
        except Exception as exc:
            self.note(kind=kind, seconds=round(time.monotonic() - start, 2), usage=getattr(self.inner, "last_usage", {}),
                      error=error_key(exc), detail=sb.redact(getattr(exc, "fields", {}) or exc))
            raise
        self.note(kind=kind, seconds=round(time.monotonic() - start, 2), usage=getattr(self.inner, "last_usage", {}),
                  reply=reply)
        return reply

    def edit(self, prompt: str) -> dict:
        return self._call("edit", self.inner.edit, prompt)

    def listen(self, wav: bytes, prompt: str) -> dict:
        self.listens += 1
        path = self.log.with_name(f"{self.log.stem}-r{self.listens}.wav")
        path.write_bytes(wav)
        return self._call("listen", self.inner.listen, wav, prompt)

    def stop(self):
        getattr(self.inner, "stop", lambda: None)()


def shuffled(jobs: list, seed: int = 7) -> list:
    """Models and tasks mixed, so time-of-day speed differences spread evenly (plan 5)."""
    out = list(jobs)
    random.Random(seed).shuffle(out)
    return out


def infra_failure(records: list[dict]) -> bool:
    """Our side broke (network, rate limit, browser, capture), not the model."""
    end = end_of(records)
    if not end or end.get("status") not in ("failed", "cancelled"):
        return False
    if end.get("error") == "harness":
        return True
    calls = [r for r in records if r.get("kind") in ("edit", "listen")]
    if calls and calls[-1].get("error") in INFRA_ERRORS:
        return True
    texts = " ".join(m.get("text", "") for m in end.get("messages", []))
    marks = [sb.msg(lang, key) for lang in sb.LANGS for key in ("no_browser", "bad_capture_data", "bad_capture_file")]
    return any(mark in texts for mark in marks)


def outcome(records: list[dict]) -> str:
    """success: a song that runs was left (done, or rounds used up). Plan 5: fix_limit, run_failed, model errors fail."""
    end = end_of(records)
    if end is None:
        return "missing"
    if infra_failure(records):
        return "infra"
    if end.get("status") in ("done", "limit") and end.get("rounds_listened", 0) >= 1:
        return "success"
    return "fail"
