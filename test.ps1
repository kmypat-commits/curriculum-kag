$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$sitePackages = Join-Path $backend "venv\Lib\site-packages"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path $bundledPython) {
    $python = $bundledPython
}
else {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Python 3.11+ is required to run the tests."
    }
    $python = $command.Source
}

$paths = @($backend)
if (Test-Path $sitePackages) {
    $paths += $sitePackages
}
$env:PYTHONPATH = ($paths -join [IO.Path]::PathSeparator)
# Keep pytest's temporary directories on the project volume.  A previous
# elevated run can leave the user profile temp root or .pytest_cache owned by
# another account, which otherwise turns a valid test run into PermissionError.
# Never reuse a temp root: acceptance may run under a different Windows
# token than the interactive shell, leaving the previous root ACL-locked.
$pytestRuntime = Join-Path $root (".runtime\pytest-" + $PID)
New-Item -ItemType Directory -Path $pytestRuntime -Force | Out-Null
$env:TEMP = $pytestRuntime
$env:TMP = $pytestRuntime
$env:PYTEST_DEBUG_TEMPROOT = $pytestRuntime

Push-Location $backend
try {
    & $python (Join-Path $backend "check_text_encoding.py")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $python (Join-Path $backend "run_tests.py")
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
