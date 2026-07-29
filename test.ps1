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
