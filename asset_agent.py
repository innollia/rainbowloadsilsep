"""The asset board's resident agent: one model call reads the board and the user's words and returns
changes for the page to apply (references, groups, names, descriptions, remakes) plus a short reply.

Calls go through the music screen's model choice, daily limits and credits; a failed call is refunded.
"""
from __future__ import annotations

import json
import secrets
import threading
import time

from credits import LedgerError, call_cost
from studio_backend import AgyCli, ModelError, lang_of, restart_message

OPS = ["add_ref", "remove_ref", "move", "rename", "describe", "set_when", "add_cat", "set_brief", "revise", "select"]
STATE_CHARS = 60000

SYSTEM = """You are the sound assistant that lives on a game's sound asset board. A game developer talks to you;
you read the board and change it for them through actions the page applies. You never hear sounds.

Actions (fill every field; use "" or [] for fields an action does not use):
- add_ref: attach a reference. target is "project", "cat:<group id>" or "asset:<sound id>". kind "text" for a note
  (text holds it, name is a short title) or "link" (url plus a short note in text). A project or group reference
  reaches every sound in it. Files cannot be attached by you; ask the user to add the file from the reference panel.
- remove_ref: target as above, name is the reference title to drop.
- move: assets are sound ids, cat is the group id they go to.
- rename: assets holds one sound id, name is its new display name.
- describe: assets, text is the new description (what the sound is and how it should feel).
- set_when: assets, text is when the game plays it.
- add_cat: cat is a new lowercase english id, name its display name, kind sfx|amb|music, parent an existing group id or "".
- set_brief: text is the project's style brief.
- revise: assets, text is how their sound should change; the board remakes them.
- select: assets to show the user (for questions like "which ones are too long?").
Act only on what the user asked. Never invent sound ids or group ids that are not on the board (except a new add_cat id).
"selected" lists the sounds the user has picked; "this", "these", "these sounds" mean them.
reply: one to three short sentences in the user's language saying what you did or answering them.
questions: empty unless you truly need the user to choose before acting."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "object", "properties": {
            "op": {"type": "string", "enum": OPS}, "target": {"type": "string"},
            "assets": {"type": "array", "items": {"type": "string"}}, "cat": {"type": "string"},
            "name": {"type": "string"}, "kind": {"type": "string"}, "parent": {"type": "string"},
            "text": {"type": "string"}, "url": {"type": "string"}},
            "required": ["op", "target", "assets", "cat", "name", "kind", "parent", "text", "url"]}},
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
            "recommended": {"type": "string"}}, "required": ["question", "options", "recommended"]}},
    },
    "required": ["reply", "actions", "questions"],
}


def prompt_for(state: dict, message: str, lang: str) -> str:
    board = json.dumps(state, ensure_ascii=False)[:STATE_CHARS]
    head = f"The user says:\n{message}"
    language = "Korean" if lang == "ko" else "English"
    return f"{head}\n\nBoard (JSON):\n{board}\n\nWrite reply and questions in {language}."


def clean(reply: dict, state: dict) -> dict:
    """Keeps only actions that point at things on the board; the page applies them as they come."""
    ids = {a.get("id") for a in state.get("assets") or [] if isinstance(a, dict)}
    cats = {c.get("id") for c in state.get("cats") or [] if isinstance(c, dict)}
    out = []
    for a in (reply.get("actions") or [])[:300]:
        if not isinstance(a, dict) or a.get("op") not in OPS:
            continue
        a = {k: a.get(k) for k in SCHEMA["properties"]["actions"]["items"]["properties"]}
        a["assets"] = [x for x in (a.get("assets") or []) if x in ids][:500]
        if a["op"] == "add_cat":
            cats.add(a.get("cat"))
        if a["op"] in ("move", "rename", "describe", "set_when", "revise", "select") and not a["assets"]:
            continue
        if a["op"] == "move" and a.get("cat") not in cats:
            continue
        target = str(a.get("target") or "")
        if a["op"] in ("add_ref", "remove_ref") and not (target == "project" or (target.startswith("cat:") and target[4:] in cats)
                                                         or (target.startswith("asset:") and target[6:] in ids)):
            continue
        out.append({k: (v if isinstance(v, list) else str(v or "")[:2000]) for k, v in a.items()})
    questions = [{"question": str(q.get("question", ""))[:300], "options": [str(o)[:120] for o in (q.get("options") or [])][:4],
                  "recommended": str(q.get("recommended", ""))[:120]}
                 for q in (reply.get("questions") or [])[:6] if isinstance(q, dict) and q.get("question")]
    return {"reply": str(reply.get("reply") or "")[:1200], "actions": out, "questions": questions}


def ask(engine, prompt: str) -> dict:
    if hasattr(engine, "ask"):
        return engine.ask(prompt, SCHEMA, "board_actions")
    if isinstance(engine, AgyCli):
        return engine._run(prompt, SCHEMA)
    if engine.__class__.__name__ == "Gemini":
        return engine._call([{"text": prompt}], SCHEMA)
    return engine._call(prompt, SCHEMA)


class Agents:
    """One running call per owner; the page polls the answer through the render args."""

    def __init__(self, store=None, ledger=None):
        """store (studio_backend.JobStore) keeps views across a restart; a call cut off by one is failed and refunded."""
        self.lock = threading.Lock()
        self.store = store
        self.views: dict[str, dict] = {}
        if store:
            self.views = store.recover("agent", ledger, "working", self._restart_failed)

    @staticmethod
    def _restart_failed(view: dict, lang: str, refunded: int):
        view.update(status="failed", error=restart_message(lang, refunded))

    def view(self, owner: str):
        return self.views.get(owner)

    def _set(self, owner: str, view: dict, lang: str = ""):
        with self.lock:
            self.views[owner] = view
            if self.store:
                self.store.save("agent", owner, view, lang_of(lang))

    def fail(self, owner: str, n, error: str):
        self._set(owner, {"n": str(n or "")[:60], "status": "failed", "error": error})

    def start(self, owner: str, request: dict, model, jobs, ledger=None):
        lang = lang_of(request.get("lang"))
        n = str(request.get("n") or "")[:60]
        with self.lock:
            current = self.views.get(owner)
            if current and current.get("status") == "working":
                raise ValueError("busy" if lang != "ko" else "에이전트가 아직 앞의 말을 처리하고 있어요.")
            self.views[owner] = {"n": n, "status": "working"}
            if self.store:
                self.store.save("agent", owner, self.views[owner], lang)
        try:
            jobs.count_call(request.get("account", ""), owner, lang)
        except ValueError as exc:
            self.fail(owner, n, str(exc))
            return
        threading.Thread(target=self._run, args=(owner, n, request, model, ledger, lang), daemon=True).start()

    def _run(self, owner, n, request, model, ledger, lang):
        email, cost, ref = request.get("account", ""), 0, None
        view = {"n": n, "status": "done"}
        try:
            if ledger and email:
                cost = call_cost(request.get("model", ""), request.get("effort", ""))
                ref = f"agent:{owner[-12:]}:{secrets.token_hex(4)}:{int(time.time())}"
                ok, credits = ledger.charge(email, cost, ref)
                view["credits"] = credits
                if not ok:
                    ref = None
                    raise ValueError("크레딧이 모자라요." if lang == "ko" else "Out of credits.")
                if self.store:
                    self.store.charged("agent", owner, email, cost, ref)
            if hasattr(model, "engine"):
                engine = model.engine(request.get("model", ""), request.get("effort", ""), system=SYSTEM)
            else:  # the local agy runner: same program, the board's own instructions
                engine = AgyCli(model.executable, model.model, system=SYSTEM)
            state = request.get("state") if isinstance(request.get("state"), dict) else {}
            reply = ask(engine, prompt_for(state, str(request.get("text") or "")[:4000], lang))
            view.update(clean(reply if isinstance(reply, dict) else {}, state))
        except (ModelError, ValueError, LedgerError, OSError) as exc:
            if ref:
                try:
                    view["credits"] = ledger.refund(email, cost, ref)
                except LedgerError:
                    pass
            view.update(status="failed", error=exc.text(lang) if isinstance(exc, ModelError) else str(exc))
        if ref and self.store:
            self.store.settled(ref)
        self._set(owner, view, lang)
