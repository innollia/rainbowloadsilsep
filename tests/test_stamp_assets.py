import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("stamp_assets", Path(__file__).resolve().parent.parent / "tools" / "stamp_assets.py")
stamp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stamp)


def test_pages_load_scripts_by_their_current_content():
    """A stale stamp lets a browser pair a new page with an old cached script (python tools/stamp_assets.py fixes it)."""
    for page in stamp.PAGES:
        assert stamp.stamped(page) == page.read_text(encoding="utf-8"), page
