@echo off
cd /d "%~dp0"
if exist "Panelbook.exe" if not exist "program\Panelbook.exe" (
  for %%F in (panelbook.html app.js styles.css update-portable.ps1 Panelbook.exe) do if not exist "%%F" goto launch
  if not exist "program" mkdir "program"
  for %%F in (panelbook.html app.js styles.css update-portable.ps1 Panelbook.exe) do (
    move /Y "%%F" "program\%%F" >nul
    if errorlevel 1 goto rollback
  )
)
goto launch
:rollback
for %%F in (panelbook.html app.js styles.css update-portable.ps1 Panelbook.exe) do if exist "program\%%F" move /Y "program\%%F" "%%F" >nul
:launch
if exist "program\Panelbook.exe" (
  "program\Panelbook.exe" %*
) else if exist "Panelbook.exe" (
  "Panelbook.exe" %*
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 program\server.py %*
  ) else (
    python program\server.py %*
  )
)
if errorlevel 1 pause
