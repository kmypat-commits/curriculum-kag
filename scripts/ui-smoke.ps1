param(
    [string]$BaseUrl = "http://localhost:3001",
    [int]$TimeoutSec = 5,
    [switch]$CheckApi,
    [string]$ApiBaseUrl = "http://localhost:8000"
)
$ErrorActionPreference = "Stop"
$routes = @('/', '/login', '/repository', '/projects/new', '/versions', '/projects/13', '/projects/13/plan', '/projects/13/coverage', '/projects/13/epvo', '/projects/13/graph')
$failed = @()
try {
    Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/') -TimeoutSec $TimeoutSec | Out-Null
} catch {
    throw "UI smoke unavailable: frontend is not reachable at $BaseUrl (timeout ${TimeoutSec}s). Start the frontend and retry."
}
foreach ($route in $routes) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + $route) -TimeoutSec $TimeoutSec
        if ($response.StatusCode -ne 200 -or $response.Content -notmatch '<meta charset="UTF-8"') { $failed += $route }
    } catch { $failed += "$route ($($_.Exception.Message))" }
}
$source = Get-Content .\frontend\src\contexts\LanguageContext.jsx -Raw
foreach ($marker in @('domains:', 'education_area:', 'Subject areas', 'ru', 'kk', 'en')) {
    if ($source -notmatch [regex]::Escape($marker)) { $failed += "language:$marker" }
}
if ($CheckApi) {
    try {
        $openapi = Invoke-RestMethod -Uri ($ApiBaseUrl.TrimEnd('/') + '/openapi.json') -TimeoutSec $TimeoutSec
        $paths = @($openapi.paths.PSObject.Properties.Name)
        foreach ($requiredPath in @('/planner/version/{project_version_id}/graph', '/planner/version/{project_version_id}/semester-insight')) {
            if ($requiredPath -notin $paths) { $failed += "api:$requiredPath" }
        }
    } catch {
        $failed += "api:$ApiBaseUrl/openapi.json ($($_.Exception.Message))"
    }
}
if ($failed.Count) { throw "UI smoke failed: $($failed -join ', ')" }
$apiStatus = if ($CheckApi) { "; graph/semester API paths present" } else { "" }
Write-Host "UI smoke passed: $($routes.Count) routes; RU/KK/EN markers present$apiStatus." -ForegroundColor Green
