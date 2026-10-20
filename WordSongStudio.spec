# PyInstaller build file:  pyinstaller WordSongStudio.spec
# Produces a single dist/WordSongStudio.exe (no console window).

a = Analysis(
    ["main.py"],
    pathex=[],
    datas=[("assets/icon.png", "assets"), ("assets/icon.ico", "assets")],
    hiddenimports=[],
    excludes=["matplotlib", "scipy", "pandas", "PIL", "IPython", "pytest", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WordSongStudio",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
