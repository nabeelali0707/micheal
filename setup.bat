@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   MCQ Helper setup / check
echo ============================================
echo.

rem ---------- 1. Python ----------
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
    py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [X] Python is NOT installed.
    echo     Install Python 3.10 or newer from https://www.python.org/downloads/
    echo     IMPORTANT: tick "Add python.exe to PATH" in the installer.
    echo     Then run setup.bat again.
    goto :end
)
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
echo [OK] Python %PYVER%  (%PY%)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)"
if errorlevel 1 (
    echo [X] Python is too old. Install Python 3.10 or newer.
    goto :end
)

rem ---------- 2. tkinter ----------
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [X] tkinter is missing. Re-run the Python installer, choose Modify,
    echo     and tick "tcl/tk and IDLE".
    goto :end
)
echo [OK] tkinter

rem ---------- 3. Python packages ----------
echo.
echo Installing Python packages (keyboard, pillow, matplotlib)...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] pip install failed. Check your internet connection.
    goto :end
)
%PY% -c "import keyboard, PIL, matplotlib" || (echo [X] packages still not importable & goto :end)
echo [OK] Python packages

rem ---------- 4. Ollama ----------
echo.
set "OLLAMA="
where ollama >nul 2>nul && set "OLLAMA=ollama"
if not defined OLLAMA if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA (
    echo [X] Ollama is NOT installed.
    echo     Download and install it from https://ollama.com/download
    echo     ^(or run:  winget install Ollama.Ollama^)
    echo     Then run setup.bat again.
    goto :end
)
echo [OK] Ollama found: %OLLAMA%
"%OLLAMA%" --version

rem ---------- 5. Model ----------
echo.
"%OLLAMA%" list 2>nul | findstr /i "gemma4:e4b" >nul
if errorlevel 1 (
    echo The model gemma4:e4b is not downloaded yet.
    choice /m "Download it now"
    if errorlevel 2 (
        echo Skipped. MCQ Helper will download it automatically on first start.
    ) else (
        "%OLLAMA%" pull gemma4:e4b
    )
) else (
    echo [OK] Model gemma4:e4b is installed
)

echo.
echo ============================================
echo   Setup done. Double-click start.bat to run.
echo   If nothing appears, run debug.bat to see the error.
echo ============================================

:end
echo.
pause
