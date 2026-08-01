$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    git config core.hooksPath .githooks
    Write-Host "Git hooks enabled from .githooks" -ForegroundColor Green
}
finally {
    Pop-Location
}
