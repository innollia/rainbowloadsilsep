"""One real draft through the Claude CLI provider: `python tools/claude_cli_trial.py [out.wav]`.

Asks this PC's signed-in `claude` (asset_generate.ClaudeCli, the owner's subscription) for one short sfx patch,
renders it with the real engine (nkido) and measures it (NodeLint), through asset_generate.run. It spends the
subscription: at most two CLI calls (the first, and one repair), never a third. Prints the seconds of each call and
what came out."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asset_generate as ag  # noqa: E402
import studio_backend as sb  # noqa: E402
from asset_engine import nkido  # noqa: E402

CALLS = 2


def main(out: str = "") -> int:
    cli = ag.ClaudeCli(model=ag.claude_model(""))
    print("signed in:", cli.check(), "model:", cli.model)
    seconds = []

    def model():
        one = cli()
        ask = one.ask

        def limited(prompt, schema, name="reply"):
            if len(seconds) >= CALLS:
                raise sb.ModelError("claudecli_failed", detail="the trial allows two calls")
            began = time.monotonic()
            try:
                return ask(prompt, schema, name)
            finally:
                seconds.append(round(time.monotonic() - began, 1))
        one.ask = limited
        return one

    body = {"request_id": "trial", "expect_credits": 0, "drafts": 1, "project": {"game": "a small arcade game"},
            "items": [{"ref": "coin", "kind": "sfx", "name": "coin pickup", "description": "a short bright coin pickup blip",
                       "seconds": 0.4}]}
    req = ag.clean_request(body, "en")
    job = ag.Job(id="trial", project=req["project"], item=req["items"][0], examples=req["examples"],
                 deadline=time.time() + ag.JOB_SECONDS)
    deps = ag.Deps(model=model, engine=nkido, measure=ag.NodeLint(), model_name=cli.model)
    began = time.monotonic()
    outcome = ag.run(job, deps)
    total = round(time.monotonic() - began, 1)
    print("calls:", len(seconds), "seconds per call:", seconds, "whole draft:", total)
    print("status:", outcome.status, outcome.error, "usd:", outcome.usd)
    if outcome.status == "done":
        got = outcome.result
        print("source:\n" + got["source"])
        print("result:", json.dumps({k: got.get(k) for k in ("seconds", "rate", "channels", "bits", "repairs", "issues")}))
        print("measure:", json.dumps({k: got["measure"].get(k) for k in ("peak", "loud", "seconds", "lead", "tail", "end")}))
        if out:
            Path(out).write_bytes(outcome.wav)
            print("wav:", out, len(outcome.wav), "bytes")
    return 0 if outcome.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
