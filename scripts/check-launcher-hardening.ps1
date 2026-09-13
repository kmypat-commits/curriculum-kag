$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$start = Get-Content -Raw (Join-Path $root 'start.ps1')
$repair = Get-Content -Raw (Join-Path $PSScriptRoot 'repair-docker-runtime.ps1')
$bat = Get-Content -Raw (Join-Path $root 'start.bat')

if ($bat -notmatch 'DOCKER_DESKTOP_BIN') {
    throw 'start.bat must expose the Docker Desktop CLI fallback path.'
}
foreach ($name in @('start.ps1', 'repair-docker-runtime.ps1')) {
    $source = if ($name -eq 'start.ps1') { $start } else { $repair }
    if ($source -match 'Start-Process[^\r\n]*-Wait') {
        throw "$name contains an unbounded Start-Process -Wait."
    }
    if ($source -notmatch 'WaitForExit\(\s*\d+\s*\)') {
        throw "$name has no bounded process wait."
    }
    if ($source -match '(?i)(Remove-Item|Move-Item)[^\r\n]*\.vhdx') {
        throw "$name must never mutate a Docker VHDX path."
    }
}

if ($repair -notmatch 'fsutil\.exe[\s\S]*reparsepoint[\s\S]*delete') {
    throw 'repair-docker-runtime.ps1 must handle Windows Error-1920 reparse points explicitly.'
}
$orphanMarker = $start.IndexOf('orphaned runtime listeners were found')
$desktopMarker = $start.IndexOf('$desktopRunning = Get-Process')
$wslMarker = $start.IndexOf('# Check WSL only after stale runtime cleanup.')
if ($orphanMarker -lt 0 -or $desktopMarker -lt 0 -or $wslMarker -lt 0 -or $orphanMarker -le $desktopMarker -or $orphanMarker -ge $wslMarker) {
    throw 'start.ps1 must repair runtime before startup only when Docker is stopped and orphaned listeners are present.'
}
if ($start -notmatch "Invoke-DockerRuntimeRepair 'Docker Engine did not start on the first attempt\.'") {
    throw 'start.ps1 must retain exactly one repair-and-retry path after a real Docker Engine startup failure.'
}
if ($start -match 'Stale Docker runtime sockets detected' -or $start -match 'foreach \(\$socket in \$runtimeSockets\)') {
    throw 'start.ps1 must not treat normal Docker listener reparse points as stale before startup.'
}
if ($start -notmatch "'-NoStart'") {
    throw 'start.ps1 must invoke the dedicated repair in no-start mode before its single retry.'
}
if ($start -match 'repairArgs[^\r\n]*-Verb\s+RunAs' -or $repair -match '-Verb\s+RunAs') {
    throw 'Docker runtime repair must stay in the interactive user token; it must not wait on UAC.'
}
if ($repair -match "sc\.exe', 'stop'" -or $repair -match '(?i)(Start|Stop)-Service[^\r\n]*(hns|vmcompute)') {
    throw 'Docker runtime repair must not stop or start global HNS/VM services.'
}

Write-Host 'Launcher hardening gate passed.'
