$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Never commit local credentials or oversized runtime artefacts.
$staged = git diff --cached --name-only --diff-filter=ACMR
foreach ($path in $staged) {
    if ($path -match '(^|/|\\)\.env($|\.)' -and $path -notmatch '\.example$') {
        throw "Refusing to commit environment file: $path"
    }
    $full = Join-Path $root $path
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $size = (Get-Item -LiteralPath $full).Length
        if ($size -gt 50MB) {
            throw "Refusing to commit file larger than 50 MB: $path"
        }
    }
}

$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $python) {
    & $python (Join-Path $root "backend\check_text_encoding.py")
    if ($LASTEXITCODE -ne 0) { throw "UTF-8 encoding check failed." }
}

git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Whitespace check failed." }
Write-Host "Pre-commit checks passed." -ForegroundColor Green
