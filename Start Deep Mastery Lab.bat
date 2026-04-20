@echo off
echo.
echo ============================================
echo   Deep Mastery Lab
echo ============================================
echo.

REM ── Check venv exists ────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo Please run install.bat first.
    echo.
    pause
    exit /b 1
)

REM ── Launch ───────────────────────────────────
echo Starting... your browser will open automatically.
echo To stop the app, close this window or press Ctrl+C.
echo.
call venv\Scripts\activate.bat
streamlit run app.py
