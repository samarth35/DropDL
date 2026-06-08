param(
    [string]$FfmpegBin
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project

$bootstrapPython = if (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} else {
    throw "Python 3.11 or newer is required."
}
$venv = ".venv-build"

if (-not (Test-Path "$venv\Scripts\python.exe")) {
    if ($bootstrapPython -eq "py") {
        & py -3 -m venv $venv
    } else {
        & python -m venv $venv
    }
}
$python = "$venv\Scripts\python.exe"
& $python -m pip install -r requirements-build.txt

if (-not $FfmpegBin) {
    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpeg) {
        $FfmpegBin = Split-Path -Parent $ffmpeg.Source
    }
}
if (-not $FfmpegBin -or -not (Test-Path (Join-Path $FfmpegBin "ffmpeg.exe"))) {
    throw "FFmpeg was not found. Pass its bin directory with -FfmpegBin 'C:\path\to\ffmpeg\bin'."
}
if (-not (Test-Path (Join-Path $FfmpegBin "ffprobe.exe"))) {
    throw "ffprobe.exe was not found beside ffmpeg.exe."
}

$vendor = Join-Path $project "vendor\ffmpeg"
New-Item -ItemType Directory -Force -Path $vendor | Out-Null
Get-ChildItem -LiteralPath $FfmpegBin -File | Copy-Item -Destination $vendor -Force
$ffmpegLicense = Join-Path (Split-Path -Parent $FfmpegBin) "LICENSE.txt"
if (Test-Path $ffmpegLicense) {
    Copy-Item -LiteralPath $ffmpegLicense -Destination (Join-Path $vendor "LICENSE.txt") -Force
}

$pyinstallerDist = Join-Path $project "outputs\DropDL"
$dist = Join-Path $project "outputs\DropDL-Windows"
$build = Join-Path $project "work\pyinstaller"
if (Test-Path $dist) {
    Remove-Item -LiteralPath $dist -Recurse -Force
}
if (Test-Path $pyinstallerDist) {
    Remove-Item -LiteralPath $pyinstallerDist -Recurse -Force
}
if (Test-Path $build) {
    Remove-Item -LiteralPath $build -Recurse -Force
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath (Join-Path $project "outputs") `
    --workpath $build `
    DropDL.spec

if (Test-Path $pyinstallerDist) {
    Move-Item -LiteralPath $pyinstallerDist -Destination $dist
}
if (-not (Test-Path (Join-Path $dist "DropDL.exe"))) {
    throw "Build completed without producing DropDL.exe."
}
Copy-Item -LiteralPath (Join-Path $project "THIRD_PARTY_NOTICES.txt") -Destination $dist -Force

$zip = Join-Path $project "outputs\DropDL-Windows.zip"
if (Test-Path $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal

Write-Host ""
Write-Host "DropDL Windows build created:"
Write-Host "  $dist"
Write-Host "  $zip"
