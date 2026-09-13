param(
    [string]$BackendUrl = "http://127.0.0.1:8000/health",
    [string]$FrontendUrl = "http://127.0.0.1:3001/",
    [switch]$CheckDocker
)
$ErrorActionPreference = "Stop"
$checks = @(
    @{ Name = "backend"; Url = $BackendUrl },
    @{ Name = "frontend"; Url = $FrontendUrl }
)
$failed = @()

function Test-DockerEngineBounded {
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $docker) {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
        if (Test-Path -LiteralPath $candidate) { $docker = @{ Source = $candidate } }
    }
    if (-not $docker) { return 'docker CLI not found' }
    $process = $null
    try {
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $docker.Source
        $info.Arguments = 'version --format "{{.Server.Version}}"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $info
        [void]$process.Start()
        if (-not $process.WaitForExit(5000)) {
            try { $process.Kill($true) } catch {}
            return 'Docker engine probe timed out'
        }
        if ($process.ExitCode -ne 0) {
            $errorText = $process.StandardError.ReadToEnd().Trim()
            return if ($errorText) { "Docker engine unavailable: $errorText" } else { 'Docker engine unavailable' }
        }
        return $null
    }
    catch { return "Docker engine probe failed: $($_.Exception.Message)" }
    finally { if ($process) { $process.Dispose() } }
}

if ($CheckDocker) {
    $dockerError = Test-DockerEngineBounded
    if ($dockerError) { $failed += "docker: $dockerError" }
}

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
