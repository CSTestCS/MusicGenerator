"""Mix a generated Song into stereo audio."""

from __future__ import annotations

import numpy as np

from .instruments import SR, SoundBank

TAIL_SECONDS = 3.0


def _comb(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    """Feedback comb filter, processed one delay-length block at a time."""
    y = x.copy()
    n = len(y)
    for k in range(delay, n, delay):
        end = min(k + delay, n)
        y[k:end] += g * y[k - delay:k - delay + (end - k)]
    return y


def _allpass(x: np.ndarray, delay: int, g: float) -> np.ndarray:
    v = -g * x
    v[delay:] += x[:-delay]
    n = len(v)
    for k in range(delay, n, delay):
        end = min(k + delay, n)
        v[k:end] += g * v[k - delay:k - delay + (end - k)]
    return v


def reverb(mono: np.ndarray, sr: int = SR, size: float = 1.0) -> np.ndarray:
    """Small Schroeder-style stereo reverb. Returns (N, 2)."""
    out = np.zeros((len(mono), 2))
    pre = np.zeros_like(mono)
    pd = int(0.012 * sr)
    pre[pd:] = mono[:-pd]
    for ch, spread in ((0, 0), (1, 23)):
        acc = np.zeros_like(mono)
        for ms, g in ((29.7, 0.80), (37.1, 0.79), (41.1, 0.78), (43.7, 0.77)):
            d = int((ms * size) * sr / 1000) + spread
            acc += _comb(pre, d, g)
        acc = _allpass(acc, int(0.005 * sr) + spread, 0.7)
        acc = _allpass(acc, int(0.0017 * sr) + spread // 2, 0.7)
        # soften the highs
        acc = np.convolve(acc, np.ones(4) / 4, mode="same")
        out[:, ch] = acc * 0.18
    return out


def _raw_mix(song, bank, progress, sr, only_track=None) -> np.ndarray:
    p = song.project
    spb = song.seconds_per_beat
    total = int((song.duration_seconds + TAIL_SECONDS) * sr)
    dry = np.zeros((total, 2))
    send = np.zeros(total)
    any_solo = any(t.solo for t in p.tracks)
    tracks = [t for t in p.tracks if not t.mute and (t.solo or not any_solo)]
    if only_track is not None:
        tracks = [t for t in p.tracks if t.id == only_track]
    for i, t in enumerate(tracks):
        if progress:
            progress(i / max(1, len(tracks)) * 0.9, f"Rendering {t.name}...")
        buf = np.zeros(total)
        for n in song.notes.get(t.id, []):
            v = bank.voice(t.instrument, n.midi, n.dur * spb, n.bright, n.drum)
            s = int(n.start * spb * sr)
            if s >= total:
                continue
            e = min(total, s + len(v))
            buf[s:e] += v[: e - s] * n.vel
        buf *= float(t.volume)
        pan = float(np.clip(t.pan, -1, 1))
        dry[:, 0] += buf * np.cos((pan + 1) * np.pi / 4)
        dry[:, 1] += buf * np.sin((pan + 1) * np.pi / 4)
        send += buf * float(t.reverb)
    if progress:
        progress(0.92, "Adding reverb...")
    if p.master_reverb > 0 and np.any(send):
        return dry + reverb(send, sr) * (float(p.master_reverb) * 2.0)
    return dry


def mix_peak(song, bank: SoundBank | None = None, sr: int = SR) -> float:
    """Peak level of the full mix before mastering (used for stems)."""
    bank = bank or SoundBank(song.project.custom_sounds, sr)
    return float(np.max(np.abs(_raw_mix(song, bank, None, sr)))) or 1.0


def render(song, bank: SoundBank | None = None, progress=None, sr: int = SR,
           only_track: str | None = None, peak: float | None = None) -> np.ndarray:
    """Render ``song`` to a float stereo array shaped (N, 2).

    ``only_track`` renders a single track (for stems); pass the full mix's
    ``peak`` (from ``mix_peak``) so stems keep their levels relative to the mix.
    """
    bank = bank or SoundBank(song.project.custom_sounds, sr)
    mix = _raw_mix(song, bank, progress, sr, only_track)
    if peak is None:
        peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / peak * 1.1
    mix = np.tanh(mix) / np.tanh(1.1) * 0.95 * float(song.project.master_volume)
    # tiny fades to avoid clicks
    f = int(0.01 * sr)
    mix[:f] *= np.linspace(0, 1, f)[:, None]
    tail = min(len(mix), int(0.5 * sr))
    mix[-tail:] *= np.linspace(1, 0, tail)[:, None]
    if progress:
        progress(1.0, "Done")
    return mix.astype(np.float32)
