@echo off
setlocal
cd /d "%~dp0"

py -c "import bs4" >nul 2>&1
if errorlevel 1 (
  echo Installing beautifulsoup4...
  py -m pip install beautifulsoup4
  if errorlevel 1 (
    echo.
    echo Could not install beautifulsoup4.
    pause
    exit /b 1
  )
)

echo.
if "%~1"=="" (
  py extract-spicychat-bots.py
) else (
  py extract-spicychat-bots.py "%~1"
)

set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" pause
exit /b %ERR%
