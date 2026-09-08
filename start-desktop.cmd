@echo off
setlocal
cd /d "%~dp0"
if exist ".venv-desktop\Scripts\python.exe" (
    ".venv-desktop\Scripts\python.exe" -m desktop.app
    if errorlevel 1 pause
    exit /b
)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" -m desktop.app
        if errorlevel 1 pause
        exit /b
    )
)
echo Creating a desktop environment. Python 3.11 must be installed.
py -3.11 -m venv .venv-desktop
if errorlevel 1 goto failure
".venv-desktop\Scripts\python.exe" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto failure
".venv-desktop\Scripts\python.exe" -m desktop.app
if errorlevel 1 goto failure
exit /b
:failure
echo Desktop could not start. See docs\CRM.md for setup instructions.
pause
exit /b 1
