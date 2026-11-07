import io
import random
import re
import wave

import numpy as np

import ear

R = 48000


def pack(x):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(R)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def beat(bpm, freq, seconds=8):
    x = np.zeros(R * seconds)
    step = int(R * 60 / bpm)
    t = np.arange(step // 2) / R
    note = 0.6 * np.sin(2 * np.pi * freq * t) * np.exp(-t * 12)
    for s in range(0, len(x) - len(note), step):
        x[s:s + len(note)] += note
    return x


def bpm_of(text):
    return float(re.search(r"측정 템포 ([\d.]+)", text).group(1))


def test_tempo_is_found_for_random_tempos():
    for bpm in random.Random(7).sample(range(70, 180), 5):
        got = bpm_of(ear.describe(pack(beat(bpm, 110))))
        # a double-time or half-time reading is the same pulse
        assert min(abs(got - bpm), abs(got - bpm * 2), abs(got - bpm / 2)) < bpm * 0.03


def test_bass_note_is_named():
    assert "A2" in ear.describe(pack(beat(120, 110))).split("저음 주요 음:")[1].split("\n")[0]


def test_band_share_follows_content():
    low, high = ear.describe(pack(beat(120, 60))), ear.describe(pack(beat(120, 3000)))
    share = lambda text, name: int(re.search(name + r" (\d+)%", text).group(1))
    assert share(low, "sub") > 50 and share(high, "high") > 50


def test_silence_is_reported_as_silence():
    assert "무음" in ear.describe(pack(np.zeros(R)))


def test_change_over_time_is_visible():
    x = np.concatenate([np.zeros(R * 4), beat(120, 110, 4)])
    row = next(r for r in ear.describe(pack(x)).splitlines() if r.strip().startswith("bass"))
    cells = row.strip().split()[1]
    assert set(cells[:12]) == {"0"} and max(cells[20:]) > "4"
