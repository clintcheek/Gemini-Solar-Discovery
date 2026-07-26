@echo off
cd /d "%~dp0"
python --version >nul 2>&1 || (echo Python not found. Reinstall it with Add Python to PATH checked.&pause&exit /b 1)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m playwright install chromium
echo SETUP COMPLETE. Double-click run.bat.
pause
