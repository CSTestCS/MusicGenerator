# Word Song Studio

A Windows desktop app (`WordSongStudio.exe`) that turns words into songs.

Type a **parent word** such as `Simple`. Each letter gets a height and an energy.
The word's rises and falls are stretched across the whole song, so the song's
register, loudness, brightness and busyness follow the word from start to end.
For `Simple`, that's high on **S**, a dip on **I**, a lift on **M/P**, then a
fall into **E**.

<img src="assets/icon.png" width="96" alt="Word Song Studio icon">

## Features

- **Parent word shaping.** Pick how letters are read: *Alphabet height*
  (a = low, z = high), *Phonetic* (open vowels are loud, hard consonants are
  quiet), or *Blend* (both).
- **Song formulas.** Use them alone or together with the word:
  1. **Pop:** Intro → Verse → Pre-Chorus → Chorus → Verse → Pre-Chorus → Chorus → Bridge → Final Chorus → Outro
  2. **Hook-First:** Chorus → Verse → Chorus → Verse → Chorus → Bridge → Final Chorus → Outro
  3. **Rock Anthem:** Intro → Verse → Chorus → Verse → Chorus → Instrumental Solo → Bridge → Double Final Chorus → Outro
  4. **Emotional Ballad:** Intro → Verse → Chorus → Verse → Chorus → Bridge → Soft Chorus → Powerful Final Chorus → Outro
  5. **Classic AABA:** Main Theme → Theme Variation → Contrasting Section → Main Theme Return → Instrumental Solo → Final Theme → Outro

  Every section has its own energy and chord loop. Sections of the same kind
  reuse the same motif, so the hook comes back each time. Every song ends on
  the home chord.
- **Shape modes.** *Word only* makes each letter a part of the song.
  *Formula only* uses just the formula. *Word + Formula* uses the formula for
  structure and lets the word bend it.
- **Tracks.** Each track has its own **word**, an **instrument or sound
  effect**, and a **role** (melody, chords, pad, bass, arpeggio, drums or
  accent hits). The track word repeats at a set rate (*repeat every N bars*)
  while riding the parent word's slow curve. A track can be limited to certain
  **letters of the parent word** (for example only during "M" and "P") and/or
  to certain sections.
- **Built-in sounds.** 15 synthesized instruments, 2 drum kits and 5 sound
  effects. No sample library is needed.
- **Custom instruments and sound effects.** Import WAV files (MP3/OGG/FLAC
  work too if ffmpeg is installed). The recorded pitch is detected
  automatically, and the sample is pitched to whatever note the music needs.
  Instruments follow note lengths (with optional looping). Sound effects play
  through in full. Custom sounds are stored inside the project file.
- **Save and export.** Projects save as `.wsong` files. Export the song as WAV
  (or MP3/OGG/FLAC with ffmpeg), as one WAV stem per track, or as MIDI.
- The **Variation** number gives a different take on the same words.

## Getting the .exe

Every push runs the **Build Windows .exe** GitHub Action. It runs the tests,
builds the app with PyInstaller, smoke-tests the built `.exe`, and uploads
`WordSongStudio.exe` as a build artifact. To download it, open the repository's
**Actions** tab, pick the latest run and download **WordSongStudio-windows**.
Pushing a tag like `v1.0.0` also attaches the `.exe` to a GitHub Release.

### Build it yourself on Windows

1. Install Python 3.10 or newer from python.org.
2. Double-click `build_exe.bat`, or run:
   ```bat
   pip install -r requirements-dev.txt
   pyinstaller --noconfirm --clean WordSongStudio.spec
   ```
3. The app is at `dist\WordSongStudio.exe`.

### Run from source (any OS)

```bash
pip install -r requirements.txt
python main.py
```

## Using it

1. Type a parent word and choose a shape mode, formula, key, scale and tempo.
2. Press **Play** (or Space). Click anywhere on the timeline to play from that
   point.
3. **+ Add Track** opens the track editor: choose a word, a sound, a role and a
   repeat rate, then pick which letters and sections it plays in. The preview
   shows the word's rises and falls.
4. **Sounds → Import Custom Instrument / Sound FX...** adds your own sounds.
5. **File → Save Project** and **File → Export Song**.

## Project layout

| Path | What it does |
| --- | --- |
| `musicgen/contour.py` | Turns a word into a smooth rise-and-fall curve |
| `musicgen/formulas.py` | The 5 song formulas (sections, energy, chords) |
| `musicgen/generator.py` | Builds the timeline and generates notes per track role |
| `musicgen/instruments.py` | Synthesized instruments, drums, SFX and custom-sample pitching |
| `musicgen/renderer.py` | Mixes tracks with panning, reverb and a limiter |
| `musicgen/project.py` | Project model and `.wsong` save/load |
| `musicgen/audio_io.py`, `musicgen/midi.py` | WAV/MP3 I/O, playback, MIDI export |
| `musicgen/gui/` | The tkinter desktop interface |
| `tests/` | `python -m pytest` |
