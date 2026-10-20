"""Dialog windows: track editor, custom sound editor and sound manager."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from ..audio_io import decode_wav, load_audio_file
from ..contour import WordShape, clean_word, sample_curve
from ..instruments import INSTRUMENT_INFO, estimate_root_midi
from ..project import ROLES, CustomSound, Track
from ..theory import midi_to_name, name_to_midi

NOTE_CHOICES = {"1/16 note": 0.25, "1/8 note": 0.5, "1/4 note": 1.0, "1/2 note": 2.0, "Whole note": 4.0}
ROLE_LABELS = {v: k for k, v in ROLES.items()}


def _center(win: tk.Toplevel, parent: tk.Misc) -> None:
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


class _Modal(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

    def run(self, parent):
        _center(self, parent)
        self.grab_set()
        self.wait_window()
        return self.result

    def cancel(self):
        self.result = None
        self.destroy()


def _scale(parent, var, frm, to, row, label, col=0, fmt="{:.2f}"):
    ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=2)
    s = ttk.Scale(parent, variable=var, from_=frm, to=to, length=170)
    s.grid(row=row, column=col + 1, sticky="we", padx=4)
    val = ttk.Label(parent, width=5)
    val.grid(row=row, column=col + 2, sticky="w")

    def upd(*_):
        try:
            val.configure(text=fmt.format(var.get()))
        except tk.TclError:
            pass
    var.trace_add("write", upd)
    upd()
    return s


# ----------------------------------------------------------------------
class TrackDialog(_Modal):
    """Edit one track: word, instrument, role, timing, letters and sections."""

    def __init__(self, app, track: Track, title="Track"):
        super().__init__(app, title)
        self.app = app
        self.track = track
        tl = app.song.timeline if app.song else None
        self.letters = tl.letters if tl else []
        self.sections = tl.sections if tl else []
        self.parent_word = clean_word(app.project.parent_word)

        body = ttk.Frame(self, padding=10)
        body.grid(sticky="nsew")
        left = ttk.LabelFrame(body, text="Sound", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ttk.LabelFrame(body, text="Track word", padding=8)
        right.grid(row=0, column=1, sticky="nsew")

        # --- sound ---------------------------------------------------------
        self.v_name = tk.StringVar(value=track.name)
        self.v_inst = tk.StringVar(value=track.instrument)
        self.v_role = tk.StringVar(value=ROLES.get(track.role, ROLES["melody"]))
        ttk.Label(left, text="Name").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(left, textvariable=self.v_name, width=24).grid(row=0, column=1, columnspan=2, sticky="we", padx=4)
        ttk.Label(left, text="Instrument / sound").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.cb_inst = ttk.Combobox(left, textvariable=self.v_inst, state="readonly", width=22,
                                    values=app.instrument_choices(), height=24)
        self.cb_inst.grid(row=1, column=1, sticky="we", padx=4)
        ttk.Button(left, text="Import...", width=9, command=self.import_sound).grid(row=1, column=2, padx=2)
        ttk.Label(left, text="Role").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Combobox(left, textvariable=self.v_role, state="readonly", width=28,
                     values=list(ROLES.values())).grid(row=2, column=1, columnspan=2, sticky="we", padx=4)

        self.v_note = tk.StringVar(value=next((k for k, v in NOTE_CHOICES.items()
                                               if abs(v - track.note_beats) < 1e-6), "1/8 note"))
        ttk.Label(left, text="Note length").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        ttk.Combobox(left, textvariable=self.v_note, state="readonly", width=12,
                     values=list(NOTE_CHOICES)).grid(row=3, column=1, sticky="w", padx=4)
        self.v_oct = tk.StringVar(value=str(track.octave))
        ttk.Label(left, text="Octave shift").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        ttk.Spinbox(left, from_=-3, to=3, textvariable=self.v_oct, width=6).grid(row=4, column=1, sticky="w", padx=4)

        mix = ttk.Frame(left)
        mix.grid(row=5, column=0, columnspan=3, sticky="we", pady=(6, 0))
        self.v_vol = tk.DoubleVar(value=track.volume)
        self.v_pan = tk.DoubleVar(value=track.pan)
        self.v_rev = tk.DoubleVar(value=track.reverb)
        _scale(mix, self.v_vol, 0, 1.5, 0, "Volume")
        _scale(mix, self.v_pan, -1, 1, 1, "Pan (L / R)")
        _scale(mix, self.v_rev, 0, 1, 2, "Reverb")

        # --- word ----------------------------------------------------------
        self.v_word = tk.StringVar(value=track.word)
        ttk.Label(right, text="Word").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ent = ttk.Entry(right, textvariable=self.v_word, width=22, font=("Segoe UI", 11, "bold"))
        ent.grid(row=0, column=1, columnspan=2, sticky="we", padx=4)
        ttk.Label(right, text="(leave blank to repeat the parent word)", foreground="#777").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=4)
        self.v_cycle = tk.StringVar(value=f"{track.cycle_bars:g}")
        ttk.Label(right, text="Repeat every (bars)").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Spinbox(right, values=("0.5", "1", "2", "3", "4", "6", "8", "12", "16"),
                    textvariable=self.v_cycle, width=6).grid(row=2, column=1, sticky="w", padx=4)
        self.v_wd = tk.DoubleVar(value=track.word_depth)
        self.v_pd = tk.DoubleVar(value=track.parent_depth)
        _scale(right, self.v_wd, 0, 1, 3, "Word influence")
        _scale(right, self.v_pd, 0, 1, 4, "Parent influence")
        self.preview = tk.Canvas(right, width=300, height=70, bg="#1e1f26", highlightthickness=0)
        self.preview.grid(row=5, column=0, columnspan=3, pady=(6, 0))
        self.v_word.trace_add("write", lambda *_: self.draw_preview())

        # --- when it plays -------------------------------------------------
        when = ttk.LabelFrame(body, text="When this track plays", padding=8)
        when.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        ttk.Label(when, text="During letters of the parent word "
                             f"\"{self.parent_word.upper()}\":").grid(row=0, column=0, sticky="w")
        lf = ttk.Frame(when)
        lf.grid(row=1, column=0, sticky="w", pady=(2, 6))
        self.v_all_letters = tk.BooleanVar(value=not track.active_letters)
        ttk.Checkbutton(lf, text="All", variable=self.v_all_letters,
                        command=self._sync_letters).grid(row=0, column=0, padx=(0, 8))
        self.letter_vars = []
        for i, ch in enumerate(self.parent_word):
            v = tk.BooleanVar(value=(not track.active_letters) or i in track.active_letters)
            cb = ttk.Checkbutton(lf, text=f"{ch.upper()}", variable=v, command=self._letter_clicked)
            cb.grid(row=i // 16, column=1 + i % 16, padx=1)
            self.letter_vars.append(v)
        ttk.Label(when, text="During sections (leave all ticked for automatic):").grid(row=2, column=0, sticky="w")
        sf = ttk.Frame(when)
        sf.grid(row=3, column=0, sticky="w")
        self.section_vars = []
        for i, s in enumerate(self.sections):
            v = tk.BooleanVar(value=(not track.active_sections) or i in track.active_sections)
            ttk.Checkbutton(sf, text=s.name, variable=v).grid(row=i // 5, column=i % 5, sticky="w", padx=2)
            self.section_vars.append(v)
        ttk.Label(when, text="Automatic = drums, bass and arpeggios rest in quiet parts and join "
                             "in as the song builds.", foreground="#777").grid(row=4, column=0, sticky="w", pady=(4, 0))

        btns = ttk.Frame(body)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="OK", width=10, command=self.ok).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Cancel", width=10, command=self.cancel).grid(row=0, column=1)
        self.bind("<Return>", lambda e: self.ok())
        ent.focus_set()
        self.after(50, self.draw_preview)

    def _sync_letters(self):
        on = self.v_all_letters.get()
        for i, v in enumerate(self.letter_vars):
            v.set(on or i == 0)

    def _letter_clicked(self):
        self.v_all_letters.set(all(v.get() for v in self.letter_vars))

    def import_sound(self):
        name = self.app.import_custom_sound(parent=self)
        if name:
            self.cb_inst.configure(values=self.app.instrument_choices())
            self.v_inst.set(name)

    def draw_preview(self):
        c = self.preview
        c.delete("all")
        word = clean_word(self.v_word.get()) or self.parent_word
        if not word:
            return
        shape = WordShape(word, self.app.project.contour_style)
        w, h = 300, 70
        xs = np.linspace(0, 2, 160)
        ys = sample_curve(shape.values, xs % 1.0, cyclic=True)
        lo, hi = float(ys.min()), float(ys.max())
        rng = (hi - lo) or 1
        pts = []
        for x, y in zip(xs, ys):
            pts += [6 + x / 2 * (w - 12), h - 10 - (y - lo) / rng * (h - 26)]
        c.create_line(*pts, fill="#7fd1ff", width=2, smooth=True)
        n = len(word)
        for rep in range(2):
            for i, ch in enumerate(word):
                x = 6 + (rep + (i + 0.5) / n) / 2 * (w - 12)
                c.create_text(x, 8, text=ch.upper(), fill="#aab", font=("Segoe UI", 8))
        c.create_text(w - 4, h - 4, text="2 repeats", anchor="se", fill="#667", font=("Segoe UI", 7))

    def ok(self):
        t = self.track
        try:
            cycle = float(self.v_cycle.get())
            octave = int(self.v_oct.get())
        except ValueError:
            messagebox.showerror("Track", "Repeat rate and octave must be numbers.", parent=self)
            return
        t.name = self.v_name.get().strip() or "Track"
        t.word = self.v_word.get().strip()
        t.instrument = self.v_inst.get()
        t.role = ROLE_LABELS.get(self.v_role.get(), "melody")
        t.note_beats = NOTE_CHOICES.get(self.v_note.get(), 0.5)
        t.octave = max(-3, min(3, octave))
        t.cycle_bars = max(0.25, min(64.0, cycle))
        t.volume, t.pan, t.reverb = self.v_vol.get(), self.v_pan.get(), self.v_rev.get()
        t.word_depth, t.parent_depth = self.v_wd.get(), self.v_pd.get()
        letters = [i for i, v in enumerate(self.letter_vars) if v.get()]
        if not letters:
            messagebox.showerror("Track", "Pick at least one letter for the track to play in.", parent=self)
            return
        t.active_letters = [] if len(letters) == len(self.letter_vars) else letters
        secs = [i for i, v in enumerate(self.section_vars) if v.get()]
        if self.section_vars and not secs:
            messagebox.showerror("Track", "Pick at least one section.", parent=self)
            return
        t.active_sections = [] if len(secs) == len(self.section_vars) else secs
        self.result = t
        self.destroy()


# ----------------------------------------------------------------------
class SoundDialog(_Modal):
    """Settings for one custom sound."""

    def __init__(self, app, sound: CustomSound, title="Custom sound"):
        super().__init__(app, title)
        self.app = app
        self.sound = sound
        f = ttk.Frame(self, padding=12)
        f.grid()
        self.v_name = tk.StringVar(value=sound.name)
        self.v_kind = tk.StringVar(value="Instrument (pitched, follows note length)"
                                   if sound.kind == "instrument" else "Sound effect (plays whole, pitched)")
        self.v_root = tk.StringVar(value=midi_to_name(sound.root_midi))
        self.v_loop = tk.BooleanVar(value=sound.loop)
        self.v_gain = tk.DoubleVar(value=sound.gain)
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(f, textvariable=self.v_name, width=30).grid(row=0, column=1, columnspan=2, sticky="we")
        ttk.Label(f, text="Type").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Combobox(f, textvariable=self.v_kind, state="readonly", width=36,
                     values=["Instrument (pitched, follows note length)",
                             "Sound effect (plays whole, pitched)"]).grid(row=1, column=1, columnspan=2, sticky="we")
        ttk.Label(f, text="Recorded pitch").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(f, textvariable=self.v_root, width=8).grid(row=2, column=1, sticky="w")
        ttk.Button(f, text="Detect", command=self.detect).grid(row=2, column=2, sticky="w")
        ttk.Label(f, text="e.g. C4, A3, F#5 - the note the sample plays as-is",
                  foreground="#777").grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Checkbutton(f, text="Loop sample to fill long notes", variable=self.v_loop).grid(
            row=4, column=1, columnspan=2, sticky="w", pady=2)
        _scale(f, self.v_gain, 0.1, 2.0, 5, "Gain")
        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Preview", command=self.preview).grid(row=0, column=0, padx=4)
        ttk.Button(b, text="OK", width=10, command=self.ok).grid(row=0, column=1, padx=4)
        ttk.Button(b, text="Cancel", width=10, command=self.cancel).grid(row=0, column=2)

    def detect(self):
        try:
            data, sr = decode_wav(self.sound.wav_bytes)
            m = estimate_root_midi(data, sr)
        except Exception:
            m = None
        if m is None:
            messagebox.showinfo("Detect pitch", "Couldn't find a clear pitch. C4 is a safe guess "
                                "for drums and noises.", parent=self)
        else:
            self.v_root.set(midi_to_name(m))

    def preview(self):
        try:
            data, sr = decode_wav(self.sound.wav_bytes)
            st = np.stack([data, data], axis=1) * float(self.v_gain.get())
            peak = float(np.max(np.abs(st))) or 1
            self.app.player.play(st / max(1.0, peak), sr)
        except Exception as exc:
            messagebox.showerror("Preview", str(exc), parent=self)

    def ok(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror("Custom sound", "Please give the sound a name.", parent=self)
            return
        if name in INSTRUMENT_INFO or (name != self.sound.name and self.app.project.sound_by_name(name)):
            messagebox.showerror("Custom sound", "That name is already used.", parent=self)
            return
        try:
            root = name_to_midi(self.v_root.get())
        except ValueError:
            messagebox.showerror("Custom sound", "Recorded pitch should look like C4 or F#3.", parent=self)
            return
        s = self.sound
        s.name = name
        s.kind = "instrument" if self.v_kind.get().startswith("Instrument") else "sfx"
        s.root_midi = max(0, min(127, root))
        s.loop = self.v_loop.get()
        s.gain = float(self.v_gain.get())
        self.result = s
        self.destroy()


class SoundManager(_Modal):
    """List, import, edit and delete custom sounds."""

    def __init__(self, app):
        super().__init__(app, "Custom instruments & sound effects")
        self.app = app
        self.resizable(True, True)
        f = ttk.Frame(self, padding=10)
        f.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        cols = ("name", "kind", "root", "loop", "source")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c, w, txt in zip(cols, (160, 110, 70, 50, 200), ("Name", "Type", "Pitch", "Loop", "File")):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        b = ttk.Frame(f)
        b.grid(row=0, column=1, sticky="n", padx=(8, 0))
        for i, (txt, cmd) in enumerate((("Import...", self.import_), ("Edit...", self.edit),
                                        ("Preview", self.preview), ("Delete", self.delete),
                                        ("Close", self.cancel))):
            ttk.Button(b, text=txt, width=12, command=cmd).grid(row=i, column=0, pady=2)
        ttk.Label(f, text="Supported: WAV (any bit depth). MP3, OGG and FLAC also work when ffmpeg "
                          "is installed. Sounds are saved inside the project file.",
                  foreground="#777", wraplength=520).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for s in self.app.project.custom_sounds:
            self.tree.insert("", "end", iid=s.name, values=(
                s.name, "Instrument" if s.kind == "instrument" else "Sound FX",
                midi_to_name(s.root_midi), "yes" if s.loop else "no", s.source_name))

    def _selected(self):
        sel = self.tree.selection()
        return self.app.project.sound_by_name(sel[0]) if sel else None

    def import_(self):
        self.app.import_custom_sound(parent=self)
        self.refresh()

    def edit(self):
        s = self._selected()
        if not s:
            return
        old = s.name
        if SoundDialog(self.app, s, "Edit custom sound").run(self):
            if s.name != old:
                for t in self.app.project.tracks:
                    if t.instrument == old:
                        t.instrument = s.name
            self.app.sounds_changed()
            self.refresh()

    def preview(self):
        s = self._selected()
        if not s:
            return
        try:
            data, sr = decode_wav(s.wav_bytes)
            self.app.player.play(np.stack([data, data], axis=1) * min(1.0, s.gain), sr)
        except Exception as exc:
            messagebox.showerror("Preview", str(exc), parent=self)

    def delete(self):
        s = self._selected()
        if not s:
            return
        users = [t.name for t in self.app.project.tracks if t.instrument == s.name]
        msg = f"Delete '{s.name}'?"
        if users:
            msg += "\n\nTracks using it will switch to Piano: " + ", ".join(users)
        if not messagebox.askyesno("Delete sound", msg, parent=self):
            return
        for t in self.app.project.tracks:
            if t.instrument == s.name:
                t.instrument = "Piano"
        self.app.project.custom_sounds.remove(s)
        self.app.sounds_changed()
        self.refresh()


def ask_import_sound(app, parent) -> CustomSound | None:
    path = filedialog.askopenfilename(
        parent=parent, title="Import instrument or sound effect",
        filetypes=[("Audio files", "*.wav *.mp3 *.ogg *.flac *.aiff *.m4a"), ("WAV", "*.wav"),
                   ("All files", "*.*")])
    if not path:
        return None
    try:
        data = load_audio_file(path)
        samples, sr = decode_wav(data)
    except Exception as exc:
        messagebox.showerror("Import sound", f"Could not read that file:\n{exc}", parent=parent)
        return None
    if len(samples) > sr * 30:
        if not messagebox.askyesno("Import sound", "This file is longer than 30 seconds and will make "
                                   "the project file large. Import anyway?", parent=parent):
            return None
    base = os.path.splitext(os.path.basename(path))[0][:40] or "Sound"
    name, k = base, 2
    while name in INSTRUMENT_INFO or app.project.sound_by_name(name):
        name, k = f"{base} {k}", k + 1
    root = estimate_root_midi(samples, sr)
    long_sound = len(samples) > sr * 1.2
    sound = CustomSound.from_wav_bytes(name, data, kind="instrument" if root else "sfx",
                                       root_midi=root or 60, loop=False,
                                       source_name=os.path.basename(path))
    if not root and not long_sound:
        sound.kind = "sfx"
    return SoundDialog(app, sound, "New custom sound").run(parent)
