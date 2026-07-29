param(
    [string]$OutputDirectory = "",
    [string]$ExistingDump = "",
    [string]$Container = "curriculum-kag-postgres-shadow",
    [string]$Database = "curriculum_kag_shadow",
    [string]$User = "curriculum_user"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $root "backups\postgres"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

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

$docker = Find-DockerCli
$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
if ($ExistingDump) {
    $dumpPath = [IO.Path]::GetFullPath($ExistingDump)
    if (-not (Test-Path -LiteralPath $dumpPath)) {
        throw "Existing dump not found: $dumpPath"
    }
    $baseName = [IO.Path]::GetFileNameWithoutExtension($dumpPath)
}
else {
    $baseName = "curriculum_kag_postgres_$stamp"
    $dumpPath = Join-Path $OutputDirectory "$baseName.dump"
}
$manifestPath = Join-Path $OutputDirectory "$baseName.manifest.json"
$containerDump = "/tmp/$baseName.dump"
$criticalTables = @(
    "users", "projects", "project_versions", "learning_outcomes",
    "courses", "course_localizations", "plans", "plan_items",
    "raw_epvo_programs", "raw_epvo_disciplines",
    "raw_epvo_learning_outcomes", "raw_epvo_expert_checks",
    "epvo_disciplines_normalized", "epvo_discipline_lo_links"
)

try {
    $status = (Invoke-Docker @("inspect", "--format", "{{.State.Status}}", $Container) | Out-String).Trim()
    if ($status -ne "running") {
        throw "PostgreSQL container '$Container' is not running."
    }
    if ($ExistingDump) {
        Write-Host "Finalizing existing PostgreSQL backup..." -ForegroundColor Cyan
        $hostBytes = (Get-Item -LiteralPath $dumpPath).Length
        $containerBytes = (
            Invoke-Docker @(
                "exec", $Container, "sh", "-lc",
                "if [ -f '$containerDump' ]; then stat -c %s '$containerDump'; else echo 0; fi"
            ) | Out-String
        ).Trim()
        if ([long]$containerBytes -ne [long]$hostBytes) {
            Invoke-Docker @("cp", $dumpPath, "${Container}:${containerDump}") | Out-Null
        }
    }
    else {
        Write-Host "Creating PostgreSQL backup..." -ForegroundColor Cyan
        Invoke-Docker @(
            "exec", $Container, "pg_dump",
            "-U", $User, "-d", $Database,
            "-Fc", "-Z", "6", "-f", $containerDump
        ) | Out-Null
    }
    Invoke-Docker @("exec", $Container, "pg_restore", "--list", $containerDump) | Out-Null
    if (-not $ExistingDump) {
        Invoke-Docker @("cp", "${Container}:${containerDump}", $dumpPath) | Out-Null
    }

    $counts = [ordered]@{}
    $countSql = ($criticalTables | ForEach-Object {
        "SELECT '$_' AS table_name, count(*)::text AS row_count FROM $_"
    }) -join " UNION ALL "
    $countLines = Invoke-Docker @(
        "exec", $Container, "psql",
        "-U", $User, "-d", $Database,
        "-At", "-F", "|", "-c", "$countSql;"
    )
    foreach ($line in $countLines) {
        $parts = ([string]$line).Split("|", 2)
        if ($parts.Count -eq 2) {
            $counts[$parts[0]] = [long]$parts[1]
        }
    }
    foreach ($table in $criticalTables) {
        if (-not $counts.Contains($table)) {
            throw "Could not capture row count for table '$table'."
        }
    }
    $databaseBytes = (
        Invoke-Docker @(
            "exec", $Container, "psql",
            "-U", $User, "-d", $Database,
            "-Atc", "SELECT pg_database_size(current_database());"
        ) | Out-String
    ).Trim()
    $postgresVersion = (
        Invoke-Docker @(
            "exec", $Container, "psql",
            "-U", $User, "-d", $Database,
            "-Atc", "SHOW server_version;"
        ) | Out-String
    ).Trim()
    $dump = Get-Item -LiteralPath $dumpPath
    $manifest = [ordered]@{
        schema_version = 1
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        database = $Database
        container = $Container
        postgres_version = $postgresVersion
        database_bytes = [long]$databaseBytes
        dump_file = $dump.Name
        dump_bytes = [long]$dump.Length
        sha256 = (Get-FileHash -LiteralPath $dump.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        critical_table_counts = $counts
        restore_verified = $false
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Write-Host "Backup created and pg_restore catalogue validated." -ForegroundColor Green
    Write-Host "Dump: $dumpPath"
    Write-Host "Manifest: $manifestPath"
}
finally {
    try {
        & $docker exec $Container rm -f $containerDump 2>$null
    }
    catch { }
}
