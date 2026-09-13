param(
    [switch]$NoBrowser,
    [switch]$RestartBackend,
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
if (-not $env:DOCKER_CLIENT_TIMEOUT) { $env:DOCKER_CLIENT_TIMEOUT = "20" }
if (-not $env:COMPOSE_HTTP_TIMEOUT) { $env:COMPOSE_HTTP_TIMEOUT = "180" }
function Get-PositiveTimeout([string]$Name, [int]$Default, [int]$Maximum = 1800) {
    $raw = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    $value = 0
    if (-not [int]::TryParse($raw, [ref]$value) -or $value -lt 5 -or $value -gt $Maximum) {
        throw "$Name must be an integer between 5 and $Maximum seconds (received '$raw')."
    }
    return $value
}
$dockerDesktopStartupTimeout = Get-PositiveTimeout "DOCKER_DESKTOP_STARTUP_TIMEOUT_SECONDS" 60
$dockerComposeStartupTimeout = Get-PositiveTimeout "DOCKER_COMPOSE_STARTUP_TIMEOUT_SECONDS" 180
$postgresStartupTimeout = Get-PositiveTimeout "POSTGRES_STARTUP_TIMEOUT_SECONDS" 300
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

function Test-LocalService([string]$HostName, [int]$Port, [string]$Url) {
    # An HTTP response alone is not sufficient: a proxy or stale health
    # response can make a dead local service look alive. Require both the
    # loopback TCP listener and the expected health endpoint.
    return (Test-TcpPort $HostName $Port 1000) -and (Test-Endpoint $Url)
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

function Invoke-DockerRuntimeRepair([string]$Reason) {
    $repairScript = Join-Path $root 'scripts\repair-docker-runtime.ps1'
    if (-not (Test-Path -LiteralPath $repairScript)) {
        Write-Warning 'Docker runtime repair script is missing.'
        return $false
    }
    Write-Warning "$Reason Running one bounded Docker runtime repair."
    $repair = $null
    try {
        $repairArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $repairScript, '-NoStart')
        # Docker's runtime socket directory belongs to the interactive user
        # profile.  Do not switch tokens with UAC here: an elevated repair
        # can leave the launcher waiting for an invisible consent prompt and
        # does not add permissions needed for this user-owned namespace.
        $repair = Start-Process -FilePath 'powershell.exe' -ArgumentList $repairArgs -PassThru -WindowStyle Hidden
        if ($repair.WaitForExit(60000) -and $repair.ExitCode -eq 0) {
            return $true
        }
        if ($repair) { try { $repair.Kill($true) } catch { } }
        Write-Warning 'Docker runtime repair did not complete within 60 seconds.'
        return $false
    }
    catch {
        Write-Warning 'Docker runtime repair could not be completed automatically.'
        return $false
    }
}

function Start-DockerDesktopIfNeeded([string]$DockerCli) {
    if (Test-DockerEngine $DockerCli) { return $true }

    $desktopCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
        "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )
    $desktop = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $desktop) {
        Write-Warning "Docker Desktop executable was not found. The Docker CLI alone cannot start the Linux engine. Restore Docker Desktop installation; Docker data remains at D:\Docker\DockerDesktopWSL\disk\docker_data.vhdx."
        return $false
    }

    $desktopRunning = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    # Listener reparse points are normal while Desktop is running.  If no
    # Desktop process exists, however, entries in this small ephemeral
    # namespace are orphaned leftovers from a prior crash and must be reset
    # before the next Engine start.  This is the precise stale-state signal;
    # it does not inspect or modify the VHDX data root.
    $runtimeNames = @('dockerEthernetVfkit', 'dockerInference', 'sailor-ingest.sock', 'userAnalyticsOtlpHttp.sock')
    $runtimeDir = Join-Path $env:LOCALAPPDATA 'Docker\run'
    $orphanRuntimeEntries = @(
        Get-ChildItem -LiteralPath $runtimeDir -Force -ErrorAction SilentlyContinue |
            Where-Object { $runtimeNames -contains $_.Name }
    )
    $secretsDir = Join-Path $env:LOCALAPPDATA 'docker-secrets-engine'
    $orphanSecretsEntries = @(
        Get-ChildItem -LiteralPath $secretsDir -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'engine.sock' }
    )
    if (-not $desktopRunning -and ($orphanRuntimeEntries.Count -gt 0 -or $orphanSecretsEntries.Count -gt 0)) {
        if (-not (Invoke-DockerRuntimeRepair 'Docker Desktop is stopped but orphaned runtime listeners were found.')) {
            return $false
        }
    }

    # Check WSL only after stale runtime cleanup.  A broken WSL access check
    # must not prevent the elevated repair from releasing/removing stale
    # Docker listener entries, which is the common cause of the Desktop
    # startup failure shown to the user.
    $wslCli = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($wslCli) {
        $wslProbe = $null
        try {
            $probeInfo = [Diagnostics.ProcessStartInfo]::new()
            $probeInfo.FileName = $wslCli.Source
            $probeInfo.Arguments = '--status'
            $probeInfo.WorkingDirectory = $root
            $probeInfo.UseShellExecute = $false
            $probeInfo.CreateNoWindow = $true
            $probeInfo.RedirectStandardOutput = $true
            $probeInfo.RedirectStandardError = $true
            $wslProbe = [Diagnostics.Process]::new()
            $wslProbe.StartInfo = $probeInfo
            [void]$wslProbe.Start()
            if (-not $wslProbe.WaitForExit(5000)) {
                try { $wslProbe.Kill($true) } catch {}
                Write-Warning 'WSL service probe timed out; continuing so Docker Desktop can start and report its own daemon state.'
            }
            if ($wslProbe.ExitCode -ne 0) {
                $probeError = $wslProbe.StandardError.ReadToEnd()
                # Keep the parser guard ASCII-only: Windows PowerShell 5 may
                # decode UTF-8 source without a BOM as mojibake and break the
                # entire launcher before Docker is even started.
                $probeKind = if ($probeError -match 'E_ACCESSDENIED|ACCESS.?DENIED') { 'E_ACCESSDENIED' } else { 'WSL_SERVICE_ERROR' }
                if ($probeKind -eq 'E_ACCESSDENIED') {
                    # Docker Desktop cannot create its Linux daemon while the
                    # current Windows session is denied access to WSL. Starting
                    # it anyway only recreates the stale runtime sockets that
                    # caused the next failure. Do not touch data; require one
                    # clean Windows restart before a new Desktop attempt.
                    Write-Warning 'WSL access is denied in this Windows session. Docker Desktop was not started, and Docker data was not changed. Restart Windows once, then run start.bat again.'
                    return $false
                }
                Write-Warning "WSL service preflight reported $probeKind; continuing with Docker Desktop startup. Docker data was not changed."
            }
        }
        catch {
            Write-Warning 'WSL service probe failed; continuing with Docker Desktop startup. Docker data was not changed.'
        }
        finally { if ($wslProbe) { $wslProbe.Dispose() } }
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
    $deadline = (Get-Date).AddSeconds($dockerDesktopStartupTimeout)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerEngine $DockerCli) { return $true }
        Start-Sleep -Seconds 5
    }
    if (Invoke-DockerRuntimeRepair 'Docker Engine did not start on the first attempt.') {
        Start-Process -FilePath $desktop -WindowStyle Hidden -ErrorAction Stop | Out-Null
        $retryDeadline = (Get-Date).AddSeconds($dockerDesktopStartupTimeout)
        while ((Get-Date) -lt $retryDeadline) {
            if (Test-DockerEngine $DockerCli) { return $true }
            Start-Sleep -Seconds 5
        }
    }
    Write-Warning "Docker Desktop did not expose a working engine after one normal start and one repair retry. The VHDX/data root was not moved or modified. Quit the Docker error dialog (never Reset to factory defaults), then run scripts\repair-docker-runtime.ps1 from the same interactive user profile and start.bat again."
    return $false
}

function Get-DockerDataRoot {
    # The WSL data location is separate from ephemeral runtime sockets.
    $settingsPath = Join-Path $env:APPDATA "Docker\settings-store.json"
    try {
        if (-not (Test-Path -LiteralPath $settingsPath)) { return $null }
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $configured = [string]$settings.CustomWslDistroDir
        if ($configured -and (Test-Path -LiteralPath $configured)) {
            return [IO.Path]::GetFullPath($configured)
        }
    } catch { }
    return $null
}

function Warn-IfDockerRestoreMayExhaustSystemDisk {
    # Check the drive hosting Docker's WSL disk without moving or rewriting it.
    $dataRoot = Get-DockerDataRoot
    $driveName = if ($dataRoot) { ([IO.Path]::GetPathRoot($dataRoot)).TrimEnd('\', ':') } else { 'C' }
    $dataDrive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
    if ($dataRoot) {
        Write-Host "Docker Desktop data root: $dataRoot (runtime sockets remain under $env:LOCALAPPDATA\Docker\run)." -ForegroundColor DarkGray
    }
    if ($dataDrive -and $dataDrive.Free -lt 12GB) {
        $freeGb = [math]::Round($dataDrive.Free / 1GB, 1)
        Write-Host "Warning: only $freeGb GB is free on $driveName`:. PostgreSQL restore verification may need additional temporary space. The launcher will not move Docker data." -ForegroundColor Yellow
    }
}

function Start-PostgresShadowIfNeeded {
    # Docker Desktop publishes the shadow database on IPv4.  Use the numeric
    # loopback address here so a slow/broken localhost IPv6 resolution cannot
    # make the launcher wait for the full startup timeout or fail falsely.
    if (Wait-TcpPort "127.0.0.1" 5433 2) { return $true }
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
        if (-not $proc.WaitForExit($dockerComposeStartupTimeout * 1000)) {
            try { $proc.Kill($true) } catch {}
            Write-Warning "Docker Compose did not respond within $dockerComposeStartupTimeout seconds; startup was stopped without deleting data."
            return $false
        }
        if ($proc.ExitCode -ne 0) { return $false }
    }
    finally { if ($proc) { $proc.Dispose() }; Pop-Location }
    return (Wait-TcpPort "127.0.0.1" 5433 $postgresStartupTimeout)
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
$venvPython = Join-Path $backendDir "venv\Scripts\python.exe"
$previousPythonPath = $env:PYTHONPATH
# Prefer the project's virtual environment.  The bundled Codex runtime is a
# fallback for an actually broken venv only: choosing it first silently loses
# the project's CUDA-enabled PyTorch and can turn a short SBERT batch into a
# tens-of-minutes CPU build.
$python = if (Test-PythonRuntime $venvPython) { $venvPython } else { $null }
if (-not $python -and (Test-Path $existingSitePackages)) {
    # A moved/removed system Python can leave a broken venv launcher while its
    # installed packages are still valid. Reuse them only in this fallback.
    $env:PYTHONPATH = $existingSitePackages
    if (Test-PythonRuntime $bundledPython) { $python = $bundledPython }
}

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

# Do not silently turn an explicitly configured GPU build into a very slow
# CPU job.  This is deliberately a launcher check: a long plan should fail
# early with a clear repair path rather than appear stuck at vectorization.
$backendEnv = Join-Path $backendDir ".env"
$requestedSbertDevice = if (Test-Path $backendEnv) {
    (Get-Content -LiteralPath $backendEnv | Where-Object { $_ -match '^\s*SBERT_DEVICE\s*=' } | Select-Object -Last 1) -replace '^\s*SBERT_DEVICE\s*=\s*', ''
} else { "" }
if ($requestedSbertDevice -match '^(cuda|gpu)$') {
    $cudaProbe = & $python -c "import torch; print('1' if torch.cuda.is_available() else '0'); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $cudaProbe -or $cudaProbe[0] -ne '1') {
        throw "SBERT_DEVICE=cuda is configured, but this project Python cannot access CUDA. Install the CUDA PyTorch wheel in backend\\venv before starting a build."
    }
    Write-Host "SBERT GPU: $($cudaProbe[1])" -ForegroundColor Green
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
    if ($postgresHost -eq "localhost") { $postgresHost = "127.0.0.1" }
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
$existingBackendHealth = if (Test-TcpPort "127.0.0.1" 8000 1000) {
    Get-EndpointJson "http://127.0.0.1:8000/health"
} else {
    $null
}
$savedBackendPid = $null
if (Test-Path $pidFile) {
    try { $savedBackendPid = (Get-Content $pidFile -Raw | ConvertFrom-Json).backend } catch { $savedBackendPid = $null }
}
if ($RestartBackend -and $savedBackendPid) {
    $savedProcess = Get-Process -Id ([int]$savedBackendPid) -ErrorAction SilentlyContinue
    if ($savedProcess -and $savedProcess.ProcessName -in @("python", "pythonw")) {
        Write-Host "Restarting project backend PID $savedBackendPid..." -ForegroundColor Yellow
        Stop-Process -Id ([int]$savedBackendPid) -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        $existingBackendHealth = $null
    }
}
$backendPortBusy = Test-TcpPort "127.0.0.1" 8000 1000
if ($backendPortBusy -and -not $existingBackendHealth) {
    # A previous launcher can leave uvicorn alive after its parent shell has
    # exited. Reap only a process that is unambiguously this project's local
    # backend; never kill an unrelated service merely because it owns 8000.
    $projectBackendProcesses = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like "*$backendDir*" -and
            $_.CommandLine -match "uvicorn.*--port\s+8000"
        }
    foreach ($staleBackend in $projectBackendProcesses) {
        Write-Host "Stopping stale project backend PID $($staleBackend.ProcessId)..." -ForegroundColor Yellow
        Stop-Process -Id ([int]$staleBackend.ProcessId) -Force -ErrorAction SilentlyContinue
    }
    if ($projectBackendProcesses) {
        Start-Sleep -Milliseconds 500
        $backendPortBusy = Test-TcpPort "127.0.0.1" 8000 1000
    }
    if ($backendPortBusy) {
        throw "Port 8000 is occupied by another process and is not a healthy Curriculum-KAG backend. Stop that process or set a different backend port."
    }
}
if ($existingBackendHealth) {
    if (-not $existingBackendHealth.database) {
        throw "Backend is already running without database diagnostics. Run stop.ps1 once, then start again."
    }
    if ($existingBackendHealth.database -ne $expectedDatabaseDialect) {
        throw "Backend is already using '$($existingBackendHealth.database)', but '$expectedDatabaseDialect' was requested. Run stop.ps1, then start again."
    }
}

$pids = @{}
if (-not (Test-LocalService "127.0.0.1" 8000 "http://127.0.0.1:8000/health")) {
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

# A planner build is CPU-intensive on local installations.  Use one durable
# queue consumer instead of starting an unconstrained one-shot Python process
# for every button click.  The worker is safe to start before a job exists and
# leaves queued work recoverable after an API restart.
$workerScript = Join-Path $backendDir "scripts\run_planner_build_worker.py"
$workerHeartbeat = Join-Path $runtime "planner-worker.heartbeat"
$existingPlannerWorker = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like "*$workerScript*" -and
        $_.CommandLine -match "--daemon" -and
        (Test-Path -LiteralPath $workerHeartbeat) -and
        ((Get-Date) - (Get-Item -LiteralPath $workerHeartbeat).LastWriteTime).TotalSeconds -lt 30
    } |
    Select-Object -First 1
if (-not $existingPlannerWorker) {
    Write-Host "Starting bounded planner worker (concurrency: 1)..."
    $plannerWorker = Start-Process -FilePath $python -ArgumentList $workerScript, "--daemon", "--poll-seconds", "2", "--max-jobs", "1" -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "planner-worker.out.log") -RedirectStandardError (Join-Path $runtime "planner-worker.err.log")
    try { $plannerWorker.PriorityClass = "BelowNormal" } catch { }
    $pids.plannerWorker = $plannerWorker.Id
}
else {
    Write-Host "Planner worker is already running (PID $($existingPlannerWorker.ProcessId))."
}

if (-not (Test-LocalService "127.0.0.1" 3001 "http://127.0.0.1:3001/api/health")) {
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
Write-Host "Login credentials are not printed. Use CURRICULUM_LOCAL_EMAIL and CURRICULUM_LOCAL_PASSWORD for local smoke/tests."
Write-Host "Use stop.bat to stop services started by this launcher."

if (-not $NoBrowser) {
    try {
        Start-Process "http://127.0.0.1:3001/" -ErrorAction Stop
    }
    catch {
        Write-Warning "Сервисы запущены, но Windows не разрешила автоматически открыть браузер. Откройте http://127.0.0.1:3001/ вручную."
    }
}
