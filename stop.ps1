$ErrorActionPreference = "Stop"
$pidFile = Join-Path $PSScriptRoot ".runtime\pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No launcher process file found. Services may already be stopped."
    exit 0
}

$saved = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($name in @("frontend", "backend", "plannerWorker")) {
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

# A launcher stop intentionally interrupts any build. Persist cancellation so
# the next start cannot inherit a false `running` lease and block new users.
$python = Join-Path $PSScriptRoot "backend\venv\Scripts\python.exe"
$recovery = Join-Path $PSScriptRoot "backend\scripts\recover_interrupted_builds.py"
if ((Test-Path $python) -and (Test-Path $recovery)) {
    & $python $recovery 2>$null
}

Remove-Item $pidFile -Force
Write-Host "Curriculum-KAG is stopped."
