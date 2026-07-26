@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Solar Lien Discovery startup > startup_error.txt
echo Started: %date% %time% >> startup_error.txt
echo Folder: %cd% >> startup_error.txt
echo. >> startup_error.txt

echo ============================================================
echo SOLAR LIEN DISCOVERY - DIAGNOSTIC START
echo ============================================================
echo.

where python >> startup_error.txt 2>&1
if errorlevel 1 (
    echo ERROR: Windows cannot find Python.
    echo Reinstall Python with "Add python.exe to PATH" checked.
    echo Details were saved to startup_error.txt
    pause
    exit /b 1
)

echo Python detected:
python --version
python --version >> startup_error.txt 2>&1
echo.

if not exist "requirements.txt" (
    echo ERROR: requirements.txt is missing.
    echo Make sure this file is inside the extracted SolarLienDiscovery folder.
    echo ERROR: requirements.txt is missing. >> startup_error.txt
    pause
    exit /b 1
)

if not exist "run.py" (
    echo ERROR: run.py is missing.
    echo Make sure this file is inside the extracted SolarLienDiscovery folder.
    echo ERROR: run.py is missing. >> startup_error.txt
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment...
    python -m venv .venv >> startup_error.txt 2>&1
    if errorlevel 1 goto :fail

    echo Installing required packages...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >> startup_error.txt 2>&1
    if errorlevel 1 goto :fail

    ".venv\Scripts\python.exe" -m pip install -r requirements.txt >> startup_error.txt 2>&1
    if errorlevel 1 goto :fail

    echo Installing browser support...
    ".venv\Scripts\python.exe" -m playwright install chromium >> startup_error.txt 2>&1
    if errorlevel 1 goto :fail
)

echo Launching application...
echo.
".venv\Scripts\python.exe" run.py
set ERR=%ERRORLEVEL%

if not "%ERR%"=="0" (
    echo.
    echo Application stopped with error code %ERR%.
    echo Send startup_error.txt to ChatGPT.
    echo Error code: %ERR% >> startup_error.txt
    pause
    exit /b %ERR%
)

echo.
echo Program closed normally.
pause
exit /b 0

:fail
echo.
echo SETUP FAILED.
echo Send startup_error.txt to ChatGPT.
pause
exit /b 1
