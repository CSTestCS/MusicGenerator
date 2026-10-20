import io
import os
import struct
import sys
import wave

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musicgen.audio_io import decode_wav, encode_wav  # noqa: E402
from musicgen.contour import WordShape, letter_values, sample_curve  # noqa: E402
from musicgen.formulas import FORMULA_NAMES, build_sections  # noqa: E402
from musicgen.generator import Timeline, generate  # noqa: E402
from musicgen.instruments import SoundBank, estimate_root_midi  # noqa: E402
from musicgen.midi import song_to_midi  # noqa: E402
from musicgen.project import CustomSound, Project, Track  # noqa: E402
from musicgen.renderer import mix_peak, render  # noqa: E402


def short_project(**kw):
    p = Project.default()
    p.tempo = 200
    p.word_bars = 12
    p.section_scale = 0.5
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def sine_wav(freq=440.0, seconds=0.5, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    return encode_wav(0.6 * np.sin(2 * np.pi * freq * t), sr)


# -- word analysis -----------------------------------------------------
def test_simple_rises_and_falls():
    v = letter_values("Simple", "alphabet")
    # s i m p l e : 18 8 12 15 11 4
    assert list(np.argsort(v))[::-1][0] == 0  # 's' is the highest letter
    assert v[1] < v[2] < v[3] and v[4] < v[3] and v[5] < v[4]


def test_curve_hits_letter_values_and_wraps():
    vals = np.array([0.0, 1.0, 0.5])
    assert sample_curve(vals, 1 / 6) == pytest.approx(0.0)
    assert sample_curve(vals, 0.5) == pytest.approx(1.0)
    # cyclic curve glides from the last letter back to the first
    assert sample_curve(vals, 1.0, cyclic=True) == pytest.approx(0.25)
    assert WordShape("!!").letters == ""


# -- formulas ----------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("Pop", ["intro", "verse", "prechorus", "chorus", "verse", "prechorus", "chorus", "bridge", "chorus", "outro"]),
    ("Hook-First", ["chorus", "verse", "chorus", "verse", "chorus", "bridge", "chorus", "outro"]),
    ("Rock Anthem", ["intro", "verse", "chorus", "verse", "chorus", "solo", "bridge", "chorus", "outro"]),
    ("Emotional Ballad", ["intro", "verse", "chorus", "verse", "chorus", "bridge", "chorus", "chorus", "outro"]),
    ("Classic AABA", ["theme", "variation", "contrast", "theme", "solo", "theme", "outro"]),
])
def test_formula_structures(name, expected):
    assert [s.kind for s in build_sections(name)] == expected


def test_ballad_builds_and_rock_climaxes():
    ballad = build_sections("Emotional Ballad")
    assert ballad[6].energy < ballad[7].energy == 1.0  # soft chorus -> powerful final chorus
    rock = build_sections("Rock Anthem")
    assert rock[7].bars == 16 and rock[7].energy == max(s.energy for s in rock)


# -- generation --------------------------------------------------------
@pytest.mark.parametrize("mode", ["word", "formula", "both"])
@pytest.mark.parametrize("formula", FORMULA_NAMES)
def test_every_mode_and_formula_generates(mode, formula):
    p = short_project(shape_mode=mode, formula=formula)
    song = generate(p)
    assert song.timeline.total_beats > 0
    for t in p.tracks:
        for n in song.notes[t.id]:
            assert 0 <= n.start < song.timeline.total_beats
            assert 0 < n.vel <= 1 and 0 <= n.midi <= 127
    assert sum(len(v) for v in song.notes.values()) > 50


def test_word_mode_uses_letters_as_parts_and_length():
    p = short_project(shape_mode="word", parent_word="Simple", word_bars=24)
    tl = Timeline(p)
    assert [l.char for l in tl.letters] == list("simple")
    assert tl.bars == 24
    # parent contour: 's' high, 'e' low
    assert tl.parent_curve(tl.letters[0].start + 1)[0] > tl.parent_curve(tl.letters[-1].start + 1)[0]


def test_lead_register_follows_parent_word():
    p = Project.default()
    p.shape_mode = "word"
    song = generate(p)
    tl = song.timeline
    lead = song.notes[p.tracks[0].id]
    first = np.mean([n.midi for n in lead if tl.letters[0].start <= n.start < tl.letters[0].end])
    last = np.mean([n.midi for n in lead if tl.letters[-1].start <= n.start < tl.letters[-1].end - 4])
    assert first > last + 3


def test_track_letter_gating():
    p = short_project(shape_mode="both", parent_word="Simple")
    t = Track(name="Only M", word="zap", role="melody", instrument="Bell", active_letters=[2])
    p.tracks = [t]
    song = generate(p)
    tl = song.timeline
    m = tl.letters[2]
    assert song.notes[t.id]
    assert all(m.start <= n.start < m.end for n in song.notes[t.id])


def test_track_word_repeats_at_its_rate():
    p = short_project(shape_mode="word", word_bars=16)
    t = Track(name="Arp", word="Wave", role="arp", instrument="Pluck", cycle_bars=1,
              note_beats=0.25, parent_depth=0.0, word_depth=1.0, active_sections=[1, 2, 3])
    p.tracks = [t]
    song = generate(p)
    notes = song.notes[t.id]
    by_bar = {}
    for n in notes:
        bar = int(n.start // 4)
        idx = round((n.start % 4) / 0.25)
        by_bar.setdefault(bar, {})[idx] = n.midi
    # same chord in two bars -> identical up/down shape
    tl = song.timeline
    bars = sorted(by_bar)
    shapes = {}
    for b in bars:
        key = tl.chord_at(b * 4)
        seq = tuple(by_bar[b].get(i) for i in range(16))
        shapes.setdefault(key, set()).add(seq)
    assert any(len(s) == 1 for s in shapes.values())


def test_song_ends_on_home_chord():
    for f in FORMULA_NAMES:
        tl = Timeline(short_project(formula=f))
        assert tl.chord_at(tl.total_beats - 1) == 0


def test_variation_changes_song():
    a = generate(short_project(variation=1))
    b = generate(short_project(variation=2))
    lead_a = [n.midi for n in a.notes[a.project.tracks[0].id]]
    lead_b = [n.midi for n in b.notes[b.project.tracks[0].id]]
    assert lead_a != lead_b


# -- audio -------------------------------------------------------------
def test_render_short_song():
    p = short_project(shape_mode="word", word_bars=8)
    bank = SoundBank(p.custom_sounds)
    song = generate(p, bank.is_kit)
    audio = render(song, bank)
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert np.isfinite(audio).all() and 0.1 < np.abs(audio).max() <= 1.0
    stem = render(song, bank, only_track=p.tracks[0].id, peak=mix_peak(song, bank))
    assert np.abs(stem).max() < np.abs(audio).max() + 1e-6


def test_custom_sound_is_pitched():
    snd = CustomSound.from_wav_bytes("Sine", sine_wav(440.0), root_midi=69, loop=True)
    bank = SoundBank([snd])
    v = bank.voice("Sine", 81, 1.0, 0.5)  # one octave up
    assert estimate_root_midi(v, bank.sr) == 81
    sfx = CustomSound.from_wav_bytes("Hit", sine_wav(440.0, 0.3), kind="sfx", root_midi=69)
    bank = SoundBank([sfx])
    assert len(bank.voice("Hit", 57, 0.1, 0.5)) > len(bank.voice("Hit", 69, 0.1, 0.5))


def test_custom_sound_in_song_and_project_roundtrip(tmp_path):
    p = short_project(shape_mode="word", word_bars=8)
    p.custom_sounds.append(CustomSound.from_wav_bytes("Sine", sine_wav(), root_midi=69, loop=True))
    p.tracks.append(Track(name="Custom", word="hey", instrument="Sine", role="melody"))
    path = tmp_path / "x.wsong"
    p.save(str(path))
    q = Project.load(str(path))
    assert q.to_dict() == p.to_dict()
    bank = SoundBank(q.custom_sounds)
    audio = render(generate(q, bank.is_kit), bank)
    assert np.isfinite(audio).all()


def test_decode_wav_formats():
    sr = 8000
    x = np.sin(np.linspace(0, 20, 400)) * 0.5
    # 24-bit PCM stereo
    pcm = (x * (1 << 23)).astype(np.int32)
    raw = b"".join(struct.pack("<i", int(v))[:3] * 2 for v in pcm)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(sr)
        w.writeframes(raw)
    y, rate = decode_wav(buf.getvalue())
    assert rate == sr and np.allclose(y, x, atol=1e-5)
    # 32-bit float mono
    body = x.astype("<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, sr, sr * 4, 4, 32)
    data = (b"RIFF" + struct.pack("<I", 4 + 8 + 16 + 8 + len(body)) + b"WAVE" + b"fmt " +
            struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(body)) + body)
    y, rate = decode_wav(data)
    assert np.allclose(y, x, atol=1e-6)


def test_midi_export():
    song = generate(short_project())
    data = song_to_midi(song)
    assert data[:4] == b"MThd"
    fmt, ntracks, ppq = struct.unpack(">HHH", data[8:14])
    assert fmt == 1 and ntracks == 1 + len(song.project.tracks) and ppq == 480
    assert data.count(b"MTrk") == ntracks
