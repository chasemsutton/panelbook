@echo off
cd /d "%~dp0"
if exist "program\Panelbook.exe" (
  "program\Panelbook.exe" %*
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 program\server.py %*
  ) else (
    python program\server.py %*
  )
)
if errorlevel 1 pause
