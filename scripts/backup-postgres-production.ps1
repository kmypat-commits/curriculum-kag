param(
    [string]$OutputDir = ".\backups\postgres-production",
    [string]$ComposeFile = ".\docker-compose.production.yml"
)
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$target = Join-Path $OutputDir "curriculum_kag_$stamp.dump"
docker compose -f $ComposeFile exec -T postgres pg_dump -Fc -U $env:POSTGRES_USER -d $env:POSTGRES_DB | Set-Content -Encoding Byte -Path $target
if (-not (Test-Path $target) -or (Get-Item $target).Length -lt 1024) { throw "Backup is missing or unexpectedly small: $target" }
Write-Host "Backup created: $target"
