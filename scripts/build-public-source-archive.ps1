param(
    [string]$Version = "snapshot",
    [string]$OutputDirectory = "release"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Force -Path $output | Out-Null

& (Join-Path $PSScriptRoot "verify-public-release.ps1")

$archive = Join-Path $output "curriculum-kag-$Version.zip"
if (Test-Path -LiteralPath $archive) {
    throw "Archive already exists: $archive"
}

git -C $root archive --format=zip --prefix="curriculum-kag-$Version/" -o $archive HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$archive.sha256" -Encoding ascii -Value "$hash  $(Split-Path -Leaf $archive)"
Write-Host "Created $archive" -ForegroundColor Green
Write-Host "SHA-256 $hash" -ForegroundColor Green
