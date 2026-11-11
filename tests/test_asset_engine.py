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


@pytest.mark.parametrize("source", [
    '"/Windows/win.ini".samples // x\n()\nsine(1) |> out(%,%)',  # a comment between a name and its bracket
    'samples // x\n("bank.json")\nsine(1) |> out(%,%)',
    '"w".wt_load // (\n("a.wav")\nsine(1) |> out(%,%)',
    'soundfont // "\n("gm")\nsine(1) |> out(%,%)',               # a quote in the comment opens no string
    'x = "//"\n"/x".samples // y\n()\nsine(1) |> out(%,%)',      # and // in a string starts no comment
    's`bd sd` |> out(%,%)',
    'x = "/Windows/win.ini"\nsine(1) |> out(%,%)',               # a path from the root of the drive
    'x = "//127.0.0.1/share/bank.json"\nsine(1) |> out(%,%)',    # another machine
    'x = "\\\\\\\\host\\\\share\\\\bank.json"\nsine(1) |> out(%,%)',
    "x = '/etc/passwd'\nsine(1) |> out(%,%)",
    'x = ` /etc/passwd`\nsine(1) |> out(%,%)',
    'x = "\\n/etc/passwd"\nsine(1) |> out(%,%)',
])
def test_refuses_what_a_comment_or_a_path_without_a_drive_would_slip_past(source):
    assert nkido.refuse(source) != ""
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render_mended(source, 1.0, exe="no-such-engine")
    assert caught.value.kind == "forbidden"


def test_the_source_is_read_the_way_the_lexer_reads_it():
    code, strings = nkido.read('a = "x // y" // z "q"\nb = \'c4\' + `l1\nl2` // "\nc = "e\\"f\\\\"')
    assert code == 'a = "" \nb = \'\' + `` \nc = ""' and strings == ["x // y", "c4", "l1\nl2", 'e"f\\']
    assert nkido.read('a = "never closed // b') == ('a = ""', ["never closed // b"])


LOADERS = ["samples", "sample", "sample_loop", "soundfont", "sf_voice", "wt_load", "smooch", "wt", "wavetable", "bank",
           "variant", "in", "midi", "midi_cc", "cc", "tune"]


@pytest.mark.parametrize("number", ["0", "3", "1e3", ".5", "12.5", "7E-2"])
def test_a_number_written_against_a_name_hides_nothing(number):
    """Akkado's lexer ends a number where its digits end, so `0samples(` is the number 0 and then a call of
    samples. A rule that looks for the start of a word saw one word there, `0samples`, and let it pass."""
    tail = "\nsine(220) |> out(%, %)"
    assert [name for name in LOADERS if not nkido.refuse(f'{number}{name}("x"){tail}')] == []
    assert [name for name in LOADERS if not nkido.refuse(f'{number}{name} // x\n("x"){tail}')] == []
    assert nkido.refuse(f'{number}s"bd sd" |> out(%, %)') and nkido.refuse(f'{number}s`bd sd` |> out(%, %)')
    assert nkido.refuse(f'{number}import "x"{tail}') and nkido.refuse(f'{number}include "x"{tail}')
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render_mended(f'{number}samples("manifest.json"){tail}', 1.0, exe="no-such-engine")
    assert caught.value.kind == "forbidden"


@pytest.mark.parametrize("source", [
    'x = "C:x.json"\nsine(1) |> out(%,%)',      # the folder the C: drive stands in, with no slash to find
    'x = "D:x.json"\nsine(1) |> out(%,%)',      # and on another drive that is its root
    'x = "D:dir/x.json"\nsine(1) |> out(%,%)',
    'x = `d:x.wav`\nsine(1) |> out(%,%)',
    "x = ' C:x.json'\nsine(1) |> out(%,%)",
])
def test_refuses_a_drive_named_without_a_slash(source):
    assert nkido.refuse(source) == "a file path"
    with pytest.raises(nkido.RenderError) as caught:
        nkido.render_mended(source, 1.0, exe="no-such-engine")
    assert caught.value.kind == "forbidden"


@needs_engine
def test_the_engine_reads_a_number_and_a_name_where_they_touch():
    """What the rule above answers: this renders, so the name after the digits is called."""
    assert nkido.render("0sine(440) * 0.3 |> out(%,%)", 0.2).wav[:4] == b"RIFF"


@pytest.mark.parametrize("source", [
    'x0samples = 2\nmix2in = (a) -> a * x0samples\nsine(440) |> mix2in(%) |> out(%,%)',  # one name each, digits inside
    'osc1cc = (a) -> a\nlfo2tune = (a) -> a\nsine(440) |> osc1cc(%) |> lfo2tune(%) |> out(%,%)',
    'remidi = (a) -> a\nmy_sample = (a) -> a\nsine(440) |> remidi(%) |> my_sample(%) |> out(%,%)',
    'sine(440) |> lp(%, 800, q: 2) |> bus(1, %, "kick")',   # a named argument and a label are no drive
    'x = n"c4:0.8 e4"\nsine(440) |> out(%,%)',
    'sin(3) + min(1, 2) |> out(%,%)', 'main = sine(440)\nmain |> out(%,%)',
    'x = n"c4 e4" // two notes, one sample each\nsine(440) / 2 |> out(%,%)',
    "a = 'c4' // a pitch\nsine(a) |> out(%,%)",
    'f = (in) -> in * 0.5 // halves what comes in\nsine(440) |> f(%) |> out(%,%)',
    'x = v"1 0 1 0" / 2\nsine(440) * x |> out(%,%)',
])
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
