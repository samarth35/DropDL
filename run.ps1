$ErrorActionPreference = "Stop"

$venv = ".venv"
$bootstrapPython = if (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} else {
    throw "Python 3.11 or newer is required."
}

if (-not (Test-Path $venv)) {
    if ($bootstrapPython -eq "py") {
        & py -3 -m venv $venv
    } else {
        & python -m venv $venv
    }
}

$python = "$venv\Scripts\python.exe"

& $python -m pip install -r requirements.txt
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
