@echo off
setlocal
cd /d "%~dp0"
if not defined PANELBOOK_MINIMIZED (
  set "PANELBOOK_MINIMIZED=1"
  start "" /min "%ComSpec%" /d /c ""%~f0" %*"
  exit /b
)
set "PANELBOOK_MINIMIZED="
title Panelbook
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
