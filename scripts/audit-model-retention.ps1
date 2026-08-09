param([string]$OutputPath = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$modelRoot = Join-Path $root "backend/models"
$productionName = "epvo-sbert-finetuned-40k"

if (-not (Test-Path -LiteralPath $modelRoot)) {
    throw "Model directory not found: $modelRoot"
}

$entries = foreach ($directory in Get-ChildItem -LiteralPath $modelRoot -Directory) {
    $bytes = (Get-ChildItem -LiteralPath $directory.FullName -Recurse -File | Measure-Object Length -Sum).Sum
    $action = if ($directory.Name -eq $productionName) {
        "keep-and-publish"
    } elseif ($directory.Name -like "*-checkpoints") {
        "archive-after-manifest"
    } elseif ($directory.Name -like "*smoke*") {
        "remove-after-verified-archive"
    } elseif ($directory.Name -eq "paraphrase-multilingual-mpnet-base-v2") {
        "archive-or-redownload-from-pinned-upstream"
    } else {
        "review-experiment-metrics-before-removal"
    }
    [pscustomobject]@{
        name = $directory.Name
        size_bytes = [int64]$bytes
        size_gb = [math]::Round($bytes / 1GB, 3)
        action = $action
    }
}

$report = [pscustomobject]@{
    generated_at = [DateTime]::UtcNow.ToString("o")
    production_model = $productionName
    total_size_gb = [math]::Round(($entries | Measure-Object size_bytes -Sum).Sum / 1GB, 3)
    entries = @($entries | Sort-Object size_bytes -Descending)
}

$json = $report | ConvertTo-Json -Depth 5
if ($OutputPath) {
    $resolved = if ([IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $root $OutputPath }
    $directory = Split-Path -Parent $resolved
    if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
    Set-Content -LiteralPath $resolved -Encoding utf8 -Value $json
    Write-Host "Retention report written to $resolved" -ForegroundColor Green
} else {
    $json
}
