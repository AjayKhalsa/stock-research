@echo off
setlocal EnableDelayedExpansion
title StockLens Launcher

echo ============================================
echo   StockLens - Indian Stock Research Tool
echo ============================================
echo.

:: Capture directories now - %~dp0 already ends with backslash
set "ROOT=%~dp0"
set "BDIR=%~dp0backend"
set "FDIR=%~dp0frontend"

:: ── Find Python ──────────────────────────────────────────────────────────────

:: Priority 1: venv already built from a previous run (fastest path)
if exist "%BDIR%\venv\Scripts\python.exe" (
    set "PYTHON=%BDIR%\venv\Scripts\python.exe"
    goto :have_python
)

:: Priority 2: known location on this machine
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Python\bin\python.exe"
    goto :have_python
)

:: Priority 3: common install directories
for %%D in (
    "C:\Python314" "C:\Python313" "C:\Python312" "C:\Python311" "C:\Python310" "C:\Python39"
    "%LOCALAPPDATA%\Programs\Python\Python314"
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\anaconda3"
    "C:\ProgramData\Miniconda3"
    "C:\ProgramData\Anaconda3"
) do (
    if exist "%%~D\python.exe" (
        if "!PYTHON!"=="" set "PYTHON=%%~D\python.exe"
    )
)

:: Priority 4: PATH fallback
if "!PYTHON!"=="" (
    where python3 >nul 2>&1 && set "PYTHON=python3"
)
if "!PYTHON!"=="" (
    where python  >nul 2>&1 && set "PYTHON=python"
)

if "!PYTHON!"=="" (
    echo [ERROR] Python not found.
    echo.
    echo Install Python 3.9+ from https://www.python.org/downloads/
    echo and tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

:have_python
echo Found Python: !PYTHON!
"!PYTHON!" --version
echo.

:: ── Create venv and install deps (first run only) ────────────────────────────
if not exist "%BDIR%\venv\Scripts\python.exe" (
    echo Creating virtual environment...
    "!PYTHON!" -m venv "%BDIR%\venv"
    if errorlevel 1 (
        echo [ERROR] Could not create venv.  Check your Python install.
        pause
        exit /b 1
    )
    echo Installing dependencies ^(first run - takes ~1 min^)...
    "%BDIR%\venv\Scripts\pip.exe" install -r "%BDIR%\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] pip install failed.  See messages above.
        pause
        exit /b 1
    )
    echo.
)

:: ── Load .env (repo root) — copy .env.example to .env and set GEMINI_API_KEY ─
if exist "%ROOT%.env" (
    echo Loading environment from .env...
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%.env") do (
        if not "%%a"=="" if not "%%b"=="" set "%%a=%%b"
    )
) else (
    echo [NOTE] No .env file found. Copy .env.example to .env and set GEMINI_API_KEY.
    echo        AI thesis will be unavailable until a key is set.
)
if "%GEMINI_API_KEY%"=="" (
    echo [NOTE] GEMINI_API_KEY not set — AI thesis layer disabled.
)

:: ── Launch Backend ───────────────────────────────────────────────────────────
:: /D sets working directory so uvicorn path stays relative (no spaces issue)
echo Starting backend  ^>  http://localhost:8000
start "StockLens Backend" /D "%BDIR%" cmd /k "venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak >nul

:: ── Launch Frontend ──────────────────────────────────────────────────────────
echo Starting frontend ^>  http://localhost:3000
start "StockLens Frontend" /D "%FDIR%" cmd /k "npm start"

echo.
echo ============================================
echo   Both servers are starting up!
echo.
echo   Frontend :  http://localhost:3000
echo   Backend  :  http://localhost:8000
echo   API docs :  http://localhost:8000/docs
echo ============================================
echo.
echo (Close the two server windows to stop StockLens)
echo.
pause
