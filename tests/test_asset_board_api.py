"""The board routes of the generation API (asset_api.py over asset_boards.BoardStore): the checks and their order,
who may sync, the counts a minute, the raw chunk route, the answers' headers and words, the copy of a finished render,
the board lane, and where real_deps puts the boards. docs/ASSET_SYNC_SPEC.md K (S2).

The same Bench as tests/test_asset_api.py (a scripted model, a clock the test moves), with a BoardStore on a temp folder."""
import hashlib
import threading
import time

import pytest

import asset_api
import asset_boards as abd
import asset_jobs as aj
from test_asset_api import API, BASE, HOME, Bench, MUSIC, bearer, body, refused

BOARD, OTHER = "0" * 31 + "1", "0" * 31 + "2"
DEV, DEV2 = "1" * 16, "2" * 16


def sha(data):
    return hashlib.sha256(data).hexdigest()


class BoardBench(Bench):
    def __init__(self, folder, boards=True, sync=True, accounts="", **deps):
        self.store = abd.BoardStore(folder / "boards" / abd.DB_NAME, free=lambda path: 100 * abd.GB,
                                    clock=lambda: self.now[0]) if boards else None
        super().__init__(folder, boards=self.store, board_sync=sync, board_accounts=accounts, **deps)

    def chunk(self, token, data, at=0, size=None, board=BOARD, h=None, **more):
        size = len(data) if size is None else size
        return self.post(f"/boards/{board}/blobs/{h or sha(data)}?at={at}&size={size}", token=token, content=data,
                         headers={"Content-Type": "application/octet-stream"}, **more)

    def sync(self, token, ops=(), since=0, dev=DEV, board=BOARD, **more):
        return self.post(f"/boards/{board}/sync", {"v": 1, "dev": dev, "since": since, "ops": list(ops)}, token, **more)


@pytest.fixture
def bench(tmp_path):
    made = []

    def make(**options):
        made.append(BoardBench(tmp_path / f"bench{len(made)}", **options))
        return made[-1]
    yield make
    for b in made:
        b.jobs.stop()
        b.jobs.store.close()
        if b.store is not None:
            b.store.close()
        b.api.close()


def made(b, token, board=BOARD, **more):
    got = b.post("/boards", {"v": 1, "board": board, **more}, token)
    assert got.status_code == 200, got.text
    return got.json()


# ---------- the checks, in their order ----------
def test_the_checks_keep_their_order_on_the_board_routes(bench):
    b = bench()
    good = b.token()
    assert refused(b.web.get(API + "/boards", headers={"Host": "evil.example", **bearer(good)}))[:2] == (403, "bad_host")
    assert refused(b.post("/boards", {"board": BOARD}, good, origin="https://evil.example"))[:2] == (403, "bad_origin")
    assert refused(b.post("/boards", {"board": BOARD}, good, origin=""))[:2] == (403, "bad_origin")
    assert refused(b.post(f"/boards/{BOARD}/sync", None, good, headers={"Content-Length": str(asset_api.MAX_BODY + 1)},
                          content=b"x"))[:2] == (413, "too_large")
    assert refused(b.get("/boards"))[:2] == (401, "no_token")  # a board route without a token
    assert refused(b.post("/boards", {"board": BOARD}))[:2] == (401, "no_token")
    assert refused(b.post("/boards", None, good, content=b"not json"))[:2] == (400, "bad_request")
    assert b.web.put(API + "/boards", headers={"Origin": HOME, **bearer(good)}).status_code == 404


def test_a_password_session_is_turned_away_and_so_is_a_switch_that_is_off(bench):
    b = bench()
    assert refused(b.get("/boards", b.token(sub="pw:session")))[:2] == (403, "acct_only")
    off = bench(sync=False)
    assert refused(off.get("/boards", off.token()))[:2] == (403, "sync_off")
    assert refused(off.get("/boards", off.token(sub="pw:session")))[:2] == (403, "sync_off")


def test_only_accounts_on_the_allow_list_sync_when_it_names_any(bench):
    b = bench(accounts=" Kid@Example.com ,teacher@example.com")
    assert b.get("/boards", b.token("kid@example.com")).status_code == 200
    assert refused(b.get("/boards", b.token("other@example.com")))[:2] == (403, "sync_off")


def test_without_a_board_store_every_board_route_is_404(bench):
    b = bench(boards=False)
    token = b.token()
    assert refused(b.get("/boards", token))[:2] == (404, "not_found")
    assert refused(b.sync(token))[:2] == (404, "not_found")
    assert refused(b.chunk(token, b"abc"))[:2] == (404, "not_found")


def test_board_and_blob_requests_have_counts_of_their_own(bench, monkeypatch):
    monkeypatch.setitem(asset_api.BOARD_RATES, "board", 3)
    monkeypatch.setitem(asset_api.BOARD_RATES, "blob", 2)
    b = bench()
    token = b.token()
    for _ in range(3):  # the generation's counts do not take from the board's
        assert b.post("/jobs/status", {"ids": []}, token).status_code == 200
    for _ in range(3):
        assert b.get("/boards", token).status_code == 200
    late = b.get("/boards", token)
    assert refused(late)[:2] == (429, "rate") and late.headers["retry-after"]
    assert b.get("/quote?items=1&drafts=1", token).status_code == 200  # the generation counts are apart
    assert b.post("/jobs/status", {"ids": []}, token).status_code == 200
    assert b.store.make("acct:" + b.ledger.key_of("a@b.c"), BOARD)["created"]
    for _ in range(2):
        assert b.post(f"/boards/{BOARD}/blobs", {"shas": []}, token).status_code == 200
    assert refused(b.post(f"/boards/{BOARD}/blobs", {"shas": []}, token))[:2] == (429, "rate")
    assert b.get("/boards", b.token("z@b.c")).status_code == 200  # another account has its own


def test_the_chunk_route_takes_raw_bytes_up_to_the_chunk_cap_and_the_other_caps_stay(bench):
    b = bench()
    token = b.token()
    made(b, token)
    data = bytes(range(256)) * 10  # not JSON, not UTF-8
    assert b.chunk(token, data[:1000], size=len(data), h=sha(data)).json() == {"at": 1000, "epoch": b.store.epoch}
    assert b.chunk(token, data[1000:], at=1000, size=len(data), h=sha(data)).json()["done"] is True
    over = b"x" * (abd.Limits.CHUNK_MAX + 1)
    assert refused(b.chunk(token, over, size=len(over) + 5))[:2] == (413, "too_large")
    assert refused(b.chunk(token, b"x", size=abd.Limits.BLOB_MAX + 1))[:2] == (413, "too_large")
    assert refused(b.chunk(token, b"abc", at=-1))[:2] == (400, "bad_request")
    assert refused(b.post("/jobs", body(), token, content=b"x" * (asset_api.MAX_BODY + 1)))[:2] == (413, "too_large")
    assert asset_api.MAX_BODY == 1_600_000 and asset_api.RAW_ROUTES == {"board_chunk"}


def test_a_sound_comes_back_whole_with_its_sha_as_etag_and_no_sniffing(bench):
    b = bench()
    token = b.token()
    made(b, token)
    data = b"RIFF....WAVE sound bytes"
    b.chunk(token, data)
    got = b.get(f"/boards/{BOARD}/blobs/{sha(data)}", token)
    assert got.status_code == 200 and got.content == data
    assert got.headers["etag"] == sha(data) and got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["cache-control"] == "no-store" and got.headers["content-type"] == "application/octet-stream"
    assert refused(b.get(f"/boards/{BOARD}/blobs/{sha(b'other')}", token))[:2] == (404, "not_found")
    assert refused(b.get(f"/boards/{OTHER}/blobs/{sha(data)}", token))[:2] == (404, "no_board")
    assert refused(b.get(f"/boards/{BOARD}/blobs/{'A' * 64}", token)) == (400, "bad_request", {"field": "sha"})


def test_errors_have_the_one_shape_and_the_tokens_language(bench):
    b = bench()
    said = b.sync(b.token(lang="ko")).json()
    assert said == {"error": {"code": "no_board", "message": abd.TEXT["ko"]["no_board"]}}
    said = b.sync(b.token(lang="en")).json()
    assert said["error"]["message"] == abd.TEXT["en"]["no_board"]
    assert refused(b.sync(b.token(), dev="xyz")) == (400, "bad_request", {"field": "dev"})
    assert refused(b.sync(b.token(), since=-1)) == (400, "bad_request", {"field": "since"})
    assert refused(b.sync(b.token(), ops=[{"kind": "cat", "uid": "x", "base": "0", "data": {}}])) == \
        (400, "bad_request", {"field": "base"})
    assert refused(b.post("/boards", {"v": 1, "board": BOARD, "first": "yes"}, b.token())) == \
        (400, "bad_request", {"field": "first"})


def test_another_protocol_version_is_409_upgrade(bench):
    b = bench()
    token = b.token()
    assert refused(b.post("/boards", {"v": 2, "board": BOARD}, token))[:2] == (409, "upgrade")
    assert refused(b.post("/boards", {"v": True, "board": BOARD}, token))[:2] == (409, "upgrade")
    assert made(b, token)["created"] is True  # with v 1
    assert b.post("/boards", {"board": OTHER}, token).status_code == 200  # and without


def test_a_whole_round_make_sync_upload_and_read_back(bench):
    b = bench()
    token = b.token()
    assert made(b, token, first=True) == {"board": BOARD, "created": True, "epoch": b.store.epoch}
    assert made(b, token, board=OTHER, first=True)["board"] == BOARD
    data = b"master bytes"
    version = {"kind": "asset", "uid": "a1", "base": 0,
               "data": {"id": "kick", "name": "킥", "versions": [{"id": "v1", "sha256": sha(data)}], "trashedAt": None}}
    first = b.sync(token, [version]).json()
    assert first["results"] == [{"need": [sha(data)]}]
    assert b.post(f"/boards/{BOARD}/blobs", {"v": 1, "shas": [sha(data)]}, token).json() == {
        "have": [], "part": {}, "epoch": b.store.epoch}
    assert b.chunk(token, data).json()["done"] is True
    wrote = b.sync(token, [version]).json()
    assert wrote["results"] == [{"rev": 1, "at": int(b.now[0])}] and wrote["peers"] == [] and wrote["up"] == 0
    b.now[0] += 7
    other = b.sync(token, dev=DEV2).json()
    assert [c["data"]["name"] for c in other["changes"]] == ["킥"] and other["peers"] == [{"dev": DEV, "age": 7}]
    assert other["up"] == 7 and other["epoch"] == b.store.epoch and other["next"] == 1 and other["more"] is False
    listing = b.get("/boards", token).json()
    assert listing["home"] == BOARD and [x["live"] for x in listing["boards"]] == [1]
    assert b.post(f"/boards/{BOARD}/open", {"v": 1}, token).json() == {"home": BOARD, "epoch": b.store.epoch}


def test_a_render_is_copied_in_only_for_its_own_account_and_its_own_bytes(bench):
    b = bench()
    token, stranger = b.token("a@b.c"), b.token("z@b.c")
    made(b, token)
    made(b, stranger, board=OTHER)
    [job] = b.make(token, items=MUSIC)
    b.jobs.drain()
    result = b.views(token, [job])[0]["result"]
    master, stem = result["sha256"], result["stems"][0]["sha256"]
    path = f"/boards/{BOARD}/blobs/{master}/job"
    assert refused(b.post(f"/boards/{OTHER}/blobs/{master}/job", {"v": 1, "job": job, "stem": None}, stranger))[:2] == \
        (404, "not_found")  # another account's job
    assert refused(b.post(path, {"v": 1, "job": job, "stem": 1}, token))[:2] == (404, "not_found")  # a stem is not the master
    assert refused(b.post(path, {"v": 1, "job": "f" * 32, "stem": None}, token))[:2] == (404, "not_found")
    assert refused(b.post(path, {"v": 1, "job": "../x", "stem": None}, token)) == (400, "bad_request", {"field": "job"})
    assert b.post(path, {"v": 1, "job": job, "stem": None}, token).json()["done"] is True
    assert b.post(f"/boards/{BOARD}/blobs/{stem}/job", {"v": 1, "job": job, "stem": 1}, token).json()["done"] is True
    assert b.get(f"/boards/{BOARD}/blobs/{master}", token).content == (b.jobs.renders / job / "master.wav").read_bytes()


def test_a_full_board_lane_is_busy_while_the_status_lookups_still_answer(bench, monkeypatch):
    monkeypatch.setattr(asset_api, "BOARD_LANE", (1, 0))
    b = bench()
    token = b.token()
    made(b, token)
    inside, gate, first = threading.Event(), threading.Event(), {}

    def hook(name):
        if name == "commit":
            inside.set()
            gate.wait(10)
    b.store.hook = hook
    worker = threading.Thread(target=lambda: first.setdefault("said", b.sync(token, web=b.client())))
    worker.start()
    try:
        assert inside.wait(10)
        assert refused(b.get("/boards", token, web=b.client()))[:2] == (503, "busy")
        assert b.post("/jobs/status", {"ids": []}, token, web=b.client()).status_code == 200
        assert b.get("/health", web=b.client()).status_code == 200
    finally:
        b.store.hook = None
        gate.set()
        worker.join(10)
    assert first["said"].status_code == 200


def test_real_deps_opens_the_boards_only_when_switched_on_and_beside_the_local_database(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(asset_api, "LOCAL_FILES", tmp_path / "home")
    monkeypatch.setattr(asset_api, "DATA", data)
    monkeypatch.setattr(aj, "DEFAULT_DB", data / "asset-gen.db")
    secret = {"OLMUSE_ASSET_TOKEN_SECRET": "x" * 40}

    def deps(**env):
        got = asset_api.real_deps({**secret, **env})
        got.store.close()
        if got.boards is not None:
            got.boards.close()
        return got

    off = deps(OLMUSE_GEN_FAKE="1")
    assert off.boards is None and off.board_sync is False and not (data / "local" / abd.DB_NAME).exists()
    on = deps(OLMUSE_GEN_FAKE="1", OLMUSE_BOARD_SYNC="1", OLMUSE_BOARD_ACCOUNTS="a@b.c", OLMUSE_BOARD_LIMITS="OPS_MAX=7")
    assert on.boards.path == data / "local" / abd.DB_NAME and on.boards.blobs == data / "local" / "asset-blobs"
    assert on.board_sync is True and on.board_accounts == "a@b.c" and on.boards.limits.OPS_MAX == 7
    there = deps(OLMUSE_GEN_FAKE="1", OLMUSE_BOARD_SYNC="1", OLMUSE_BOARD_DB=str(tmp_path / "x" / "b.sqlite3"),
                 OLMUSE_BOARD_BLOBS=str(tmp_path / "bytes"))
    assert there.boards.path == tmp_path / "x" / "b.sqlite3" and there.boards.blobs == tmp_path / "bytes"
    held = abd.BoardStore(data / "local" / abd.DB_NAME)
    try:
        with pytest.raises(abd.StoreTaken):
            asset_api.real_deps({**secret, "OLMUSE_GEN_FAKE": "1", "OLMUSE_BOARD_SYNC": "1"})
        aj.GenStore(str(data / "local" / "asset-gen.db")).close()  # the generation store was let go again
    finally:
        held.close()
