param(
    [ValidateSet("postgresql", "sqlite", "any")]
    [string]$ExpectedDatabase = "postgresql"
)

$ErrorActionPreference = "Stop"

function Read-Health([string]$Name, [string]$Url) {
    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 15
    }
    catch {
        throw "${Name} health check failed: $($_.Exception.Message)"
    }
    if ($response.status -ne "healthy") {
        throw "${Name} returned status '$($response.status)'."
    }
    return $response
}

$backend = Read-Health "Backend" "http://127.0.0.1:8000/health"
if ($backend.database_status -ne "connected") {
    throw "Backend is running, but its database is not connected."
}
if ($ExpectedDatabase -ne "any" -and $backend.database -ne $ExpectedDatabase) {
    throw "Expected database '$ExpectedDatabase', but backend uses '$($backend.database)'."
}

$frontend = Read-Health "Frontend proxy" "http://127.0.0.1:3001/api/health"
if ($frontend.database -ne $backend.database) {
    throw "Frontend proxy and backend report different database modes."
}

Write-Host "Production smoke-test passed." -ForegroundColor Green
Write-Host "Backend: healthy; database: $($backend.database); connection: $($backend.database_status)"
Write-Host "Frontend proxy: healthy"
