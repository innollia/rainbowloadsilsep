"""nkido (Akkado) adapter: render(source) -> 48 kHz WAV + one WAV per labelled bus.

The source is written by an AI from a stranger's request, so it is treated as hostile:
- refused before running if it names anything that reaches files, the network or devices,
- run in an empty temp folder with a bare environment,
- killed past a wall-clock limit, and (Windows) held in a job object with a memory cap and no child processes.
"""
from __future__ import annotations

import ctypes
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

EXE = os.environ.get("OLMUSE_NKIDO", r"C:\projects\_tools\nkido\build-clang\bin\nkido.exe")
RATE = 48000
MAX_SOURCE = 20_000
MAX_SECONDS = 90.0
MAX_STEMS = 8
TIME_LIMIT = 30.0
MEMORY_LIMIT = 1024 * 1024 * 1024

# Everything in Akkado that reaches outside the patch. A match anywhere (comments included) refuses the source, and
# so does a match in the code with its comments taken out (refuse).
#
# A name is forbidden where it is called. Akkado has no other use for a built-in: it cannot be a value, so it
# cannot be renamed or handed on. midi stands for every name that starts with it.
CALLS = {"samples": "samples()", "sample": "sample()", "sample_loop": "sample()", "soundfont": "soundfont()",
         "sf_voice": "sf_voice()", "wavetable": "a wavetable", "wt": "a wavetable", "wt_load": "a wavetable",
         "smooch": "a wavetable", "bank": ".bank()", "variant": ".bank()", "in": "in()", "midi": "midi()",
         "cc": "cc()", "tune": "tune()"}
WORDS = {"import": "import", "include": "include"}  # these wherever they stand
# The names and the numbers of a text, cut the way Akkado's lexer cuts them (akkado/src/lexer.cpp): a name is a
# letter or _ and then letters, digits and _; a number is its digits, a fraction and an exponent that has digits,
# and it ends there. So `0samples(` is the number 0 and then the name samples, and `x0samples(` is one name.
WORD = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
BRACKET = re.compile(r"\s*\(")
FORBIDDEN = (
    (r"\$", "a $ directive"),
    (r"://|\b(?:file|github|bundled|blob|idb|https?):", "a URI"),
    (r"[A-Za-z]:[\\/]|\.\.[\\/]", "a file path"),
)
QUOTES = "\"'`"
ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}
# How a string starts that is a path out of the render's folder: from the root of the drive, to another machine, or
# on a drive it names (`D:x` needs no slash: it is x in the folder that drive stands in).
OUTSIDE = re.compile(r"\s*(?:[\\/]|[A-Za-z]:)")
ERROR_LINE = re.compile(r":(\d+):(\d+):\s*error(?:\[(\w+)\])?:?\s*(.*)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class RenderError(Exception):
    """kind: forbidden | limit | compile | warning | timeout | crashed | missing-engine.

    warning: nkido rendered but complained (a delay silently bypassed, a sample not found), so the file is not
    what the patch says."""

    def __init__(self, kind: str, message: str, line: int = 0):
        super().__init__(message)
        self.kind, self.message, self.line = kind, message, line


@dataclass
class Rendered:
    wav: bytes
    stems: dict[str, bytes] = field(default_factory=dict)
    rate: int = RATE
    channels: int = 2
    seconds: float = 0.0


def read(source: str) -> tuple[str, list[str]]:
    """The source the way Akkado's lexer reads it: (the code, with every // comment gone and every string emptied,
    what the strings say). A string is opened by ", ' or ` and runs to the same mark, over line ends, and a
    backslash takes the next character with it. // starts a comment only outside a string, and the comment ends
    with its line."""
    code, strings, at, end = [], [], 0, len(source)
    while at < end:
        mark = source[at]
        if mark in QUOTES:
            said, at = [], at + 1
            while at < end and source[at] != mark:
                if source[at] == "\\" and at + 1 < end:
                    at += 1
                    said.append(ESCAPES.get(source[at], source[at]))
                else:
                    said.append(source[at])
                at += 1
            strings.append("".join(said))
            code.append(mark + mark)
            at += 1
        elif source.startswith("//", at):
            while at < end and source[at] != "\n":
                at += 1
        else:
            code.append(mark)
            at += 1
    return "".join(code), strings


def called(text: str) -> str:
    """The first forbidden name the text calls or says, or ''. A name counts from where the lexer starts it, so
    digits written against it hide nothing and a longer name that only ends like it is left alone."""
    for found in WORD.finditer(text):
        name, end = found.group("name"), found.end()
        if not name:
            continue
        if name in WORDS:
            return WORDS[name]
        if name == "s" and text[end:end + 1] in ('"', "`"):
            return 's"..." sample pattern'
        if BRACKET.match(text, end):
            what = CALLS.get("midi" if name.startswith("midi") else name)
            if what:
                return what
    return ""


def refuse(source: str) -> str:
    """The first forbidden thing the source names, or ''. The rules are tried on the source as it was written and
    on its code as the lexer reads it: the lexer passes over a comment, so one between a name and its bracket
    must hide nothing here either. And no string may start like a path out of the render's folder (OUTSIDE),
    which need not have a slash after a drive letter or a `..` for the rules to find."""
    code, strings = read(source)
    for text in (source, code):
        named = called(text)
        if named:
            return named
        for pattern, name in FORBIDDEN:
            if re.search(pattern, text):
                return name
    return "a file path" if any(OUTSIDE.match(said) for said in strings) else ""


def wav_facts(data: bytes) -> tuple[int, int, float]:
    with wave.open(io.BytesIO(data)) as w:
        return w.getframerate(), w.getnchannels(), w.getnframes() / float(w.getframerate() or 1)


def render(source: str, seconds: float, bpm: float | None = None, exe: str = "", time_limit: float = TIME_LIMIT,
           memory_limit: int = MEMORY_LIMIT) -> Rendered:
    exe = exe or EXE
    if not isinstance(source, str) or not source.strip():
        raise RenderError("compile", "empty source")
    if len(source) > MAX_SOURCE:
        raise RenderError("limit", f"source is longer than {MAX_SOURCE} characters")
    if not 0 < seconds <= MAX_SECONDS:
        raise RenderError("limit", f"seconds must be within 0..{MAX_SECONDS:g}")
    named = refuse(source)
    if named:
        raise RenderError("forbidden", f"the source uses {named}; only synthesis is allowed")
    if not Path(exe).is_file():
        raise RenderError("missing-engine", "nkido is not installed on this server")
    folder = tempfile.mkdtemp(prefix="olmuse-nkido-")
    try:
        Path(folder, "patch.akkado").write_text(source, encoding="utf-8", newline="\n")
        cmd = [exe, "render", "--no-default-bank", "--no-default-soundfont", "--stems", "--rate", str(RATE),
               "--seconds", f"{seconds:g}", "-o", "out.wav"]
        if bpm:
            cmd += ["--bpm", f"{float(bpm):g}"]
        code, text = run_caged(cmd + ["patch.akkado"], folder, time_limit, memory_limit)
        out = Path(folder, "out.wav")
        if code != 0 or not out.is_file():
            text = ANSI.sub("", text)
            found = ERROR_LINE.search(text)
            if found:
                line = min(int(found.group(1)), len(source.splitlines()))
                raise RenderError("compile", found.group(4).strip()[:400] or "compile error", line)
            raise RenderError("crashed", (text.strip() or f"nkido stopped with code {code}")[:400])
        if text.strip():
            raise RenderError("warning", ANSI.sub("", text).strip()[:400])
        wav = out.read_bytes()
        rate, channels, length = wav_facts(wav)
        stems = {}
        for path in sorted(Path(folder).glob("out.*.wav"))[:MAX_STEMS]:
            stems[path.name[len("out."):-len(".wav")]] = path.read_bytes()
        return Rendered(wav, stems, rate, channels, length)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


TAKEN = re.compile(r"Cannot (?:reassign immutable variable|assign to read-only builtin variable) '(\w+)'")
MENDS = 4


def rename_taken(source: str, name: str) -> str:
    """Rename a variable that collides with a built-in name; calls, methods, named arguments and strings stay."""
    fresh = name + "_v"
    while re.search(rf"\b{fresh}\b", source):
        fresh += "v"
    parts = re.split(r'("(?:[^"\\]|\\.)*")', source)
    word = re.compile(rf"(?<![\w.]){re.escape(name)}(?!\w|\s*[(:])")
    return "".join(part if i % 2 else word.sub(fresh, part) for i, part in enumerate(parts))


def render_mended(source: str, seconds: float, bpm: float | None = None, **limits) -> tuple[Rendered, str]:
    """render(), but the model's most common slip (a variable named like a built-in) is fixed here instead of
    costing another model call. Returns the render and the source that produced it."""
    for _ in range(MENDS):
        try:
            return render(source, seconds, bpm, **limits), source
        except RenderError as exc:
            taken = TAKEN.search(exc.message) if exc.kind == "compile" else None
            mended = rename_taken(source, taken.group(1)) if taken else source
            if mended == source:
                raise
            source = mended
    return render(source, seconds, bpm, **limits), source


def run_caged(cmd: list[str], cwd: str, time_limit: float, memory_limit: int) -> tuple[int, str]:
    """Run with a bare environment, a wall-clock limit and (Windows) a job object. Returns (exit code, stderr)."""
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATH") if k in os.environ}
    env.update(TEMP=cwd, TMP=cwd, HOME=cwd, USERPROFILE=cwd, APPDATA=cwd, LOCALAPPDATA=cwd, XDG_CACHE_HOME=cwd,
               NO_COLOR="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, creationflags=flags)
    job = None
    try:
        if sys.platform == "win32":
            job = cage(proc, memory_limit)
        _, out = proc.communicate(timeout=time_limit)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RenderError("timeout", f"the render took longer than {time_limit:g} seconds")
    finally:
        if job:
            ctypes.windll.kernel32.CloseHandle(job)
    return proc.returncode, out.decode("utf-8", "replace")


def cage(proc: subprocess.Popen, memory_limit: int):
    """Windows job object: memory cap per process, no child processes, everything dies with the handle."""
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    info = Extended()
    # ACTIVE_PROCESS 0x8 | PROCESS_MEMORY 0x100 | DIE_ON_UNHANDLED_EXCEPTION 0x400 | KILL_ON_JOB_CLOSE 0x2000
    info.Basic.LimitFlags = 0x8 | 0x100 | 0x400 | 0x2000
    info.Basic.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = memory_limit
    if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or \
            not k.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
        k.CloseHandle(job)
        proc.kill()
        raise RenderError("crashed", "could not isolate the render")
    return job
