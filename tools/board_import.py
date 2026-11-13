"""Put a folder of game sounds on an account's board kept on the server, as a new board (docs/ASSET_SYNC_SPEC.md J).

  python tools/board_import.py FOLDER --email kid@example.com [--home] [--local] [--dry-run]
  python tools/board_import.py FOLDER --email kid@example.com --into BOARD     fill an existing board instead

FOLDER is what the asset room opens as a bundle: a spec (game-audio.spec.json, else any .json with an `assets` list),
the sounds (WAV, by the spec's `file` or named <id>.wav anywhere under FOLDER), and optionally the Akkado patches
(<id>.akkado), which make those versions nkido versions the room can revise. tools/board_import.js turns the folder
into the board's records with the page's own measure.js, store.js and board.js, so the board is the one the page
would have made; this file uploads the sound bytes and writes the records the way a browser's sync does.

--into BOARD fills a board the account already has (one made from the same list of sounds): a sound whose id is on
it, outside the bin and not being made, gets the folder's sound as a new version that becomes its current one and is
approved; its earlier versions and its own fields stay. A sound the board does not have is added. Categories the
added sounds need are added; the board's game, rules, references and other sounds are left as they are.

Without --into the board is new and the account is its owner. --home makes it the board the account's devices open next; without it
the account finds it in the board list. Works beside a running API (admin mode, like tools/board_admin.py).
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import asset_boards as ab  # noqa: E402
import board_admin  # noqa: E402

DEV = "b0a2d1e0" + "0" * 8  # the device id this tool writes as (16 hex)


def records_of(folder: str) -> dict:
    out = subprocess.run(["node", str(ROOT / "tools" / "board_import.js"), folder], capture_output=True, timeout=600)
    if out.returncode != 0:
        raise SystemExit("board_import.js: " + out.stderr.decode("utf-8", "replace").strip())
    return json.loads(out.stdout.decode("utf-8"))


def upload(store: ab.BoardStore, owner: str, board: str, blob: dict, chunk: int):
    data = Path(blob["path"]).read_bytes()
    at, size = 0, len(data)
    while True:
        got = store.chunk(owner, board, blob["sha"], at, size, data[at:at + chunk])
        if got.get("done"):
            return
        at = got["at"]


def run(argv=None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Put a folder of game sounds on an account's board.")
    ap.add_argument("folder")
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", default="")
    who.add_argument("--owner", default="")
    ap.add_argument("--home", action="store_true", help="open this board next on the account's devices")
    ap.add_argument("--into", default="", help="an existing board of the account to fill")
    ap.add_argument("--db", default="")
    ap.add_argument("--blobs", default="")
    ap.add_argument("--local", action="store_true", help="the boards of a local or scripted run")
    ap.add_argument("--dry-run", action="store_true", help="build and check the records, write nothing")
    args = ap.parse_args(argv)

    made = records_of(args.folder)
    out(f"{made['game']}: {len(made['records'])} records, {len(made['blobs'])} sound files")
    if args.dry_run:
        return 0
    owner = board_admin.owner_of(args.email, args.owner)
    store = board_admin.open_store(args.db, args.blobs, args.local)
    try:
        if args.into:
            board, (written, bad, skipped) = args.into, fill(store, owner, args.into, made)
            for line in skipped:
                out("left alone " + line)
        else:
            board, written, bad = put(store, owner, made, args.home)
    finally:
        store.close()
    for line in bad:
        out("refused " + line)
    out(f"board {board}: {written} of {written + len(bad)} records written" + (", home" if args.home else ""))
    return 1 if bad else 0


def write(store: ab.BoardStore, owner: str, board: str, ops: list) -> tuple[int, list[str]]:
    bad = []
    for start in range(0, len(ops), store.limits.OPS_MAX):
        res = store.sync(owner, board, DEV, 0, ops[start:start + store.limits.OPS_MAX])
        for op, r in zip(ops[start:], res["results"]):
            if "rev" not in r and "same" not in r:
                bad.append(f"{op['kind']}/{op['uid']}: {json.dumps(r, ensure_ascii=False)[:200]}")
    return len(ops) - len(bad), bad


def fill(store: ab.BoardStore, owner: str, board: str, made: dict) -> tuple[int, list[str], list[str]]:
    """(records written, refusals, sounds left alone) for --into: see the module's text."""
    ab.board_id(board)
    with store.lock:
        store._member(owner, board)
    rows = {(r["kind"], r["uid"]): r for r in store.records(board) if not r["gone"]}
    now = {key: store.history(board, *key)[0] for key in rows if key[0] in ("asset", "cat")}
    live = {}
    for (kind, uid), h in now.items():
        d = h["data"]
        if kind == "asset" and not d.get("trashedAt"):
            live.setdefault(d.get("id"), (uid, h["rev"], d))
    cats = {uid for kind, uid in now if kind == "cat"}
    for blob in made["blobs"]:
        upload(store, owner, board, blob, store.limits.CHUNK_MAX)
    ops, skipped, need = [], [], set()
    for kind, uid, data in made["records"]:
        if kind != "asset" or not data.get("versions"):
            continue
        mine = data["versions"][0]
        found = live.get(data["id"])
        if found is None:
            ops.append({"kind": "asset", "uid": uid, "base": 0, "data": data})
            need.add(data["cat"])
            continue
        their_uid, rev, theirs = found
        if theirs.get("work"):
            skipped.append(f"{data['id']}: it is being made")
            continue
        if any(v.get("sha256") == mine["sha256"] for v in theirs.get("versions") or []):
            skipped.append(f"{data['id']}: it already has this sound")
            continue
        new = dict(theirs, versions=[*(theirs.get("versions") or []), mine], cur=mine["id"], status="approved")
        ops.append({"kind": "asset", "uid": their_uid, "base": rev, "data": new})
    for kind, uid, data in made["records"]:
        if kind == "cat" and uid in need and uid not in cats:
            ops.insert(0, {"kind": "cat", "uid": uid, "base": 0, "data": data})
    written, bad = write(store, owner, board, ops)
    return written, bad, skipped


def put(store: ab.BoardStore, owner: str, made: dict, home: bool = False) -> tuple[str, int, list[str]]:
    """(the new board's id, records written, refusals): the sound files first, then the records that point at them."""
    board = secrets.token_hex(16)
    store.make(owner, board, first=False, home=home)
    for blob in made["blobs"]:
        upload(store, owner, board, blob, store.limits.CHUNK_MAX)
    ops = [{"kind": k, "uid": u, "base": 0, "data": d} for k, u, d in made["records"]]
    written, bad = write(store, owner, board, ops)
    return board, written, bad

if __name__ == "__main__":
    sys.exit(run())
