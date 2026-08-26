param(
    [Parameter(Mandatory = $true)]
    [string]$Manifest,
    [Parameter(Mandatory = $true)]
    [string]$VerificationDatabase,
    [string]$Container = "curriculum-kag-postgres-shadow",
    [string]$User = "curriculum_user"
)

# Finalizes a restore which was intentionally allowed to continue after its
# interactive launcher stopped.  It never touches the working database.
$ErrorActionPreference = "Stop"
$manifestPath = [IO.Path]::GetFullPath($Manifest)
$metadata = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$resultPath = [IO.Path]::ChangeExtension($manifestPath, ".restore.json")
# The interactive verifier may finish while this detached helper is starting.
# Its successful report is authoritative; do not try to inspect a database it
# has already removed.
if ((Test-Path -LiteralPath $resultPath) -and ((Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json).passed)) {
    Write-Host "Restore was already verified by the interactive verifier."
    exit 0
}
$docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
if (-not (Test-Path $docker)) { throw "Docker CLI not found." }

function Invoke-Docker([string[]]$Arguments) {
    $result = & $docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed: docker $($Arguments -join ' ')" }
    return $result
}

while ($true) {
    $top = (Invoke-Docker @("top", $Container) | Out-String)
    if ($top -notmatch [regex]::Escape("-d $VerificationDatabase")) { break }
    Start-Sleep -Seconds 15
}

$actualCounts = [ordered]@{}
$mismatches = @()
foreach ($property in $metadata.critical_table_counts.PSObject.Properties) {
    $table = $property.Name
    $expected = [long]$property.Value
    $actual = (Invoke-Docker @(
        "exec", $Container, "psql", "-U", $User, "-d", $VerificationDatabase,
        "-Atc", "SELECT count(*) FROM $table;"
    ) | Out-String).Trim()
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
    isolated_restore_database = $VerificationDatabase
    expected_counts = $metadata.critical_table_counts
    actual_counts = $actualCounts
    mismatches = $mismatches
}
[IO.File]::WriteAllText($resultPath, ($result | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
if ($passed) {
    $metadata.restore_verified = $true
    $metadata | Add-Member -NotePropertyName restore_verified_at -NotePropertyValue $result.verified_at -Force
    [IO.File]::WriteAllText($manifestPath, ($metadata | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
}
Invoke-Docker @("exec", $Container, "psql", "-U", $User, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "DROP DATABASE IF EXISTS $VerificationDatabase WITH (FORCE);") | Out-Null
if (-not $passed) { throw "Restore verification failed: $($mismatches -join '; ')" }
Write-Host "Isolated restore verification passed." -ForegroundColor Green
