"""Main application window."""

from __future__ import annotations

import copy
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .. import APP_NAME, __version__
from ..audio_io import Player, export_with_ffmpeg, find_ffmpeg, write_wav
from ..contour import CONTOUR_STYLES, clean_word
from ..formulas import FORMULA_NAMES, SHAPE_MODES, describe
from ..generator import active_ranges, generate
from ..instruments import BUILTIN_NAMES, SR, SoundBank
from ..midi import write_midi
from ..project import PROJECT_EXT, ROLES, Project, Track
from ..renderer import mix_peak, render
from ..theory import KEYS, SCALES
from .dialogs import SoundManager, TrackDialog, ask_import_sound

MODE_LABELS = {v: k for k, v in SHAPE_MODES.items()}
STYLE_LABELS = {"blend": "Blend (alphabet + sound)", "alphabet": "Alphabet height",
                "phonetic": "Phonetic (vowel energy)"}
STYLE_KEYS = {v: k for k, v in STYLE_LABELS.items()}
SECTION_SCALES = {"Short (0.5x)": 0.5, "Compact (0.75x)": 0.75, "Normal (1x)": 1.0,
                  "Long (1.5x)": 1.5, "Epic (2x)": 2.0}

SECTION_COLORS = {"intro": "#4c5d82", "verse": "#2f7a68", "prechorus": "#8d7a32",
                  "chorus": "#a8443b", "bridge": "#6a4a91", "solo": "#b8641a",
                  "outro": "#4a5663", "theme": "#2f6a8f", "variation": "#2f7a68",
                  "contrast": "#8f4a6d", "letter": "#34476a"}
LANE_COLORS = ["#7fd1ff", "#ffb86b", "#9be38a", "#ff8fb1", "#c9a6ff", "#ffe27a", "#7ef2d8", "#ff9e7a"]
BG = "#1b1c23"
FG = "#d9dbe4"
DIM = "#6f7385"

HELP_TEXT = """HOW IT WORKS

1. Type a PARENT WORD. Each letter gets a height (a = low ... z = high, vowels add
   energy). Those rises and falls are stretched across the whole song: the song's
   register, loudness, brightness and busyness follow the word from start to end.

2. Pick a SHAPE MODE:
   • Word only - the parent word alone shapes the song; each letter becomes a part.
   • Formula only - a song formula (Pop, Rock Anthem...) sets the sections.
   • Word + Formula - the formula gives the structure, the word bends it.

3. TRACKS. Every track has an instrument (or sound effect), a role (melody, chords,
   bass...), and its own word. A track's word repeats at its own rate ("repeat every
   N bars") while still riding the parent word's slow curve. Leave the word blank to
   repeat the parent word.

   In the track editor you can limit a track to certain LETTERS of the parent word
   (e.g. only during the "M" and "P" parts) or to certain sections.

4. CUSTOM SOUNDS. Sounds > Import... loads a WAV (or MP3/OGG/FLAC with ffmpeg).
   Set the note it was recorded at and it will be pitched to fit the music.
   Instruments follow note lengths; sound effects play whole, at the needed pitch.

5. Press PLAY (Space). Click the timeline to play from any point.
   Save projects with Ctrl+S, export audio (WAV / MP3) or MIDI from the File menu.

Tip: change "Variation" for a different take on the same words.
"""


def resource_path(*parts) -> str:
    """Path to a bundled file (works from source and from the PyInstaller .exe)."""
    import sys
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, *parts)


def _set_dpi_awareness():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


class App(tk.Tk):
    def __init__(self, path: str | None = None):
        _set_dpi_awareness()
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1280x860")
        self.minsize(980, 680)
        try:
            self._icon = tk.PhotoImage(file=resource_path("assets", "icon.png"))
            self.iconphoto(True, self._icon)
        except tk.TclError:
            pass
        self._init_style()

        self.project = Project.default()
        self.path: str | None = None
        self.dirty = False
        self.song = None
        self.bank = SoundBank([])
        self.player = Player()
        self.audio = None
        self.audio_key = None
        self.rendering = False
        self.render_q: queue.Queue = queue.Queue()
        self.playing = False
        self.play_t0 = 0.0
        self.cursor_sec = 0.0
        self._loading = False
        self._regen_job = None

        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.load_vars_from_project()
        self.regenerate()
        self.after(100, self._poll)
        if path:
            self.after(200, lambda: self.open_project(path))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _init_style(self):
        style = ttk.Style(self)
        if os.name != "nt" and "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Big.TEntry", padding=4)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=24)

    def _build_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="New Project", accelerator="Ctrl+N", command=self.new_project)
        fm.add_command(label="Open Project...", accelerator="Ctrl+O", command=self.open_project)
        fm.add_command(label="Save Project", accelerator="Ctrl+S", command=self.save_project)
        fm.add_command(label="Save Project As...", accelerator="Ctrl+Shift+S",
                       command=lambda: self.save_project(as_new=True))
        fm.add_separator()
        fm.add_command(label="Export Song (WAV / MP3)...", accelerator="Ctrl+E", command=self.export_audio)
        fm.add_command(label="Export Track Stems (WAV)...", command=self.export_stems)
        fm.add_command(label="Export MIDI...", command=self.export_midi)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.on_close)
        m.add_cascade(label="File", menu=fm)
        tm = tk.Menu(m, tearoff=0)
        tm.add_command(label="Add Track...", accelerator="Ctrl+T", command=self.add_track)
        tm.add_command(label="Edit Track...", command=self.edit_track)
        tm.add_command(label="Duplicate Track", command=self.duplicate_track)
        tm.add_command(label="Delete Track", command=self.delete_track)
        m.add_cascade(label="Tracks", menu=tm)
        sm = tk.Menu(m, tearoff=0)
        sm.add_command(label="Import Custom Instrument / Sound FX...", command=self.import_custom_sound)
        sm.add_command(label="Manage Custom Sounds...", command=lambda: SoundManager(self).run(self))
        m.add_cascade(label="Sounds", menu=sm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="How It Works", command=self.show_help)
        hm.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", f"{APP_NAME} {__version__}\nSongs shaped by words."))
        m.add_cascade(label="Help", menu=hm)
        self.config(menu=m)

    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # --- song settings -------------------------------------------------
        top = ttk.LabelFrame(root, text="Song", padding=8)
        top.grid(row=0, column=0, sticky="we")
        self.v_word = tk.StringVar()
        self.v_mode = tk.StringVar()
        self.v_formula = tk.StringVar()
        self.v_style = tk.StringVar()
        self.v_key = tk.StringVar()
        self.v_scale = tk.StringVar()
        self.v_tempo = tk.StringVar()
        self.v_bars = tk.StringVar()
        self.v_secscale = tk.StringVar()
        self.v_variation = tk.StringVar()
        self.v_mvol = tk.DoubleVar()
        self.v_mrev = tk.DoubleVar()

        wrow = ttk.Frame(top)
        wrow.grid(row=0, column=0, columnspan=10, sticky="we", pady=(0, 6))
        ttk.Label(wrow, text="Parent word", font=("Segoe UI", 11, "bold")).pack(side="left")
        ent = ttk.Entry(wrow, textvariable=self.v_word, width=22, font=("Segoe UI", 16, "bold"))
        ent.pack(side="left", padx=10)
        self.word_entry = ent
        ttk.Label(wrow, text="Its letters' rises and falls are stretched over the whole song.",
                  foreground="#666").pack(side="left", padx=6)
        self.lbl_length = ttk.Label(wrow, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_length.pack(side="right", padx=4)

        def field(col, label, widget):
            ttk.Label(top, text=label).grid(row=1, column=col - 1, sticky="w", padx=4)
            widget.grid(row=2, column=col - 1, sticky="we", padx=4)
            return widget

        field(1, "Shape mode", ttk.Combobox(top, textvariable=self.v_mode, state="readonly", width=15,
                                            values=list(SHAPE_MODES.values())))
        self.cb_formula = field(2, "Song formula", ttk.Combobox(top, textvariable=self.v_formula,
                                                                state="readonly", width=16,
                                                                values=FORMULA_NAMES))
        field(3, "Letter analysis", ttk.Combobox(top, textvariable=self.v_style, state="readonly", width=22,
                                                 values=[STYLE_LABELS[s] for s in CONTOUR_STYLES]))
        field(4, "Key", ttk.Combobox(top, textvariable=self.v_key, state="readonly", width=4, values=KEYS))
        field(5, "Scale", ttk.Combobox(top, textvariable=self.v_scale, state="readonly", width=15,
                                       values=list(SCALES)))
        field(6, "Tempo (BPM)", ttk.Spinbox(top, from_=40, to=220, textvariable=self.v_tempo, width=6))
        self.sp_bars = field(7, "Length (bars)", ttk.Spinbox(top, from_=8, to=256, increment=4,
                                                             textvariable=self.v_bars, width=6))
        self.cb_secscale = field(8, "Section length", ttk.Combobox(top, textvariable=self.v_secscale,
                                                                   state="readonly", width=14,
                                                                   values=list(SECTION_SCALES)))
        field(9, "Variation", ttk.Spinbox(top, from_=1, to=9999, textvariable=self.v_variation, width=6))

        mixf = ttk.Frame(top)
        mixf.grid(row=3, column=0, columnspan=9, sticky="we", pady=(6, 0))
        ttk.Label(mixf, text="Master volume").pack(side="left", padx=4)
        ttk.Scale(mixf, variable=self.v_mvol, from_=0.1, to=1.0, length=140).pack(side="left")
        ttk.Label(mixf, text="Reverb").pack(side="left", padx=(16, 4))
        ttk.Scale(mixf, variable=self.v_mrev, from_=0.0, to=1.0, length=140).pack(side="left")

        self.lbl_formula = ttk.Label(top, text="", wraplength=1100, foreground="#555")
        self.lbl_formula.grid(row=4, column=0, columnspan=10, sticky="w", pady=(6, 0))

        for v in (self.v_word, self.v_mode, self.v_formula, self.v_style, self.v_key, self.v_scale,
                  self.v_tempo, self.v_bars, self.v_secscale, self.v_variation, self.v_mvol, self.v_mrev):
            v.trace_add("write", lambda *_: self.on_song_change())

        # --- timeline ------------------------------------------------------
        tlf = ttk.LabelFrame(root, text="Song shape  (click to set the play position)", padding=4)
        tlf.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        tlf.columnconfigure(0, weight=1)
        tlf.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(tlf, bg=BG, highlightthickness=0, height=330)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tlf, orient="vertical", command=self.canvas.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.bind("<Configure>", lambda e: self.draw_timeline())
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        # --- tracks --------------------------------------------------------
        trf = ttk.LabelFrame(root, text="Tracks", padding=4)
        trf.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        trf.columnconfigure(0, weight=1)
        trf.rowconfigure(0, weight=1)
        cols = ("name", "word", "inst", "role", "rate", "letters", "sections", "vol", "state")
        heads = ("Track", "Word", "Instrument / sound", "Role", "Repeats", "Letters", "Sections", "Vol", "")
        widths = (120, 110, 150, 170, 80, 120, 140, 50, 70)
        self.tree = ttk.Treeview(trf, columns=cols, show="headings", selectmode="browse", height=6)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w", stretch=c in ("inst", "role", "sections"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        tsb = ttk.Scrollbar(trf, orient="vertical", command=self.tree.yview)
        tsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.bind("<Double-1>", lambda e: self.edit_track())
        bf = ttk.Frame(trf)
        bf.grid(row=0, column=2, sticky="ns", padx=(6, 0))
        for i, (txt, cmd) in enumerate((("+ Add Track", self.add_track), ("Edit...", self.edit_track),
                                        ("Duplicate", self.duplicate_track), ("Delete", self.delete_track),
                                        ("Move Up", lambda: self.move_track(-1)),
                                        ("Move Down", lambda: self.move_track(1)),
                                        ("Mute", self.toggle_mute), ("Solo", self.toggle_solo))):
            ttk.Button(bf, text=txt, width=11, command=cmd).grid(row=i // 2, column=i % 2, pady=1, padx=1)

        # --- transport -----------------------------------------------------
        tp = ttk.Frame(root, padding=(0, 8, 0, 0))
        tp.grid(row=3, column=0, sticky="we")
        self.btn_play = ttk.Button(tp, text="▶  Play", style="Accent.TButton", width=12, command=self.toggle_play)
        self.btn_play.pack(side="left")
        ttk.Button(tp, text="⏮  Start", width=9, command=self.rewind).pack(side="left", padx=4)
        ttk.Button(tp, text="■  Stop", width=9, command=self.stop).pack(side="left")
        ttk.Button(tp, text="Export Song...", command=self.export_audio).pack(side="left", padx=(16, 4))
        ttk.Button(tp, text="Save Project", command=self.save_project).pack(side="left")
        self.lbl_time = ttk.Label(tp, text="0:00 / 0:00", font=("Consolas", 11), width=16)
        self.lbl_time.pack(side="right")
        self.progress = ttk.Progressbar(tp, length=180, mode="determinate")
        self.progress.pack(side="right", padx=8)
        self.lbl_status = ttk.Label(tp, text="Ready", foreground="#555")
        self.lbl_status.pack(side="right", padx=8)

    def _bind_keys(self):
        self.bind_all("<Control-n>", lambda e: self.new_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-s>", lambda e: self.save_project())
        self.bind_all("<Control-S>", lambda e: self.save_project(as_new=True))
        self.bind_all("<Control-e>", lambda e: self.export_audio())
        self.bind_all("<Control-t>", lambda e: self.add_track())

        def space(e):
            if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
                return
            self.toggle_play()
            return "break"
        self.bind_all("<space>", space)
        self.bind_all("<Delete>", lambda e: None if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox))
                      else self.delete_track())

    # ------------------------------------------------------------------
    # project <-> widgets
    # ------------------------------------------------------------------
    def load_vars_from_project(self):
        self._loading = True
        p = self.project
        self.v_word.set(p.parent_word)
        self.v_mode.set(SHAPE_MODES.get(p.shape_mode, SHAPE_MODES["both"]))
        self.v_formula.set(p.formula)
        self.v_style.set(STYLE_LABELS.get(p.contour_style, STYLE_LABELS["blend"]))
        self.v_key.set(p.key)
        self.v_scale.set(p.scale)
        self.v_tempo.set(str(p.tempo))
        self.v_bars.set(str(p.word_bars))
        self.v_secscale.set(next((k for k, v in SECTION_SCALES.items() if abs(v - p.section_scale) < 1e-6),
                                 "Normal (1x)"))
        self.v_variation.set(str(p.variation))
        self.v_mvol.set(p.master_volume)
        self.v_mrev.set(p.master_reverb)
        self._loading = False
        self.bank = SoundBank(p.custom_sounds)
        self._update_mode_widgets()
        self.refresh_tracks()

    def _read_vars(self):
        p = self.project

        def as_int(var, default, lo, hi):
            try:
                return max(lo, min(hi, int(float(var.get()))))
            except (ValueError, tk.TclError):
                return default
        p.parent_word = self.v_word.get()
        p.shape_mode = MODE_LABELS.get(self.v_mode.get(), "both")
        p.formula = self.v_formula.get() or "Pop"
        p.contour_style = STYLE_KEYS.get(self.v_style.get(), "blend")
        p.key = self.v_key.get() or "C"
        p.scale = self.v_scale.get() or "Major"
        p.tempo = as_int(self.v_tempo, p.tempo, 40, 220)
        p.word_bars = as_int(self.v_bars, p.word_bars, 8, 256)
        p.section_scale = SECTION_SCALES.get(self.v_secscale.get(), 1.0)
        p.variation = as_int(self.v_variation, p.variation, 1, 9999)
        try:
            p.master_volume = float(self.v_mvol.get())
            p.master_reverb = float(self.v_mrev.get())
        except tk.TclError:
            pass

    def _update_mode_widgets(self):
        mode = self.project.shape_mode
        self.sp_bars.configure(state="normal" if mode == "word" else "disabled")
        self.cb_formula.configure(state="disabled" if mode == "word" else "readonly")
        self.cb_secscale.configure(state="disabled" if mode == "word" else "readonly")
        if mode == "word":
            self.lbl_formula.configure(text="Word only: each letter of the parent word becomes a part "
                                            "of the song, and the word's rises and falls shape it from "
                                            "start to finish.")
        else:
            prefix = "Formula + word: " if mode == "both" else "Formula: "
            self.lbl_formula.configure(text=prefix + describe(self.project.formula))

    def on_song_change(self):
        if self._loading:
            return
        old_word = clean_word(self.project.parent_word)
        old_formula = (self.project.shape_mode, self.project.formula)
        self._read_vars()
        new_word = clean_word(self.project.parent_word)
        if new_word != old_word:
            for t in self.project.tracks:
                t.active_letters = [i for i in t.active_letters if i < len(new_word)]
        if (self.project.shape_mode, self.project.formula) != old_formula:
            for t in self.project.tracks:
                t.active_sections = []
        self._update_mode_widgets()
        self.mark_dirty()
        if self._regen_job:
            self.after_cancel(self._regen_job)
        self._regen_job = self.after(250, self.regenerate)

    def mark_dirty(self, dirty=True):
        self.dirty = dirty
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.title(f"{'*' if dirty else ''}{name} - {APP_NAME}")

    # ------------------------------------------------------------------
    # generation & drawing
    # ------------------------------------------------------------------
    def regenerate(self):
        self._regen_job = None
        try:
            self.song = generate(self.project, self.bank.is_kit)
        except Exception as exc:  # keep the UI alive whatever happens
            self.set_status(f"Could not build song: {exc}")
            return
        d = self.song.duration_seconds
        self.lbl_length.configure(text=f"{self.song.timeline.bars} bars  •  {int(d // 60)}:{int(d % 60):02d}")
        self.cursor_sec = min(self.cursor_sec, d)
        self.refresh_tracks()
        self.draw_timeline()
        self._update_time_label()

    def project_key(self) -> str:
        return json.dumps(self.project.to_dict(), sort_keys=True)

    def instrument_choices(self) -> list[str]:
        out = []
        for name in BUILTIN_NAMES:
            out.append(name)
        for s in self.project.custom_sounds:
            out.append(s.name)
        return out

    def _geometry(self):
        w = max(self.canvas.winfo_width(), 700)
        return 118, w - 14

    def draw_timeline(self):
        c = self.canvas
        c.delete("all")
        song = self.song
        if not song:
            return
        tl = song.timeline
        x0, x1 = self._geometry()
        tb = tl.total_beats

        def bx(b):
            return x0 + (x1 - x0) * b / tb

        y = 6
        # sections
        c.create_text(8, y + 11, text="Sections" if tl.mode != "word" else "Parts", anchor="w",
                      fill=DIM, font=("Segoe UI", 8))
        for s in tl.sections:
            xa, xb = bx(s.start), bx(s.end)
            c.create_rectangle(xa, y, xb - 1, y + 22, fill=SECTION_COLORS.get(s.kind, "#445"), outline="")
            if xb - xa > 26:
                label = s.name if (xb - xa) > len(s.name) * 6.5 else s.name[:max(1, int((xb - xa) / 7))]
                c.create_text((xa + xb) / 2, y + 11, text=label, fill="white", font=("Segoe UI", 8))
        y += 26
        # letters of the parent word
        c.create_text(8, y + 15, text="Parent word", anchor="w", fill=DIM, font=("Segoe UI", 8))
        for i, l in enumerate(tl.letters):
            xa, xb = bx(l.start), bx(l.end)
            c.create_rectangle(xa, y, xb - 1, y + 30, fill="#262836" if i % 2 else "#2d3040", outline="")
            c.create_text((xa + xb) / 2, y + 15, text=l.char.upper(), fill="#f0f0ff",
                          font=("Segoe UI", 14, "bold"))
        y += 34
        # contour + energy
        h = 110
        c.create_text(8, y + 14, text="Word shape", anchor="w", fill="#7fd1ff", font=("Segoe UI", 8))
        c.create_text(8, y + 30, text="Energy", anchor="w", fill="#e0a050", font=("Segoe UI", 8))
        c.create_rectangle(x0, y, x1, y + h, fill="#20222c", outline="")
        beats = np.linspace(0, tb, 360)
        en = tl.energy(beats)
        pc = tl.parent_curve(beats)
        poly = [x0, y + h]
        for b, e in zip(beats, en):
            poly += [bx(b), y + h - e * (h - 8)]
        poly += [x1, y + h]
        c.create_polygon(*poly, fill="#4a3a22", outline="")
        line = []
        for b, e in zip(beats, en):
            line += [bx(b), y + h - e * (h - 8)]
        c.create_line(*line, fill="#e0a050", width=1)
        line = []
        for b, v in zip(beats, pc):
            line += [bx(b), y + h - 6 - v * (h - 14)]
        c.create_line(*line, fill="#7fd1ff", width=3, smooth=True)
        y += h + 8
        # tracks
        any_solo = any(t.solo for t in self.project.tracks)
        sel = self.tree.selection()
        lane_h = 40
        for i, t in enumerate(self.project.tracks):
            col = LANE_COLORS[i % len(LANE_COLORS)]
            off = t.mute or (any_solo and not t.solo)
            if sel and sel[0] == t.id:
                c.create_rectangle(0, y - 1, x1 + 12, y + lane_h - 1, fill="#2a2d3d", outline="")
            c.create_text(8, y + 12, text=t.name[:16], anchor="w", fill=DIM if off else col,
                          font=("Segoe UI", 9, "bold"))
            sub = (clean_word(t.word) or "(parent)").upper()
            c.create_text(8, y + 27, text=sub[:16], anchor="w", fill=DIM, font=("Segoe UI", 8))
            c.create_rectangle(x0, y, x1, y + lane_h - 4, fill="#20222c", outline="")
            for s, e in active_ranges(tl, t, 0.5):
                c.create_rectangle(bx(s), y, bx(e), y + lane_h - 4, fill="#2a2e3e", outline="")
            notes = song.notes.get(t.id, [])
            if notes:
                lo = min(n.midi for n in notes)
                hi = max(n.midi for n in notes)
                rng = max(1, hi - lo)
                fill = "#555a6a" if off else col
                for n in notes:
                    ny = y + lane_h - 7 - (n.midi - lo) / rng * (lane_h - 12)
                    xa = bx(n.start)
                    xb = max(xa + 1.5, bx(n.start + n.dur) - 0.5)
                    c.create_line(xa, ny, xb, ny, fill=fill, width=2)
            y += lane_h
        self._timeline_bottom = y
        c.configure(scrollregion=(0, 0, x1 + 14, y + 6))
        # cursor & playhead
        dur = song.duration_seconds or 1
        cx = x0 + (x1 - x0) * self.cursor_sec / dur
        c.create_line(cx, 0, cx, y, fill="#ffd34d", width=1, dash=(3, 3), tags="cursor")
        c.create_line(-10, 0, -10, y, fill="white", width=2, tags="playhead")

    def on_canvas_click(self, event):
        if not self.song:
            return
        x0, x1 = self._geometry()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if cx < x0:
            # clicking a lane name selects that track
            idx = int((cy - (6 + 26 + 34 + 118)) // 40)
            if 0 <= idx < len(self.project.tracks):
                tid = self.project.tracks[idx].id
                self.tree.selection_set(tid)
                self.draw_timeline()
            return
        frac = min(1.0, max(0.0, (cx - x0) / (x1 - x0)))
        self.cursor_sec = frac * self.song.duration_seconds
        was_playing = self.playing
        self.draw_timeline()
        self._update_time_label()
        if was_playing:
            self.play()

    # ------------------------------------------------------------------
    # tracks
    # ------------------------------------------------------------------
    def refresh_tracks(self):
        sel = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        tl = self.song.timeline if self.song else None
        word = clean_word(self.project.parent_word)
        for t in self.project.tracks:
            if t.active_letters:
                letters = " ".join(word[i].upper() for i in t.active_letters if i < len(word))
            else:
                letters = "All"
            if t.active_sections and tl:
                secs = ", ".join(tl.sections[i].name for i in t.active_sections if i < len(tl.sections))
            else:
                secs = "Auto"
            state = ("M " if t.mute else "") + ("S" if t.solo else "")
            rate = f"{t.cycle_bars:g} bar" + ("" if t.cycle_bars == 1 else "s")
            self.tree.insert("", "end", iid=t.id, values=(
                t.name, (clean_word(t.word) or "(parent)").upper(), t.instrument,
                ROLES.get(t.role, t.role), rate, letters, secs, f"{t.volume:.2f}", state))
        if sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def selected_track(self) -> Track | None:
        sel = self.tree.selection()
        return self.project.track_by_id(sel[0]) if sel else None

    def tracks_changed(self, select: str | None = None):
        self.mark_dirty()
        self.regenerate()
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)
            self.draw_timeline()

    def add_track(self):
        n = len(self.project.tracks) + 1
        t = Track(name=f"Track {n}", word="", instrument="Bell", role="melody", cycle_bars=1.0,
                  note_beats=0.5, octave=1, volume=0.55, reverb=0.35)
        if TrackDialog(self, t, "Add track").run(self):
            self.project.tracks.append(t)
            self.tracks_changed(t.id)

    def edit_track(self):
        t = self.selected_track()
        if not t:
            return
        work = copy.deepcopy(t)
        if TrackDialog(self, work, f"Edit track - {t.name}").run(self):
            idx = self.project.tracks.index(t)
            self.project.tracks[idx] = work
            self.tracks_changed(work.id)

    def duplicate_track(self):
        t = self.selected_track()
        if not t:
            return
        d = copy.deepcopy(t)
        d.id = Track().id
        d.name = t.name + " copy"
        self.project.tracks.insert(self.project.tracks.index(t) + 1, d)
        self.tracks_changed(d.id)

    def delete_track(self):
        t = self.selected_track()
        if not t:
            return
        if messagebox.askyesno("Delete track", f"Delete track '{t.name}'?"):
            self.project.tracks.remove(t)
            self.tracks_changed()

    def move_track(self, d):
        t = self.selected_track()
        if not t:
            return
        tr = self.project.tracks
        i = tr.index(t)
        j = max(0, min(len(tr) - 1, i + d))
        tr[i], tr[j] = tr[j], tr[i]
        self.tracks_changed(t.id)

    def toggle_mute(self):
        t = self.selected_track()
        if t:
            t.mute = not t.mute
            self.tracks_changed(t.id)

    def toggle_solo(self):
        t = self.selected_track()
        if t:
            t.solo = not t.solo
            self.tracks_changed(t.id)

    # ------------------------------------------------------------------
    # custom sounds
    # ------------------------------------------------------------------
    def import_custom_sound(self, parent=None) -> str | None:
        s = ask_import_sound(self, parent or self)
        if not s:
            return None
        self.project.custom_sounds.append(s)
        self.sounds_changed()
        self.set_status(f"Imported '{s.name}'. Pick it as a track's instrument.")
        return s.name

    def sounds_changed(self):
        self.bank = SoundBank(self.project.custom_sounds)
        self.audio_key = None
        self.tracks_changed()

    # ------------------------------------------------------------------
    # rendering & playback
    # ------------------------------------------------------------------
    def set_status(self, text):
        self.lbl_status.configure(text=text)

    def ensure_audio(self, then):
        """Render the song in the background if needed, then call ``then()``."""
        key = self.project_key()
        if self.audio is not None and self.audio_key == key:
            then()
            return
        if self.rendering:
            self._after_render = then
            return
        self.rendering = True
        self._after_render = then
        snapshot = Project.from_dict(json.loads(key))
        bank = self.bank

        def work():
            try:
                song = generate(snapshot, bank.is_kit)
                audio = render(song, bank, progress=lambda f, m: self.render_q.put(("progress", f, m)))
                self.render_q.put(("done", key, audio))
            except Exception as exc:
                self.render_q.put(("error", str(exc), None))
        threading.Thread(target=work, daemon=True).start()
        self.set_status("Rendering...")

    def _poll(self):
        try:
            while True:
                msg = self.render_q.get_nowait()
                if msg[0] == "progress":
                    self.progress["value"] = msg[1] * 100
                    self.set_status(msg[2])
                elif msg[0] == "done":
                    self.rendering = False
                    self.audio, self.audio_key = msg[2], msg[1]
                    self.progress["value"] = 0
                    self.set_status("Ready")
                    cb, self._after_render = self._after_render, None
                    if self.audio_key != self.project_key():
                        # settings changed while rendering - render again
                        if cb:
                            self.ensure_audio(cb)
                    elif cb:
                        cb()
                elif msg[0] == "error":
                    self.rendering = False
                    self.progress["value"] = 0
                    self.set_status("Render failed")
                    messagebox.showerror("Render failed", msg[1])
        except queue.Empty:
            pass
        if self.playing:
            pos = time.time() - self.play_t0
            dur = (len(self.audio) / SR) if self.audio is not None else 0
            if pos >= dur:
                self.playing = False
                self.btn_play.configure(text="▶  Play")
                self.canvas.coords("playhead", -10, 0, -10, 1)
            else:
                self._move_playhead(pos)
            self._update_time_label(pos)
        self.after(40, self._poll)

    def _move_playhead(self, sec):
        if not self.song:
            return
        x0, x1 = self._geometry()
        x = x0 + (x1 - x0) * sec / (self.song.duration_seconds or 1)
        self.canvas.coords("playhead", x, 0, x, getattr(self, "_timeline_bottom", 400))

    def _update_time_label(self, pos=None):
        if not self.song:
            return
        pos = self.cursor_sec if pos is None else pos
        d = self.song.duration_seconds
        self.lbl_time.configure(text=f"{int(pos // 60)}:{int(pos % 60):02d} / {int(d // 60)}:{int(d % 60):02d}")

    def toggle_play(self):
        if self.playing:
            self.stop()
        else:
            self.play()

    def play(self):
        def go():
            try:
                self.player.play(self.audio, SR, self.cursor_sec)
            except Exception as exc:
                messagebox.showerror("Playback", str(exc))
                return
            self.playing = True
            self.play_t0 = time.time() - self.cursor_sec
            self.btn_play.configure(text="❚❚  Pause")
        self.player.stop()
        self.playing = False
        self.ensure_audio(go)

    def stop(self):
        if self.playing:
            self.cursor_sec = min(time.time() - self.play_t0, self.song.duration_seconds if self.song else 0)
        self.player.stop()
        self.playing = False
        self.btn_play.configure(text="▶  Play")
        self.draw_timeline()
        self._update_time_label()

    def rewind(self):
        was = self.playing
        self.player.stop()
        self.playing = False
        self.cursor_sec = 0.0
        self.draw_timeline()
        self._update_time_label()
        if was:
            self.play()
        else:
            self.btn_play.configure(text="▶  Play")

    # ------------------------------------------------------------------
    # files
    # ------------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", "Save changes to the current project first?")
        if ans is None:
            return False
        if ans:
            return self.save_project()
        return True

    def new_project(self):
        if not self._confirm_discard():
            return
        self.stop()
        self.project = Project.default()
        self.path = None
        self.audio = None
        self.cursor_sec = 0
        self.load_vars_from_project()
        self.regenerate()
        self.mark_dirty(False)

    def open_project(self, path=None):
        if not path:
            if not self._confirm_discard():
                return
            path = filedialog.askopenfilename(title="Open project", defaultextension=PROJECT_EXT,
                                              filetypes=[("Word Song project", f"*{PROJECT_EXT}"),
                                                         ("All files", "*.*")])
            if not path:
                return
        try:
            proj = Project.load(path)
        except Exception as exc:
            messagebox.showerror("Open project", f"Could not open the project:\n{exc}")
            return
        self.stop()
        self.project = proj
        self.path = path
        self.audio = None
        self.cursor_sec = 0
        self.load_vars_from_project()
        self.regenerate()
        self.mark_dirty(False)
        self.set_status(f"Opened {os.path.basename(path)}")

    def save_project(self, as_new=False) -> bool:
        path = self.path
        if as_new or not path:
            default = (clean_word(self.project.parent_word) or "song") + PROJECT_EXT
            path = filedialog.asksaveasfilename(title="Save project", defaultextension=PROJECT_EXT,
                                                initialfile=default,
                                                filetypes=[("Word Song project", f"*{PROJECT_EXT}")])
            if not path:
                return False
        try:
            self.project.save(path)
        except Exception as exc:
            messagebox.showerror("Save project", f"Could not save:\n{exc}")
            return False
        self.path = path
        self.mark_dirty(False)
        self.set_status(f"Saved {os.path.basename(path)}")
        return True

    def export_audio(self):
        word = clean_word(self.project.parent_word) or "song"
        types = [("WAV audio", "*.wav")]
        if find_ffmpeg():
            types += [("MP3 audio", "*.mp3"), ("OGG audio", "*.ogg"), ("FLAC audio", "*.flac")]
        path = filedialog.asksaveasfilename(title="Export song", defaultextension=".wav",
                                            initialfile=f"{word}.wav", filetypes=types)
        if not path:
            return

        def write():
            try:
                if path.lower().endswith(".wav"):
                    write_wav(path, self.audio, SR)
                else:
                    export_with_ffmpeg(path, self.audio, SR)
            except Exception as exc:
                messagebox.showerror("Export", f"Export failed:\n{exc}")
                return
            self.set_status(f"Exported {os.path.basename(path)}")
            messagebox.showinfo("Export", f"Song exported to:\n{path}")
        self.ensure_audio(write)

    def export_stems(self):
        folder = filedialog.askdirectory(title="Choose a folder for the track stems")
        if not folder:
            return
        snapshot = Project.from_dict(self.project.to_dict())
        bank = self.bank
        word = clean_word(snapshot.parent_word) or "song"

        def work():
            try:
                song = generate(snapshot, bank.is_kit)
                self.render_q.put(("progress", 0.0, "Measuring full mix..."))
                peak = mix_peak(song, bank)
                any_solo = any(t.solo for t in snapshot.tracks)
                tracks = [t for t in snapshot.tracks if not t.mute and (t.solo or not any_solo)]
                for i, t in enumerate(tracks):
                    self.render_q.put(("progress", (i + 1) / (len(tracks) + 1), f"Stem: {t.name}"))
                    audio = render(song, bank, only_track=t.id, peak=peak)
                    safe = "".join(ch for ch in t.name if ch.isalnum() or ch in " -_").strip() or "track"
                    write_wav(os.path.join(folder, f"{word} - {i + 1:02d} {safe}.wav"), audio, SR)
                self.render_q.put(("progress", 0, f"Stems saved to {folder}"))
            except Exception as exc:
                self.render_q.put(("error", str(exc), None))
        threading.Thread(target=work, daemon=True).start()

    def export_midi(self):
        word = clean_word(self.project.parent_word) or "song"
        path = filedialog.asksaveasfilename(title="Export MIDI", defaultextension=".mid",
                                            initialfile=f"{word}.mid", filetypes=[("MIDI file", "*.mid")])
        if not path:
            return
        try:
            write_midi(path, generate(self.project, self.bank.is_kit))
        except Exception as exc:
            messagebox.showerror("Export MIDI", str(exc))
            return
        self.set_status(f"Exported {os.path.basename(path)}")

    def show_help(self):
        win = tk.Toplevel(self)
        win.title("How it works")
        txt = tk.Text(win, wrap="word", width=86, height=34, font=("Segoe UI", 10), padx=12, pady=10)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

    def on_close(self):
        if not self._confirm_discard():
            return
        self.player.cleanup()
        self.destroy()


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    app = App(argv[0] if argv else None)
    app.mainloop()
