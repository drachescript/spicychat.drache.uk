@echo off
setlocal
cd /d "%~dp0\.."
if not exist "assets\data\bots.json" (
  echo assets\data\bots.json not found. Nothing deleted.
  pause
  exit /b 1
)
for %%F in ("assets\bots.json" "assets\bot-stats.json" "assets\bot-history.json") do (
  if exist %%F (
    echo Removing legacy %%F
    del /q %%F
  )
)
echo Done. The site now reads assets\data\ only.
pause
