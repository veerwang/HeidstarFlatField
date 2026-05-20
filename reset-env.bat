@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

REM One-shot: remove the heidstar_flat conda env, then re-run the main launcher.
REM Safe to run repeatedly. Delete this file after the first successful launch.

cd /d "%~dp0"

set ENV_NAME=heidstar_flat
set MINICONDA_DIR=%UserProfile%\Miniconda3

REM ---------- Locate conda ----------
set CONDA_EXE=
where conda >nul 2>&1
if not errorlevel 1 set CONDA_EXE=conda

if "%CONDA_EXE%"=="" (
    if exist "%MINICONDA_DIR%\Scripts\conda.exe" (
        set "CONDA_EXE=%MINICONDA_DIR%\Scripts\conda.exe"
    )
)

if "%CONDA_EXE%"=="" (
    echo [ERROR] conda not found in PATH or at %MINICONDA_DIR%.
    pause
    exit /b 1
)

echo [RESET] Removing conda env "%ENV_NAME%" via conda ...
call "%CONDA_EXE%" env remove -n %ENV_NAME% -y
REM Exit code ignored - env may or may not have existed.

REM Belt-and-suspenders: nuke the env folder in case conda left a partial install.
if exist "%MINICONDA_DIR%\envs\%ENV_NAME%" (
    echo [RESET] Force-removing leftover folder "%MINICONDA_DIR%\envs\%ENV_NAME%" ...
    rmdir /s /q "%MINICONDA_DIR%\envs\%ENV_NAME%"
)

echo.
echo [RESET] Re-running run-windows.bat ...
echo.
call "%~dp0run-windows.bat"

endlocal
exit /b %errorlevel%
