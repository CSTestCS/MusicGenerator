"""Small music-theory helpers: keys, scales and chords."""

from __future__ import annotations

KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# name: (melody steps, harmony steps).  Harmony always uses a 7-note scale so
# chords can be stacked in thirds; pentatonic/blues melodies borrow chords
# from their parent scale.
_MAJOR = [0, 2, 4, 5, 7, 9, 11]
_MINOR = [0, 2, 3, 5, 7, 8, 10]
SCALES = {
    "Major": (_MAJOR, _MAJOR),
    "Minor": (_MINOR, _MINOR),
    "Dorian": ([0, 2, 3, 5, 7, 9, 10], [0, 2, 3, 5, 7, 9, 10]),
    "Mixolydian": ([0, 2, 4, 5, 7, 9, 10], [0, 2, 4, 5, 7, 9, 10]),
    "Harmonic Minor": ([0, 2, 3, 5, 7, 8, 11], [0, 2, 3, 5, 7, 8, 11]),
    "Major Pentatonic": ([0, 2, 4, 7, 9], _MAJOR),
    "Minor Pentatonic": ([0, 3, 5, 7, 10], _MINOR),
    "Blues": ([0, 3, 5, 6, 7, 10], _MINOR),
}

NOTE_NAMES = KEYS


def key_root(key: str) -> int:
    """Pitch class of the key (0 = C)."""
    return KEYS.index(key) if key in KEYS else 0


def midi_to_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def name_to_midi(name: str) -> int:
    """Parse names like "C4", "F#3", or a plain number."""
    name = name.strip().upper().replace("♯", "#")
    if name.lstrip("-").isdigit():
        return int(name)
    for i in (2, 1):
        pc = name[:i]
        if pc in KEYS:
            try:
                octave = int(name[i:])
            except ValueError:
                continue
            return KEYS.index(pc) + (octave + 1) * 12
    raise ValueError(f"Not a note name: {name!r}")


class Harmony:
    """Turns scale degrees into MIDI notes for one key and scale."""

    def __init__(self, key: str = "C", scale: str = "Major"):
        self.root = key_root(key)
        self.melody_steps, self.harmony_steps = SCALES.get(scale, SCALES["Major"])

    # -- melody ---------------------------------------------------------
    def melody_note(self, index: int, base_octave: int = 5) -> int:
        """Scale step ``index`` (0 = tonic of base_octave) to MIDI."""
        n = len(self.melody_steps)
        octave, step = divmod(index, n)
        return 12 * (base_octave + octave) + self.root + self.melody_steps[step]

    def nearest_melody_index(self, midi: int, base_octave: int = 5) -> int:
        best, best_d = 0, 999
        n = len(self.melody_steps)
        approx = int(round((midi - 12 * base_octave - self.root) / 12.0 * n))
        for i in range(approx - n, approx + n + 1):
            d = abs(self.melody_note(i, base_octave) - midi)
            if d < best_d:
                best, best_d = i, d
        return best

    # -- chords ---------------------------------------------------------
    def chord_pcs(self, degree: int, seventh: bool = False) -> list[int]:
        """Pitch classes (relative semitones, may exceed 12) of a chord."""
        steps = self.harmony_steps
        out = []
        for k in (0, 2, 4, 6) if seventh else (0, 2, 4):
            idx = degree + k
            octave, s = divmod(idx, 7)
            out.append(self.root + steps[s] + 12 * octave)
        return out

    def chord_notes(self, degree: int, octave: int = 4, seventh: bool = False,
                    inversion: int = 0) -> list[int]:
        notes = [12 * octave + pc for pc in self.chord_pcs(degree, seventh)]
        for _ in range(inversion % len(notes)):
            notes = notes[1:] + [notes[0] + 12]
        return notes

    def chord_root(self, degree: int, octave: int = 2) -> int:
        return 12 * octave + self.chord_pcs(degree)[0]

    def chord_fifth(self, degree: int, octave: int = 2) -> int:
        return 12 * octave + self.chord_pcs(degree)[2]

    def is_chord_tone(self, midi: int, degree: int, seventh: bool = False) -> bool:
        pcs = {p % 12 for p in self.chord_pcs(degree, seventh)}
        return midi % 12 in pcs
