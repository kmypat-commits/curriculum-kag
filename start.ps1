param(
    [switch]$NoBrowser,
    [switch]$Rebuild,
    [ValidateSet("auto", "sqlite", "postgres-shadow", "postgres")]
    [string]$Database = "auto"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runtime = Join-Path $root ".runtime"
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$runtimeDist = Join-Path $runtime "dist"
$pidFile = Join-Path $runtime "pids.json"
$cpuThreads = if ($env:CURRICULUM_CPU_THREADS) { $env:CURRICULUM_CPU_THREADS } else { "4" }
foreach ($threadVariable in @("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")) {
    if (-not [Environment]::GetEnvironmentVariable($threadVariable, "Process")) {
        [Environment]::SetEnvironmentVariable($threadVariable, $cpuThreads, "Process")
    }
}

# Some desktop launchers inject both `Path` and `PATH`. PowerShell's
# Start-Process rejects that duplicate environment key, so normalize it once.
$pathMixed = [Environment]::GetEnvironmentVariable("Path", "Process")
$pathUpper = [Environment]::GetEnvironmentVariable("PATH", "Process")
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable(
    "Path",
    (($pathMixed, $pathUpper | Where-Object { $_ }) -join ";"),
    "Process"
)

function Test-Endpoint([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Wait-Endpoint([string]$Name, [string]$Url, [int]$Seconds = 120) {
    Write-Host "Waiting for $Name..."
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint $Url) {
            Write-Host "$Name is ready."
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not start in $Seconds seconds. Check logs in .runtime."
}

function Get-LatestSourceTime {
    $files = @(
        Get-ChildItem (Join-Path $frontendDir "src") -File -Recurse -ErrorAction SilentlyContinue
        Get-Item (Join-Path $frontendDir "package.json") -ErrorAction SilentlyContinue
        Get-Item (Join-Path $frontendDir "package-lock.json") -ErrorAction SilentlyContinue
        Get-Item (Join-Path $frontendDir "vite.config.js") -ErrorAction SilentlyContinue
        Get-Item (Join-Path $frontendDir "index.html") -ErrorAction SilentlyContinue
    )
    return ($files | Measure-Object LastWriteTimeUtc -Maximum).Maximum
}

function Build-FrontendIfNeeded {
    $index = Join-Path $runtimeDist "index.html"
    $needsBuild = $Rebuild -or -not (Test-Path $index)
    if (-not $needsBuild) {
        $needsBuild = (Get-LatestSourceTime) -gt (Get-Item $index).LastWriteTimeUtc
    }
    if (-not $needsBuild) {
        Write-Host "Frontend build is up to date."
        return
    }

    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    $codexNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    Push-Location $frontendDir
    try {
        if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
            if (-not $npm) {
                throw "Node.js/npm is required to install frontend dependencies: https://nodejs.org/"
            }
            Write-Host "Installing frontend dependencies..."
            & $npm.Source install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
        }
        Write-Host "Building frontend..."
        if ($npm) {
            & $npm.Source run build
        }
        elseif (Test-Path $codexNode) {
            $esbuildInstaller = Join-Path $frontendDir "node_modules\esbuild\install.js"
            if (Test-Path $esbuildInstaller) { & $codexNode $esbuildInstaller }
            & $codexNode (Join-Path $frontendDir "node_modules\vite\bin\vite.js") build
        }
        else {
            throw "Node.js/npm is required to build the frontend: https://nodejs.org/"
        }
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    }
    finally {
        Pop-Location
    }

    New-Item -ItemType Directory -Path $runtimeDist -Force | Out-Null
    Copy-Item (Join-Path $frontendDir "dist\*") $runtimeDist -Recurse -Force
}

New-Item -ItemType Directory -Path $runtime -Force | Out-Null

function Test-PythonRuntime([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    try {
        & $Path -c "import fastapi, uvicorn, sqlalchemy, pydantic_settings, numpy, pandas, openpyxl" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$existingSitePackages = Join-Path $backendDir "venv\Lib\site-packages"
$pythonCandidates = @(
    $bundledPython,
    (Join-Path $backendDir "venv\Scripts\python.exe")
)
$previousPythonPath = $env:PYTHONPATH
if (Test-Path $existingSitePackages) {
    # A moved/removed system Python can leave a broken venv launcher while its
    # installed packages are still valid. The bundled Python is the same ABI
    # and can safely reuse those local packages.
    $env:PYTHONPATH = $existingSitePackages
}
$python = $pythonCandidates | Where-Object { Test-PythonRuntime $_ } | Select-Object -First 1

if (-not $python) {
    $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        throw "Python 3.11+ is required: https://www.python.org/downloads/"
    }

    $venvDir = Join-Path $backendDir "venv"
    Write-Host "Preparing the local Python environment (first launch only)..."
    & $systemPython.Source -m venv --clear $venvDir
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }

    $python = Join-Path $venvDir "Scripts\python.exe"
    & $python -m pip install --disable-pip-version-check -r (Join-Path $backendDir "requirements-local.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install backend dependencies." }
}

Build-FrontendIfNeeded

# Keep the one-click local launch usable when the optional PostgreSQL service is
# not running. Environment variables override backend/.env for the child process.
$sqlitePath = (Join-Path $backendDir "curriculum_kag.db").Replace('\', '/')
if ($Database -eq "sqlite") {
    $env:DATABASE_URL = "sqlite:///$sqlitePath"
    Write-Host "Using SQLite database." -ForegroundColor Cyan
}
elseif ($Database -eq "postgres-shadow") {
    $env:DATABASE_URL = "postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow"
    Write-Host "Using shadow PostgreSQL database on localhost:5433." -ForegroundColor Cyan
}
elseif ($Database -eq "postgres") {
    # Local primary PostgreSQL cutover uses the verified migrated database.
    # Keep postgres-shadow as a backward-compatible alias during transition.
    $env:DATABASE_URL = "postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow"
    Write-Host "Using PostgreSQL primary database on localhost:5433." -ForegroundColor Cyan
}
$configuredDatabaseUrl = $env:DATABASE_URL
if (-not $configuredDatabaseUrl) {
    $envFiles = @(
        (Join-Path $backendDir ".env"),
        (Join-Path $root ".env")
    )
    foreach ($envFile in $envFiles) {
        if ($configuredDatabaseUrl) { break }
        if (Test-Path $envFile) {
            $databaseLine = Get-Content $envFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
            if ($databaseLine) { $configuredDatabaseUrl = $databaseLine.Substring("DATABASE_URL=".Length) }
        }
    }
}
if ($configuredDatabaseUrl -match '^postgresql') {
    $postgresHost = "localhost"
    $postgresPort = 5432
    if ($configuredDatabaseUrl -match '@([^/:]+)(?::(\d+))?/') {
        $postgresHost = $Matches[1]
        if ($Matches[2]) { $postgresPort = [int]$Matches[2] }
    }
    if (-not (Test-NetConnection -ComputerName $postgresHost -Port $postgresPort -InformationLevel Quiet -WarningAction SilentlyContinue)) {
        if ($Database -in @("postgres", "postgres-shadow")) {
            throw "PostgreSQL ${postgresHost}:${postgresPort} is unavailable. Start Docker/PostgreSQL or use -Database sqlite."
        }
        $env:DATABASE_URL = "sqlite:///$sqlitePath"
        Write-Host "PostgreSQL ${postgresHost}:${postgresPort} is unavailable; using the local SQLite database." -ForegroundColor Yellow
    }
}

$pids = @{}
if (-not (Test-Endpoint "http://127.0.0.1:8000/health")) {
    Write-Host "Starting backend..."
    $backend = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "backend.out.log") -RedirectStandardError (Join-Path $runtime "backend.err.log")
    try { $backend.PriorityClass = "BelowNormal" } catch { }
    $pids.backend = $backend.Id
}
else {
    Write-Host "Backend is already running."
}

Wait-Endpoint "backend" "http://127.0.0.1:8000/health"

if (-not (Test-Endpoint "http://127.0.0.1:3001/api/health")) {
    Write-Host "Starting frontend..."
    $frontend = Start-Process -FilePath $python -ArgumentList (Join-Path $root "frontend_server.py") -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "frontend.out.log") -RedirectStandardError (Join-Path $runtime "frontend.err.log")
    $pids.frontend = $frontend.Id
}
else {
    Write-Host "Frontend is already running."
}

Wait-Endpoint "frontend" "http://127.0.0.1:3001/api/health"

if ($pids.Count -gt 0) {
    $pids | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8
}

Write-Host ""
Write-Host "Curriculum-KAG is ready: http://localhost:3001/" -ForegroundColor Green
Write-Host "Login: admin@curriculum-kag.local / admin123"
Write-Host "Use stop.bat to stop services started by this launcher."

if (-not $NoBrowser) {
    Start-Process "http://localhost:3001/"
}
