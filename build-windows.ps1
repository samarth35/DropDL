param(
    [string]$FfmpegBin,
    [string]$Python,
    [switch]$RecreateEnvironment
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project

function Resolve-BuildPython {
    if ($Python) {
        if (-not (Test-Path -LiteralPath $Python)) {
            throw "Python executable not found: $Python"
        }
        return (Resolve-Path -LiteralPath $Python).Path
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py"
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    throw "Standard 64-bit Windows Python 3.12 is required."
}

function Invoke-PackagedSmokeTest {
    param(
        [string]$Executable,
        [string]$ResultPath,
        [string]$Label
    )

    Remove-Item -LiteralPath $ResultPath -Force -ErrorAction SilentlyContinue
    $quotedResult = '"' + $ResultPath + '"'
    $process = Start-Process `
        -FilePath $Executable `
        -ArgumentList @("--smoke-test", $quotedResult) `
        -PassThru

    if (-not $process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "$Label smoke test did not exit within 30 seconds."
    }

    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $ResultPath)) {
        $log = Join-Path $env:LOCALAPPDATA "DropDL\dropdl.log"
        if (Test-Path -LiteralPath $log) {
            Write-Host "DropDL log:"
            Get-Content -LiteralPath $log | Select-Object -Last 100
        }
        throw "$Label smoke test failed with exit code $($process.ExitCode)."
    }

    $result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    if (-not $result.ok `
        -or -not $result.title_present `
        -or -not $result.frozen `
        -or -not $result.health.ffmpeg `
        -or -not $result.media_tools.ffmpeg `
        -or -not $result.media_tools.ffprobe) {
        throw "$Label smoke test returned invalid proof: $(Get-Content -LiteralPath $ResultPath -Raw)"
    }
    return $result
}

$bootstrapPython = Resolve-BuildPython
$venv = ".venv-build"
$venvPython = Join-Path $venv "Scripts\python.exe"

if ($RecreateEnvironment -and (Test-Path -LiteralPath $venv)) {
    $resolvedVenv = (Resolve-Path -LiteralPath $venv).Path
    if (-not $resolvedVenv.StartsWith($project, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a build environment outside the project: $resolvedVenv"
    }
    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($bootstrapPython -eq "py") {
        & py -3.12 -m venv $venv
    } else {
        & $bootstrapPython -m venv $venv
    }
}

& $venvPython -c "import sys, sysconfig; assert sys.version_info[:2] == (3, 12), sys.version; assert sysconfig.get_platform() == 'win-amd64', sysconfig.get_platform()"
& $venvPython -m pip install --disable-pip-version-check -r requirements-windows.lock
& $venvPython -m pip check

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

$outputs = Join-Path $project "outputs"
$pyinstallerDist = Join-Path $outputs "DropDL"
$dist = Join-Path $outputs "DropDL-Windows"
$zip = Join-Path $outputs "DropDL-Windows.zip"
$checksum = Join-Path $outputs "DropDL-Windows.sha256"
$proof = Join-Path $outputs "DropDL-Windows.proof.json"
$build = Join-Path $project "work\pyinstaller"
$smoke = Join-Path $project "work\smoke"
$zipExtract = Join-Path $project "work\zip-smoke"

foreach ($path in @($pyinstallerDist, $dist, $build, $smoke, $zipExtract)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
foreach ($path in @($zip, $checksum, $proof)) {
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $outputs, $smoke, $zipExtract | Out-Null

& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $outputs `
    --workpath $build `
    DropDL.spec

if (Test-Path -LiteralPath $pyinstallerDist) {
    Move-Item -LiteralPath $pyinstallerDist -Destination $dist
}
$exe = Join-Path $dist "DropDL.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build completed without producing DropDL.exe."
}
Copy-Item -LiteralPath (Join-Path $project "THIRD_PARTY_NOTICES.txt") -Destination $dist -Force

$folderResultPath = Join-Path $smoke "folder-result.json"
$folderResult = Invoke-PackagedSmokeTest -Executable $exe -ResultPath $folderResultPath -Label "Built folder"

Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
Expand-Archive -LiteralPath $zip -DestinationPath $zipExtract
$zipExe = Get-ChildItem -LiteralPath $zipExtract -Recurse -Filter "DropDL.exe" | Select-Object -First 1
if (-not $zipExe) {
    throw "DropDL.exe was not found after extracting the release ZIP."
}
$zipResultPath = Join-Path $smoke "zip-result.json"
$zipResult = Invoke-PackagedSmokeTest -Executable $zipExe.FullName -ResultPath $zipResultPath -Label "Extracted ZIP"

$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  DropDL-Windows.zip" | Set-Content -LiteralPath $checksum -Encoding ascii
$lockHash = (Get-FileHash -LiteralPath (Join-Path $project "requirements-windows.lock") -Algorithm SHA256).Hash.ToLowerInvariant()
$ffmpegVersion = (& (Join-Path $FfmpegBin "ffmpeg.exe") -version | Select-Object -First 1).Trim()

$versions = & $venvPython -c "import json, sys; from importlib.metadata import version; print(json.dumps({'python': sys.version.split()[0], 'fastapi': version('fastapi'), 'uvicorn': version('uvicorn'), 'yt_dlp': version('yt-dlp'), 'pillow': version('Pillow'), 'pystray': version('pystray'), 'pyinstaller': version('pyinstaller')}))" | ConvertFrom-Json

[ordered]@{
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    zip_sha256 = $hash
    zip_size_bytes = (Get-Item -LiteralPath $zip).Length
    requirements_lock_sha256 = $lockHash
    ffmpeg = $ffmpegVersion
    dependencies = $versions
    built_folder_smoke = $folderResult
    extracted_zip_smoke = $zipResult
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $proof -Encoding utf8

Write-Host ""
Write-Host "DropDL Windows release passed all packaged smoke tests:"
Write-Host "  $dist"
Write-Host "  $zip"
Write-Host "  $checksum"
Write-Host "  $proof"
