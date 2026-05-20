@echo off
setlocal EnableDelayedExpansion

REM Heidstar Flatfield Inspector - Windows one-click launcher
REM   1. Locate / auto-install Miniconda
REM   2. Create conda env + install deps (first run only)
REM   3. Launch the GUI

REM Switch console to UTF-8 so the GUI's stdout (Chinese) is not garbled.
chcp 65001 >nul

cd /d "%~dp0"

set ENV_NAME=heidstar_flat
set PY_VERSION=3.11
set MINICONDA_DIR=%UserProfile%\Miniconda3
set MINICONDA_URL=https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
set MINICONDA_INSTALLER=%TEMP%\Miniconda3-latest-Windows-x86_64.exe

REM ========== 1. Locate conda ==========
set CONDA_EXE=

where conda >nul 2>&1
if not errorlevel 1 (
    set CONDA_EXE=conda
    goto :have_conda
)

if exist "%MINICONDA_DIR%\Scripts\conda.exe" (
    set "CONDA_EXE=%MINICONDA_DIR%\Scripts\conda.exe"
    echo [INFO] Using Miniconda at "%MINICONDA_DIR%".
    goto :have_conda
)

REM ---------- Conda not found: offer auto-install ----------
echo.
echo ====================================================================
echo  Conda was not found on this system.
echo  This script can download and install Miniconda automatically:
echo    Download size : ~80 MB
echo    Install size  : ~400 MB
echo    Install dir   : %MINICONDA_DIR%
echo    Per-user install, no admin required, no PATH changes.
echo ====================================================================
echo.
set /p REPLY="Install Miniconda now? [Y/N] "
if /I not "%REPLY%"=="Y" (
    echo.
    echo Aborted. Please install Miniconda manually:
    echo   https://docs.conda.io/en/latest/miniconda.html
    pause
    exit /b 1
)

REM ---------- Download installer ----------
echo [SETUP] Downloading Miniconda installer...
where curl >nul 2>&1
if not errorlevel 1 (
    curl -L --fail -o "%MINICONDA_INSTALLER%" "%MINICONDA_URL%"
) else (
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%MINICONDA_URL%' -OutFile '%MINICONDA_INSTALLER%'"
)
if errorlevel 1 (
    echo [ERROR] Failed to download Miniconda installer.
    echo Check your network connection or download manually from:
    echo   %MINICONDA_URL%
    pause
    exit /b 1
)
if not exist "%MINICONDA_INSTALLER%" (
    echo [ERROR] Installer file missing after download.
    pause
    exit /b 1
)

REM ---------- Run installer (silent) ----------
echo [SETUP] Running Miniconda installer - silent mode, may take 1-3 minutes...
REM /D=... must be the LAST argument and unquoted (NSIS installer convention).
"%MINICONDA_INSTALLER%" /InstallationType=JustMe /AddToPath=0 /RegisterPython=0 /S /D=%MINICONDA_DIR%
if errorlevel 1 (
    echo [ERROR] Miniconda installer returned non-zero exit code.
    pause
    exit /b 1
)
if not exist "%MINICONDA_DIR%\Scripts\conda.exe" (
    echo [ERROR] conda.exe not found after install at:
    echo   %MINICONDA_DIR%\Scripts\conda.exe
    pause
    exit /b 1
)
set "CONDA_EXE=%MINICONDA_DIR%\Scripts\conda.exe"
echo [SETUP] Miniconda installed at %MINICONDA_DIR%.
del "%MINICONDA_INSTALLER%" 2>nul

:have_conda

REM ========== 2. Create env if missing ==========
"%CONDA_EXE%" env list | findstr /B /C:"%ENV_NAME% " >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Conda env "%ENV_NAME%" not found. Creating with Python %PY_VERSION% from conda-forge ...
    call "%CONDA_EXE%" create -y -n %ENV_NAME% -c conda-forge --override-channels python=%PY_VERSION% pip
    if errorlevel 1 (
        echo [ERROR] Failed to create conda env.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Using existing conda env "%ENV_NAME%".
)

REM ========== 3. Verify deps; install if anything missing ==========
echo [SETUP] Verifying Python dependencies ...
call "%CONDA_EXE%" run --no-capture-output -n %ENV_NAME% python -c "import PyQt5, numpy, tifffile, skimage, basicpy, imagecodecs, matplotlib" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing dependencies - first run takes 2-5 minutes; downloads basicpy/jaxlib CPU wheels...
    call "%CONDA_EXE%" run --no-capture-output -n %ENV_NAME% python -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] pip upgrade failed.
        pause
        exit /b 1
    )

    call "%CONDA_EXE%" run --no-capture-output -n %ENV_NAME% python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Check network or requirements.txt.
        echo Manual retry: "%CONDA_EXE%" activate %ENV_NAME% ^&^& pip install -r requirements.txt
        pause
        exit /b 1
    )

    echo [SETUP] Done.
) else (
    echo [INFO] All dependencies present.
)

REM ========== 3. Launch GUI ==========
echo [RUN] python run.py ...
call "%CONDA_EXE%" run --no-capture-output -n %ENV_NAME% python run.py
set EXITCODE=%errorlevel%

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] Program exited with code %EXITCODE%.
    pause
)

endlocal
exit /b %EXITCODE%
