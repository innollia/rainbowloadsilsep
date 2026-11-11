"""Two computers of one account against the real API (docs/ASSET_SYNC_SPEC.md K, X): the API runs with
OLMUSE_GEN_FAKE=1 and OLMUSE_BOARD_SYNC=1 on a temp folder and a free port, and tests/js/sync_two.js plays the scenes
the libraries alone cannot: 12 (work taken over from a computer that stopped, and not while it is there) and 24 (the
computer that stopped opens again and neither cancels nor undoes what was taken over). Scenes 15, 19 and 22 need the
page and run in tests/e2e_asset_sync.py."""
import dataclasses, hashlib, json, os, pathlib, secrets, socket, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from credits import LocalLedger  # noqa: E402


class SyncApi:
    """The generation API with boards on, for pages of page_origin. token() signs an account token of one account."""

    def __init__(self, folder, page_origin, email="two@test.example"):
        import uvicorn

        import asset_api
        import asset_token
        self.sign, self.secret, self.email = asset_token, secrets.token_hex(32), email
        self.sub = "acct:e2e-" + secrets.token_hex(4)
        self.who = hashlib.sha256(self.sub.encode()).hexdigest()[:16]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}/api/asset"
        folder = pathlib.Path(folder)
        env = dict(os.environ, OLMUSE_GEN_FAKE="1", OLMUSE_GEN_DB=str(folder / "asset-gen.db"), OLMUSE_RENDERS=str(folder / "renders"),
                   OLMUSE_API_HOSTS=f"127.0.0.1:{port}", OLMUSE_API_ORIGINS=page_origin, STRUDEL_CREDITS_URL="", STRUDEL_LOCAL_LEDGER="",
                   OLMUSE_BOARD_SYNC="1", OLMUSE_BOARD_ACCOUNTS=email, OLMUSE_BOARD_DB=str(folder / "boards.sqlite3"),
                   OLMUSE_BOARD_BLOBS=str(folder / "blobs"))
        env[asset_token.SECRET_ENV] = self.secret
        # An account's credits come from a ledger in memory: this PC's ledger files are never opened.
        deps = asset_api.real_deps(env)
        self.boards = deps.boards
        self.app = asset_api.create_app(dataclasses.replace(deps, ledger=LocalLedger(":memory:", pepper="p", free=1000)))
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning", access_log=False, proxy_headers=False))
        threading.Thread(target=self.server.run, daemon=True).start()
        deadline = time.time() + 15
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("the API did not start")
            time.sleep(0.05)

    def up_for(self, seconds):
        """The API says it has been up this long (it knows who is there): taking work over may happen."""
        self.app.state.api.up_since -= seconds

    def token(self):
        return self.sign.sign(self.sign.payload_for("acct", self.sub, self.email, "en", time.time()), self.secret)

    def stop(self):
        self.server.should_exit = True
        self.app.state.api.jobs.stop()
        self.app.state.api.jobs.store.close()
        self.app.state.api.close()
        self.boards.close()


def test_work_of_a_stopped_computer_is_taken_over_only_once_it_is_gone_and_it_leaves_that_work_alone_when_it_opens_again():
    origin = "http://127.0.0.1:9"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        api = SyncApi(tmp, origin)
        try:
            api.up_for(1000)
            env = {"base": api.base, "origin": origin, "token": api.token(), "who": api.who}
            out = subprocess.run(["node", str(ROOT / "tests" / "js" / "sync_two.js")], input=json.dumps(env), capture_output=True,
                                 text=True, encoding="utf-8", timeout=200)
            assert out.returncode == 0, out.stderr[-4000:]
            got = json.loads(out.stdout)
        finally:
            api.stop()
    print(got)
    assert got["joined"] == [True, True]
    assert got["asked"] == [True, ""] and got["jobRecordOnServer"] and got["bSeesAsWork"]
    # Scene 12: nothing is taken while A is seen; once A is away past PEER_GONE, B wins the record on the server and
    # brings the drafts in.
    assert got["whileOnline"] == 0 and got["whileOnlineDev"]
    assert got["taken"] == ["k1"] and got["serverHasB"]
    # (one draft asked for: it comes in as the sound's version, status draft)
    assert got["bGotDrafts"] == ["draft", 1, False, []]
    # Scene 24: A opens again holding its old record, receives B's, and neither polls, collects nor cancels.
    assert got["reopenedHeldMine"] and got["converged"]
    assert got["aCancelOrPoll"] == []
    assert got["aEnd"] == {"status": "draft", "sounds": 1, "work": False} and got["bEnd"] == {"status": "draft", "sounds": 1}
    # How every scene ends: the same records on both computers and the server, nothing to send, head unchanged.
    assert got["same"] and got["left"] == [0, 0] and got["headStill"]
