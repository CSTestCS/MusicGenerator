@echo off
REM Builds dist\WordSongStudio.exe on Windows. Needs Python 3.10+ from python.org.
setlocal
cd /d "%~dp0"
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q || goto :fail
pyinstaller --noconfirm --clean WordSongStudio.spec || goto :fail
echo.
echo Done! Your app is at dist\WordSongStudio.exe
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
