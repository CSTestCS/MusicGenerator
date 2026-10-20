"""Song formulas: ordered sections with a length, energy and chord loop.

Energy (0..1) controls how loud, busy and bright a section is, and which
parts play (drums, bass and arpeggios need a minimum energy to join in).
Progressions are scale degrees: 0 = I, 1 = ii, 3 = IV, 4 = V, 5 = vi ...
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    name: str
    kind: str          # intro, verse, prechorus, chorus, bridge, solo, outro, theme ...
    bars: int
    energy: float
    progression: list[int] = field(default_factory=lambda: [0, 5, 3, 4])
    # Sections that share a motif key reuse the same melody & rhythm (hooks!)
    motif: str = ""

    def motif_key(self) -> str:
        return self.motif or self.kind


# Common chord loops
VERSE = [0, 5, 3, 4]        # I vi IV V
PRE = [1, 3, 4, 4]          # ii IV V V
CHORUS = [3, 4, 0, 5]       # IV V I vi
BRIDGE = [5, 3, 0, 4]       # vi IV I V
INTRO = [0, 3, 0, 4]        # I IV I V
OUTRO = [3, 4, 0, 0]        # IV V I I  (resolves home)
ROCK_V = [0, 4, 3, 0]       # I V IV I
ROCK_C = [0, 4, 5, 3]       # I V vi IV
SOLO = [5, 3, 0, 4]
BALLAD_V = [0, 4, 5, 3]
BALLAD_C = [3, 0, 4, 5]
A_THEME = [0, 3, 4, 0]
A_VAR = [0, 5, 1, 4]
B_CONTRAST = [3, 2, 1, 4]


def _s(name, kind, bars, energy, prog, motif=""):
    return Section(name, kind, bars, energy, list(prog), motif)


FORMULAS: dict[str, dict] = {
    "Pop": {
        "description": "Create a complete pop song: Intro → Verse → Pre-Chorus → Chorus → "
                       "Verse → Pre-Chorus → Chorus → Bridge → Final Chorus → Outro. "
                       "Catchy hook, memorable melody, satisfying ending.",
        "sections": lambda: [
            _s("Intro", "intro", 4, 0.30, INTRO),
            _s("Verse 1", "verse", 8, 0.48, VERSE),
            _s("Pre-Chorus", "prechorus", 4, 0.64, PRE),
            _s("Chorus", "chorus", 8, 0.88, CHORUS),
            _s("Verse 2", "verse", 8, 0.55, VERSE),
            _s("Pre-Chorus", "prechorus", 4, 0.70, PRE),
            _s("Chorus", "chorus", 8, 0.92, CHORUS),
            _s("Bridge", "bridge", 8, 0.58, BRIDGE),
            _s("Final Chorus", "chorus", 8, 1.00, CHORUS),
            _s("Outro", "outro", 4, 0.32, OUTRO),
        ],
    },
    "Hook-First": {
        "description": "Create a complete song: Chorus → Verse → Chorus → Verse → Chorus → "
                       "Bridge → Final Chorus → Outro. Introduce the main hook immediately "
                       "and build around it.",
        "sections": lambda: [
            _s("Chorus (Hook)", "chorus", 8, 0.80, CHORUS),
            _s("Verse 1", "verse", 8, 0.50, VERSE),
            _s("Chorus", "chorus", 8, 0.86, CHORUS),
            _s("Verse 2", "verse", 8, 0.56, VERSE),
            _s("Chorus", "chorus", 8, 0.90, CHORUS),
            _s("Bridge", "bridge", 8, 0.60, BRIDGE),
            _s("Final Chorus", "chorus", 8, 1.00, CHORUS),
            _s("Outro", "outro", 4, 0.32, OUTRO),
        ],
    },
    "Rock Anthem": {
        "description": "Create a complete rock song: Intro → Verse → Chorus → Verse → Chorus → "
                       "Instrumental Solo → Bridge → Double Final Chorus → Outro. Build "
                       "intensity toward a powerful climax.",
        "sections": lambda: [
            _s("Intro", "intro", 4, 0.55, ROCK_V),
            _s("Verse 1", "verse", 8, 0.58, ROCK_V),
            _s("Chorus", "chorus", 8, 0.82, ROCK_C),
            _s("Verse 2", "verse", 8, 0.64, ROCK_V),
            _s("Chorus", "chorus", 8, 0.88, ROCK_C),
            _s("Instrumental Solo", "solo", 8, 0.90, SOLO),
            _s("Bridge", "bridge", 8, 0.70, BRIDGE),
            _s("Double Final Chorus", "chorus", 16, 1.00, ROCK_C),
            _s("Outro", "outro", 4, 0.60, OUTRO),
        ],
    },
    "Emotional Ballad": {
        "description": "Create a complete ballad: Intro → Verse → Chorus → Verse → Chorus → "
                       "Bridge → Soft Chorus → Powerful Final Chorus → Outro. Gradually "
                       "build emotional intensity.",
        "sections": lambda: [
            _s("Intro", "intro", 4, 0.20, INTRO),
            _s("Verse 1", "verse", 8, 0.32, BALLAD_V),
            _s("Chorus", "chorus", 8, 0.55, BALLAD_C),
            _s("Verse 2", "verse", 8, 0.42, BALLAD_V),
            _s("Chorus", "chorus", 8, 0.66, BALLAD_C),
            _s("Bridge", "bridge", 8, 0.58, BRIDGE),
            _s("Soft Chorus", "chorus", 8, 0.36, BALLAD_C),
            _s("Powerful Final Chorus", "chorus", 8, 1.00, BALLAD_C),
            _s("Outro", "outro", 4, 0.24, OUTRO),
        ],
    },
    "Classic AABA": {
        "description": "Create a complete song: Main Theme → Theme Variation → Contrasting "
                       "Section → Main Theme Return → Instrumental Solo → Final Theme → "
                       "Outro. Use melodic development, contrast, and a resolved ending.",
        "sections": lambda: [
            _s("Main Theme (A)", "theme", 8, 0.50, A_THEME, "A"),
            _s("Theme Variation (A')", "variation", 8, 0.58, A_VAR, "A"),
            _s("Contrasting Section (B)", "contrast", 8, 0.66, B_CONTRAST, "B"),
            _s("Main Theme Return (A)", "theme", 8, 0.70, A_THEME, "A"),
            _s("Instrumental Solo", "solo", 8, 0.84, SOLO),
            _s("Final Theme (A)", "theme", 8, 0.92, A_THEME, "A"),
            _s("Outro", "outro", 4, 0.34, OUTRO),
        ],
    },
}

FORMULA_NAMES = list(FORMULAS)

SHAPE_MODES = {
    "word": "Word only",
    "formula": "Formula only",
    "both": "Word + Formula",
}

# Chord loops chosen per letter when no formula is used.
WORD_PROGRESSIONS = [VERSE, CHORUS, BRIDGE, INTRO, BALLAD_V, ROCK_C, A_VAR, PRE]


def build_sections(formula: str, scale: float = 1.0) -> list[Section]:
    """Sections of ``formula`` with bar lengths multiplied by ``scale``."""
    if formula not in FORMULAS:
        formula = "Pop"
    out = []
    for s in FORMULAS[formula]["sections"]():
        s.bars = max(2, int(round(s.bars * scale / 2.0)) * 2)
        out.append(s)
    return out


def describe(formula: str) -> str:
    return FORMULAS.get(formula, {}).get("description", "")
