"""Word analysis: turn a word into a curve of rises and falls.

Every letter gets two numbers between 0 and 1:

* height  - where the letter sits in the alphabet (a = low, z = high)
* energy  - how open / loud the letter sounds (vowels are loud, hard
            consonants like "t" or "k" are quiet)

The "contour" of a word is a blend of those values, chosen with a style:

* "alphabet" - only the alphabet height
* "phonetic" - only the sound energy
* "blend"    - a mix of the two (default)

The letter values are joined into a smooth curve so they can be stretched
over any length of time (the whole song for the parent word, or a short
repeating cycle for a track word).
"""

from __future__ import annotations

import numpy as np

CONTOUR_STYLES = ("blend", "alphabet", "phonetic")

_VOWEL_ENERGY = {"a": 1.0, "o": 0.95, "e": 0.88, "i": 0.8, "u": 0.75, "y": 0.7}
_SONORANTS = set("lmnrw")
_VOICED = set("bdgvzj")


def clean_word(word: str) -> str:
    """Keep only letters and digits, lower-cased."""
    return "".join(ch for ch in (word or "").lower() if ch.isalnum() and ch.isascii())


def letter_height(ch: str) -> float:
    if ch.isdigit():
        return int(ch) / 9.0
    return (ord(ch) - ord("a")) / 25.0


def letter_energy(ch: str) -> float:
    if ch.isdigit():
        return 0.5
    if ch in _VOWEL_ENERGY:
        return _VOWEL_ENERGY[ch]
    if ch in _SONORANTS:
        return 0.62
    if ch in _VOICED:
        return 0.5
    return 0.35


def letter_values(word: str, style: str = "blend") -> np.ndarray:
    """Contour value (0..1) for each letter of ``word``."""
    w = clean_word(word)
    if not w:
        return np.array([0.5])
    h = np.array([letter_height(c) for c in w])
    e = np.array([letter_energy(c) for c in w])
    if style == "alphabet":
        v = h
    elif style == "phonetic":
        v = e
    else:
        v = 0.65 * h + 0.35 * e
    return np.clip(v, 0.0, 1.0)


def energy_values(word: str) -> np.ndarray:
    """Loudness / intensity value (0..1) for each letter."""
    w = clean_word(word)
    if not w:
        return np.array([0.5])
    h = np.array([letter_height(c) for c in w])
    e = np.array([letter_energy(c) for c in w])
    return np.clip(0.55 * e + 0.45 * h, 0.0, 1.0)


def _smooth(t: np.ndarray) -> np.ndarray:
    # smoothstep-like easing so the curve glides between letters
    return t * t * (3.0 - 2.0 * t)


def sample_curve(values: np.ndarray, x, cyclic: bool = False) -> np.ndarray:
    """Sample a smooth curve through ``values``.

    ``x`` runs from 0 to 1 across the word. Each letter owns an equal slice
    and its value sits in the middle of its slice.  With ``cyclic=True`` the
    end of the word glides back into the start (used for repeating words).
    """
    x = np.asarray(x, dtype=float)
    vals = np.asarray(values, dtype=float)
    n = len(vals)
    if n == 1:
        return np.full_like(x, vals[0])
    pos = x * n - 0.5  # position in "letter units"
    if cyclic:
        pos = np.mod(pos, n)
        i0 = np.floor(pos).astype(int) % n
        i1 = (i0 + 1) % n
        frac = pos - np.floor(pos)
    else:
        pos = np.clip(pos, 0.0, n - 1.0)
        i0 = np.minimum(np.floor(pos).astype(int), n - 2)
        i1 = i0 + 1
        frac = pos - i0
    f = _smooth(frac)
    return vals[i0] * (1.0 - f) + vals[i1] * f


class WordShape:
    """Convenience wrapper holding a word's contour and energy."""

    def __init__(self, word: str, style: str = "blend"):
        self.word = clean_word(word)
        self.style = style
        self.values = letter_values(self.word, style)
        self.energy = energy_values(self.word)

    @property
    def letters(self) -> str:
        return self.word

    def __len__(self) -> int:
        return max(1, len(self.word))

    def contour_at(self, x, cyclic: bool = False):
        return sample_curve(self.values, x, cyclic)

    def energy_at(self, x, cyclic: bool = False):
        return sample_curve(self.energy, x, cyclic)

    def letter_index_at(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        return np.clip((x * len(self)).astype(int), 0, len(self) - 1)
