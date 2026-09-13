param(
    [string]$BackendImage = "curriculum-kag-backend:latest",
    [string]$FrontendImage = "curriculum-kag-frontend:latest",
    [string]$OutputDir = ".runtime/sbom",
    [ValidateRange(10, 900)]
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = [IO.Path]::GetFullPath((Join-Path $root $OutputDir))
function Find-DockerCli {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\resources\bin\docker.exe"),
        "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Docker CLI is required. Install Docker Desktop or add its resources\\bin directory to PATH."
}
$dockerCli = Find-DockerCli

& $dockerCli scout sbom --help 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Scout SBOM support is required (docker scout sbom)."
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
foreach ($entry in @(
    @{ Name = "backend"; Image = $BackendImage },
    @{ Name = "frontend"; Image = $FrontendImage }
)) {
    $target = Join-Path $outputPath "$($entry.Name).spdx.json"
    & $dockerCli image inspect $entry.Image *> $null
    if ($LASTEXITCODE -ne 0) { throw "Image not found locally: $($entry.Image)" }
    $scout = Start-Process -FilePath $dockerCli -ArgumentList @(
        'scout', 'sbom', '--format', 'spdx', '--output', $target, "local://$($entry.Image)"
    ) -WindowStyle Hidden -PassThru
    if (-not $scout.WaitForExit($TimeoutSeconds * 1000)) {
        try { $scout.Kill($true) } catch { }
        throw "Docker Scout SBOM timed out after $TimeoutSeconds seconds for $($entry.Image). Check Docker Scout connectivity, then retry; the image was not modified."
    }
    if ($scout.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $target) -or (Get-Item -LiteralPath $target).Length -lt 256) {
        throw "SBOM generation failed or produced an unexpectedly small file: $target"
    }
    Write-Host "SBOM created: $target"
}
