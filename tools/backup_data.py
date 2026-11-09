"""Copy the SQLite files in .studio-data (jobs, listening test, local ledger) to a dated folder.

  python tools/backup_data.py                    -> .studio-data/backups/YYYY-MM-DD/, newest 14 days kept
  python tools/backup_data.py --dest D:/olmuse   -> another disk or a synced folder (or set OLMUSE_BACKUP_DIR)

Uses SQLite's backup API, so a database in WAL mode is copied whole. Restore: stop the app and copy the file back.
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server_ops import backup_sqlite, data_files  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Back up .studio-data/*.sqlite*")
    ap.add_argument("--dest", default=os.environ.get("OLMUSE_BACKUP_DIR") or str(ROOT / ".studio-data" / "backups"))
    ap.add_argument("--keep", type=int, default=14, help="day folders to keep")
    a = ap.parse_args()
    folder = ROOT / ".studio-data"
    out = backup_sqlite(folder, a.dest, a.keep)
    print(f"backed up {len(data_files(folder))} file(s) to {out}")


if __name__ == "__main__":
    main()
