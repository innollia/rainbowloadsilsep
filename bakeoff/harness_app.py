"""Streamlit entry for the bakeoff: the real studio with the engine swapped and every call recorded (see harness.py).

Streamlit reruns this file on every interaction; the patches live in an imported module so they apply once.
"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness  # noqa: E402

harness.install()

runpy.run_path(str(HERE.parent / "app.py"), run_name="__main__")
