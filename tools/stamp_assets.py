"""Puts a content hash on every local script and stylesheet the studio pages load (app.js?v=1a2b3c4d).

Cloudflare tells browsers to keep .js and .css for four hours while the pages themselves are never cached,
so without this a browser mixes a new page with an old script and the page breaks. run_public.ps1 runs this
before starting the server, and tests/test_stamp_assets.py fails when a stamp is stale.

python tools/stamp_assets.py          rewrite the stamps
python tools/stamp_assets.py --check  exit 1 if any stamp is stale
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "studio_frontend"
PAGES = [ROOT / "index.html", ROOT / "asset_studio" / "index.html"]
REF = re.compile(r'((?:src|href)=")([A-Za-z0-9_./-]+\.(?:js|css))(?:\?v=[0-9a-f]*)?(")')


def stamped(page: Path) -> str:
    def swap(m):
        target = page.parent / m.group(2)
        if not target.is_file():
            return m.group(0)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:10]
        return f"{m.group(1)}{m.group(2)}?v={digest}{m.group(3)}"
    return REF.sub(swap, page.read_text(encoding="utf-8"))


def main(argv) -> int:
    stale = []
    for page in PAGES:
        text = stamped(page)
        if text != page.read_text(encoding="utf-8"):
            stale.append(page)
            if "--check" not in argv:
                page.write_text(text, encoding="utf-8", newline="")
    if stale and "--check" in argv:
        print("stale stamps:", ", ".join(str(p) for p in stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
