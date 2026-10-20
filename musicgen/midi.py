"""Standard MIDI File (type 1) export, written by hand (no dependencies)."""

from __future__ import annotations

import struct

from .instruments import INSTRUMENT_INFO, KITS

PPQ = 480


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack(">I", len(body)) + body


def _track(events: list[tuple[int, bytes]], name: str) -> bytes:
    events = sorted(events, key=lambda e: (e[0], e[1][0] & 0xF0 != 0x80))
    body = b"\x00\xff\x03" + _vlq(len(name.encode("latin-1", "replace"))) + name.encode("latin-1", "replace")
    last = 0
    for tick, data in events:
        body += _vlq(max(0, tick - last)) + data
        last = tick
    body += b"\x00\xff\x2f\x00"
    return _chunk(b"MTrk", body)


def song_to_midi(song) -> bytes:
    p = song.project
    tempo_us = int(60_000_000 / song.timeline.tempo)
    conductor = [(0, b"\xff\x51\x03" + tempo_us.to_bytes(3, "big")),
                 (0, b"\xff\x58\x04\x04\x02\x18\x08")]
    for s in song.timeline.sections:
        txt = s.name.encode("latin-1", "replace")
        conductor.append((int(s.start * PPQ), b"\xff\x06" + _vlq(len(txt)) + txt))
    chunks = [_track(conductor, p.parent_word or "Song")]
    any_solo = any(t.solo for t in p.tracks)
    chan = 0
    for t in p.tracks:
        if t.mute or (any_solo and not t.solo):
            continue
        notes = song.notes.get(t.id, [])
        if t.instrument in KITS:
            ch = 9
        else:
            ch = chan
            chan += 1
            if chan == 9:
                chan = 10
            if chan > 15:
                chan = 0
        prog = INSTRUMENT_INFO.get(t.instrument, ("", 0))[1]
        ev = []
        if ch != 9 and prog >= 0:
            ev.append((0, bytes([0xC0 | ch, prog & 0x7F])))
        ev.append((0, bytes([0xB0 | ch, 7, int(max(0, min(1, t.volume)) * 127)])))
        ev.append((0, bytes([0xB0 | ch, 10, int((t.pan + 1) / 2 * 127)])))
        for n in notes:
            on = int(n.start * PPQ)
            off = on + max(1, int(n.dur * PPQ))
            key = max(0, min(127, int(n.midi)))
            vel = max(1, min(127, int(n.vel * 127)))
            ev.append((on, bytes([0x90 | ch, key, vel])))
            ev.append((off, bytes([0x80 | ch, key, 0])))
        chunks.append(_track(ev, t.name))
    header = _chunk(b"MThd", struct.pack(">HHH", 1, len(chunks), PPQ))
    return header + b"".join(chunks)


def write_midi(path: str, song) -> None:
    with open(path, "wb") as fh:
        fh.write(song_to_midi(song))
