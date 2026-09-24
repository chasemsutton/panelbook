param(
  [Parameter(Mandatory=$true)][string]$AppFolder,
  [Parameter(Mandatory=$true)][int]$ServerPid,
  [Parameter(Mandatory=$true)][string]$DownloadUrl,
  [Parameter(Mandatory=$true)][string]$ExpectedSha256,
  [Parameter(Mandatory=$true)][string]$ExpectedVersion,
  [Parameter(Mandatory=$true)][string]$HostName,
  [Parameter(Mandatory=$true)][int]$Port,
  [Parameter(Mandatory=$true)][string]$DataDir,
  [switch]$SecureCookies
)

$ErrorActionPreference = 'Stop'
$app = (Resolve-Path -LiteralPath $AppFolder).Path
$program = Join-Path $app 'program'
$exe = Join-Path $program 'Panelbook.exe'
$work = Join-Path ([System.IO.Path]::GetTempPath()) ('panelbook-update-' + [guid]::NewGuid().ToString('N'))
$files = @('Panelbook.cmd', 'README.md', 'program\Panelbook.exe', 'program\panelbook.html', 'program\app.js', 'program\styles.css', 'program\update-portable.ps1')
$zip = Join-Path $work 'release.zip'
$staging = Join-Path $work 'staging'
$backup = Join-Path $work 'backup'
$log = Join-Path $DataDir 'updater.log'
$copied = New-Object System.Collections.Generic.List[string]
$stopped = $false
$newProcess = $null
$keepWork = $false
$startupOut = Join-Path $work 'startup.stdout.log'
$startupErr = Join-Path $work 'startup.stderr.log'
$statusUrl = 'http://{0}:{1}/api/status' -f $(if ($HostName -match ':') { "[$HostName]" } else { $HostName }), $Port

function Write-UpdateLog([string]$message) {
  Add-Content -LiteralPath $log -Value ('{0} {1}' -f (Get-Date -Format o), $message)
}

function Start-Panelbook {
  if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Panelbook.exe is missing from $program." }
  $arguments = @('--host', $HostName, '--port', [string]$Port, '--data-dir', ('"' + $DataDir + '"'), '--no-browser')
  if ($SecureCookies) { $arguments += '--secure-cookies' }
  Start-Process -FilePath $exe -WorkingDirectory $program -ArgumentList $arguments -PassThru `
    -RedirectStandardOutput $startupOut -RedirectStandardError $startupErr
}

function Write-StartupOutput {
  foreach ($path in @($startupOut, $startupErr)) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
      foreach ($line in @(Get-Content -LiteralPath $path -Tail 30 -ErrorAction SilentlyContinue)) {
        Write-UpdateLog ("{0}: {1}" -f (Split-Path -Leaf $path), $line)
      }
    }
  }
}

function Copy-WithRetry([string]$source, [string]$destination) {
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
      Copy-Item -LiteralPath $source -Destination $destination -Force -ErrorAction Stop
      return
    } catch {
      if ($attempt -eq 59) { throw }
      Start-Sleep -Milliseconds 500
    }
  }
}

try {
  New-Item -ItemType Directory -Path $work, $staging, $backup, $DataDir -Force | Out-Null
  Write-UpdateLog "Downloading $ExpectedVersion."
  Invoke-WebRequest -Uri $DownloadUrl -OutFile $zip -UseBasicParsing
  $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
  if ($actual -ine $ExpectedSha256) { throw 'The downloaded release failed its SHA-256 check.' }
  Expand-Archive -LiteralPath $zip -DestinationPath $staging
  foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $staging $name) -PathType Leaf)) {
      throw "The release is missing $name."
    }
  }
  try { Wait-Process -Id $ServerPid -Timeout 60 -ErrorAction Stop } catch {
    if (Get-Process -Id $ServerPid -ErrorAction SilentlyContinue) { throw 'Panelbook did not close for the update.' }
  }
  $portReleased = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
      $listener = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2
      Start-Sleep -Milliseconds 500
    } catch [System.Net.WebException] {
      $portReleased = $true
      break
    }
  }
  if (-not $portReleased) {
    throw "Another Panelbook server (version $($listener.version)) is still listening on port $Port. Close it before updating."
  }
  $stopped = $true
  foreach ($name in $files) {
    $target = Join-Path $app $name
    $targetParent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
    if (Test-Path -LiteralPath $target) {
      $backupPath = Join-Path $backup $name
      New-Item -ItemType Directory -Path (Split-Path -Parent $backupPath) -Force | Out-Null
      Copy-Item -LiteralPath $target -Destination $backupPath -Force
    }
    $copied.Add($name)
    Copy-WithRetry (Join-Path $staging $name) $target
  }
  Write-UpdateLog 'Files copied; starting Panelbook.'
  $ready = $false
  for ($launch = 1; $launch -le 3 -and -not $ready; $launch++) {
    $newProcess = Start-Panelbook
    Write-UpdateLog "Started process $($newProcess.Id) (attempt $launch)."
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
      Start-Sleep -Milliseconds 500
      try {
        $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2
        if ($status.version -eq $ExpectedVersion.TrimStart('v')) { $ready = $true; break }
      } catch { }
      if ($newProcess.HasExited) {
        Write-UpdateLog "Panelbook exited during startup with code $($newProcess.ExitCode)."
        Write-StartupOutput
        break
      }
    }
    if (-not $ready -and -not $newProcess.HasExited) {
      throw 'The updated Panelbook did not respond at its previous address.'
    }
    if (-not $ready -and $launch -lt 3) { Start-Sleep -Seconds (2 * $launch) }
  }
  if (-not $ready) {
    try {
      $status = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2
      if ($status.version -eq $ExpectedVersion.TrimStart('v')) { $ready = $true }
    } catch { }
  }
  if (-not $ready) { throw 'The updated Panelbook failed to start after three attempts. See the startup output above.' }
  Write-UpdateLog "Panelbook $ExpectedVersion is ready."
} catch {
  $failure = $_.Exception.Message
  try { Write-UpdateLog "Update failed: $failure" } catch { }
  try { Write-StartupOutput } catch { }
  if ($newProcess -and -not $newProcess.HasExited) {
    & taskkill.exe /PID $newProcess.Id /T /F 2>$null | Out-Null
    try { Wait-Process -Id $newProcess.Id -Timeout 10 -ErrorAction SilentlyContinue } catch { }
  }
  $restored = $true
  foreach ($name in $copied) {
    $original = Join-Path $backup $name
    $target = Join-Path $app $name
    try {
      if (Test-Path -LiteralPath $original) { Copy-WithRetry $original $target }
      else { Remove-Item -LiteralPath $target -Force -ErrorAction Stop }
    } catch {
      $restored = $false
      $keepWork = $true
      try { Write-UpdateLog "Could not restore ${name}: $($_.Exception.Message)" } catch { }
    }
  }
  if ($keepWork) {
    try { Write-UpdateLog "Recovery copies retained in $backup." } catch { }
  }
  if ($stopped -and $restored) {
    try {
      $oldProcess = Start-Panelbook
      $oldReady = $false
      for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($oldProcess.HasExited) { throw "Previous version exited during startup with code $($oldProcess.ExitCode)." }
        try {
          $null = Invoke-RestMethod -Uri $statusUrl -TimeoutSec 2
          $oldReady = $true
          break
        } catch { }
      }
      if (-not $oldReady) { throw 'Previous version did not respond after rollback.' }
      Write-UpdateLog 'Previous version restarted.'
    }
    catch {
      Write-UpdateLog "Could not restart the previous version: $($_.Exception.Message)"
      Write-StartupOutput
    }
  }
} finally {
  if (-not $keepWork) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}
