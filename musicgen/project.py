"""Project data: the parent word, song settings, tracks and custom sounds.

Projects are saved as JSON (``.wsong``).  Custom sounds are embedded in the
file (base64 WAV data) so a project can be moved to another computer.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import asdict, dataclass, field, fields

PROJECT_EXT = ".wsong"
FILE_VERSION = 1

ROLES = {
    "melody": "Melody (lead line)",
    "harmony": "Chords (rhythmic)",
    "pad": "Pad (held chords)",
    "bass": "Bass line",
    "arp": "Arpeggio",
    "drums": "Drums / rhythm",
    "accent": "Accent hits (one per word peak)",
}


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Track:
    name: str = "Track"
    word: str = ""              # blank = follows the parent word only
    instrument: str = "Piano"
    role: str = "melody"
    cycle_bars: float = 2.0     # the track word repeats once every N bars
    note_beats: float = 0.5     # base note length (beats); 0.5 = eighth notes
    octave: int = 0             # octave shift (-2..+2)
    volume: float = 0.8
    pan: float = 0.0            # -1 left .. +1 right
    reverb: float = 0.25
    word_depth: float = 0.6     # how strongly the track word bends the part
    parent_depth: float = 1.0   # how strongly the parent word bends the part
    active_letters: list[int] = field(default_factory=list)   # empty = all letters
    active_sections: list[int] = field(default_factory=list)  # empty = all sections
    mute: bool = False
    solo: bool = False
    id: str = field(default_factory=_new_id)

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class CustomSound:
    name: str
    kind: str = "instrument"    # "instrument" (sustained, pitched) or "sfx" (one-shot)
    root_midi: int = 60         # the pitch the recording was made at
    loop: bool = False          # loop the sample to fill long notes
    gain: float = 1.0
    data_b64: str = ""          # WAV file bytes
    source_name: str = ""

    @property
    def wav_bytes(self) -> bytes:
        return base64.b64decode(self.data_b64) if self.data_b64 else b""

    @classmethod
    def from_wav_bytes(cls, name: str, data: bytes, **kw) -> "CustomSound":
        return cls(name=name, data_b64=base64.b64encode(data).decode("ascii"), **kw)

    @classmethod
    def from_dict(cls, d: dict) -> "CustomSound":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Project:
    parent_word: str = "Simple"
    shape_mode: str = "both"        # "word", "formula", "both"
    formula: str = "Pop"
    contour_style: str = "blend"
    key: str = "C"
    scale: str = "Major"
    tempo: int = 112
    word_bars: int = 48             # song length when no formula is used
    section_scale: float = 1.0      # stretch formula sections (0.5 .. 2)
    variation: int = 1              # seed: change to get a different take
    master_volume: float = 0.9
    master_reverb: float = 0.35
    tracks: list[Track] = field(default_factory=list)
    custom_sounds: list[CustomSound] = field(default_factory=list)

    # ------------------------------------------------------------------
    @classmethod
    def default(cls) -> "Project":
        p = cls()
        p.tracks = [
            Track(name="Lead", instrument="Synth Lead", role="melody", word="",
                  note_beats=0.5, volume=0.75, reverb=0.3),
            Track(name="Chords", instrument="Electric Piano", role="harmony",
                  note_beats=1.0, volume=0.55, pan=-0.25, reverb=0.3),
            Track(name="Pad", instrument="Warm Pad", role="pad", volume=0.4,
                  pan=0.2, reverb=0.5),
            Track(name="Bass", instrument="Synth Bass", role="bass", volume=0.75,
                  note_beats=0.5, reverb=0.05),
            Track(name="Drums", instrument="Drum Kit", role="drums", volume=0.8,
                  reverb=0.12),
            # example of a track with its own word, only playing during some letters
            Track(name="Sparkle", word="Bright", instrument="Pluck", role="arp",
                  cycle_bars=1.0, note_beats=0.25, octave=1, volume=0.4, pan=0.35,
                  reverb=0.45, active_letters=[2, 3, 4]),
        ]
        return p

    def track_by_id(self, tid: str):
        return next((t for t in self.tracks if t.id == tid), None)

    def sound_by_name(self, name: str):
        return next((s for s in self.custom_sounds if s.name == name), None)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["file_version"] = FILE_VERSION
        d["app"] = "WordSongStudio"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        names = {f.name for f in fields(cls)} - {"tracks", "custom_sounds"}
        p = cls(**{k: v for k, v in d.items() if k in names})
        p.tracks = [Track.from_dict(t) for t in d.get("tracks", [])]
        p.custom_sounds = [CustomSound.from_dict(s) for s in d.get("custom_sounds", [])]
        return p

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))
