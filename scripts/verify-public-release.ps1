$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$required = @(
    "README.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "CITATION.cff",
    "MODEL_CARD.md",
    "DATASET_CARD.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "PUBLICATION_CHECKLIST.md",
    "artifacts.public.json",
    "model-retention-policy.json"
)

foreach ($relative in $required) {
    $path = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required public-release file is missing: $relative"
    }
}

$tracked = @(git -C $root ls-files)
if ($LASTEXITCODE -ne 0) { throw "git ls-files failed" }

$forbiddenPatterns = @(
    '(^|/)\.env$',
    '(^|/)\.env\.(local|production|development|test)$',
    '\.(db|sqlite|db-wal|db-shm)$',
    '(^|/)(backups|\.runtime|node_modules|pgdata)/',
    '\.(safetensors|pt|pth|ckpt|onnx)$'
)

$violations = foreach ($file in $tracked) {
    foreach ($pattern in $forbiddenPatterns) {
        if ($file -match $pattern) { $file; break }
    }
}

if ($violations) {
    throw "Forbidden release artefacts are tracked:`n$($violations -join "`n")"
}

git -C $root diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check failed" }

Write-Host "Public release structure: OK" -ForegroundColor Green
Write-Host "Tracked files checked: $($tracked.Count)" -ForegroundColor Green
Write-Host "Note: dataset redistribution and artifact URLs still require approval." -ForegroundColor Yellow
