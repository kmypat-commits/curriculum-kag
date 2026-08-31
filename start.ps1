param(
    [switch]$NoBrowser,
    [switch]$Rebuild,
    [ValidateSet("auto", "sqlite", "postgres-shadow", "postgres")]
    # PostgreSQL is the primary data store. SQLite is an explicit rollback
    # mode only (`-Database sqlite`) and must never be selected silently.
    [string]$Database = "postgres"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runtime = Join-Path $root ".runtime"
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$runtimeDist = Join-Path $runtime "dist"
$pidFile = Join-Path $runtime "pids.json"

# Prevent concurrent launchers (duplicate services and Docker calls).
$launcherMutex = [Threading.Mutex]::new($false, "Global\CurriculumKAGLauncher")
try { if (-not $launcherMutex.WaitOne(0)) { throw "Another Curriculum-KAG launcher is already running." } }
catch [Threading.AbandonedMutexException] { }
Register-EngineEvent PowerShell.Exiting -Action { try { $launcherMutex.ReleaseMutex() } catch {} } | Out-Null
$cpuThreads = if ($env:CURRICULUM_CPU_THREADS) { $env:CURRICULUM_CPU_THREADS } else { "4" }
# Prevent an unavailable Docker engine from leaving the launcher waiting
# indefinitely. Users can override these values in the environment when a
# remote Docker endpoint legitimately needs more time.
if (-not $env:DOCKER_CLIENT_TIMEOUT) { $env:DOCKER_CLIENT_TIMEOUT = "10" }
if (-not $env:COMPOSE_HTTP_TIMEOUT) { $env:COMPOSE_HTTP_TIMEOUT = "30" }
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

function Get-EndpointJson([string]$Url) {
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMilliseconds = 1000) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync($HostName, $Port)
        return $connect.Wait($TimeoutMilliseconds) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-TcpPort([string]$HostName, [int]$Port, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort $HostName $Port 750) {
            return $true
        }
        Start-Sleep -Milliseconds 750
    }
    return $false
}

function Find-DockerCli {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\resources\bin\docker.exe"),
        "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            # Docker Desktop installs the CLI outside the default PATH on
            # Windows.  Make child `docker compose` calls use the same CLI.
            $bin = Split-Path -Parent $candidate
            if (-not (($env:Path -split ';') -contains $bin)) {
                $env:Path = "$bin;$env:Path"
            }
            return $candidate
        }
    }
    return $null
}

function Test-DockerEngine([string]$DockerCli, [int]$TimeoutMilliseconds = 5000) {
    # docker.exe may block while the Desktop daemon is wedged; invoking it
    # directly made the launcher appear frozen despite client timeouts.
    $process = $null
    try {
        $info = [System.Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $DockerCli
        $info.Arguments = 'version --format "{{.Server.Version}}"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [System.Diagnostics.Process]::new()
        $process.StartInfo = $info
        [void]$process.Start()
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            $process.Kill($true)
            return $false
        }
        return $process.ExitCode -eq 0
    }
    catch { return $false }
    finally { if ($process) { $process.Dispose() } }
}

function Start-DockerDesktopIfNeeded([string]$DockerCli) {
    if (Test-DockerEngine $DockerCli) { return $true }

    $desktopCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
        "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )
    $desktop = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $desktop) { return $false }

    # Remove only a stale inference socket after Desktop has fully exited.
    # Docker Desktop recreates it; deleting the data-root or WSL disk here
    # would be unsafe and is deliberately never attempted.
    $runtimeSocketNames = @(
        "dockerEthernetVfkit",
        "dockerInference",
        "sailor-ingest.sock",
        "userAnalyticsOtlpHttp.sock"
    )
    $runtimeSockets = $runtimeSocketNames |
        ForEach-Object { Join-Path $env:LOCALAPPDATA "Docker\run\$_" } |
        Where-Object { Test-Path -LiteralPath $_ }
    $desktopRunning = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if ($runtimeSockets) {
        # A stale socket can survive a crashed Desktop process and prevents
        # the Linux engine from starting. Recover the runtime state in-place;
        # never touch the WSL disk or Docker data root.
        if ($desktopRunning) {
            Write-Host "Recovering Docker Desktop runtime sockets..." -ForegroundColor Yellow
            Get-Process -Name "Docker Desktop", "com.docker.backend" -ErrorAction SilentlyContinue |
                Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            $desktopRunning = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
        }
        try {
            foreach ($socket in $runtimeSockets) {
                Remove-Item -LiteralPath $socket -Force -ErrorAction Stop
            }
            Write-Host "Removed stale Docker runtime sockets; Desktop will recreate them." -ForegroundColor DarkGray
        }
        catch {
            Write-Warning "Docker Desktop has stale runtime sockets under '$($env:LOCALAPPDATA)\Docker\run'. Reboot Windows once, then run start.bat again. No Docker data was changed."
            return $false
        }
    }

    # Avoid launching a second Desktop instance when the daemon is still
    # initializing (a common cause of duplicate backends and high CPU usage).
    if (-not $desktopRunning) {
        Write-Host "Starting Docker Desktop..." -ForegroundColor Cyan
        try {
            Start-Process -FilePath $desktop -WindowStyle Hidden -ErrorAction Stop | Out-Null
        }
        catch {
            Write-Host "Docker Desktop could not be started automatically; continuing with the available local database." -ForegroundColor Yellow
            return $false
        }
    }
    else {
        Write-Host "Docker Desktop is already running; waiting for its daemon..." -ForegroundColor DarkGray
    }
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerEngine $DockerCli) { return $true }
        Start-Sleep -Seconds 2
    }
    Write-Warning "Docker Desktop did not expose a working engine within 45 seconds. If it shows an 'unexpected error' about dockerInference, choose Quit (not Reset to factory defaults), then run start.bat again."
    return $false
}

function Warn-IfDockerRestoreMayExhaustSystemDisk {
    # Docker Desktop stores its WSL disk on C: by default. A PostgreSQL
    # restore temporarily needs roughly the database size again, even when
    # project data and dumps are stored on D:. Warn early instead of letting
    # Docker stall the machine during a recovery drill.
    $systemDrive = Get-PSDrive -Name C -ErrorAction SilentlyContinue
    if ($systemDrive -and $systemDrive.Free -lt 12GB) {
        $freeGb = [math]::Round($systemDrive.Free / 1GB, 1)
        Write-Host "Warning: only $freeGb GB is free on C:. PostgreSQL restore verification may require more space because Docker Desktop uses its WSL disk there. Free space or move Docker data to D: before a restore drill." -ForegroundColor Yellow
    }
}

function Start-PostgresShadowIfNeeded {
    if (Wait-TcpPort "localhost" 5433 2) { return $true }
    $composeFile = Join-Path $root "docker-compose.postgres-only.yml"
    if (-not (Test-Path $composeFile)) { return $false }
    $docker = Find-DockerCli
    if (-not $docker) { return $false }
    if (-not (Start-DockerDesktopIfNeeded $docker)) { return $false }
    Warn-IfDockerRestoreMayExhaustSystemDisk

    Write-Host "Starting local PostgreSQL shadow database..." -ForegroundColor Cyan
    Push-Location $root
    $proc = $null
    try {
        # Hard timeout avoids an apparently frozen launcher when Docker Desktop
        # is recovering its moved WSL data directory.
        $psi = [Diagnostics.ProcessStartInfo]::new()
        $psi.FileName = $docker
        $psi.Arguments = "compose -f `"$composeFile`" up -d"
        $psi.WorkingDirectory = $root
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [Diagnostics.Process]::new(); $proc.StartInfo = $psi
        [void]$proc.Start()
        if (-not $proc.WaitForExit(45000)) {
            try { $proc.Kill($true) } catch {}
            Write-Warning "Docker Compose did not respond within 45 seconds; startup was stopped without deleting data."
            return $false
        }
        if ($proc.ExitCode -ne 0) { return $false }
    }
    finally { if ($proc) { $proc.Dispose() }; Pop-Location }
    return (Wait-TcpPort "localhost" 5433 90)
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
if ($Database -in @("auto", "postgres", "postgres-shadow")) {
    Start-PostgresShadowIfNeeded | Out-Null
}
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
elseif (Test-NetConnection -ComputerName localhost -Port 5433 -InformationLevel Quiet -WarningAction SilentlyContinue) {
    # Prefer the verified local PostgreSQL migration when it is already
    # available. This avoids silently falling back to SQLite because an old
    # backend/.env still points at an unavailable localhost:5432 instance.
    $env:DATABASE_URL = "postgresql+psycopg2://curriculum_user:curriculum_pass@localhost:5433/curriculum_kag_shadow"
    Write-Host "Using available local PostgreSQL database on localhost:5433." -ForegroundColor Cyan
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
    if (-not (Test-TcpPort $postgresHost $postgresPort 1000)) {
        if ($Database -in @("postgres", "postgres-shadow")) {
            throw "PostgreSQL ${postgresHost}:${postgresPort} is unavailable. Start Docker/PostgreSQL or use -Database sqlite."
        }
        $env:DATABASE_URL = "sqlite:///$sqlitePath"
        Write-Host "PostgreSQL ${postgresHost}:${postgresPort} is unavailable; using the local SQLite database." -ForegroundColor Yellow
    }
}

$effectiveDatabaseUrl = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { $configuredDatabaseUrl }
$expectedDatabaseDialect = if ($effectiveDatabaseUrl -match '^postgresql') { "postgresql" } else { "sqlite" }
$existingBackendHealth = Get-EndpointJson "http://127.0.0.1:8000/health"
if ($existingBackendHealth) {
    if (-not $existingBackendHealth.database) {
        throw "Backend is already running without database diagnostics. Run stop.ps1 once, then start again."
    }
    if ($existingBackendHealth.database -ne $expectedDatabaseDialect) {
        throw "Backend is already using '$($existingBackendHealth.database)', but '$expectedDatabaseDialect' was requested. Run stop.ps1, then start again."
    }
}

$pids = @{}
if (-not (Test-Endpoint "http://127.0.0.1:8000/health")) {
    if ($expectedDatabaseDialect -eq "postgresql") {
        Write-Host "Applying PostgreSQL migrations..."
        Push-Location $backendDir
        try {
            & $python -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) {
                throw "Alembic migration failed. The backend was not started."
            }
        }
        finally {
            Pop-Location
        }
    }
    Write-Host "Starting backend..."
    $backend = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "backend.out.log") -RedirectStandardError (Join-Path $runtime "backend.err.log")
    try { $backend.PriorityClass = "BelowNormal" } catch { }
    $pids.backend = $backend.Id
}
else {
    Write-Host "Backend is already running."
}

Wait-Endpoint "backend" "http://127.0.0.1:8000/health"
$backendHealth = Get-EndpointJson "http://127.0.0.1:8000/health"
if (-not $backendHealth -or $backendHealth.database_status -ne "connected") {
    throw "Backend started, but its database health check failed. Check .runtime/backend.err.log."
}
if ($backendHealth.database -ne $expectedDatabaseDialect) {
    throw "Backend started with '$($backendHealth.database)' instead of '$expectedDatabaseDialect'."
}

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
Write-Host "Curriculum-KAG is ready: http://127.0.0.1:3001/ (localhost is also supported)" -ForegroundColor Green
Write-Host "Login: admin@curriculum-kag.local / admin123"
Write-Host "Use stop.bat to stop services started by this launcher."

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:3001/"
}
