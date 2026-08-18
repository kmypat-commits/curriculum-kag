param(
    [Parameter(Mandatory = $true)]
    [string]$Manifest,
    [switch]$FinalizeExistingResult,
    [string]$Container = "curriculum-kag-postgres-shadow",
    [string]$User = "curriculum_user"
)

$ErrorActionPreference = "Stop"
$manifestPath = [IO.Path]::GetFullPath($Manifest)
$metadata = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$dumpPath = Join-Path (Split-Path $manifestPath -Parent) $metadata.dump_file
if (-not (Test-Path -LiteralPath $dumpPath)) {
    throw "Backup dump not found: $dumpPath"
}
$actualHash = (Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne [string]$metadata.sha256) {
    throw "Backup checksum mismatch."
}
$resultPath = [IO.Path]::ChangeExtension($manifestPath, ".restore.json")

if ($FinalizeExistingResult) {
    if (-not (Test-Path -LiteralPath $resultPath)) {
        throw "Restore result not found: $resultPath"
    }
    $existingResult = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $existingResult.passed -or -not $existingResult.sha256_verified -or $existingResult.mismatches.Count -ne 0) {
        throw "Existing restore result is not successful."
    }
    $metadata.restore_verified = $true
    $metadata | Add-Member -NotePropertyName restore_verified_at -NotePropertyValue $existingResult.verified_at -Force
    $metadata | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Write-Host "Existing isolated restore result finalized." -ForegroundColor Green
    exit 0
}

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
$verificationDatabase = "curriculum_kag_restore_verify_$PID"
$containerDump = "/tmp/$([IO.Path]::GetFileName($dumpPath))"
$passed = $false
try {
    Invoke-Docker @("cp", $dumpPath, "${Container}:${containerDump}") | Out-Null
    Invoke-Docker @(
        "exec", $Container, "psql",
        "-U", $User, "-d", "postgres",
        "-v", "ON_ERROR_STOP=1",
        "-c", "DROP DATABASE IF EXISTS $verificationDatabase WITH (FORCE);"
    ) | Out-Null
    Invoke-Docker @(
        "exec", $Container, "psql",
        "-U", $User, "-d", "postgres",
        "-v", "ON_ERROR_STOP=1",
        "-c", "CREATE DATABASE $verificationDatabase OWNER $User;"
    ) | Out-Null
    Write-Host "Restoring backup into isolated database $verificationDatabase..." -ForegroundColor Cyan
    Invoke-Docker @(
        "exec", $Container, "pg_restore",
        "-U", $User, "-d", $verificationDatabase,
        "--no-owner", "--no-privileges", "--exit-on-error",
        $containerDump
    ) | Out-Null

    $actualCounts = [ordered]@{}
    $mismatches = @()
    foreach ($property in $metadata.critical_table_counts.PSObject.Properties) {
        $table = $property.Name
        $expected = [long]$property.Value
        $actual = (
            Invoke-Docker @(
                "exec", $Container, "psql",
                "-U", $User, "-d", $verificationDatabase,
                "-Atc", "SELECT count(*) FROM $table;"
            ) | Out-String
        ).Trim()
        $actualCounts[$table] = [long]$actual
        if ([long]$actual -ne $expected) {
            $mismatches += "${table}: expected=${expected}, actual=${actual}"
        }
    }
    $passed = $mismatches.Count -eq 0
    $result = [ordered]@{
        verified_at = (Get-Date).ToUniversalTime().ToString("o")
        passed = $passed
        source_manifest = [IO.Path]::GetFileName($manifestPath)
        sha256_verified = $true
        isolated_restore_database = $verificationDatabase
        expected_counts = $metadata.critical_table_counts
        actual_counts = $actualCounts
        mismatches = $mismatches
    }
    # PowerShell 5's ``-Encoding UTF8`` writes a BOM.  Keep machine-readable
    # restore evidence consumable by Python, CI and external tooling without
    # a special ``utf-8-sig`` decoder.
    [IO.File]::WriteAllText(
        $resultPath,
        ($result | ConvertTo-Json -Depth 6),
        [Text.UTF8Encoding]::new($false)
    )
    if (-not $passed) {
        throw "Restore verification failed: $($mismatches -join '; ')"
    }
    $metadata.restore_verified = $true
    $metadata | Add-Member -NotePropertyName restore_verified_at -NotePropertyValue $result.verified_at -Force
    [IO.File]::WriteAllText(
        $manifestPath,
        ($metadata | ConvertTo-Json -Depth 6),
        [Text.UTF8Encoding]::new($false)
    )
    Write-Host "Isolated restore verification passed." -ForegroundColor Green
    Write-Host "Result: $resultPath"
}
finally {
    try {
        & $docker exec $Container psql -U $User -d postgres -c "DROP DATABASE IF EXISTS $verificationDatabase WITH (FORCE);" 2>$null | Out-Null
    }
    catch { }
    try {
        & $docker exec $Container rm -f $containerDump 2>$null
    }
    catch { }
}

if (-not $passed) { exit 1 }
