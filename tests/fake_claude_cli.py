"""Stands in for the Claude Code CLI in tests: `python fake_claude_cli.py <plan.json> <the CLI's own arguments>`.

The plan says what to do: write down what it was given (record), wait (sleep), print (stdout, stderr, or `answer`
as the structured output of a --output-format json result), exit with `code`. `auth status` prints plan["auth"].
Every start and end is a file in the folder plan["times"] when that is named, so a test can see how many ran at once."""
import json
import os
import sys
import time


def main():
    plan_path, args = sys.argv[1], sys.argv[2:]
    with open(plan_path, encoding="utf-8") as stream:
        plan = json.load(stream)
    if args[:2] == ["auth", "status"]:
        print(json.dumps(plan.get("auth", {"loggedIn": True, "authMethod": "claude.ai"})))
        return plan.get("auth_code", 0)
    stdin = sys.stdin.read()
    if plan.get("times"):  # one file per event: appends from several processes at once can be lost on Windows
        open(os.path.join(plan["times"], f"start {time.time()} {os.getpid()}"), "w").close()
    if plan.get("record"):
        here = os.getcwd()
        with open(plan["record"], "w", encoding="utf-8") as stream:
            json.dump({"args": args, "stdin": stdin, "cwd": here, "files": os.listdir(here), "env": dict(os.environ)}, stream)
    time.sleep(float(plan.get("sleep", 0)))
    if plan.get("times"):
        open(os.path.join(plan["times"], f"end {time.time()} {os.getpid()}"), "w").close()
    if "answer" in plan:
        sys.stdout.write(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "",
                                     "structured_output": plan["answer"], "total_cost_usd": 0.05}))
    sys.stdout.write(plan.get("stdout", ""))
    sys.stderr.write(plan.get("stderr", ""))
    return int(plan.get("code", 0))


if __name__ == "__main__":
    sys.exit(main())
