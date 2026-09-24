param(
    [switch]$Setup,
    [string]$Uri
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms

$repo = 'chasemsutton/panelbook'
$files = @('styles.css', 'app.js', 'README.md', 'Panelbook-Setup.cmd', 'update-panelbook.ps1', 'release.json', 'panelbook.html')
$scratch = $null

function Show-Result([string]$message, [bool]$failed = $false) {
    $icon = if ($failed) { [System.Windows.Forms.MessageBoxIcon]::Error } else { [System.Windows.Forms.MessageBoxIcon]::Information }
    [void][System.Windows.Forms.MessageBox]::Show($message, 'Panelbook updater', [System.Windows.Forms.MessageBoxButtons]::OK, $icon)
}

function Get-VersionParts([string]$tag) {
    if ($tag -notmatch '^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$') { return $null }
    return @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [string]$Matches[4])
}

function Compare-Tags([string]$left, [string]$right) {
    $a = Get-VersionParts $left
    $b = Get-VersionParts $right
    if ($null -eq $a -or $null -eq $b) { return 0 }
    for ($i = 0; $i -lt 3; $i++) {
        if ($a[$i] -gt $b[$i]) { return 1 }
        if ($a[$i] -lt $b[$i]) { return -1 }
    }
    if (!$a[3] -and $b[3]) { return 1 }
    if ($a[3] -and !$b[3]) { return -1 }
    return [Math]::Sign([string]::CompareOrdinal($a[3], $b[3]))
}

function Select-InstallFolder {
    $picker = New-Object System.Windows.Forms.FolderBrowserDialog
    $picker.Description = 'Choose the folder that contains your existing panelbook.html file.'
    $picker.ShowNewFolderButton = $false
    try {
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Setup canceled.' }
        return $picker.SelectedPath
    } finally {
        $picker.Dispose()
    }
}

try {
    $channel = 'stable'
    if (!$Setup) {
        $request = [regex]::Match($Uri, '^panelbook-update:(stable|beta)$')
        if (!$request.Success) { throw 'Invalid update request. Run Panelbook-Setup.cmd to set up the updater.' }
        $channel = $request.Groups[1].Value
    }
    $folder = if ($Setup) { Select-InstallFolder } else { Split-Path -Parent $PSCommandPath }
    if (!(Test-Path -LiteralPath (Join-Path $folder 'panelbook.html') -PathType Leaf)) { throw 'That folder does not contain panelbook.html. Choose your existing Panelbook folder.' }

    $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases?per_page=100" -Headers @{ Accept = 'application/vnd.github+json'; 'User-Agent' = 'Panelbook-Updater' }
    $latest = $null
    foreach ($release in $releases) {
        if ($release.draft -or ($channel -eq 'stable' -and $release.prerelease) -or $null -eq (Get-VersionParts $release.tag_name)) { continue }
        if ($null -eq $latest -or (Compare-Tags $release.tag_name $latest.tag_name) -gt 0) { $latest = $release }
    }
    if ($null -eq $latest) { throw "No $channel release is available." }

    $currentTag = 'v0.0.0'
    $currentManifest = Join-Path $folder 'release.json'
    if (Test-Path -LiteralPath $currentManifest) {
        try { $currentTag = (Get-Content -LiteralPath $currentManifest -Raw | ConvertFrom-Json).version } catch {}
    }
    if (!$Setup -and (Compare-Tags $latest.tag_name $currentTag) -le 0) {
        Show-Result "Panelbook is already up to date ($currentTag)."
        return
    }

    $scratch = Join-Path ([IO.Path]::GetTempPath()) ('panelbook-update-' + [guid]::NewGuid().ToString('N'))
    $download = Join-Path $scratch 'download'
    $backup = Join-Path $scratch 'backup'
    [void][IO.Directory]::CreateDirectory($download)
    [void][IO.Directory]::CreateDirectory($backup)
    $baseUrl = "https://raw.githubusercontent.com/$repo/$($latest.tag_name)"
    Invoke-WebRequest -Uri "$baseUrl/release.json" -UseBasicParsing -OutFile (Join-Path $download 'release.json')
    $manifest = Get-Content -LiteralPath (Join-Path $download 'release.json') -Raw | ConvertFrom-Json
    if ($manifest.version -ne $latest.tag_name) { throw 'The release manifest has the wrong version.' }

    foreach ($name in $files | Where-Object { $_ -ne 'release.json' }) {
        $expected = $manifest.files.$name
        if ($expected -notmatch '^[a-f0-9]{64}$') { throw "The release manifest is missing a valid hash for $name." }
        $destination = Join-Path $download $name
        Invoke-WebRequest -Uri "$baseUrl/$name" -UseBasicParsing -OutFile $destination
        $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "$name failed the release integrity check." }
    }

    foreach ($name in $files) {
        $target = Join-Path $folder $name
        if (Test-Path -LiteralPath $target) { Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name) }
    }
    $written = New-Object 'System.Collections.Generic.List[string]'
    try {
        foreach ($name in $files) {
            $written.Add($name)
            Copy-Item -LiteralPath (Join-Path $download $name) -Destination (Join-Path $folder $name) -Force
        }
    } catch {
        $writeError = $_.Exception.Message
        $restored = $true
        for ($i = $written.Count - 1; $i -ge 0; $i--) {
            $name = $written[$i]
            try {
                $old = Join-Path $backup $name
                $target = Join-Path $folder $name
                if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $target -Force }
                elseif (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target }
            } catch { $restored = $false }
        }
        if ($restored) { throw "Update failed: $writeError Previous app files were restored." }
        throw "Update failed: $writeError Some app files could not be restored. Your browser data was not changed."
    }

    if ($Setup) {
        $protocol = 'HKCU:\Software\Classes\panelbook-update'
        $commandKey = Join-Path $protocol 'shell\open\command'
        New-Item -Path $protocol -Force | Out-Null
        New-Item -Path (Join-Path $protocol 'shell') -Force | Out-Null
        New-Item -Path (Join-Path $protocol 'shell\open') -Force | Out-Null
        New-Item -Path $commandKey -Force | Out-Null
        Set-Item -Path $protocol -Value 'URL:Panelbook Update Protocol'
        New-ItemProperty -Path $protocol -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
        $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $installedScript = Join-Path $folder 'update-panelbook.ps1'
        $command = '"{0}" -NoProfile -ExecutionPolicy Bypass -STA -File "{1}" -Uri "%1"' -f $powershell, $installedScript
        Set-Item -Path $commandKey -Value $command
        Show-Result "Panelbook $($latest.tag_name) is installed. Open the same panelbook.html file in the same browser to keep your saved panels. Future updates can start from the app."
    } else {
        Show-Result "Panelbook $($latest.tag_name) is installed. Reload the same panelbook.html file in your browser."
    }
} catch {
    Show-Result $_.Exception.Message $true
    exit 1
} finally {
    if ($scratch -and [IO.Directory]::Exists($scratch) -and [IO.Path]::GetFileName($scratch) -match '^panelbook-update-[a-f0-9]{32}$') {
        try { [IO.Directory]::Delete($scratch, $true) } catch {}
    }
}
