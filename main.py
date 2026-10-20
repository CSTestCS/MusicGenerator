"""Word Song Studio - launch the desktop app.

    WordSongStudio.exe [project.wsong]
    WordSongStudio.exe --selftest out.wav     (render the demo song without a window)
"""

import multiprocessing
import sys


def selftest(out_path: str) -> int:
    from musicgen.audio_io import write_wav
    from musicgen.generator import generate
    from musicgen.instruments import SR, SoundBank
    from musicgen.midi import song_to_midi
    from musicgen.project import Project
    from musicgen.renderer import render

    p = Project.default()
    p.section_scale = 0.5
    bank = SoundBank(p.custom_sounds)
    song = generate(p, bank.is_kit)
    audio = render(song, bank)
    write_wav(out_path, audio, SR)
    return 0 if len(song_to_midi(song)) > 100 and audio.shape[0] > SR else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2] if len(sys.argv) > 2 else "selftest.wav"))
    from musicgen.gui.app import main
    main()
