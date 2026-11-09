"""Make a credit coupon on the ledger the public site uses.

  python tools/coupon.py OLMUSE-START-1 10000          one account can use it once
  python tools/coupon.py TEAM2026 300 --uses 50        50 different accounts

Codes keep only letters and digits (6+). Each account can use a coupon once. Users type it in the credits window.
Uses the same ledger as the public site: STRUDEL_CREDITS_URL (env, .streamlit/secrets.toml or run_public.ps1) and the
admin token in ~/.all-tomorrow/strudel-credits-admin.token (or STRUDEL_CREDITS_ADMIN_TOKEN), made by deploy/credits/deploy.ps1.
The web server's app token cannot make coupons. Without the url or admin token it stops, unless STRUDEL_LOCAL_LEDGER=1
asks for the local ledger (.studio-data/credits.sqlite).
"""
import argparse
import os
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from credits import LedgerError, LocalLedger, RemoteLedger  # noqa: E402


def setting(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        found = str(tomllib.loads((ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8")).get(name, ""))
    except OSError:
        found = ""
    if not found:  # the public site sets it in run_public.ps1
        try:
            m = re.search(r"\$env:" + name + r"""\s*=\s*["']([^"']+)["']""", (ROOT / "run_public.ps1").read_text(encoding="utf-8"))
            found = m.group(1) if m else ""
        except OSError:
            pass
    return found


ADMIN_TOKEN_FILE = pathlib.Path.home() / ".all-tomorrow" / "strudel-credits-admin.token"


def ledger():
    url = setting("STRUDEL_CREDITS_URL")
    token = os.environ.get("STRUDEL_CREDITS_ADMIN_TOKEN", "")
    if not token:
        try:
            token = ADMIN_TOKEN_FILE.read_text(encoding="ascii").strip()
        except OSError:
            token = ""
    if os.environ.get("STRUDEL_LOCAL_LEDGER") == "1":
        (ROOT / ".studio-data").mkdir(exist_ok=True)
        return LocalLedger(str(ROOT / ".studio-data" / "credits.sqlite"), pepper=setting("STRUDEL_CREDITS_PEPPER") or "local-only"), "local"
    if url and token:
        return RemoteLedger(url, token), "remote"
    sys.exit(f"not made: no ledger url or admin token ({ADMIN_TOKEN_FILE}); run deploy/credits/deploy.ps1, "
             "or set STRUDEL_LOCAL_LEDGER=1 for the local ledger")


def main():
    ap = argparse.ArgumentParser(description="Make a credit coupon")
    ap.add_argument("code")
    ap.add_argument("credits", type=int)
    ap.add_argument("--uses", type=int, default=1, help="how many accounts can use it (each once)")
    a = ap.parse_args()
    led, where = ledger()
    try:
        code = led.make_coupon(a.code, a.credits, a.uses)
    except (ValueError, LedgerError) as exc:
        sys.exit(f"not made: {exc}")
    print(f"coupon {code}: {a.credits} credits, {a.uses} use(s), {where} ledger")


if __name__ == "__main__":
    main()
