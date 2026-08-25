param(
    [string]$ApiBaseUrl = "http://localhost:8000",
    [int]$ProjectVersionId = 13,
    [string]$Email = $env:CURRICULUM_KAG_SMOKE_EMAIL,
    [string]$Password = $env:CURRICULUM_KAG_SMOKE_PASSWORD
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Email) -or [string]::IsNullOrWhiteSpace($Password)) {
    throw "Set CURRICULUM_KAG_SMOKE_EMAIL and CURRICULUM_KAG_SMOKE_PASSWORD; credentials are never stored in the repository."
}

$base = $ApiBaseUrl.TrimEnd('/')
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" `
    -ContentType "application/x-www-form-urlencoded" `
    -Body @{ username = $Email; password = $Password }
if ([string]::IsNullOrWhiteSpace($login.access_token)) {
    throw "Authentication returned no access token."
}

$headers = @{ Authorization = "Bearer $($login.access_token)" }
$me = Invoke-RestMethod -Method Get -Uri "$base/auth/me" -Headers $headers
if (-not $me.email) { throw "Authenticated /auth/me response has no email." }

$graph = Invoke-RestMethod -Method Get `
    -Uri "$base/planner/version/$ProjectVersionId/graph?variant=A" `
    -Headers $headers
if ($null -eq $graph.nodes -or $null -eq $graph.edges) {
    throw "Graph response does not contain nodes and edges."
}

Write-Host "Authenticated API smoke passed: user=$($me.email); graph nodes=$(@($graph.nodes).Count), edges=$(@($graph.edges).Count)." -ForegroundColor Green
