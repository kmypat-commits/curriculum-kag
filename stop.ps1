$ErrorActionPreference = "Stop"
$pidFile = Join-Path $PSScriptRoot ".runtime\pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No launcher process file found. Services may already be stopped."
    exit 0
}

$saved = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($name in @("frontend", "backend")) {
    $processId = $saved.$name
    if (-not $processId) { continue }

    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process) { continue }

    # The launcher writes this PID immediately after Start-Process. Uvicorn's
    # command line does not contain its working directory, so checking for the
    # repository path incorrectly leaves the backend running forever. Limit
    # the trusted PID file to the runtimes this project actually launches.
    if ($process.ProcessName -in @("python", "pythonw", "node")) {
        Stop-Process -Id $processId -Force
        Write-Host "Stopped $name."
    }
    else {
        Write-Warning "Skipped PID ${processId}: it no longer belongs to this project."
    }
}

Remove-Item $pidFile -Force
Write-Host "Curriculum-KAG is stopped."
