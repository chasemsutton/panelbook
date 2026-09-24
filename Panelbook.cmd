@echo off
cd /d "%~dp0"
if exist "Panelbook.exe" (
  "Panelbook.exe" %*
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 server.py %*
  ) else (
    python server.py %*
  )
)
if errorlevel 1 pause
