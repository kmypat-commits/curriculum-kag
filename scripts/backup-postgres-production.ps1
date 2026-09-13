param(
    [string]$OutputDir = ".\backups\postgres-production",
    [string]$ComposeFile = ".\docker-compose.production.yml",
    [string]$EnvFile = ".\.env.production",
    [ValidateRange(30, 86400)]
    [int]$TimeoutSec = 1800
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-DotEnvValue([string]$Path, [string]$Name) {
    $line = Get-Content -LiteralPath $Path -ErrorAction Stop |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -First 1
    if (-not $line) { throw "Required variable $Name is missing from $Path." }
    $value = ($line -replace "^\s*$([regex]::Escape($Name))\s*=\s*", "").Trim()
    if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Required variable $Name is empty in $Path." }
    return $value
}

function Find-DockerCli {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Docker CLI not found."
}

$envPath = [IO.Path]::GetFullPath((Join-Path $root $EnvFile))
$composePath = [IO.Path]::GetFullPath((Join-Path $root $ComposeFile))
if (-not (Test-Path -LiteralPath $envPath)) { throw "Production env file not found: $envPath. Copy .env.production.example and fill real values." }
if (-not (Test-Path -LiteralPath $composePath)) { throw "Compose file not found: $composePath" }
$postgresUser = Get-DotEnvValue $envPath "POSTGRES_USER"
$postgresDb = Get-DotEnvValue $envPath "POSTGRES_DB"
$docker = Find-DockerCli
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $OutputDir))
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$target = Join-Path $outputPath "curriculum_kag_$stamp.dump"
$stderr = Join-Path $env:TEMP "curriculum-kag-pg-dump-$stamp.err"
try {
    # pg_dump -Fc is binary.  Native stdout must go directly to a file;
    # PowerShell's object/string pipeline can corrupt arbitrary bytes.
    $process = Start-Process -FilePath $docker -ArgumentList @(
        "compose", "--env-file", $envPath, "-f", $composePath, "exec", "-T", "postgres",
        "pg_dump", "-Fc", "--no-owner", "--no-acl", "-U", $postgresUser, "-d", $postgresDb
    ) -RedirectStandardOutput $target -RedirectStandardError $stderr -NoNewWindow -PassThru
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        try { $process.Kill() } catch { }
        $detail = if (Test-Path -LiteralPath $stderr) { (Get-Content -LiteralPath $stderr -Raw).Trim() } else { "" }
        throw "pg_dump timed out after $TimeoutSec seconds. Docker/Compose did not finish. $detail"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) {
        $detail = if (Test-Path -LiteralPath $stderr) { (Get-Content -LiteralPath $stderr -Raw).Trim() } else { "" }
        throw "pg_dump failed (exit $($process.ExitCode)): $detail"
    }
}
finally {
    Remove-Item -LiteralPath $stderr -Force -ErrorAction SilentlyContinue
}
if (-not (Test-Path $target) -or (Get-Item $target).Length -lt 1024) { throw "Backup is missing or unexpectedly small: $target" }
Write-Host "Backup created: $target"
