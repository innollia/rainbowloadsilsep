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

# Everything in Akkado that reaches outside the patch. A match anywhere (comments included) refuses the source.
FORBIDDEN = (
    (r"\bsamples\s*\(", "samples()"),
    (r"\bsample\s*\(", "sample()"),
    (r"\bsoundfont\s*\(", "soundfont()"),
    (r"\bsf_voice\s*\(", "sf_voice()"),
    (r"\bwavetable\s*\(", "wavetable()"),
    (r"\bwt_load\s*\(", "wt_load()"),
    (r"\.bank\s*\(", ".bank()"),
    (r"\bs\"", 's"..." sample pattern'),
    (r"\bin\s*\(", "in()"),
    (r"\bmidi\w*\s*\(", "midi()"),
    (r"\bcc\s*\(", "cc()"),
    (r"\bimport\b", "import"),
    (r"\binclude\b", "include"),
    (r"://|\b(?:file|github|bundled|blob|idb|https?):", "a URI"),
    (r"[A-Za-z]:[\\/]|\.\.[\\/]", "a file path"),
)
ERROR_LINE = re.compile(r":(\d+):(\d+):\s*error(?:\[(\w+)\])?:?\s*(.*)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class RenderError(Exception):
    """kind: forbidden | limit | compile | timeout | crashed | missing-engine."""

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


def refuse(source: str) -> str:
    """The first forbidden thing the source names, or ''."""
    for pattern, name in FORBIDDEN:
        if re.search(pattern, source):
            return name
    return ""


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
        wav = out.read_bytes()
        rate, channels, length = wav_facts(wav)
        stems = {}
        for path in sorted(Path(folder).glob("out.*.wav"))[:MAX_STEMS]:
            stems[path.name[len("out."):-len(".wav")]] = path.read_bytes()
        return Rendered(wav, stems, rate, channels, length)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run_caged(cmd: list[str], cwd: str, time_limit: float, memory_limit: int) -> tuple[int, str]:
    """Run with a bare environment, a wall-clock limit and (Windows) a job object. Returns (exit code, output)."""
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATH") if k in os.environ}
    env.update(TEMP=cwd, TMP=cwd, HOME=cwd, USERPROFILE=cwd, APPDATA=cwd, LOCALAPPDATA=cwd, XDG_CACHE_HOME=cwd,
               NO_COLOR="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, creationflags=flags)
    job = None
    try:
        if sys.platform == "win32":
            job = cage(proc, memory_limit)
        out, _ = proc.communicate(timeout=time_limit)
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
