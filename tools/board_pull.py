"""Take a board's sounds back into a folder: the way back from tools/board_import.py (docs/ASSET_SYNC_SPEC.md J).

  python tools/board_pull.py BOARD OUT --email kid@example.com [--approved] [--local]

For every sound on the board (outside the bin) it writes OUT/<id>.wav, the bytes of the sound's current version, and
OUT/<id>.akkado when that version is an nkido version with its patch. OUT/board.json lists each sound: id, name,
status, the current version's sha256, engine and note, and how many versions it has, so a game folder can see which
sounds were changed or approved on the board. --approved writes the files of approved sounds only (board.json still
lists every sound). Works beside a running API (admin mode, like tools/board_admin.py); it writes nothing to the board.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import board_admin  # noqa: E402


def current(d: dict) -> dict | None:
    vs = d.get("versions") or []
    return next((v for v in vs if v.get("id") == d.get("cur")), vs[-1] if vs else None)


def sounds(store, board: str) -> list[dict]:
    """The board's live sounds, newest record of each, as their data."""
    out = []
    for r in store.records(board):
        if r["kind"] != "asset" or r["gone"]:
            continue
        d = store.history(board, "asset", r["uid"])[0]["data"]
        if not d.get("trashedAt") and d.get("id"):
            out.append(d)
    return sorted(out, key=lambda d: d["id"])


def pull(store, owner: str, board: str, out_dir: Path, approved_only: bool = False) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    listed = []
    for d in sounds(store, board):
        v = current(d)
        row = {"id": d["id"], "name": d.get("name", d["id"]), "status": d.get("status", ""), "versions": len(d.get("versions") or []),
               "sha256": v.get("sha256") if v else None, "engine": v.get("engine") if v else None,
               "note": (v.get("note") or {}).get("key") if v and isinstance(v.get("note"), dict) else (v or {}).get("note"),
               "wrote": False}
        if v and v.get("sha256") and (not approved_only or row["status"] == "approved"):
            path, _ = store.blob(owner, board, v["sha256"])
            shutil.copyfile(path, out_dir / f"{d['id']}.wav")
            if v.get("source"):
                (out_dir / f"{d['id']}.akkado").write_text(v["source"], encoding="utf-8")
            row["wrote"] = True
        listed.append(row)
    (out_dir / "board.json").write_text(json.dumps({"board": board, "sounds": listed}, ensure_ascii=False, indent=1), encoding="utf-8")
    return listed


def run(argv=None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Take a board's sounds back into a folder.")
    ap.add_argument("board")
    ap.add_argument("out")
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", default="")
    who.add_argument("--owner", default="")
    ap.add_argument("--approved", action="store_true", help="write the files of approved sounds only")
    ap.add_argument("--db", default="")
    ap.add_argument("--blobs", default="")
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args(argv)
    owner = board_admin.owner_of(args.email, args.owner)
    store = board_admin.open_store(args.db, args.blobs, args.local)
    try:
        listed = pull(store, owner, args.board, Path(args.out), args.approved)
    finally:
        store.close()
    wrote = sum(r["wrote"] for r in listed)
    out(f"board {args.board}: {len(listed)} sounds, {wrote} written to {args.out}, "
        f"{sum(r['status'] == 'approved' for r in listed)} approved")
    return 0


if __name__ == "__main__":
    sys.exit(run())
