"""nkido adapter: what it refuses, what it renders, and that the cage holds."""
import sys
from pathlib import Path

import pytest

from asset_engine import nkido

needs_engine = pytest.mark.skipif(not Path(nkido.EXE).is_file(), reason="nkido is not installed")
needs_windows = pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows only")


@pytest.mark.parametrize("source", [
    'samples("github:tidalcycles/Dirt-Samples")\nsine(440) |> out(%,%)',
    's"bd sd" |> out(%,%)',
    'n"c4".bank("TR808") |> out(%,%)',
    'soundfont("gm")\nsine(1) |> out(%,%)',
    'in() |> out(%,%)',
    'midi() |> out(%,%)',
    'import "x"\nsine(1) |> out(%,%)',
    '// see https://example.com\nsine(1) |> out(%,%)',
    'x = "C:\\\\Windows\\\\win.ini"\nsine(1) |> out(%,%)',
    'x = "../../secret.wav"\nsine(1) |> out(%,%)',
])
def test_refuses_anything_that_reaches_outside(source):
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render(source, 1.0, exe="no-such-engine")
    assert caught.value.kind == "forbidden"


@pytest.mark.parametrize("source", ['sin(3) + min(1, 2) |> out(%,%)', 'main = sine(440)\nmain |> out(%,%)'])
def test_plain_synthesis_is_not_refused(source):
    assert nkido.refuse(source) == ""


def test_limits_come_before_the_engine():
    with pytest.raises(nkido.RenderError) as long_source:
        nkido.render("a" * (nkido.MAX_SOURCE + 1), 1.0)
    with pytest.raises(nkido.RenderError) as long_render:
        nkido.render("sine(440) |> out(%,%)", nkido.MAX_SECONDS + 1)
    assert long_source.value.kind == long_render.value.kind == "limit"


def test_missing_engine_is_named():
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render("sine(440) |> out(%,%)", 1.0, exe="no-such-engine")
    assert caught.value.kind == "missing-engine"


@needs_engine
def test_renders_48k_stereo_of_the_asked_length():
    made = nkido.render("sine(440) * 0.3 |> out(%,%)", 1.0)
    assert (made.rate, made.channels) == (48000, 2)
    assert abs(made.seconds - 1.0) < 0.01
    assert made.wav[:4] == b"RIFF"


@needs_engine
def test_compile_error_names_the_line_in_the_source():
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render("a = 1\nb = 2\nc = = 3\nsine(440) * 0.1 |> out(%,%)", 0.2)
    assert (caught.value.kind, caught.value.line) == ("compile", 3)
    with pytest.raises(nkido.RenderError) as at_end:
        nkido.render("sine(440 * 0.3 |> out(%,%)", 0.2)
    assert (at_end.value.kind, at_end.value.line) == ("compile", 1)


@needs_engine
def test_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(nkido.tempfile, "tempdir", str(tmp_path))
    nkido.render("sine(440) * 0.3 |> out(%,%)", 0.2)
    assert list(tmp_path.iterdir()) == []


@needs_windows
def test_cage_stops_memory_children_and_long_runs(tmp_path):
    code, text = nkido.run_caged([sys.executable, "-c", "x = bytearray(2**31)"], str(tmp_path), 20, 256 * 1024 * 1024)
    assert code != 0 and "MemoryError" in text
    spawn = "import subprocess, sys; subprocess.run([sys.executable, '-c', 'print(1)'])"
    code, _ = nkido.run_caged([sys.executable, "-c", spawn], str(tmp_path), 20, 1024 ** 3)
    assert code != 0
    with pytest.raises(nkido.RenderError) as caught:
        nkido.run_caged([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), 1, 1024 ** 3)
    assert caught.value.kind == "timeout"


def test_rename_taken_leaves_calls_methods_named_arguments_and_strings():
    lines = ["drop = 3", "x = drop * 2 + drop(4) |> lp(@, 800, drop: 1)", 'y = n"drop c4".drop(1)']
    mended = ["drop_v = 3", "x = drop_v * 2 + drop(4) |> lp(@, 800, drop: 1)", 'y = n"drop c4".drop(1)']
    assert nkido.rename_taken(chr(10).join(lines), "drop") == chr(10).join(mended)


@needs_engine
def test_a_variable_named_like_a_builtin_is_mended_without_the_model():
    source = chr(10).join(["snap = sine(440) * 0.3", "snap |> out(%, %)"])
    with pytest.raises(nkido.RenderError):
        nkido.render(source, 0.2)
    made, used = nkido.render_mended(source, 0.2)
    assert made.wav[:4] == b'RIFF' and 'snap_v' in used


@needs_engine
def test_other_compile_errors_are_not_mended():
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render_mended('c = = 3', 0.2)
    assert caught.value.kind == 'compile'
