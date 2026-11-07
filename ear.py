"""Turns a real capture into a text score a model without audio input can reason about.

Everything here is measured from the samples. It reports tempo, notes, where energy sits
over time and how it moves; it does not claim to know how the music feels.
"""
from __future__ import annotations

import io
import wave

import numpy as np

BANDS = (("sub", 20, 80), ("bass", 80, 250), ("mid", 250, 2000), ("high", 2000, 6000), ("air", 6000, 20000))
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FRAME, HOP = 4096, 480
NOTE_FRAME = 16384
SLOTS = 32


def read_mono(wav: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav), "rb") as handle:
        rate, channels = handle.getframerate(), handle.getnchannels()
        if handle.getsampwidth() != 2:
            raise ValueError("16-bit WAV만 분석할 수 있어.")
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return data.reshape(-1, channels).mean(axis=1), rate


def spectrogram(x: np.ndarray) -> np.ndarray:
    if len(x) < FRAME:
        x = np.pad(x, (0, FRAME - len(x)))
    starts = np.arange(0, len(x) - FRAME + 1, HOP)
    window = np.hanning(FRAME)
    # Batched so a 16-second capture stays well under a free Cloud instance's memory.
    return np.vstack([np.abs(np.fft.rfft(np.stack([x[s:s + FRAME] * window for s in part]), axis=1)).astype(np.float32)
                      for part in np.array_split(starts, max(1, len(starts) // 256))])


def tempo(flux: np.ndarray, rate: int) -> tuple[float | None, float]:
    """Beat tempo from flux autocorrelation, with the confidence of the winning lag."""
    fps = rate / HOP
    f = flux - flux.mean()
    if not np.any(f):
        return None, 0.0
    ac = np.correlate(f, f, "full")[len(f) - 1:]
    if ac[0] <= 0:
        return None, 0.0
    low, high = int(fps * 60 / 260), min(len(ac) - 1, int(fps * 60 / 50))
    if high <= low:
        return None, 0.0
    lag = low + int(np.argmax(ac[low:high]))
    return round(60 * fps / lag, 1), round(float(ac[lag] / ac[0]), 2)


def top_notes(x: np.ndarray, rate: int, low: float, high: float, count: int) -> list[str]:
    """Named pitches from local spectral peaks. Uses a long window: at 110 Hz a semitone is only 6 Hz."""
    window = np.hanning(NOTE_FRAME)
    freqs = np.fft.rfftfreq(NOTE_FRAME, 1 / rate)
    band = np.flatnonzero((freqs >= low) & (freqs < high))
    energy: dict[str, float] = {}
    for start in range(0, max(1, len(x) - NOTE_FRAME), rate // 8):
        chunk = x[start:start + NOTE_FRAME]
        if len(chunk) < NOTE_FRAME:
            break
        mag = np.abs(np.fft.rfft(chunk * window))
        limit = mag[band].max() * 0.3
        for i in band[1:-1]:
            if mag[i] > limit and mag[i] >= mag[i - 1] and mag[i] > mag[i + 1]:
                midi = int(round(69 + 12 * np.log2(freqs[i] / 440)))
                name = f"{NOTES[midi % 12]}{midi // 12 - 1}"
                energy[name] = energy.get(name, 0) + float(mag[i])
    return sorted(energy, key=energy.get, reverse=True)[:count]


def describe(wav: bytes) -> str:
    x, rate = read_mono(wav)
    seconds = len(x) / rate
    if not len(x) or np.max(np.abs(x)) < 1e-3:
        return f"길이 {seconds:.1f}초, 사실상 무음."
    spec = spectrogram(x)
    freqs = np.fft.rfftfreq(FRAME, 1 / rate)
    flux = np.maximum(0, np.diff(spec, axis=0)).sum(axis=1)
    bpm, confidence = tempo(flux, rate)
    threshold = flux.mean() + flux.std()
    peaks = (flux[1:-1] > threshold) & (flux[1:-1] >= flux[:-2]) & (flux[1:-1] > flux[2:])
    onsets = int(peaks.sum())

    power = spec ** 2
    chunks = np.array_split(np.arange(len(power)), min(SLOTS, len(power)))
    totals = {}
    rows = []
    reference = 10 * np.log10(power.sum(axis=1).max() + 1e-12)
    for name, low, high in BANDS:
        mask = (freqs >= low) & (freqs < high)
        energy = power[:, mask].sum(axis=1)
        totals[name] = float(energy.sum())
        levels = [10 * np.log10(energy[c].mean() + 1e-12) for c in chunks]
        rows.append(f"{name:>4} " + "".join(str(int(np.clip((v - reference + 60) / 6, 0, 9))) for v in levels))
    whole = sum(totals.values()) or 1
    share = ", ".join(f"{k} {100 * v / whole:.0f}%" for k, v in totals.items())

    rms = np.sqrt(np.mean(x ** 2))
    crest = 20 * np.log10(np.max(np.abs(x)) / (rms + 1e-12))
    parts = [np.sqrt(np.mean(c ** 2)) for c in np.array_split(x, 16)]
    swing = 20 * np.log10((max(parts) + 1e-9) / (min(parts) + 1e-9))
    return "\n".join([
        f"길이 {seconds:.1f}초",
        f"측정 템포 {bpm} BPM (신뢰도 {confidence})" if bpm else "측정 템포 없음",
        f"어택 {onsets}개, 초당 {onsets / seconds:.1f}개",
        f"저음 주요 음: {' '.join(top_notes(x, rate, 30, 250, 4)) or '없음'}",
        f"중음 주요 음: {' '.join(top_notes(x, rate, 250, 2000, 6)) or '없음'}",
        f"대역 에너지 비율: {share}",
        f"크레스트 {crest:.1f}dB, 구간 음량 변화폭 {swing:.1f}dB",
        f"시간별 대역 세기 (왼쪽→오른쪽 {len(chunks)}칸, 0 없음 ~ 9 최대):",
        *rows,
    ])
