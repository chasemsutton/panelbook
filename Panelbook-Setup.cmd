@echo off
setlocal
set "PANELBOOK_UPDATER=%TEMP%\panelbook-updater-v0.1.4.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $path=Join-Path $env:TEMP 'panelbook-updater-v0.1.4.ps1'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/chasemsutton/panelbook/v0.1.4/update-panelbook.ps1' -OutFile $path; if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'c0a7ab01a17b983aad1ab6cefe344999286ed6c2e6fe1271fbf215e2d6df8b14') { throw 'The updater download failed its integrity check.' }"
if errorlevel 1 (
  echo Could not download the verified Panelbook updater.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%PANELBOOK_UPDATER%" -Setup
set "PANELBOOK_RESULT=%ERRORLEVEL%"
del /q "%PANELBOOK_UPDATER%" >nul 2>&1
if not "%PANELBOOK_RESULT%"=="0" pause
exit /b %PANELBOOK_RESULT%
