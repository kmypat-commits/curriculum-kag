param(
    [Parameter(Mandatory = $true)][int]$CohortProcessId,
    [Parameter(Mandatory = $true)][string]$CohortReport,
    [Parameter(Mandatory = $true)][string]$SourceDatabase,
    [Parameter(Mandatory = $true)][string]$TargetDatabaseUrl,
    [Parameter(Mandatory = $true)][string]$Manifest,
    [Parameter(Mandatory = $true)][string]$Output,
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'
Wait-Process -Id $CohortProcessId
$cohort = Get-Content -LiteralPath $CohortReport -Raw | ConvertFrom-Json
if ($cohort.status -ne 'passed') {
    $status = [string]$cohort.status
    throw "Cohort ended with status '$status'; migration acceptance was not started."
}

$arguments = @(
    'backend/scripts/accept_sqlite_postgres_migration.py',
    '--source', $SourceDatabase,
    '--target', $TargetDatabaseUrl,
    '--manifest', $Manifest,
    '--output', $Output
)
if ($Restore) { $arguments += '--restore' }
& (Join-Path $PSScriptRoot '..\backend\venv\Scripts\python.exe') @arguments
if ($LASTEXITCODE -ne 0) {
    throw "SQLite to PostgreSQL acceptance failed with exit code $LASTEXITCODE."
}
