"""Song generation: turn a Project into notes for every track.

How the words shape the song
----------------------------
* The **parent word** is stretched across the whole song.  Its letters split
  the song into equal parts, and its contour is a slow curve over the full
  length.  That curve lifts and lowers the register of every part and (in
  "word" modes) the energy: loudness, brightness and how busy parts are.
* A **track word** repeats every ``cycle_bars`` bars.  Its contour bends the
  track's own melody / arpeggio / bass movement on top of the slow parent
  curve, so tracks rise and fall with the parent word naturally.
* A **formula** splits the song into sections (verse, chorus...) with their
  own energy and chord loops.  Sections of the same kind share a motif, so
  the chorus hook comes back every time.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field

import numpy as np

from .contour import WordShape, clean_word
from .formulas import WORD_PROGRESSIONS, build_sections
from .project import Project, Track
from .theory import Harmony

# General-MIDI drum numbers used by the drum generator
KICK, SNARE, CLAP, HAT, OPEN_HAT, CRASH, TOM_LO, TOM_HI = 36, 38, 39, 42, 46, 49, 45, 48


@dataclass
class Note:
    start: float        # beats
    dur: float          # beats
    midi: int
    vel: float          # 0..1
    bright: float = 0.6  # 0..1 tone brightness
    drum: bool = False


@dataclass
class TLSection:
    index: int
    name: str
    kind: str
    start: float        # beats
    end: float
    energy: float
    progression: list[int]
    motif: str


@dataclass
class TLLetter:
    index: int
    char: str
    start: float
    end: float


@dataclass
class Song:
    project: Project
    timeline: "Timeline"
    notes: dict[str, list[Note]] = field(default_factory=dict)

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / self.timeline.tempo

    @property
    def duration_seconds(self) -> float:
        return self.timeline.total_beats * self.seconds_per_beat


def _norm(vals: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(vals)), float(np.max(vals))
    if hi - lo < 0.04:
        return np.full_like(vals, 0.5)
    return (vals - lo) / (hi - lo)


def stable_seed(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode("utf-8"))


class Timeline:
    """Sections, letters, chords and the parent curves for one song."""

    def __init__(self, project: Project):
        self.project = project
        self.mode = project.shape_mode
        self.tempo = max(30, min(240, int(project.tempo)))
        self.parent = WordShape(project.parent_word or "song", project.contour_style)
        self.harmony = Harmony(project.key, project.scale)
        # normalised curves so every word uses the full range of motion
        self._parent_vals = _norm(self.parent.values)
        self._parent_energy = _norm(0.5 * self.parent.values + 0.5 * self.parent.energy)

        if self.mode == "word":
            self.sections = self._word_sections(project)
        else:
            self.sections = self._formula_sections(project)
        self.total_beats = self.sections[-1].end if self.sections else 64.0
        self.bars = int(round(self.total_beats / 4))
        self.letters = self._letters()
        self._bar_chords = self._chords()

    # -- construction ---------------------------------------------------
    def _formula_sections(self, p: Project) -> list[TLSection]:
        out, beat = [], 0.0
        for i, s in enumerate(build_sections(p.formula, p.section_scale)):
            end = beat + s.bars * 4
            out.append(TLSection(i, s.name, s.kind, beat, end, s.energy,
                                 s.progression, s.motif_key()))
            beat = end
        return out

    def _word_sections(self, p: Project) -> list[TLSection]:
        """Without a formula each letter of the parent word is a section."""
        letters = self.parent.letters or "a"
        n = len(letters)
        bars = max(n, int(p.word_bars))
        out = []
        for i, ch in enumerate(letters):
            b0 = round(i * bars / n)
            b1 = round((i + 1) * bars / n)
            prog = WORD_PROGRESSIONS[(ord(ch) * 7 + 3) % len(WORD_PROGRESSIONS)]
            energy = 0.3 + 0.7 * float(self._parent_energy[i])
            kind = "outro" if i == n - 1 and n > 2 else ("intro" if i == 0 and n > 2 else "letter")
            out.append(TLSection(i, f"'{ch.upper()}'", kind, b0 * 4.0, b1 * 4.0,
                                 energy, list(prog), f"letter-{ch}"))
        return out

    def _letters(self) -> list[TLLetter]:
        letters = self.parent.letters or "a"
        n = len(letters)
        if self.mode == "word":
            return [TLLetter(i, ch, s.start, s.end)
                    for i, (ch, s) in enumerate(zip(letters, self.sections))]
        out = []
        bars = self.total_beats / 4
        for i, ch in enumerate(letters):
            if bars >= n:
                s, e = round(i * bars / n) * 4.0, round((i + 1) * bars / n) * 4.0
            else:
                s = round(i * self.total_beats / n)
                e = round((i + 1) * self.total_beats / n)
            out.append(TLLetter(i, ch, float(s), float(e)))
        return out

    def _chords(self) -> list[int]:
        chords = []
        for s in self.sections:
            nbars = int(round((s.end - s.start) / 4))
            for b in range(nbars):
                chords.append(s.progression[b % len(s.progression)])
        if chords:
            chords[-1] = 0  # always end on the home chord
            if len(chords) > 1 and self.sections[-1].kind == "outro":
                chords[-2] = chords[-2] if chords[-2] in (3, 4) else 4
        return chords

    # -- queries --------------------------------------------------------
    def pos(self, beat):
        return np.clip(np.asarray(beat, dtype=float) / self.total_beats, 0.0, 1.0)

    def section_at(self, beat: float) -> TLSection:
        for s in self.sections:
            if beat < s.end:
                return s
        return self.sections[-1]

    def next_section(self, sec: TLSection):
        i = sec.index + 1
        return self.sections[i] if i < len(self.sections) else None

    def letter_at(self, beat: float) -> TLLetter:
        for l in self.letters:
            if beat < l.end:
                return l
        return self.letters[-1]

    def chord_at(self, beat: float) -> int:
        bar = int(beat // 4)
        if not self._bar_chords:
            return 0
        return self._bar_chords[min(max(bar, 0), len(self._bar_chords) - 1)]

    def parent_curve(self, beat) -> np.ndarray:
        """Slow parent-word contour (0..1) stretched over the whole song."""
        from .contour import sample_curve
        if self.mode == "formula":
            e = np.vectorize(lambda b: self.section_at(b).energy)(np.atleast_1d(beat))
            return 0.3 + 0.4 * e
        return np.atleast_1d(sample_curve(self._parent_vals, self.pos(beat)))

    def energy(self, beat) -> np.ndarray:
        """Overall intensity (0..1) at ``beat``."""
        from .contour import sample_curve
        beats = np.atleast_1d(np.asarray(beat, dtype=float))
        word_e = 0.25 + 0.75 * sample_curve(self._parent_energy, self.pos(beats))
        if self.mode == "word":
            out = word_e
        else:
            form = np.array([self._formula_energy(b) for b in beats])
            out = form if self.mode == "formula" else 0.6 * form + 0.4 * word_e
        return np.clip(out, 0.05, 1.0)

    def _formula_energy(self, beat: float) -> float:
        s = self.section_at(beat)
        e = s.energy
        nxt = self.next_section(s)
        # build-ups: last 4 beats of a section glide toward the next one
        if nxt is not None and s.kind in ("prechorus", "bridge", "intro") and beat > s.end - 4:
            f = (beat - (s.end - 4)) / 4.0
            e = e + (nxt.energy - e) * f
        if s.kind == "outro":
            f = (beat - s.start) / max(1.0, s.end - s.start)
            e = e * (1.0 - 0.45 * f)
        return float(e)


# ----------------------------------------------------------------------
# Track generators
# ----------------------------------------------------------------------
class TrackContext:
    def __init__(self, tl: Timeline, track: Track, project: Project, is_kit: bool):
        self.tl = tl
        self.track = track
        self.is_kit = is_kit
        word = clean_word(track.word) or tl.parent.letters
        self.shape = WordShape(word, project.contour_style)
        self._vals = _norm(self.shape.values)
        self.cycle = max(0.25, float(track.cycle_bars)) * 4.0
        self.variation = project.variation
        self.h = tl.harmony
        steps = max(0.125, float(track.note_beats))
        self.step = steps

    def word_curve(self, beat: float) -> float:
        from .contour import sample_curve
        phase = (beat % self.cycle) / self.cycle
        return float(sample_curve(self._vals, phase, cyclic=True))

    def rng(self, *parts) -> random.Random:
        return random.Random(stable_seed(self.variation, self.track.id, *parts))

    def pitch_offset(self, beat: float, span: float = 8.0) -> float:
        """Combined rise/fall in scale steps from parent + track word."""
        t = self.track
        p = float(self.tl.parent_curve(beat)[0]) - 0.5
        w = self.word_curve(beat) - 0.5
        scale_len = len(self.h.melody_steps) / 7.0
        return (t.parent_depth * p * span + t.word_depth * w * span) * scale_len


def _role_allowed(role: str, energy: float, kind: str) -> bool:
    if role == "drums":
        return energy >= 0.34
    if role == "bass":
        return energy >= 0.28
    if role == "arp":
        return energy >= 0.5 or kind == "solo"
    if role == "harmony":
        return energy >= 0.22
    return True


def _section_steps(ctx: TrackContext, sec: TLSection, step: float):
    b = sec.start
    while b < sec.end - 1e-6:
        yield b
        b += step


def gen_melody(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes: list[Note] = []
    base_oct = 5 + t.octave
    last_bar_start = tl.total_beats - 4
    for sec in tl.sections:
        solo = sec.kind == "solo"
        step = ctx.step / (2 if solo else 1)
        steps_per_motif = max(1, int(round(8 / step)))  # 2-bar motif
        rng = ctx.rng("melody-rhythm", sec.motif)
        orng = ctx.rng("melody-notes", sec.motif, sec.kind if sec.kind == "variation" else "")
        pattern = []
        for i in range(steps_per_motif):
            pos = i * step
            strong = abs(pos % 2.0) < 1e-6
            pattern.append((rng.random(), strong, orng.choice([-1, 0, 0, 0, 1, 2 if solo else 0])))
        onsets = []
        for b in _section_steps(ctx, sec, step):
            if b >= last_bar_start:
                break
            i = int(round((b - sec.start) / step)) % steps_per_motif
            r, strong, off = pattern[i]
            e = float(tl.energy(b)[0])
            if sec.kind == "intro" and tl.mode != "word":
                e *= 0.6
            p_on = 0.3 + 0.55 * e + (0.3 if strong else 0.0) + (0.15 if solo else 0.0)
            if i == 0 or r < p_on:
                onsets.append((b, strong, off, e))
        for k, (b, strong, off, e) in enumerate(onsets):
            nxt = onsets[k + 1][0] if k + 1 < len(onsets) else min(sec.end, last_bar_start)
            dur = min(nxt - b, 2.0)
            if rng.random() < 0.12 and dur > step:
                dur *= 0.5
            span = 10.0 if solo else 8.0
            idx = int(round(ctx.pitch_offset(b, span))) + off
            deg = tl.chord_at(b)
            if strong:
                idx = _snap_chord_tone(h, idx, base_oct, deg)
            midi = h.melody_note(idx, base_oct)
            w = ctx.word_curve(b)
            vel = 0.42 + 0.45 * e + 0.12 * (w - 0.5) + (0.06 if strong else 0.0)
            notes.append(Note(b, max(0.1, dur * 0.95), midi, float(np.clip(vel, 0.1, 1.0)), e))
    # satisfying ending: hold the tonic over the final bar
    if tl.total_beats >= 4:
        e = float(tl.energy(last_bar_start)[0])
        midi = h.melody_note(0, base_oct)
        notes.append(Note(last_bar_start, 4.0, midi, 0.5 + 0.3 * e, e))
    return notes


def _snap_chord_tone(h: Harmony, idx: int, base_oct: int, degree: int) -> int:
    for d in (0, -1, 1, -2, 2):
        if h.is_chord_tone(h.melody_note(idx + d, base_oct), degree):
            return idx + d
    return idx


def gen_harmony(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes = []
    for bar in range(tl.bars):
        b0 = bar * 4.0
        e = float(tl.energy(b0)[0])
        deg = tl.chord_at(b0)
        reg = float(tl.parent_curve(b0)[0])
        inv = int(round(reg * 2 * t.parent_depth))
        seventh = e > 0.62
        chord = h.chord_notes(deg, 4 + t.octave, seventh, inv)
        if bar == tl.bars - 1:
            for m in h.chord_notes(0, 4 + t.octave, False, inv):
                notes.append(Note(b0, 4.0, m, 0.55, e))
            continue
        if e < 0.4:
            hits = [(0.0, 4.0)]
        elif e < 0.65:
            hits = [(0.0, 2.0), (2.0, 2.0)]
        elif e < 0.85:
            hits = [(0.0, 1.5), (1.5, 1.0), (2.5, 1.5)]
        else:
            hits = [(0.0, 1.0), (1.0, 0.5), (1.5, 1.0), (2.5, 0.5), (3.0, 1.0)]
        step = max(ctx.step, 0.25)
        if step >= 2:
            hits = [(0.0, 4.0)] if step >= 4 else [(0.0, 2.0), (2.0, 2.0)]
        for off, d in hits:
            b = b0 + off
            w = ctx.word_curve(b)
            vel = 0.35 + 0.4 * e + 0.2 * t.word_depth * (w - 0.5)
            for m in chord:
                notes.append(Note(b, d * 0.92, m, float(np.clip(vel, 0.1, 1)), e))
    return notes


def gen_pad(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes = []
    for bar in range(tl.bars):
        b0 = bar * 4.0
        e = float(tl.energy(b0)[0])
        deg = tl.chord_at(b0)
        reg = float(tl.parent_curve(b0)[0])
        inv = int(round(reg * 2 * t.parent_depth))
        w = ctx.word_curve(b0)
        last = bar == tl.bars - 1
        chord = h.chord_notes(0 if last else deg, 4 + t.octave, e > 0.6 and not last, inv)
        vel = 0.3 + 0.35 * e + 0.15 * t.word_depth * (w - 0.5)
        for m in chord:
            notes.append(Note(b0, 4.15, m, float(np.clip(vel, 0.1, 1)), e * 0.7))
    return notes


def gen_bass(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes = []
    octv = 2 + t.octave
    for bar in range(tl.bars):
        b0 = bar * 4.0
        e = float(tl.energy(b0)[0])
        deg = tl.chord_at(b0)
        root = h.chord_root(deg, octv)
        if bar == tl.bars - 1:
            notes.append(Note(b0, 4.0, h.chord_root(0, octv), 0.7, e))
            continue
        if e < 0.45:
            step = 2.0
        elif e < 0.75:
            step = 1.0
        else:
            step = max(0.5, min(ctx.step, 1.0))
        b = b0
        while b < b0 + 4 - 1e-6:
            w = ctx.word_curve(b)
            choice = w * t.word_depth + (1 - t.word_depth) * 0.0
            if abs(b - b0) < 1e-6 or choice < 0.35:
                m = root
            elif choice < 0.6:
                m = h.chord_fifth(deg, octv)
                if m - root > 7:
                    m -= 12
            elif choice < 0.85:
                m = root + 12
            else:
                m = h.chord_notes(deg, octv)[1]
            vel = 0.55 + 0.35 * e + (0.08 if abs((b - b0) % 2) < 1e-6 else 0)
            notes.append(Note(b, step * 0.9, m, float(np.clip(vel, 0.1, 1)), e))
            b += step
    return notes


def gen_arp(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes = []
    step = ctx.step if ctx.step <= 1 else 0.5
    total = tl.total_beats - 4
    b = 0.0
    while b < total - 1e-6:
        e = float(tl.energy(b)[0])
        deg = tl.chord_at(b)
        reg = float(tl.parent_curve(b)[0])
        base = 4 + t.octave + (1 if reg * t.parent_depth > 0.7 else 0)
        tones = h.chord_notes(deg, base) + h.chord_notes(deg, base + 1)
        w = ctx.word_curve(b)
        idx = int(round(w * (len(tones) - 1)))
        vel = 0.3 + 0.45 * e + (0.1 if abs(b % 1) < 1e-6 else 0)
        notes.append(Note(b, step * 0.85, tones[idx], float(np.clip(vel, 0.1, 1)), e))
        b += step
    if tl.total_beats >= 4:
        notes.append(Note(total, 3.0, h.chord_notes(0, 5 + t.octave)[0], 0.4, 0.5))
    return notes


def gen_accent(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes = []
    vals = ctx._vals
    n = len(vals)
    slot = ctx.cycle / n
    peaks = [i for i in range(n)
             if vals[i] >= vals[(i - 1) % n] and vals[i] >= vals[(i + 1) % n]] or [0]
    c = 0.0
    while c < tl.total_beats - 1e-6:
        for i in peaks:
            b = c + i * slot
            if b >= tl.total_beats:
                break
            e = float(tl.energy(b)[0])
            idx = int(round(ctx.pitch_offset(b)))
            midi = h.melody_note(idx, 4 + t.octave)
            notes.append(Note(b, max(0.25, slot), midi, float(np.clip(0.4 + 0.5 * e, 0, 1)), e))
        c += ctx.cycle
    return notes


def gen_drums(ctx: TrackContext) -> list[Note]:
    tl, h, t = ctx.tl, ctx.h, ctx.track
    notes = []
    for bar in range(tl.bars):
        b0 = bar * 4.0
        sec = tl.section_at(b0)
        e = float(tl.energy(b0)[0])
        last = bar == tl.bars - 1
        sec_first_bar = abs(b0 - sec.start) < 1e-6
        nxt = tl.next_section(sec)
        sec_last_bar = b0 + 4 >= sec.end - 1e-6
        hits = []
        if last:
            hits += [(0.0, CRASH, 0.9), (0.0, KICK, 1.0)]
        else:
            if sec_first_bar and e >= 0.55:
                hits.append((0.0, CRASH, 0.75))
            if e < 0.5:
                hits += [(0.0, KICK, 0.85), (2.5, KICK, 0.6), (1.0, SNARE, 0.6), (3.0, SNARE, 0.65)]
                hits += [(q, HAT, 0.45) for q in (0.0, 1.0, 2.0, 3.0)]
            elif e < 0.78:
                hits += [(0.0, KICK, 0.95), (1.5, KICK, 0.55), (2.0, KICK, 0.85),
                         (1.0, SNARE, 0.8), (3.0, SNARE, 0.85)]
                hits += [(q * 0.5, HAT, 0.5 if q % 2 else 0.6) for q in range(8)]
            else:
                hits += [(q, KICK, 1.0) for q in (0.0, 1.0, 2.0, 3.0)]
                hits += [(1.0, SNARE, 0.95), (3.0, SNARE, 1.0), (1.0, CLAP, 0.5), (3.0, CLAP, 0.55)]
                hits += [(q * 0.5, HAT if q % 2 == 0 else OPEN_HAT, 0.55) for q in range(8)]
            # fill into a bigger section
            if sec_last_bar and nxt is not None and nxt.energy > sec.energy + 0.08:
                hits = [x for x in hits if x[0] < 2.0]
                hits += [(2.0 + k * 0.25, TOM_HI if k < 4 else (TOM_LO if k < 6 else SNARE),
                          0.55 + 0.05 * k) for k in range(8)]
        for off, drum, vel in hits:
            b = b0 + off
            w = ctx.word_curve(b)
            v = vel * (0.55 + 0.45 * e) * (1 + 0.35 * t.word_depth * (w - 0.5))
            notes.append(Note(b, 0.25, drum, float(np.clip(v, 0.05, 1)), e, drum=True))
        # the track word adds ghost notes where it rises high
        if not last and e > 0.6:
            for k in range(8):
                b = b0 + k * 0.5 + 0.25
                if ctx.word_curve(b) > 0.78 and t.word_depth > 0.2:
                    notes.append(Note(b, 0.25, HAT, 0.3 * e, e, drum=True))
    if not ctx.is_kit:
        # pitched rhythm: turn the drum hits into tuned hits
        tuned = []
        for n in notes:
            if n.midi in (CRASH, OPEN_HAT):
                continue
            idx = int(round(ctx.pitch_offset(n.start)))
            base = {KICK: 3, SNARE: 4, CLAP: 4, TOM_LO: 3, TOM_HI: 4}.get(n.midi, 5)
            tuned.append(Note(n.start, n.dur, h.melody_note(idx, base + t.octave), n.vel, n.bright))
        notes = tuned
    return notes


GENERATORS = {
    "melody": gen_melody,
    "harmony": gen_harmony,
    "pad": gen_pad,
    "bass": gen_bass,
    "arp": gen_arp,
    "accent": gen_accent,
    "drums": gen_drums,
}


def track_active(tl: Timeline, track: Track, beat: float) -> bool:
    if track.active_letters and tl.letter_at(beat).index not in track.active_letters:
        return False
    sec = tl.section_at(beat)
    if track.active_sections:
        return sec.index in track.active_sections
    return _role_allowed(track.role, float(tl.energy(beat)[0]), sec.kind)


def active_ranges(tl: Timeline, track: Track, resolution: float = 0.25):
    """List of (start_beat, end_beat) where ``track`` may play."""
    ranges = []
    b, cur = 0.0, None
    while b < tl.total_beats - 1e-9:
        on = track_active(tl, track, b)
        if on and cur is None:
            cur = b
        elif not on and cur is not None:
            ranges.append((cur, b))
            cur = None
        b += resolution
    if cur is not None:
        ranges.append((cur, tl.total_beats))
    return ranges


def generate_track(tl: Timeline, track: Track, project: Project, is_kit: bool = False) -> list[Note]:
    ctx = TrackContext(tl, track, project, is_kit)
    gen = GENERATORS.get(track.role, gen_melody)
    raw = gen(ctx)
    ranges = active_ranges(tl, track)
    out = []
    for n in raw:
        for s, e in ranges:
            if s - 1e-6 <= n.start < e:
                if not n.drum:
                    n.dur = min(n.dur, e - n.start + 0.15)
                out.append(n)
                break
    return out


def generate(project: Project, is_kit=lambda name: False) -> Song:
    tl = Timeline(project)
    song = Song(project, tl)
    for track in project.tracks:
        song.notes[track.id] = generate_track(tl, track, project, is_kit(track.instrument))
    return song
