"""The board store (asset_boards.BoardStore): conditional writes, history, deletes as marks, the change feed, the
sound bytes and their ceilings, one process per file, the epoch, and hard kills. docs/ASSET_SYNC_SPEC.md K (S1).

No API, no key: a store on a temp folder with the test's own clock and free space."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import asset_boards as ab
import server_ops
from asset_generate import GenError

ROOT = Path(__file__).resolve().parents[1]
A, B = "acct:" + "a" * 64, "acct:" + "b" * 64
BOARD, OTHER = "0" * 31 + "1", "0" * 31 + "2"
D1, D2 = "1" * 16, "2" * 16
T0 = 1_800_000_000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def open_store(folder, free=100 * ab.GB, clock=None, **limits):
    return ab.BoardStore(Path(folder) / ab.DB_NAME, limits=ab.Limits(**limits), clock=clock or Clock(),
                         free=lambda path: free if not callable(free) else free())


@pytest.fixture
def store(tmp_path):
    s = open_store(tmp_path)
    s.make(A, BOARD)
    yield s
    s.close()


def refused(call, *args, **kwargs):
    with pytest.raises(GenError) as err:
        call(*args, **kwargs)
    return err.value.status, err.value.code, err.value.extras


def asset(name="kick", versions=(), trashed=None, **more):
    return {"id": name, "name": name, "trashedAt": trashed, "versions": [dict(v) for v in versions], **more}


def put(store, kind, uid, base, data=None, gone=False, dev=D1, owner=A, board=BOARD, since=0):
    op = {"kind": kind, "uid": uid, "base": base, **({"gone": True} if gone else {"data": data})}
    return store.sync(owner, board, dev, since, [op])


def one(store, *args, **kwargs):
    return put(store, *args, **kwargs)["results"][0]


def upload(store, data: bytes, board=BOARD, owner=A, step=None):
    """All of data in chunks of step; the last answer."""
    step, at, said = step or max(1, len(data)), 0, None
    while True:
        said = store.chunk(owner, board, sha(data), at, len(data), data[at:at + step])
        if said.get("done"):
            return said
        at = said["at"]


def text_total(store, board=BOARD):
    with store.lock:
        a = store.db.execute("select coalesce(sum(size),0) from rec where board=?", (board,)).fetchone()[0]
        b = store.db.execute("select coalesce(sum(size),0) from rec_hist where board=?", (board,)).fetchone()[0]
        t = store.db.execute("select text from board where id=?", (board,)).fetchone()[0]
    return a + b, t


# ---------- records ----------
def test_only_the_right_base_writes_and_a_wrong_one_gets_the_servers_value(store):
    assert one(store, "cat", "drums", 0, {"id": "drums", "name": "Drums"}) == {"rev": 1, "at": T0}
    lost = one(store, "cat", "drums", 0, {"id": "drums", "name": "Beats"}, dev=D2)
    assert lost == {"conflict": {"rev": 1, "dev": D1, "gone": False, "data": {"id": "drums", "name": "Drums"}}}
    assert one(store, "cat", "drums", 1, {"id": "drums", "name": "Beats"}, dev=D2) == {"rev": 2, "at": T0}
    assert store.history(BOARD, "cat", "drums")[0]["data"]["name"] == "Beats"


def test_the_same_content_again_is_same_and_moves_no_rev(store):
    one(store, "cat", "x", 0, {"b": 1, "a": "가"})
    assert one(store, "cat", "x", 0, {"a": "가", "b": 1}) == {"same": 1}  # the answer was lost: the retry ends here
    assert put(store, "cat", "x", 1, {"a": "가", "b": 1})["head"] == 1


def test_history_keeps_the_last_values_up_to_the_cap(tmp_path):
    s = open_store(tmp_path, HISTORY_PER_RECORD=3)
    s.make(A, BOARD)
    for n in range(6):
        assert one(s, "cat", "x", n, {"n": n})["rev"] == n + 1
    kept = s.history(BOARD, "cat", "x")
    assert [h["rev"] for h in kept] == [6, 5, 4, 3] and [h["current"] for h in kept] == [True, False, False, False]
    assert text_total(s)[0] == text_total(s)[1]
    s.close()


def test_a_delete_is_a_mark_that_keeps_the_data_and_a_stale_edit_of_it_is_a_conflict(store):
    one(store, "cat", "x", 0, {"name": "x"})
    assert one(store, "cat", "x", 1, gone=True) == {"rev": 2, "at": T0}
    assert one(store, "cat", "x", 2, gone=True) == {"same": 2}
    assert one(store, "cat", "x", 1, {"name": "y"}, dev=D2) == {
        "conflict": {"rev": 2, "dev": D1, "gone": True, "data": {"name": "x"}}}
    change = put(store, "cat", "nothing", 0, gone=True, dev=D2)["changes"][0]
    assert change["gone"] is True and change["data"] == {"name": "x"}


def test_an_asset_write_that_loses_a_version_is_refused(store):
    one(store, "asset", "a1", 0, asset(versions=[{"id": "v1"}, {"id": "v2"}]))
    assert one(store, "asset", "a1", 1, asset(versions=[{"id": "v2"}])) == {"bad": "versions"}
    assert one(store, "asset", "a1", 1, asset(versions=[{"id": "v2"}, {"id": "v1"}, {"id": "v3"}]))["rev"] == 2


def test_an_asset_is_deleted_only_from_the_trash_or_as_an_untouched_sample(store):
    one(store, "asset", "a1", 0, asset())
    assert one(store, "asset", "a1", 1, gone=True) == {"bad": "trash_first"}
    one(store, "asset", "a1", 1, asset(trashed=T0))
    assert one(store, "asset", "a1", 2, gone=True)["rev"] == 3
    one(store, "asset", "s_kick", 0, asset("kick"))
    assert one(store, "asset", "s_kick", 4, gone=True)["rev"] == 5


def test_born_is_the_first_rev_and_stays(store):
    one(store, "cat", "x", 0, {"n": 1})
    one(store, "cat", "y", 0, {"n": 1})
    one(store, "cat", "x", 1, {"n": 2})
    changes = put(store, "cat", "z", 0, {"n": 1}, dev=D2)["changes"]
    assert [(c["uid"], c["rev"], c["born"]) for c in changes] == [("y", 2, 2), ("x", 3, 1)]


def test_content_checks_refuse_one_op_and_let_the_rest_through(store):
    ops = [{"kind": "song", "uid": "x", "base": 0, "data": {}}, {"kind": "cat", "uid": "a/b", "base": 0, "data": {}},
           {"kind": "cat", "uid": "x", "base": 0, "data": [1]}, {"kind": "cat", "uid": "x", "base": 0, "data": {"t": "\ud800"}},
           {"kind": "meta", "uid": "other", "base": 0, "data": {}}, {"kind": "cat", "uid": "x", "base": 0, "data": {"ok": 1}},
           {"kind": "cat", "uid": "y", "base": 0, "data": {"n": float("nan")}}]
    said = store.sync(A, BOARD, D1, 0, ops)
    assert [r.get("bad") or r.get("rev") for r in said["results"]] == ["kind", "uid", "data", "text", "uid", 1, "data"]


def test_a_record_over_the_size_cap_is_too_large(tmp_path):
    s = open_store(tmp_path, RECORD_MAX=50)
    s.make(A, BOARD)
    assert one(s, "cat", "x", 0, {"t": "x" * 60}) == {"bad": "too_large"}
    s.close()


def test_meta_game_names_the_board_and_live_counts_sounds_out_of_the_trash(store, tmp_path):
    one(store, "meta", "game", 0, {"game": {"en": "Run", "ko": "달려"}, "demo": False})
    one(store, "asset", "a1", 0, asset())
    one(store, "asset", "a2", 0, asset(trashed=T0))
    assert store.boards(A)["boards"] == [{"id": BOARD, "name": {"en": "Run", "ko": "달려"}, "live": 1, "changed": T0, "made": T0}]


def test_changes_past_the_cap_come_in_pages_and_none_is_missed(tmp_path):
    s = open_store(tmp_path, CHANGES_MAX=200)
    s.make(A, BOARD)
    for n in range(30):
        one(s, "cat", f"c{n}", 0, {"pad": "x" * 40, "n": n})
    one(s, "cat", "big", 0, {"pad": "y" * 500})  # one row over the cap still comes, alone
    got, since, pages = [], 0, 0
    while True:
        said = s.sync(A, BOARD, D2, since, [])
        got += [c["uid"] for c in said["changes"]]
        pages += 1
        since = said["next"]
        if not said["more"]:
            break
    assert got == [f"c{n}" for n in range(30)] + ["big"] and pages > 5 and since == 31
    s.close()


def test_the_feed_leaves_out_what_the_request_wrote_but_moves_past_it(store):
    one(store, "cat", "x", 0, {"n": 1})
    said = put(store, "cat", "y", 0, {"n": 1}, since=1)
    assert said["changes"] == [] and said["next"] == 2 and said["head"] == 2


def test_a_feed_read_during_another_requests_write_waits_and_does_not_skip_it(store):
    seen = {}

    def other():
        seen["said"] = store.sync(A, BOARD, D2, 0, [])

    def hook(name):
        if name == "commit" and not seen:
            seen["started"] = True
            reader = threading.Thread(target=other)
            seen["thread"] = reader
            reader.start()
            time.sleep(0.3)  # the reader is held at the lock, after the number was taken and before the commit
    store.hook = hook
    one(store, "cat", "x", 0, {"n": 1})
    store.hook = None
    seen["thread"].join(5)
    assert [c["uid"] for c in seen["said"]["changes"]] == ["x"] and seen["said"]["next"] == 1


# ---------- boards ----------
def test_no_board_and_not_a_member_are_the_same_404(store):
    assert refused(store.sync, B, BOARD, D1, 0, []) == (404, "no_board", {})
    assert refused(store.sync, B, OTHER, D1, 0, []) == (404, "no_board", {})
    assert refused(store.open, B, BOARD) == (404, "no_board", {})
    assert refused(store.make, B, BOARD) == (404, "no_board", {})
    assert refused(store.have, B, BOARD, []) == (404, "no_board", {})


def test_first_makes_one_board_per_account_and_a_retry_is_idempotent(tmp_path):
    s = open_store(tmp_path)
    assert s.make(A, BOARD, first=True) == {"board": BOARD, "created": True, "epoch": s.epoch}
    assert s.make(A, OTHER, first=True) == {"board": BOARD, "created": False, "epoch": s.epoch}
    assert s.make(A, BOARD, first=True)["created"] is False
    assert [b["id"] for b in s.boards(A)["boards"]] == [BOARD] and s.boards(A)["home"] == BOARD
    assert s.make(A, OTHER)["created"] is True and s.boards(A)["home"] == BOARD  # home stays without home:true
    assert s.open(A, OTHER) == {"home": OTHER, "epoch": s.epoch}
    third = "0" * 31 + "3"
    s.make(A, third, home=True)
    assert s.boards(A)["home"] == third
    s.close()


def test_boards_per_account_has_a_cap(tmp_path):
    s = open_store(tmp_path, BOARDS_PER_ACCOUNT=2)
    s.make(A, BOARD)
    s.make(A, OTHER)
    assert refused(s.make, A, "0" * 31 + "3") == (409, "board_full", {"limit": 2})
    s.close()


def test_records_per_board_and_text_per_board_have_caps(tmp_path):
    s = open_store(tmp_path, RECORDS_PER_BOARD=2, TEXT_PER_BOARD=120)
    s.make(A, BOARD)
    one(s, "cat", "a", 0, {"t": "a" * 30})
    one(s, "cat", "b", 0, {"t": "b" * 30})
    assert one(s, "cat", "c", 0, {"t": "c"}) == {"bad": "board_full"}
    rev = 1
    for n in range(1, 6):  # the history makes room by going, oldest first
        rev = one(s, "cat", "a", rev, {"t": str(n) * 30})["rev"]
    total, counted = text_total(s)
    assert total == counted <= 120
    assert one(s, "cat", "b", 2, {"t": "z" * 100}) == {"bad": "board_full"}  # does not fit even with no history
    s.close()


# ---------- bytes ----------
def test_chunks_come_in_order_resume_from_the_part_and_end_in_place(store, tmp_path):
    data = os.urandom(2500)
    h = sha(data)
    assert store.chunk(A, BOARD, h, 0, 2500, data[:1000]) == {"at": 1000, "epoch": store.epoch}
    assert store.have(A, BOARD, [h]) == {"have": [], "part": {h: 1000}, "epoch": store.epoch}
    assert refused(store.chunk, A, BOARD, h, 0, 2500, data[:1000]) == (409, "offset", {"at": 1000})
    assert refused(store.chunk, A, BOARD, h, 2000, 2500, data[2000:]) == (409, "offset", {"at": 1000})
    assert store.chunk(A, BOARD, h, 1000, 2500, data[1000:2000])["at"] == 2000
    assert store.chunk(A, BOARD, h, 2000, 2500, data[2000:])["done"] is True
    assert store.have(A, BOARD, [h])["have"] == [h]
    path, size = store.blob(A, BOARD, h)
    assert path.read_bytes() == data and size == 2500 and path == tmp_path / "asset-blobs" / h[:2] / h
    assert list((tmp_path / "asset-blobs" / "part").iterdir()) == []


def test_bytes_that_do_not_match_their_address_are_dropped(store, tmp_path):
    assert refused(store.chunk, A, BOARD, "f" * 64, 0, 3, b"abc") == (400, "bad_blob", {})
    assert list((tmp_path / "asset-blobs" / "part").iterdir()) == []
    assert store.have(A, BOARD, ["f" * 64]) == {"have": [], "part": {}, "epoch": store.epoch}


def test_a_sha_on_another_board_is_not_had_until_its_bytes_are_sent(store, tmp_path):
    store.make(A, OTHER)
    data = b"shared sound"
    upload(store, data)
    first = (tmp_path / "asset-blobs" / sha(data)[:2] / sha(data)).stat().st_mtime_ns
    assert store.have(A, OTHER, [sha(data)])["have"] == []
    assert refused(store.blob, A, OTHER, sha(data)) == (404, "not_found", {})
    upload(store, data, board=OTHER)
    assert store.have(A, OTHER, [sha(data)])["have"] == [sha(data)]
    assert (tmp_path / "asset-blobs" / sha(data)[:2] / sha(data)).stat().st_mtime_ns == first  # not written again
    with store.lock:
        assert store.db.execute("select bytes from board where id=?", (OTHER,)).fetchone()[0] == len(data)


def test_a_record_waits_for_the_bytes_it_newly_points_at(store):
    data = b"master"
    rec = asset(versions=[{"id": "v1", "sha256": sha(data), "stems": [{"sha256": sha(b"stem")}]}])
    assert one(store, "asset", "a1", 0, rec) == {"need": sorted([sha(data), sha(b"stem")])}
    upload(store, data)
    upload(store, b"stem")
    assert one(store, "asset", "a1", 0, rec)["rev"] == 1


def test_a_sha_whose_file_went_heals_and_the_sounds_text_still_syncs(store, tmp_path):
    data = b"lost bytes"
    upload(store, data)
    one(store, "asset", "a1", 0, asset(versions=[{"id": "v1", "sha256": sha(data)}]))
    (tmp_path / "asset-blobs" / sha(data)[:2] / sha(data)).unlink()
    assert refused(store.blob, A, BOARD, sha(data)) == (404, "not_found", {})
    assert store.have(A, BOARD, [sha(data)])["have"] == []
    assert one(store, "asset", "a1", 1, asset("renamed", versions=[{"id": "v1", "sha256": sha(data)}]))["rev"] == 2
    assert one(store, "asset", "a2", 0, asset(versions=[{"id": "v9", "sha256": sha(data)}])) == {"need": [sha(data)]}


@pytest.mark.parametrize("board, h", [("../" + "0" * 29, "a" * 64), ("A" * 32, "a" * 64), ("0" * 31, "a" * 64),
                                      (BOARD, "../" + "a" * 61), (BOARD, "A" * 64), (BOARD, "a" * 63), (BOARD, None)])
def test_a_board_or_sha_of_the_wrong_shape_makes_no_file(store, tmp_path, board, h):
    before = sorted(p for p in tmp_path.rglob("*"))
    for call in (lambda: store.chunk(A, board, h, 0, 3, b"abc"), lambda: store.blob(A, board, h),
                 lambda: store.have(A, board, [h]), lambda: store.adopt(A, board, h, tmp_path / ab.DB_NAME)):
        with pytest.raises(GenError) as err:
            call()
        assert (err.value.status, err.value.code) == (400, "bad_request")
    assert sorted(p for p in tmp_path.rglob("*") if not p.name.endswith(("-wal", "-shm"))) == \
        [p for p in before if not p.name.endswith(("-wal", "-shm"))]


def test_two_chunks_at_once_on_one_part_turn_one_away(store):
    data, gate, inside = os.urandom(100), threading.Event(), threading.Event()

    def hook(name):
        if name == "append":
            inside.set()
            gate.wait(5)
    store.hook = hook
    first = {}
    t = threading.Thread(target=lambda: first.setdefault("said", store.chunk(A, BOARD, sha(data), 0, 100, data[:50])))
    t.start()
    assert inside.wait(5)
    store.hook = None
    assert refused(store.chunk, A, BOARD, sha(data), 0, 100, data[:50]) == (409, "offset", {"at": 0})
    gate.set()
    t.join(5)
    assert first["said"]["at"] == 50 and store.have(A, BOARD, [sha(data)])["part"] == {sha(data): 50}


def test_chunk_and_blob_size_caps(tmp_path):
    s = open_store(tmp_path, CHUNK_MAX=10, BLOB_MAX=30)
    s.make(A, BOARD)
    assert refused(s.chunk, A, BOARD, "a" * 64, 0, 31, b"x")[:2] == (413, "too_large")
    assert refused(s.chunk, A, BOARD, "a" * 64, 0, 30, b"x" * 11)[:2] == (413, "too_large")
    assert refused(s.chunk, A, BOARD, "a" * 64, 0, 5, b"x" * 6)[:2] == (400, "bad_request")
    s.close()


def test_board_account_part_and_folder_byte_caps(tmp_path):
    s = open_store(tmp_path, BOARD_BYTES=10, ACCOUNT_BYTES=15, PARTS_PER_ACCOUNT=1, ALL_BYTES=100)
    s.make(A, BOARD)
    s.make(A, OTHER)
    upload(s, b"x" * 8)
    assert refused(upload, s, b"y" * 3) == (409, "board_full", {"limit": 10})
    assert refused(upload, s, b"z" * 8, board=OTHER) == (409, "board_full", {"limit": 15})
    s.chunk(A, OTHER, sha(b"abcd"), 0, 4, b"ab")  # one part file open
    status, code, _ = refused(s.chunk, A, OTHER, sha(b"wxyz"), 0, 4, b"wx")
    assert (status, code) == (503, "busy")
    s.make(B, "0" * 31 + "9")
    s.limits.ALL_BYTES = 12
    assert refused(upload, s, b"q" * 5, board="0" * 31 + "9", owner=B)[:2] == (503, "busy")
    s.close()


def test_stalled_part_files_make_room_for_a_new_sound_but_a_moving_one_does_not(tmp_path):
    s = open_store(tmp_path, PARTS_PER_ACCOUNT=2, PART_STALL=600)
    s.make(A, BOARD)
    big = [bytes([65 + i]) * 10 for i in range(2)]
    for data in big:  # two uploads cut short after their first chunk
        s.chunk(A, BOARD, sha(data), 0, 10, data[:3])
    assert refused(s.chunk, A, BOARD, sha(b"new"), 0, 3, b"new")[:2] == (503, "busy")  # both still moving
    old = time.time() - 3600
    os.utime(s._part(BOARD, sha(big[0])), (old, old))
    assert s.chunk(A, BOARD, sha(b"new"), 0, 3, b"new")["done"]  # the stalled one went, the new sound is in
    assert not s._part(BOARD, sha(big[0])).exists() and s._part(BOARD, sha(big[1])).exists()
    s.close()


def test_with_little_free_room_writes_and_uploads_wait_but_reading_goes_on(tmp_path):
    room = [100 * ab.GB]
    s = open_store(tmp_path, free=lambda: room[0])
    s.make(A, BOARD)
    one(s, "cat", "x", 0, {"n": 1})
    room[0] = ab.GB
    assert refused(put, s, "cat", "y", 0, {"n": 1})[:2] == (503, "busy")
    assert refused(s.chunk, A, BOARD, sha(b"abc"), 0, 3, b"abc")[:2] == (503, "busy")
    assert [c["uid"] for c in s.sync(A, BOARD, D2, 0, [])["changes"]] == ["x"]
    s.close()


def test_a_render_is_copied_in_only_when_its_bytes_are_the_address(store, tmp_path):
    render = tmp_path / "master.wav"
    render.write_bytes(b"RIFF render")
    assert refused(store.adopt, A, BOARD, "e" * 64, render) == (404, "not_found", {})
    assert store.adopt(A, BOARD, sha(b"RIFF render"), render)["done"] is True
    assert store.blob(A, BOARD, sha(b"RIFF render"))[0].read_bytes() == b"RIFF render"
    assert [p.name for p in (tmp_path / "asset-blobs" / "part").iterdir()] == []


# ---------- the file ----------
def test_a_second_store_on_the_file_is_refused(store, tmp_path):
    with pytest.raises(ab.StoreTaken):
        open_store(tmp_path)
    code = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import asset_boards as ab
        try:
            ab.BoardStore({str(tmp_path / ab.DB_NAME)!r})
        except ab.StoreTaken:
            print("taken")
    """)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "taken", done.stderr


def test_lock_and_boots_files_have_no_sqlite_in_their_names(store, tmp_path):
    names = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
    assert "asset-boards.lock" in names and "asset-boards.boots" in names
    assert [p.name for p in server_ops.data_files(tmp_path)] == [ab.DB_NAME]


def test_the_epoch_stays_over_restarts_and_changes_when_the_database_comes_back_from_a_copy(tmp_path):
    s = open_store(tmp_path)
    first = s.epoch
    s.close()
    shutil.copy(tmp_path / ab.DB_NAME, tmp_path / "old.copy")
    s = open_store(tmp_path)
    assert s.epoch == first
    s.close()
    shutil.copy(tmp_path / "old.copy", tmp_path / ab.DB_NAME)
    s = open_store(tmp_path)
    assert s.epoch != first and s.sync  # a restore: every device takes the board again from 0
    second = s.epoch
    s.close()
    s = open_store(tmp_path)
    assert s.epoch == second
    s.close()


def test_the_daily_backup_takes_the_board_database_and_not_its_lock_while_the_store_is_open(store, tmp_path):
    one(store, "cat", "x", 0, {"n": 1})
    other = sqlite3.connect(tmp_path / "jobs.sqlite3")
    other.execute("create table t (n)")
    other.commit()
    other.close()
    out = server_ops.backup_sqlite(tmp_path, tmp_path / "backups", day="2026-11-11")
    assert sorted(p.name for p in out.iterdir()) == [ab.DB_NAME, "jobs.sqlite3"]
    copy = sqlite3.connect(out / ab.DB_NAME)
    assert copy.execute("select uid from rec").fetchall() == [("x",)]
    copy.close()


# ---------- hard kills ----------
KILL = textwrap.dedent("""
    import os, sys, time, hashlib
    sys.path.insert(0, ROOT)
    import asset_boards as ab
    s = ab.BoardStore(D + "/asset-boards.sqlite3", free=lambda p: 10 ** 12)
    def hook(name):
        if name == AT:
            open(D + "/stopped", "w").write("x")
            time.sleep(600)
    s.hook = hook
    if AT == "commit":
        s.sync("acct:" + "a" * 64, "0" * 31 + "1", "1" * 16, 0,
               [{"kind": "cat", "uid": "k" + str(n), "base": 0, "data": {"n": n}} for n in range(3)])
    else:
        data = b"killed between the move and the rows"
        s.chunk("acct:" + "a" * 64, "0" * 31 + "1", hashlib.sha256(data).hexdigest(), 0, len(data), data)
""")


def kill_at(folder, at):
    code = f"ROOT={str(ROOT)!r}\nD={str(folder)!r}\nAT={at!r}\n" + KILL
    child = subprocess.Popen([sys.executable, "-c", code])
    try:
        for _ in range(600):
            if (folder / "stopped").exists():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the child never got there")
    finally:
        child.kill()
        child.wait()


def test_a_kill_inside_the_transaction_leaves_no_hole_in_the_revs(tmp_path):
    s = open_store(tmp_path)
    s.make(A, BOARD)
    one(s, "cat", "first", 0, {"n": 0})
    s.close()
    kill_at(tmp_path, "commit")
    s = open_store(tmp_path)
    said = put(s, "cat", "after", 0, {"n": 1})
    assert said["results"] == [{"rev": 2, "at": T0}] and said["head"] == 2
    assert [r["rev"] for r in s.records(BOARD)] == [1, 2]
    s.close()


def test_a_kill_between_moving_the_file_and_writing_its_rows_ends_when_it_is_sent_again(tmp_path):
    s = open_store(tmp_path)
    s.make(A, BOARD)
    s.close()
    kill_at(tmp_path, "moved")
    data = b"killed between the move and the rows"
    s = open_store(tmp_path)
    assert s.have(A, BOARD, [sha(data)]) == {"have": [], "part": {}, "epoch": s.epoch}
    assert upload(s, data)["done"] is True
    assert s.blob(A, BOARD, sha(data))[0].read_bytes() == data
    s.close()


# ---------- the canonical text ----------
def test_the_canonical_size_is_the_byte_count_of_the_browsers_canon():
    data = {"name": "킥 드럼", "z": [1, 2.5, -3, 0.125, 1e21, 12345678901], "a": {"b": "é", "a": None, "t": True}, "e": ""}
    board_js = ROOT / "studio_frontend" / "asset_studio" / "board.js"
    canon = ("const b = require(" + json.dumps(str(board_js)) + "); const canon = (b.canon || globalThis.assetBoard.canon);"
             if board_js.is_file() else
             "const canon = (x) => JSON.stringify(x, (k, v) => v && typeof v === 'object' && !Array.isArray(v) ?"
             " Object.fromEntries(Object.keys(v).sort().map((key) => [key, v[key]])) : v);")
    code = canon + " const x = JSON.parse(require('fs').readFileSync(0, 'utf8'));" \
                   " console.log(JSON.stringify([Buffer.byteLength(canon(x), 'utf8'), canon(x)]));"
    done = subprocess.run(["node", "-e", code], input=json.dumps(data), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    size, text = json.loads(done.stdout)
    op = ab.prepare({"kind": "cat", "uid": "x", "base": 0, "data": data}, ab.Limits())
    assert (op.size, op.text) == (size, text)


def test_limits_come_from_the_environment_text():
    limits = ab.Limits.parse("RECORD_MAX=10, ops_max=3,NOPE=1,CHUNK_MAX=-1,BLOB_MAX=x")
    assert (limits.RECORD_MAX, limits.OPS_MAX, limits.CHUNK_MAX, limits.BLOB_MAX) == (10, 3, 1_000_000, 60 * ab.MB)


def test_importing_opens_nothing_and_needs_no_streamlit():
    code = "import sys, threading, asset_boards; print(threading.active_count(), 'streamlit' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.stdout.split() == ["1", "False"], done.stderr
