param(
    [string]$BackendUrl = "http://127.0.0.1:8000",
    [string]$FrontendUrl = "http://127.0.0.1:3001/",
    [switch]$CheckDocker,
    [int]$ProjectVersionId = 0,
    [string]$BackupDir = "",
    [ValidateRange(1, 8760)]
    [int]$MaxAgeHours = 26,
    [switch]$VerifyChecksum,
    [switch]$RequirePlannerSample,
    [switch]$CheckPlannerObservability,
    [ValidateRange(0, 1000000)]
    [int]$MaxFailedOrTimedOut = 0,
    [ValidateRange(0, 1000000)]
    [int]$MaxActiveLeases = 0
)

$ErrorActionPreference = "Continue"
$failures = [System.Collections.Generic.List[string]]::new()
$scriptRoot = $PSScriptRoot

function Invoke-Monitor([string]$Name, [string]$Script, [string[]]$Arguments) {
    & (Join-Path $scriptRoot $Script) @Arguments
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("$Name (exit $LASTEXITCODE)")
    }
}

$healthArgs = @('-BackendUrl', "$($BackendUrl.TrimEnd('/'))/health", '-FrontendUrl', $FrontendUrl)
if ($CheckDocker) { $healthArgs += '-CheckDocker' }
Invoke-Monitor 'health' 'monitor-health.ps1' $healthArgs

if ($ProjectVersionId -gt 0) {
    $performanceArgs = @('-ProjectVersionId', "$ProjectVersionId", '-ApiBaseUrl', $BackendUrl)
    if ($RequirePlannerSample) { $performanceArgs += '-RequireSample' }
    Invoke-Monitor 'planner performance' 'monitor-planner-performance.ps1' $performanceArgs
}

if ($CheckPlannerObservability) {
    $headers = @{}
    $monitorToken = [Environment]::GetEnvironmentVariable('CURRICULUM_PLANNER_MONITOR_TOKEN')
    if ([string]::IsNullOrWhiteSpace($monitorToken)) {
        $failures.Add('planner observability (CURRICULUM_PLANNER_MONITOR_TOKEN is missing)')
    } else {
        $headers.Authorization = "Bearer $monitorToken"
        try {
            $summary = Invoke-RestMethod -Uri "$($BackendUrl.TrimEnd('/'))/planner/observability/summary" -Headers $headers -TimeoutSec 15
            $failedBuilds = [int]$summary.failed_or_timed_out
            $activeLeases = [int]$summary.active_leases
            $sampleSize = [int]$summary.telemetry_sample_size
            $p95 = $summary.duration_ms.p95
            if ($RequirePlannerSample -and $sampleSize -lt 1) {
                $failures.Add('planner observability (no telemetry samples are available)')
            }
            if ($failedBuilds -gt $MaxFailedOrTimedOut) {
                $failures.Add("planner observability (failed/timed out: $failedBuilds > $MaxFailedOrTimedOut)")
            }
            if ($activeLeases -gt $MaxActiveLeases) {
                $failures.Add("planner observability (active leases: $activeLeases > $MaxActiveLeases)")
            }
            if ($sampleSize -gt 0 -and $summary.p95_within_budget -eq $false) {
                $failures.Add("planner observability (p95 budget exceeded: $p95 ms)")
            }
            $p95Display = if ($null -eq $p95) { '-' } else { $p95 }
            Write-Host ("Planner observability: failed/timed out={0}, active leases={1}, samples={2}, p95={3} ms." -f $failedBuilds, $activeLeases, $sampleSize, $p95Display)
        } catch {
            $failures.Add("planner observability (endpoint unavailable: $($_.Exception.Message))")
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($BackupDir)) {
    $backupArgs = @('-BackupDir', $BackupDir, '-MaxAgeHours', "$MaxAgeHours")
    if ($VerifyChecksum) { $backupArgs += '-VerifyChecksum' }
    Invoke-Monitor 'backup freshness' 'monitor-backup-age.ps1' $backupArgs
}

if ($failures.Count) {
    Write-Error ("Staging observability gate failed: " + ($failures -join '; '))
    exit 1
}
Write-Host ("Staging observability gate passed ({0})." -f (Get-Date -Format o)) -ForegroundColor Green
exit 0
