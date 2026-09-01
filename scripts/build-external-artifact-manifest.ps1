param(
    [string]$ModelPath = "backend/models/epvo-sbert-finetuned-40k",
    [string]$DatabaseArtifact = "",
    [string]$Output = ".runtime/external-artifact-manifest.json"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    $entries = @()
    $model = Join-Path $root $ModelPath
    if (-not (Test-Path -LiteralPath $model -PathType Container)) {
        throw "Model directory not found: $model"
    }
    $modelFiles = @(Get-ChildItem -LiteralPath $model -Recurse -File)
    foreach ($file in $modelFiles) {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName
        $relative = $file.FullName.Substring($root.Length).TrimStart([char]'\', [char]'/')
        $entries += [ordered]@{
            kind = "model"
            path = $relative.Replace("\", "/")
            bytes = $file.Length
            sha256 = $hash.Hash.ToLowerInvariant()
        }
    }
    if ($DatabaseArtifact) {
        $database = Join-Path $root $DatabaseArtifact
        if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
            throw "Database artifact not found: $database"
        }
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $database
        $file = Get-Item -LiteralPath $database
        $relative = $file.FullName.Substring($root.Length).TrimStart([char]'\', [char]'/')
        $entries += [ordered]@{
            kind = "database"
            path = $relative.Replace("\", "/")
            bytes = $file.Length
            sha256 = $hash.Hash.ToLowerInvariant()
        }
    }
    $payload = [ordered]@{
        schema_version = 1
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = (git rev-parse HEAD).Trim()
        distribution = "external-only; never add these files to the public Git tree"
        artifacts = $entries
    }
    $target = Join-Path $root $Output
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $target -Encoding UTF8
    $totalBytes = [int64]0
    foreach ($entry in $entries) { $totalBytes += [int64]$entry.bytes }
    Write-Output (ConvertTo-Json ([ordered]@{
        output = $target
        artifact_count = $entries.Count
        total_bytes = $totalBytes
        commit = $payload.git_commit
    }) -Compress)
}
finally {
    Pop-Location
}
