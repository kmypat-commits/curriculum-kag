param(
    [switch]$RequireVerifiedBackup,
    [switch]$IncludeFreshGeneration,
    [switch]$IncludeInterdisciplinaryGeneration
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runtime = Join-Path $root ".runtime"
$backend = Join-Path $root "backend"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$databaseUrl = "postgresql+psycopg2://curriculum_user:curriculum_pass@127.0.0.1:5433/curriculum_kag_shadow"
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

if (Test-Path $bundledPython) {
    $python = $bundledPython
}
else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python 3.11+ is required." }
    $python = $pythonCommand.Source
}
$sitePackages = Join-Path $backend "venv\Lib\site-packages"
$pythonPaths = @($backend)
if (Test-Path $sitePackages) { $pythonPaths += $sitePackages }
$env:PYTHONPATH = $pythonPaths -join [IO.Path]::PathSeparator
$env:DATABASE_URL = $databaseUrl

function Invoke-Checked([scriptblock]$Command, [string]$Name) {
    Write-Host "[$Name]" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

Invoke-Checked { powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "test.ps1") } "Backend tests"
Invoke-Checked { powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "smoke-test.ps1") -ExpectedDatabase postgresql } "PostgreSQL smoke test"
Invoke-Checked {
    & $python (Join-Path $backend "scripts\audit_control_programs_api.py") `
        --projects 13 14 15 16 17 19 `
        --output (Join-Path $runtime "plan-quality-acceptance.json")
} "Control programmes A/B/C audit"
Invoke-Checked {
    & $python (Join-Path $backend "scripts\audit_course_localizations.py") `
        --database-url $databaseUrl `
        --output (Join-Path $runtime "course-localization-acceptance.json")
} "RU/KK/EN localization audit"
if ($IncludeFreshGeneration) {
    Invoke-Checked {
        & $python (Join-Path $backend "scripts\audit_cross_level_generation.py") `
            --level bachelor `
            --output (Join-Path $runtime "fresh-bachelor-acceptance.json") `
            --variants A B C
    } "Fresh bachelor A/B/C generation"
    Invoke-Checked {
        & $python (Join-Path $backend "scripts\audit_cross_level_generation.py") `
            --level master `
            --output (Join-Path $runtime "fresh-master-acceptance.json") `
            --variants A B C
    } "Fresh master A/B/C generation"
    Invoke-Checked {
        & $python (Join-Path $backend "scripts\audit_cross_level_generation.py") `
            --level doctorate `
            --output (Join-Path $runtime "fresh-doctorate-acceptance.json") `
            --variants A B C
    } "Fresh doctorate A/B/C generation"
}
if ($IncludeInterdisciplinaryGeneration) {
    Invoke-Checked {
        & $python (Join-Path $backend "scripts\audit_cross_level_generation.py") `
            --level bachelor `
            --profile ict-medicine `
            --output (Join-Path $runtime "fresh-ict-medicine-acceptance.json") `
            --variants A B C
    } "Fresh interdisciplinary ICT + medicine A/B/C generation"
}
Invoke-Checked { & npm.cmd --prefix (Join-Path $root "frontend") run build } "Frontend production build"

if ($RequireVerifiedBackup) {
    $manifest = Get-ChildItem (Join-Path $root "backups\postgres\*.manifest.json") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $manifest) { throw "No PostgreSQL backup manifest found." }
    $backup = Get-Content -LiteralPath $manifest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $backup.restore_verified) {
        throw "Latest PostgreSQL backup has not passed isolated restore verification."
    }
    Write-Host "[Verified PostgreSQL backup] $($manifest.Name)" -ForegroundColor Cyan
}

Write-Host "Full production acceptance passed." -ForegroundColor Green
