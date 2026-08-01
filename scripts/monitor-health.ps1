param(
    [string]$BackendUrl = "http://127.0.0.1:8000/health",
    [string]$FrontendUrl = "http://127.0.0.1:3001/"
)
$ErrorActionPreference = "Stop"
$checks = @(
    @{ Name = "backend"; Url = $BackendUrl },
    @{ Name = "frontend"; Url = $FrontendUrl }
)
$failed = @()
foreach ($check in $checks) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $check.Url -TimeoutSec 15
        if ($response.StatusCode -ne 200) { $failed += "$($check.Name): HTTP $($response.StatusCode)" }
    } catch { $failed += "$($check.Name): $($_.Exception.Message)" }
}
try {
    $health = Invoke-RestMethod -Uri $BackendUrl -TimeoutSec 15
    if ($health.database -ne "postgresql" -or $health.database_status -ne "connected") { $failed += "postgresql: not connected" }
} catch { $failed += "postgresql: health payload unavailable" }
if ($failed.Count) { Write-Error ("Health check failed: " + ($failed -join "; ")); exit 1 }
Write-Host ("Healthy: backend, frontend, PostgreSQL ({0})" -f (Get-Date -Format o)) -ForegroundColor Green
