param(
    [string]$Python,
    [ValidateRange(0, 65535)][int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$Update,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
Set-Location -LiteralPath $project
$venv = Join-Path $project ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$check = "import sys, sysconfig; raise SystemExit(0 if sys.version_info >= (3,11) and sysconfig.get_platform().startswith('win') else 1)"

function Test-Python([string]$Executable, [string[]]$Prefix = @()) {
    if (-not $Executable) { return $false }
    try {
        & $Executable @Prefix -c $check 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

if (-not (Test-Python $venvPython)) {
    $bootstrap = $null
    $bootstrapArgs = @()
    if ($Python) {
        if (-not (Test-Python $Python)) { throw "-Python must point to a working Windows Python 3.11+ installation." }
        $bootstrap = $Python
    } else {
        foreach ($candidate in @("py", "python", "python3")) {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            $candidateArgs = if ($candidate -eq "py") { @("-3") } else { @() }
            if ($command -and (Test-Python $command.Source $candidateArgs)) {
                $bootstrap = $command.Source
                $bootstrapArgs = $candidateArgs
                break
            }
        }
    }
    if (-not $bootstrap) {
        throw "Install Windows Python 3.11+ from https://www.python.org/downloads/windows/ (enable Add Python to PATH), then double-click Start DropDL.cmd again."
    }
    if (Test-Path -LiteralPath $venv) {
        $backup = Join-Path $project (".venv-broken-" + [guid]::NewGuid().ToString("N"))
        Move-Item -LiteralPath $venv -Destination $backup
        Write-Host "Rebuilding the unavailable Python environment. Previous files were kept in $backup"
    }
    & $bootstrap @bootstrapArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create DropDL's Python environment." }
}

$requirements = Join-Path $project "requirements.txt"
$stamp = Join-Path $venv ".dropdl-requirements"
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $fingerprint = [BitConverter]::ToString($sha256.ComputeHash([System.IO.File]::ReadAllBytes($requirements))).Replace("-", "")
} finally { $sha256.Dispose() }
$saved = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { "" }
$dependenciesAvailable = $false
try {
    & $venvPython -c "import fastapi, uvicorn, yt_dlp" 2>$null | Out-Null
    $dependenciesAvailable = $LASTEXITCODE -eq 0
} catch { $dependenciesAvailable = $false }
if ($Update -or -not $dependenciesAvailable -or $saved -ne $fingerprint) {
    Write-Host "Setting up DropDL (internet is required the first time)..."
    $pipArgs = @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements)
    if ($Update) { $pipArgs += "--upgrade" }
    & $venvPython @pipArgs
    if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed. Check your internet connection and run Start DropDL.cmd again." }
    Set-Content -LiteralPath $stamp -Value $fingerprint -Encoding ASCII
}

if ($SetupOnly) { Write-Host "DropDL is ready."; exit 0 }
$launchArgs = @("-m", "app", "--port", "$Port")
if ($NoBrowser) { $launchArgs += "--no-browser" }
& $venvPython @launchArgs
exit $LASTEXITCODE
