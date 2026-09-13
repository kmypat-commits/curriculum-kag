param(
    [Parameter(Mandatory = $true)]
    [int]$ProjectVersionId,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    # Prefer the environment variable so the token is not exposed in the
    # command line/process list. BearerToken remains for compatibility.
    [string]$BearerToken = "",
    [ValidateRange(1, 86400)]
    [int]$TimeoutSec = 15,
    [switch]$RequireSample
)

$ErrorActionPreference = "Stop"
$headers = @{}
$monitorToken = $BearerToken
if ([string]::IsNullOrWhiteSpace($monitorToken)) {
    $monitorToken = [Environment]::GetEnvironmentVariable('CURRICULUM_PLANNER_MONITOR_TOKEN')
}
if (-not [string]::IsNullOrWhiteSpace($monitorToken)) {
    $headers.Authorization = "Bearer $monitorToken"
}
$uri = "{0}/planner/{1}/performance" -f $ApiBaseUrl.TrimEnd('/'), $ProjectVersionId
try {
    $payload = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec $TimeoutSec
}
catch {
    Write-Error ("Planner performance endpoint unavailable: {0}" -f $_.Exception.Message)
    exit 2
}

$sampleSize = [int]($payload.sample_size | ForEach-Object { $_ })
$p95 = $payload.duration_ms.p95
$budget = [int]$payload.p95_budget_ms
if ($RequireSample -and $sampleSize -lt 1) {
    Write-Error "No planner telemetry samples are available for project version $ProjectVersionId."
    exit 1
}
if ($null -eq $p95 -or $null -eq $payload.p95_within_budget) {
    Write-Error "Planner performance payload has no usable p95 result."
    exit 1
}
if (-not [bool]$payload.p95_within_budget) {
    Write-Error ("Planner p95 budget exceeded: {0} ms > {1} ms (samples: {2})." -f $p95, $budget, $sampleSize)
    exit 1
}
Write-Host ("Planner p95 within budget: {0} ms <= {1} ms (samples: {2})." -f $p95, $budget, $sampleSize) -ForegroundColor Green
exit 0
