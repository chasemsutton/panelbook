param(
  [Parameter(Mandatory=$true)][string]$AppFolder,
  [Parameter(Mandatory=$true)][ValidateSet('program','flat')][string]$Layout,
  [Parameter(Mandatory=$true)][int]$ServerPid,
  [Parameter(Mandatory=$true)][string]$DownloadUrl,
  [Parameter(Mandatory=$true)][string]$ExpectedSha256
)

$ErrorActionPreference = 'Stop'
$app = (Resolve-Path -LiteralPath $AppFolder).Path
$work = Join-Path ([System.IO.Path]::GetTempPath()) ('panelbook-update-' + [guid]::NewGuid().ToString('N'))
$files = if ($Layout -eq 'program') {
  @('Panelbook.cmd', 'README.md', 'program\Panelbook.exe', 'program\panelbook.html', 'program\app.js', 'program\styles.css', 'program\update-portable.ps1')
} else {
  @('Panelbook.exe', 'Panelbook.cmd', 'panelbook.html', 'app.js', 'styles.css', 'update-portable.ps1', 'README.md')
}
$zip = Join-Path $work 'release.zip'
$staging = Join-Path $work 'staging'
$backup = Join-Path $work 'backup'

try {
  New-Item -ItemType Directory -Path $work, $staging, $backup | Out-Null
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
  $copied = New-Object System.Collections.Generic.List[string]
  try {
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
      Copy-Item -LiteralPath (Join-Path $staging $name) -Destination $target -Force
    }
    Start-Process -FilePath (Join-Path $app 'Panelbook.cmd') -WorkingDirectory $app -WindowStyle Hidden
  } catch {
    foreach ($name in $copied) {
      $original = Join-Path $backup $name
      $target = Join-Path $app $name
      if (Test-Path -LiteralPath $original) { Copy-Item -LiteralPath $original -Destination $target -Force }
      else { Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue }
    }
    throw
  }
} catch {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show("Panelbook update failed: $($_.Exception.Message)", 'Panelbook update') | Out-Null
} finally {
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
