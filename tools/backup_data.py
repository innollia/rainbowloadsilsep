"""Copy the SQLite files in .studio-data (jobs, listening test, local ledger, boards) to a dated folder, and the
boards' sound files (.studio-data/asset-blobs) to <dest>/asset-blobs.

  python tools/backup_data.py                    -> .studio-data/backups/YYYY-MM-DD/, newest 14 days kept,
                                                    and .studio-data/backups/asset-blobs/
  python tools/backup_data.py --dest D:/olmuse   -> another disk or a synced folder (or set OLMUSE_BACKUP_DIR)

Uses SQLite's backup API, so a database in WAL mode is copied whole. Restore: stop the app and copy the file back.
The sound files are named by the sha256 of their bytes, so only the ones the copy does not have yet are copied, and
none is ever deleted from it. Restore one: copy it back to the same <2 letters>/<sha256> place.
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server_ops import BLOBS, backup_blobs, backup_sqlite, data_files  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Back up .studio-data/*.sqlite*")
    ap.add_argument("--dest", default=os.environ.get("OLMUSE_BACKUP_DIR") or str(ROOT / ".studio-data" / "backups"))
    ap.add_argument("--keep", type=int, default=14, help="day folders to keep")
    a = ap.parse_args()
    folder = ROOT / ".studio-data"
    out = backup_sqlite(folder, a.dest, a.keep)
    print(f"backed up {len(data_files(folder))} file(s) to {out}")
    copied = backup_blobs(folder / BLOBS, pathlib.Path(a.dest) / BLOBS)
    print(f"copied {copied} new board sound file(s) to {pathlib.Path(a.dest) / BLOBS}")


if __name__ == "__main__":
    main()
