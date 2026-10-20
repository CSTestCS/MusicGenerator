"""Reading/writing audio files and playing audio.

* WAV reading supports 8/16/24/32-bit PCM and 32/64-bit float files.
* MP3 / OGG / FLAC import and export work when ``ffmpeg`` is installed
  (or ``ffmpeg.exe`` sits next to the app).
* Playback uses ``winsound`` on Windows (built in, no extra packages).
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

import numpy as np


# ----------------------------------------------------------------------
# WAV
# ----------------------------------------------------------------------
def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Decode WAV bytes into (mono float array in -1..1, sample rate)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Not a WAV file")
    pos = 12
    fmt = None
    raw = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:  # WAVE_FORMAT_EXTENSIBLE
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError("WAV file is missing format or data")
    tag, ch, rate, bits = fmt
    width = bits // 8
    usable = len(raw) - len(raw) % (width * ch)
    raw = raw[:usable]
    if tag == 3:  # IEEE float
        arr = np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif tag == 1:
        if bits == 8:
            arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128.0
        elif bits == 16:
            arr = np.frombuffer(raw, dtype="<i2") / 32768.0
        elif bits == 24:
            b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            v = np.where(v >= 1 << 23, v - (1 << 24), v)
            arr = v / float(1 << 23)
        elif bits == 32:
            arr = np.frombuffer(raw, dtype="<i4") / float(1 << 31)
        else:
            raise ValueError(f"Unsupported bit depth: {bits}")
    else:
        raise ValueError(f"Unsupported WAV encoding (format {tag})")
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    return np.asarray(arr, dtype=np.float64), int(rate)


def encode_wav(stereo: np.ndarray, sr: int) -> bytes:
    """Float stereo (N, 2) or mono (N,) -> 16-bit WAV bytes."""
    a = np.asarray(stereo, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def write_wav(path: str, stereo: np.ndarray, sr: int) -> None:
    with open(path, "wb") as fh:
        fh.write(encode_wav(stereo, sr))


# ----------------------------------------------------------------------
# ffmpeg helpers (optional)
# ----------------------------------------------------------------------
def find_ffmpeg() -> str | None:
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
    for cand in (os.path.join(here, "ffmpeg.exe"), os.path.join(here, "ffmpeg")):
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffmpeg")


def _no_window():
    if os.name == "nt":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def load_audio_file(path: str) -> bytes:
    """Return WAV bytes for any supported audio file."""
    if path.lower().endswith(".wav"):
        with open(path, "rb") as fh:
            data = fh.read()
        decode_wav(data)  # validate
        return data
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("Only .wav files can be imported unless ffmpeg is installed.")
    res = subprocess.run([ff, "-v", "error", "-i", path, "-f", "wav", "-acodec", "pcm_s16le", "-"],
                         capture_output=True, **_no_window())
    if res.returncode != 0 or not res.stdout:
        raise RuntimeError(res.stderr.decode(errors="ignore") or "ffmpeg could not read the file")
    return res.stdout


def export_with_ffmpeg(path: str, stereo: np.ndarray, sr: int) -> None:
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg was not found. Install ffmpeg (or put ffmpeg.exe next to "
                           "the app) to export MP3/OGG/FLAC, or export WAV instead.")
    extra = ["-b:a", "256k"] if path.lower().endswith(".mp3") else []
    res = subprocess.run([ff, "-y", "-v", "error", "-f", "wav", "-i", "-", *extra, path],
                         input=encode_wav(stereo, sr), capture_output=True, **_no_window())
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode(errors="ignore") or "ffmpeg export failed")


# ----------------------------------------------------------------------
# playback
# ----------------------------------------------------------------------
class Player:
    """Plays a stereo buffer from a given position. One sound at a time."""

    def __init__(self):
        self._proc = None
        self._tmp = os.path.join(tempfile.gettempdir(), f"wordsong_preview_{os.getpid()}.wav")

    def play(self, stereo: np.ndarray, sr: int, start_sec: float = 0.0) -> None:
        self.stop()
        start = int(max(0.0, start_sec) * sr)
        write_wav(self._tmp, stereo[start:], sr)
        if os.name == "nt":
            import winsound
            winsound.PlaySound(self._tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        for cmd in (["afplay"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
            if shutil.which(cmd[0]):
                self._proc = subprocess.Popen(cmd + [self._tmp], stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
                return
        raise RuntimeError("No audio player found on this system.")

    def stop(self) -> None:
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def cleanup(self) -> None:
        self.stop()
        try:
            os.remove(self._tmp)
        except OSError:
            pass
