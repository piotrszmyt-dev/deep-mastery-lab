@echo off
echo.
echo ============================================
echo   Deep Mastery Lab - Installer
echo ============================================
echo.

REM ── Check Python is installed ───────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found.
    echo.
    echo Install Python 3.11 or newer from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: On the first screen of the installer,
    echo check the box labelled "Add Python to PATH"
    echo before clicking Install Now.
    echo.
    pause
    exit /b 1
)

REM ── Show detected Python version ────────────
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo Detected: %PYVER%

REM ── Warn if version is below 3.11 ───────────
python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARNING] Python 3.11 or newer is recommended.
    echo The app may not work correctly on older versions.
    echo.
    echo Continue anyway? Press Ctrl+C to cancel, or
    pause
)

echo.

REM ── Create virtual environment ───────────────
if exist "venv\" (
    echo Virtual environment already exists, skipping creation.
) else (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo.

REM ── Install dependencies ─────────────────────
echo Installing dependencies - this may take a minute...
echo.
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo Check the error above and try running install.bat again.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Installation complete!
echo   Run "Start Deep Mastery Lab.bat" to begin.
echo ============================================
echo.
pause
