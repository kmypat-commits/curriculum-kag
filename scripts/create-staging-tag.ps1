param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,
    [switch]$BrowserSmokeVerified
)

$ErrorActionPreference = "Stop"
if ($Tag -notmatch '^staging-\d{4}\.\d{2}\.\d{2}(?:-[0-9A-Za-z.-]+)?$') {
    throw "Tag must look like staging-YYYY.MM.DD[-suffix]."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    if (@(git status --porcelain).Count -ne 0) { throw "Refusing to tag a dirty worktree." }
    $manifestPath = Join-Path $root ".runtime/staging-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Staging manifest is missing; run build-staging-manifest.ps1." }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.git.dirty -ne $false) { throw "Manifest records a dirty worktree." }
    if (-not $BrowserSmokeVerified) {
        throw "Pass -BrowserSmokeVerified only after manually checking graph and RU/KK/EN in an authenticated browser session."
    }

    $restore = Get-ChildItem (Join-Path $root "backups/postgres/*.manifest.restore.json") -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $restore) { throw "No PostgreSQL restore manifest found." }
    $restorePayload = Get-Content $restore.FullName -Raw | ConvertFrom-Json
    if ($restorePayload.passed -ne $true -or $restorePayload.sha256_verified -ne $true) {
        throw "Latest PostgreSQL restore manifest is not verified."
    }

    $port = Get-NetTCPConnection -LocalPort 5433 -State Listen -ErrorAction SilentlyContinue
    if (-not $port) { throw "PostgreSQL is not listening on localhost:5433; run runtime gates before tagging." }
    $env:CURRICULUM_SKIP_PUBLIC_RELEASE = "1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ui-smoke.ps1 -TimeoutSec 5 -CheckApi
    if ($LASTEXITCODE -ne 0) { throw "UI smoke failed." }
    if (git tag --list $Tag) { throw "Tag already exists: $Tag" }
    git tag -a $Tag -m "Curriculum-KAG staging release $Tag"
    Write-Output "Created $Tag after manifest, restore, PostgreSQL and UI gates."
}
finally {
    Pop-Location
}
