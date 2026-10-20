"""Built-in synthesized instruments, drum kits, sound effects and custom samples.

Everything is generated with numpy so the app needs no sample library.
``SoundBank.voice`` returns one rendered note (mono float array) and caches
results, because songs repeat the same notes a lot.
"""

from __future__ import annotations

import numpy as np

from .audio_io import decode_wav

SR = 44100

INSTRUMENT_INFO = {
    # name: (category, General-MIDI program for MIDI export)
    "Piano": ("Keys", 0),
    "Electric Piano": ("Keys", 4),
    "Organ": ("Keys", 16),
    "Bell": ("Keys", 14),
    "Marimba": ("Keys", 12),
    "Pluck": ("Guitar / Pluck", 25),
    "Synth Lead": ("Synth", 81),
    "Square Lead": ("Synth", 80),
    "Brass": ("Orchestral", 61),
    "Strings": ("Orchestral", 48),
    "Flute": ("Orchestral", 73),
    "Choir": ("Orchestral", 52),
    "Warm Pad": ("Synth", 89),
    "Synth Bass": ("Bass", 38),
    "Deep Bass": ("Bass", 33),
    "Drum Kit": ("Drums", -1),
    "Electronic Kit": ("Drums", -1),
    "Riser (SFX)": ("Sound FX", 122),
    "Impact (SFX)": ("Sound FX", 127),
    "Laser Zap (SFX)": ("Sound FX", 127),
    "Whoosh (SFX)": ("Sound FX", 122),
    "Sparkle (SFX)": ("Sound FX", 98),
}

KITS = {"Drum Kit", "Electronic Kit"}
SFX = {n for n, (c, _) in INSTRUMENT_INFO.items() if c == "Sound FX"}
BUILTIN_NAMES = list(INSTRUMENT_INFO)


def midi_to_freq(m: float) -> float:
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


# ----------------------------------------------------------------------
# building blocks
# ----------------------------------------------------------------------
def adsr(n_note: int, a: float, d: float, s: float, r: float, sr: int = SR) -> np.ndarray:
    """Envelope covering the note plus its release tail."""
    a_n, d_n, r_n = max(1, int(a * sr)), max(1, int(d * sr)), max(1, int(r * sr))
    total = n_note + r_n
    env = np.empty(total)
    held = max(n_note, 1)
    t = np.arange(held)
    seg = np.where(t < a_n, t / a_n,
                   np.where(t < a_n + d_n, 1.0 - (1.0 - s) * (t - a_n) / d_n, s))
    env[:held] = seg
    level = seg[-1] if held else s
    env[held:] = level * np.linspace(1.0, 0.0, total - held) ** 2
    return env


def _phase(freq: float, n: int, sr: int, vib_rate=0.0, vib_depth=0.0, vib_delay=0.15):
    t = np.arange(n) / sr
    if vib_depth > 0:
        ramp = np.clip((t - vib_delay) / 0.3, 0, 1)
        f = freq * 2.0 ** (vib_depth * ramp * np.sin(2 * np.pi * vib_rate * t) / 12.0)
        return 2 * np.pi * np.cumsum(f) / sr
    return 2 * np.pi * freq * t


def additive(freq, n, amps, sr=SR, decays=None, ratios=None, vib=(0, 0), detune_cents=0.0):
    out = np.zeros(n)
    t = np.arange(n) / sr
    base = _phase(freq * 2 ** (detune_cents / 1200), n, sr, vib[0], vib[1])
    rng = np.random.default_rng(int(freq * 100) % 9973)
    for i, a in enumerate(amps):
        r = ratios[i] if ratios is not None else i + 1
        if freq * r >= sr * 0.45 or a == 0:
            continue
        comp = a * np.sin(r * base + rng.uniform(0, 2 * np.pi))
        if decays is not None:
            comp *= np.exp(-decays[i] * t)
        out += comp
    return out


def saw_amps(count, bright):
    k = np.arange(1, count + 1)
    return (1.0 / k) * np.exp(-(k - 1) * (1.4 - bright) * 0.35)


def square_amps(count, bright):
    k = np.arange(1, count + 1)
    a = np.where(k % 2 == 1, 1.0 / k, 0.0)
    return a * np.exp(-(k - 1) * (1.4 - bright) * 0.25)


def noise(n, seed=0):
    return np.random.default_rng(seed).uniform(-1, 1, n)


def lowpass(x, width):
    """Cheap moving-average low-pass."""
    width = max(1, int(width))
    if width == 1:
        return x
    k = np.ones(width) / width
    return np.convolve(x, k, mode="same")


def highpass(x):
    return np.diff(x, prepend=0.0)


def fm(freq, n, ratio, index, sr=SR, index_decay=2.0):
    t = np.arange(n) / sr
    mod = index * np.exp(-index_decay * t) * np.sin(2 * np.pi * freq * ratio * t)
    return np.sin(2 * np.pi * freq * t + mod)


# ----------------------------------------------------------------------
# instruments
# ----------------------------------------------------------------------
def synth_note(name: str, midi: int, dur: float, bright: float, sr: int = SR) -> np.ndarray:
    f = midi_to_freq(midi)
    n_note = max(1, int(dur * sr))
    b = float(np.clip(bright, 0, 1))

    if name == "Piano":
        env = adsr(n_note, 0.003, 0.05, 0.85, 0.25, sr)
        n = len(env)
        cnt = 14
        k = np.arange(1, cnt + 1)
        amps = (1 / k ** 1.15) * np.exp(-(k - 1) * (1.2 - b) * 0.3)
        ratios = k * np.sqrt(1 + 0.0004 * k ** 2)
        decays = (0.8 + 0.35 * k) * (1 + (midi - 60) / 48)
        sig = additive(f, n, amps, sr, decays, ratios)
        return sig * env * 0.55

    if name == "Electric Piano":
        env = adsr(n_note, 0.002, 0.3, 0.6, 0.3, sr)
        n = len(env)
        sig = fm(f, n, 1.0, 1.2 + 2.0 * b, sr, 2.5) + 0.25 * fm(f, n, 14.0, 0.6 * b, sr, 12)
        t = np.arange(n) / sr
        return sig * env * np.exp(-0.9 * t) * 0.45

    if name == "Organ":
        env = adsr(n_note, 0.01, 0.01, 1.0, 0.06, sr)
        amps = [1, 0.8, 0.5, 0.45, 0, 0.3 * b, 0, 0.25 * b]
        return additive(f, len(env), amps, sr, vib=(6.5, 0.08)) * env * 0.3

    if name == "Bell":
        env = adsr(n_note, 0.002, 0.1, 0.9, 1.2, sr)
        n = len(env)
        t = np.arange(n) / sr
        sig = fm(f, n, 3.5, 2.0 + 2 * b, sr, 1.5) * np.exp(-1.3 * t)
        return sig * env * 0.4

    if name == "Marimba":
        env = adsr(n_note, 0.001, 0.05, 1.0, 0.3, sr)
        n = len(env)
        t = np.arange(n) / sr
        sig = np.sin(2 * np.pi * f * t) * np.exp(-4 * t) + 0.3 * b * np.sin(2 * np.pi * f * 3.9 * t) * np.exp(-14 * t)
        return sig * env * 0.6

    if name == "Pluck":
        env = adsr(n_note, 0.002, 0.05, 1.0, 0.2, sr)
        cnt = 16
        k = np.arange(1, cnt + 1)
        amps = np.sin(np.pi * k * 0.18) / k * (0.6 + 0.6 * b)
        decays = 2.0 + 1.6 * k
        return additive(f, len(env), amps, sr, decays) * env * 0.7

    if name in ("Synth Lead", "Square Lead"):
        env = adsr(n_note, 0.008, 0.12, 0.75, 0.12, sr)
        n = len(env)
        amps = saw_amps(18, b) if name == "Synth Lead" else square_amps(18, b)
        sig = additive(f, n, amps, sr, vib=(5.5, 0.22), detune_cents=-6)
        sig += additive(f, n, amps, sr, vib=(5.5, 0.22), detune_cents=6)
        return sig * env * 0.22

    if name == "Brass":
        env = adsr(n_note, 0.05, 0.15, 0.8, 0.15, sr)
        n = len(env)
        t = np.arange(n) / sr
        swell = np.clip(t / 0.12, 0, 1)
        cnt = 14
        k = np.arange(1, cnt + 1)
        sig = np.zeros(n)
        base = _phase(f, n, sr, 5, 0.12)
        for i, kk in enumerate(k):
            if f * kk > sr * 0.45:
                break
            sig += (1 / kk) * np.sin(kk * base) * np.clip(swell * (0.4 + b) * 2.2 - i * 0.12, 0, 1)
        return sig * env * 0.3

    if name == "Strings":
        env = adsr(n_note, 0.18, 0.2, 0.85, 0.45, sr)
        n = len(env)
        amps = saw_amps(14, b * 0.8)
        sig = sum(additive(f, n, amps, sr, vib=(5.0, 0.12), detune_cents=c) for c in (-8, 0, 7))
        return sig * env * 0.13

    if name == "Flute":
        env = adsr(n_note, 0.06, 0.1, 0.85, 0.12, sr)
        n = len(env)
        sig = additive(f, n, [1, 0.25 * b, 0.1], sr, vib=(5, 0.18))
        sig += 0.08 * lowpass(noise(n, midi), 6)
        return sig * env * 0.45

    if name == "Choir":
        env = adsr(n_note, 0.25, 0.2, 0.85, 0.5, sr)
        n = len(env)
        k = np.arange(1, 30)
        fk = f * k
        form = (np.exp(-((fk - 700) / 180) ** 2) + 0.7 * np.exp(-((fk - 1150) / 220) ** 2)
                + 0.3 * np.exp(-((fk - 2600) / 300) ** 2) + 0.15 / k)
        sig = sum(additive(f, n, form, sr, vib=(5.2, 0.15), detune_cents=c) for c in (-7, 6))
        return sig * env * 0.25

    if name == "Warm Pad":
        env = adsr(n_note, 0.5, 0.4, 0.85, 0.9, sr)
        n = len(env)
        amps = saw_amps(10, b * 0.5)
        sig = sum(additive(f, n, amps, sr, vib=(0.3, 0.06), detune_cents=c) for c in (-10, 0, 11))
        return sig * env * 0.14

    if name == "Synth Bass":
        env = adsr(n_note, 0.004, 0.1, 0.8, 0.06, sr)
        n = len(env)
        k = np.arange(1, 11)
        decays = 1.5 + k * (2.5 - b * 1.5)
        sig = additive(f, n, 1 / k, sr, decays) + 0.7 * np.sin(np.pi * 2 * f * np.arange(n) / sr)
        return np.tanh(sig * 1.2) * env * 0.5

    if name == "Deep Bass":
        env = adsr(n_note, 0.006, 0.2, 0.9, 0.08, sr)
        sig = additive(f, len(env), [1, 0.35 + 0.2 * b, 0.1], sr)
        return sig * env * 0.6

    # unknown name -> piano
    return synth_note("Piano", midi, dur, bright, sr)


# ----------------------------------------------------------------------
# drums
# ----------------------------------------------------------------------
def drum_hit(kit: str, drum: int, sr: int = SR) -> np.ndarray:
    electronic = kit == "Electronic Kit"
    seed = drum * 31 + (7 if electronic else 0)
    if drum in (35, 36):  # kick
        n = int((0.9 if electronic else 0.45) * sr)
        t = np.arange(n) / sr
        f = 48 + (110 if electronic else 120) * np.exp(-t * (18 if electronic else 30))
        ph = 2 * np.pi * np.cumsum(f) / sr
        sig = np.sin(ph) * np.exp(-t * (3.5 if electronic else 7.5))
        sig[: int(0.003 * sr)] += 0.4 * noise(int(0.003 * sr), seed)
        return np.tanh(sig * 1.5) * 0.9
    if drum in (38, 40):  # snare
        n = int(0.3 * sr)
        t = np.arange(n) / sr
        tone = np.sin(2 * np.pi * (185 if not electronic else 210) * t) * np.exp(-t * 25)
        nz = highpass(noise(n, seed)) * np.exp(-t * (14 if not electronic else 18))
        return (0.5 * tone + 0.9 * nz) * 0.7
    if drum == 39:  # clap
        n = int(0.35 * sr)
        t = np.arange(n) / sr
        env = np.exp(-t * 16)
        for d in (0.0, 0.011, 0.022):
            env += 0.8 * np.exp(-np.clip(t - d, 0, None) * 120) * (t >= d)
        return highpass(lowpass(noise(n, seed), 2)) * env * 0.45
    if drum in (42, 44, 46):  # hats
        n = int((0.07 if drum != 46 else 0.35) * sr)
        t = np.arange(n) / sr
        nz = highpass(highpass(noise(n, seed)))
        metal = sum(np.sign(np.sin(2 * np.pi * fr * t)) for fr in (3150, 4510, 5870)) * 0.08
        dec = 45 if drum != 46 else 8
        if electronic:
            dec *= 1.4
        return (nz * 0.6 + metal) * np.exp(-t * dec) * 0.35
    if drum in (49, 57):  # crash
        n = int(1.6 * sr)
        t = np.arange(n) / sr
        nz = highpass(noise(n, seed))
        metal = sum(np.sin(2 * np.pi * fr * t) for fr in (3200, 4100, 5300, 6700)) * 0.05
        return (nz * 0.55 + metal) * np.exp(-t * 2.8) * 0.4
    # toms and anything else
    base = {41: 90, 43: 105, 45: 120, 47: 145, 48: 170, 50: 200}.get(drum, 150)
    n = int(0.45 * sr)
    t = np.arange(n) / sr
    f = base * (1 + 0.5 * np.exp(-t * 25))
    ph = 2 * np.pi * np.cumsum(f) / sr
    return np.sin(ph) * np.exp(-t * 7) * 0.7


# ----------------------------------------------------------------------
# sound effects (made at middle C, pitched by resampling)
# ----------------------------------------------------------------------
def sfx_sample(name: str, sr: int = SR) -> np.ndarray:
    if name.startswith("Riser"):
        n = int(2.5 * sr)
        t = np.arange(n) / sr
        f = 261.6 * 2 ** (t / 2.5 * 2)
        tone = np.sin(2 * np.pi * np.cumsum(f) / sr)
        nz = highpass(noise(n, 5)) * (t / 2.5) ** 2
        env = (t / 2.5) ** 1.5
        return (0.5 * tone + 0.6 * nz) * env * 0.6
    if name.startswith("Impact"):
        n = int(2.0 * sr)
        t = np.arange(n) / sr
        f = 65 * (1 + 2 * np.exp(-t * 12))
        boom = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 2)
        nz = lowpass(noise(n, 9), 4) * np.exp(-t * 6)
        return np.tanh((boom + 0.6 * nz) * 1.4) * 0.8
    if name.startswith("Laser"):
        n = int(0.4 * sr)
        t = np.arange(n) / sr
        f = 261.6 * 4 * np.exp(-t * 9) + 100
        return np.sign(np.sin(2 * np.pi * np.cumsum(f) / sr)) * np.exp(-t * 6) * 0.3
    if name.startswith("Whoosh"):
        n = int(1.5 * sr)
        t = np.arange(n) / sr
        env = np.sin(np.pi * t / 1.5) ** 2
        nz = noise(n, 13)
        lo, hi = lowpass(nz, 12), highpass(nz)
        mix = np.clip(t / 1.5, 0, 1)
        return (lo * (1 - mix) + hi * mix * 0.4) * env * 0.9
    if name.startswith("Sparkle"):
        n = int(1.5 * sr)
        out = np.zeros(n)
        rng = np.random.default_rng(21)
        for i in range(10):
            start = int(i * 0.08 * sr)
            m = 72 + rng.choice([0, 4, 7, 12, 16, 19])
            seg = fm(midi_to_freq(m), n - start, 3.5, 1.5, sr, 3.0)
            t = np.arange(n - start) / sr
            out[start:] += seg * np.exp(-t * 5) * (0.5 - i * 0.03)
        return out * 0.4
    return np.zeros(int(0.1 * sr))


def pitch_shift(sample: np.ndarray, semitones: float) -> np.ndarray:
    ratio = 2.0 ** (semitones / 12.0)
    if abs(ratio - 1.0) < 1e-4:
        return sample.copy()
    n_out = max(1, int(len(sample) / ratio))
    x = np.arange(n_out) * ratio
    return np.interp(x, np.arange(len(sample)), sample)


def resample(sample: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return sample
    n_out = int(len(sample) * sr_out / sr_in)
    return np.interp(np.arange(n_out) * sr_in / sr_out, np.arange(len(sample)), sample)


# ----------------------------------------------------------------------
class SoundBank:
    """Renders notes for built-in and custom sounds, with caching."""

    def __init__(self, custom_sounds=(), sr: int = SR):
        self.sr = sr
        self.custom = {}
        for cs in custom_sounds:
            try:
                data, rate = decode_wav(cs.wav_bytes)
                data = resample(data, rate, sr)
                peak = float(np.max(np.abs(data))) or 1.0
                self.custom[cs.name] = (cs, data / peak)
            except Exception:  # broken sample: skip it rather than crash
                continue
        self._cache: dict = {}
        self._sfx: dict = {}

    def names(self) -> list[str]:
        return BUILTIN_NAMES + [n for n in self.custom]

    def is_kit(self, name: str) -> bool:
        return name in KITS

    def voice(self, name: str, midi: int, dur: float, bright: float, drum: bool = False) -> np.ndarray:
        key = (name, midi, round(dur, 2), round(bright * 4) / 4, drum)
        v = self._cache.get(key)
        if v is None:
            v = self._render(name, midi, round(dur, 2), round(bright * 4) / 4, drum)
            if len(self._cache) > 4000:
                self._cache.clear()
            self._cache[key] = v
        return v

    def _render(self, name, midi, dur, bright, drum):
        sr = self.sr
        if name in KITS:
            return drum_hit(name, midi if drum else 38, sr)
        if name in SFX:
            if name not in self._sfx:
                self._sfx[name] = sfx_sample(name, sr)
            return pitch_shift(self._sfx[name], midi - 60)
        if name in self.custom:
            cs, data = self.custom[name]
            return self._render_custom(cs, data, midi, dur)
        if drum:  # drum notes on a melodic instrument
            return synth_note(name, 48 + (midi % 12), 0.25, bright, sr)
        return synth_note(name, midi, dur, bright, sr)

    def _render_custom(self, cs, data, midi, dur):
        sr = self.sr
        shifted = pitch_shift(data, midi - int(cs.root_midi)) * float(cs.gain)
        if cs.kind == "sfx":
            return shifted
        n_note = max(1, int(dur * sr))
        rel = int(0.08 * sr)
        total = n_note + rel
        if len(shifted) < total and cs.loop and len(shifted) > 256:
            fade = min(256, len(shifted) // 4)
            loop = shifted.copy()
            loop[:fade] *= np.linspace(0, 1, fade)
            loop[-fade:] *= np.linspace(1, 0, fade)
            reps = int(np.ceil(total / (len(loop) - fade))) + 1
            out = np.zeros(reps * (len(loop) - fade) + fade)
            for i in range(reps):
                s = i * (len(loop) - fade)
                out[s:s + len(loop)] += loop
            shifted = out
        out = np.zeros(total)
        m = min(total, len(shifted))
        out[:m] = shifted[:m]
        env = adsr(n_note, 0.004, 0.01, 1.0, 0.08, sr)[:total]
        return out * env


def estimate_root_midi(sample: np.ndarray, sr: int) -> int | None:
    """Guess the pitch of a recording (autocorrelation). None if unclear."""
    if len(sample) < sr // 20:
        return None
    start = min(len(sample) // 4, int(0.05 * sr))
    seg = sample[start:start + int(0.4 * sr)]
    seg = seg - seg.mean()
    if np.max(np.abs(seg)) < 1e-4:
        return None
    seg = seg * np.hanning(len(seg))
    n = 1 << int(np.ceil(np.log2(len(seg) * 2)))
    spec = np.fft.rfft(seg, n)
    ac = np.fft.irfft(spec * np.conj(spec))[: len(seg)]
    ac /= ac[0] or 1.0
    lo, hi = int(sr / 1500), int(sr / 50)
    if hi >= len(ac):
        return None
    lag = lo + int(np.argmax(ac[lo:hi]))
    if ac[lag] < 0.5:
        return None
    freq = sr / lag
    return int(round(69 + 12 * np.log2(freq / 440.0)))
