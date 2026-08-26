param(
    [string]$OutputDir = ".\backups\postgres",
    [string]$Container = "curriculum-kag-postgres-shadow",
    [string]$Database = "curriculum_kag_shadow",
    [string]$User = "curriculum_user",
    [string]$ExistingDumpPath = ""
)

$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot

function Find-DockerCli {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    throw "Docker CLI not found."
}

function Invoke-Docker([string[]]$Arguments) {
    $result = & $docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed: docker $($Arguments -join ' ')"
    }
    return $result
}

function Get-Sha256([string]$Path) {
    # Windows PowerShell editions in lightweight launchers may not expose
    # Get-FileHash. Use the .NET implementation so backup verification is
    # available in both Windows PowerShell and PowerShell 7.
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $hasher.Dispose()
    }
}

$docker = Find-DockerCli
$outputPath = [IO.Path]::GetFullPath((Join-Path $taskRoot $OutputDir))
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$dumpName = "curriculum_kag_postgres_$stamp.dump"
$dumpPath = Join-Path $outputPath $dumpName
$containerDump = "/tmp/$dumpName"

if ($ExistingDumpPath) {
    $dumpPath = [IO.Path]::GetFullPath($ExistingDumpPath)
    $dumpName = Split-Path -Leaf $dumpPath
}
else {
    try {
        Invoke-Docker @("inspect", "--format", "{{.State.Running}}", $Container) | Out-Null
        Invoke-Docker @("exec", $Container, "pg_dump", "--format=custom", "--no-owner", "--no-acl", "-U", $User, "-d", $Database, "-f", $containerDump) | Out-Null
        Invoke-Docker @("cp", "${Container}:$containerDump", $dumpPath) | Out-Null
    }
    finally {
        try { & $docker exec $Container rm -f $containerDump 2>$null | Out-Null } catch { }
    }
}

if (-not (Test-Path -LiteralPath $dumpPath) -or (Get-Item -LiteralPath $dumpPath).Length -lt 1024) {
    throw "Backup is missing or unexpectedly small: $dumpPath"
}

$tables = @(
    "project_versions", "plans", "projects", "learning_outcomes", "users", "plan_items",
    "raw_epvo_programs", "courses", "course_localizations", "raw_epvo_expert_checks",
    "raw_epvo_disciplines", "epvo_disciplines_normalized", "raw_epvo_learning_outcomes",
    "epvo_discipline_lo_links"
)
$counts = [ordered]@{}
foreach ($table in $tables) {
    $value = (Invoke-Docker @("exec", $Container, "psql", "-U", $User, "-d", $Database, "-Atc", "SELECT count(*) FROM $table;") | Out-String).Trim()
    $counts[$table] = [long]$value
}
$databaseBytes = [long]((Invoke-Docker @("exec", $Container, "psql", "-U", $User, "-d", $Database, "-Atc", "SELECT pg_database_size(current_database());") | Out-String).Trim())
$postgresVersion = (Invoke-Docker @("exec", $Container, "psql", "-U", $User, "-d", $Database, "-Atc", "SELECT version();") | Out-String).Trim()
$manifestPath = [IO.Path]::ChangeExtension($dumpPath, ".manifest.json")
$manifest = [ordered]@{
    schema_version = 1
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    database = $Database
    container = $Container
    postgres_version = $postgresVersion
    database_bytes = $databaseBytes
    dump_file = $dumpName
    dump_bytes = (Get-Item -LiteralPath $dumpPath).Length
    sha256 = Get-Sha256 $dumpPath
    critical_table_counts = $counts
    restore_verified = $false
}
[IO.File]::WriteAllText(
    $manifestPath,
    ($manifest | ConvertTo-Json -Depth 6),
    [Text.UTF8Encoding]::new($false)
)
Write-Host "Backup created: $dumpPath" -ForegroundColor Green
Write-Host "Manifest: $manifestPath" -ForegroundColor Green
