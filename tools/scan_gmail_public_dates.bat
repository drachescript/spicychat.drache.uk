@echo off
setlocal EnableExtensions
title SpicyChat - Gmail Public Date Scanner
cd /d "%~dp0"

echo ============================================================
echo  SpicyChat - Gmail Public Date Scanner
echo ============================================================
echo.
echo Scans saved Gmail HTML / EML files for:
echo   "Your character is live"
echo.
echo It only auto-applies dates that fit safely between the
echo site's known non-public/public observations.
echo Existing confirmed public dates are never overwritten.
echo.

set "PYTHON_CMD="

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python 3 was not found.
    echo Install Python 3 or add it to PATH, then run this BAT again.
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% "%~dp0scan_gmail_public_dates.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Finished.
) else (
    echo Scanner finished with error %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
