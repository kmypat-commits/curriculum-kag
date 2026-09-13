[CmdletBinding()]
param(
    [switch]$NoStart,
    [switch]$RepairWslService
)

$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Stop-WslServiceForDockerRuntime {
    if (-not $RepairWslService) { return $false }
    if (-not (Test-IsAdministrator)) {
        throw 'The -RepairWslService mode must be run from an elevated PowerShell window. It only restarts WslService and does not modify the Docker VHDX or container data.'
    }

    $service = Get-Service -Name 'WslService' -ErrorAction SilentlyContinue
    if ($null -eq $service) { return $false }
    $wasRunning = $service.Status -eq 'Running'
    if ($wasRunning) {
        Stop-Service -Name 'WslService' -Force -ErrorAction Stop
        Start-Sleep -Seconds 2
    }
    return $wasRunning
}

$runtimeDir = Join-Path $env:LOCALAPPDATA 'Docker\run'
$secretsRuntimeDir = Join-Path $env:LOCALAPPDATA 'docker-secrets-engine'
$runtimeNames = @(
    'dockerEthernetVfkit',
    'dockerInference',
    'sailor-ingest.sock',
    'userAnalyticsOtlpHttp.sock'
)

function Remove-EphemeralPathBounded([string]$Path) {
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $Path)) { return $true }

    # Windows may expose Docker listeners as reparse points that make `del`
    # block indefinitely.  Never let runtime cleanup hang the launcher.
    $del = Start-Process -FilePath "$env:ComSpec" -ArgumentList '/c', 'del', '/f', '/q', $Path -WindowStyle Hidden -PassThru
    if (-not $del.WaitForExit(5000)) {
        Stop-Process -Id $del.Id -Force -ErrorAction SilentlyContinue
    } elseif (-not (Test-Path -LiteralPath $Path)) {
        return $true
    }
    # Error 1920 means Windows still exposes the entry as a reparse point.
    # Removing that tag is scoped to this ephemeral socket, never its target.
    $reparse = Start-Process -FilePath "$env:SystemRoot\System32\fsutil.exe" -ArgumentList 'reparsepoint', 'delete', $Path -WindowStyle Hidden -PassThru
    if ($reparse.WaitForExit(5000)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    return -not (Test-Path -LiteralPath $Path)
}

function Move-EphemeralDirectoryBounded([string]$Source, [string]$Destination) {
    $move = Start-Process -FilePath "$env:ComSpec" -ArgumentList '/c', 'move', $Source, $Destination -WindowStyle Hidden -PassThru
    if (-not $move.WaitForExit(10000)) {
        Stop-Process -Id $move.Id -Force -ErrorAction SilentlyContinue
        return $false
    }
    return (Test-Path -LiteralPath $Destination) -and (-not (Test-Path -LiteralPath $Source))
}

function Get-RuntimeEntries([string]$Directory, [string[]]$Names) {
    # Broken Docker AF_UNIX listener reparse points can make Test-Path return
    # false (ERROR 1920) while the entry remains in the directory. Enumerate
    # the runtime namespace instead: it is the authoritative, bounded source.
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $Names -contains $_.Name }
    )
}

Get-Process -Name 'Docker Desktop','com.docker.backend','com.docker.service' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
$wslShutdown = Start-Process -FilePath 'wsl.exe' -ArgumentList '--shutdown' -WindowStyle Hidden -PassThru
if (-not $wslShutdown.WaitForExit(10000)) {
    Stop-Process -Id $wslShutdown.Id -Force -ErrorAction SilentlyContinue
    Write-Warning 'WSL shutdown did not finish within 10 seconds; continuing with runtime cleanup.'
}

# A malformed AF_UNIX reparse point can be held by WslService even after all
# Docker processes exit. This opt-in elevated repair releases that *runtime*
# handle before the directory is quarantined. It never touches the data VHDX.
$restartWslService = Stop-WslServiceForDockerRuntime

# A crashed Docker backend can leave AF_UNIX listener reparse points that
# reject all individual-path operations. `run` is exclusively ephemeral
# runtime state, so atomically replace the directory instead of relying on
# a growing collection of socket-specific fallbacks.
$runtimeEntries = Get-RuntimeEntries $runtimeDir $runtimeNames
if ($runtimeEntries.Count -gt 0) {
    $quarantine = Join-Path (Split-Path -Parent $runtimeDir) ('run.quarantine-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if (Move-EphemeralDirectoryBounded $runtimeDir $quarantine) {
        New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
        Write-Host "Quarantined stale Docker runtime directory: $quarantine" -ForegroundColor DarkGray
    } else {
        throw "Docker runtime directory is locked by Windows. Reboot once, then run start.bat again; VHDX and Docker data were not modified."
    }
}

# Secrets Engine uses a sibling directory (without the `Docker` component).
# Keep this separate from Docker's ephemeral run directory; both are runtime
# sockets and neither contains the WSL data disk.
$secretEngineSocket = Join-Path $secretsRuntimeDir 'engine.sock'
if (Test-Path -LiteralPath $secretEngineSocket) {
    [void](Remove-EphemeralPathBounded $secretEngineSocket)
}

# Restore the host service only after all broken runtime entries are gone.
if ($restartWslService) {
    Start-Service -Name 'WslService' -ErrorAction Stop
}
if (Test-Path -LiteralPath $secretEngineSocket) {
    $secretQuarantine = Join-Path (Split-Path -Parent $secretsRuntimeDir) ('docker-secrets-engine.quarantine-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if (Move-EphemeralDirectoryBounded $secretsRuntimeDir $secretQuarantine) {
        New-Item -ItemType Directory -Force -Path $secretsRuntimeDir | Out-Null
        Write-Host "Quarantined stale Docker secrets-engine directory: $secretQuarantine" -ForegroundColor DarkGray
    } else {
        throw "Docker secrets-engine directory is locked by Windows. Reboot once, then run start.bat again; VHDX and Docker data were not modified."
    }
}

$remaining = Get-RuntimeEntries $runtimeDir $runtimeNames
if ($remaining.Count -gt 0) {
    throw "Docker runtime cleanup incomplete: $($remaining.Name -join ', ')"
}
if (Test-Path -LiteralPath $secretEngineSocket) {
    throw "Docker secrets-engine cleanup incomplete: $secretEngineSocket"
}

if (-not $NoStart) {
    $desktop = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
    if (Test-Path -LiteralPath $desktop) {
        Start-Process -FilePath $desktop -WindowStyle Hidden
    }
}

Write-Host 'Docker runtime cleanup completed. VHDX and Docker data were not modified.'
