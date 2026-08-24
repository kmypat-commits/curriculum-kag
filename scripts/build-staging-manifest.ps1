param(
    [string]$Output = ".runtime/staging-manifest.json"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $root
try {
    $status = @(git status --porcelain)
    $tracked = @(git ls-files)
    $files = foreach ($relative in $tracked) {
        $path = Join-Path $root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $path
        [ordered]@{
            path = $relative.Replace("\", "/")
            bytes = (Get-Item -LiteralPath $path).Length
            sha256 = $hash.Hash.ToLowerInvariant()
        }
    }
    $payload = [ordered]@{
        schema_version = 1
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        git = [ordered]@{
            commit = (git rev-parse HEAD).Trim()
            branch = (git branch --show-current).Trim()
            dirty = ($status.Count -gt 0)
        }
        release_policy = [ordered]@{
            database = "PostgreSQL backup and restore verification required"
            migrations = "alembic upgrade head; check_alembic_state.py"
            models = "distributed separately; never copied into the public Git tree"
            epvo_dataset = "distributed separately with checksum and legal review"
        }
        tracked_file_count = $files.Count
        files = $files
    }
    $target = Join-Path $root $Output
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $target -Encoding UTF8
    Write-Output (ConvertTo-Json ([ordered]@{
        output = $target
        commit = $payload.git.commit
        dirty = $payload.git.dirty
        tracked_file_count = $payload.tracked_file_count
    }) -Compress)
}
finally {
    Pop-Location
}
