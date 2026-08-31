[CmdletBinding()]
param(
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argsList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($NoStart) { $argsList += '-NoStart' }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argsList
    exit 0
}

$runtimeDir = Join-Path $env:LOCALAPPDATA 'Docker\run'
$runtimeNames = @(
    'dockerEthernetVfkit',
    'dockerInference',
    'sailor-ingest.sock',
    'userAnalyticsOtlpHttp.sock'
)

Get-Process -Name 'Docker Desktop','com.docker.backend','com.docker.service' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
wsl.exe --shutdown 2>$null

$services = @('hns', 'vmcompute')
$running = @()
foreach ($name in $services) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq 'Running') {
        Stop-Service -Name $name -Force
        $running += $name
    }
}

foreach ($name in $runtimeNames) {
    $path = Join-Path $runtimeDir $name
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

foreach ($name in $running) {
    Start-Service -Name $name
}

if (-not $NoStart) {
    $desktop = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
    if (Test-Path -LiteralPath $desktop) {
        Start-Process -FilePath $desktop
    }
}

$remaining = $runtimeNames | Where-Object { Test-Path -LiteralPath (Join-Path $runtimeDir $_) }
if ($remaining) {
    throw "Docker runtime cleanup incomplete: $($remaining -join ', ')"
}
Write-Host 'Docker runtime cleanup completed. VHDX and Docker data were not modified.'
