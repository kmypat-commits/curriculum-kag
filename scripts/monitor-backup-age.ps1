param(
    [string]$BackupDir = ".\backups\postgres-production",
    [ValidateRange(1, 8760)]
    [int]$MaxAgeHours = 26,
    [switch]$VerifyChecksum
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$directory = if ([IO.Path]::IsPathRooted($BackupDir)) {
    [IO.Path]::GetFullPath($BackupDir)
} else {
    [IO.Path]::GetFullPath((Join-Path $root $BackupDir))
}
if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
    Write-Error "Backup directory does not exist: $directory"
    exit 2
}

$dump = Get-ChildItem -LiteralPath $directory -Filter "*.dump" -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $dump) {
    Write-Error "No PostgreSQL dump found in $directory"
    exit 1
}
if ($dump.Length -lt 1024) {
    Write-Error "Latest PostgreSQL dump is unexpectedly small: $($dump.FullName)"
    exit 1
}
$ageHours = ((Get-Date) - $dump.LastWriteTime).TotalHours
if ($ageHours -gt $MaxAgeHours) {
    Write-Error ("Latest PostgreSQL dump is too old: {0:N1} hours > {1} hours ({2})." -f $ageHours, $MaxAgeHours, $dump.FullName)
    exit 1
}

$manifest = [IO.Path]::ChangeExtension($dump.FullName, ".manifest.json")
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    Write-Error "Backup manifest is missing: $manifest"
    exit 1
}
if ($VerifyChecksum) {
    $payload = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    $actual = (Get-FileHash -LiteralPath $dump.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([string]$payload.sha256 -ne $actual) {
        Write-Error "Backup checksum mismatch: $($dump.FullName)"
        exit 1
    }
}
Write-Host ("Backup is fresh: {0:N1} hours old; manifest present ({1})." -f $ageHours, $manifest) -ForegroundColor Green
exit 0
