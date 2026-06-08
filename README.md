# DropDL

DropDL is a local Windows desktop app for downloading video and audio with
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp). It provides a straightforward
interface for choosing output quality, extracting audio, downloading
subtitles, and saving only a specific section of a video.

Everything runs on the user's computer. The packaged release includes
`yt-dlp` and FFmpeg, starts its own local server, and opens the interface in
the default web browser.

## Download

### [Download DropDL for Windows](https://github.com/samarth35/DropDL/releases/download/v1.0.3/DropDL-Windows.zip)

1. Download and extract `DropDL-Windows.zip`.
2. Keep the extracted folder together.
3. Open `DropDL.exe`.

No Python installation, FFmpeg installation, command prompt, or `PATH`
configuration is required. Downloads are saved under:

```text
%USERPROFILE%\Downloads\DropDL
```

Windows may display a SmartScreen warning because the executable is not
code-signed. Select **More info**, then **Run anyway** if you downloaded it
from this repository.

See [all releases](https://github.com/samarth35/DropDL/releases) for older
versions and release notes.

## Features

- Download video using the best available format or a maximum resolution
- Extract audio as MP3, M4A, Opus, or WAV
- Fetch the title, uploader, duration, and thumbnail before downloading
- Crop video or audio using start and end timestamps
- Download individual videos or playlists
- Save English subtitles when available
- Display download progress, speed, ETA, and processing status
- Keep completed downloads available for saving again during the session
- Run entirely on localhost without a hosted backend

## Timeline Cropping

Enable **Download a specific part** and provide a start and end time.
Accepted formats are:

```text
90
01:30
01:02:30
```

These represent raw seconds, `MM:SS`, and `HH:MM:SS` respectively. DropDL
uses yt-dlp download ranges and FFmpeg keyframe re-encoding for accurate
cuts. Processing a precise video segment can therefore take longer than
downloading the complete file.

## How It Works

The desktop executable launches a FastAPI server on a random localhost port
and opens the interface in the default browser. DropDL remains available in
the Windows notification area, where the interface can be reopened or the
local server can be stopped cleanly.

```text
Default web browser
        |
        v
FastAPI on 127.0.0.1
        |
        +-- yt-dlp: metadata and downloads
        |
        +-- FFmpeg: merging, conversion, and trimming
        |
        v
Downloads\DropDL
```

The Windows release is packaged with PyInstaller and contains:

- Python runtime
- FastAPI and Uvicorn
- yt-dlp
- FFmpeg and FFprobe
- HTML, CSS, and JavaScript interface

## Running From Source

Requirements:

- Windows 10 or Windows 11
- Python 3.11 or newer
- FFmpeg and FFprobe available on `PATH`

Clone the repository and start the development server:

```powershell
git clone https://github.com/samarth35/DropDL.git
cd DropDL
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

The interface will be available at <http://127.0.0.1:8000>.

## Building The Windows Release

The build script creates a portable application folder and ZIP archive:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

If FFmpeg is not on `PATH`, provide its `bin` directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1 `
  -FfmpegBin "C:\path\to\ffmpeg\bin"
```

Build output:

```text
outputs\DropDL-Windows\DropDL.exe
outputs\DropDL-Windows.zip
```

The project uses the complete shared FFmpeg runtime. Distribute the generated
ZIP or the entire `DropDL-Windows` folder, not `DropDL.exe` by itself.

Version tags matching `v*` trigger the
[Windows release workflow](https://github.com/samarth35/DropDL/actions/workflows/release-windows.yml),
which builds the app and attaches the ZIP to a GitHub Release.

## Project Structure

```text
app/
  main.py                 FastAPI API and yt-dlp job handling
static/
  index.html              Desktop interface
  styles.css              Responsive styling
  app.js                  UI state and API requests
desktop.py                Windows tray launcher and server lifecycle
DropDL.spec               PyInstaller configuration
run.ps1                   Development launcher
build-windows.ps1         Windows packaging script
requirements.txt          Runtime dependencies
requirements-build.txt    Packaging dependencies
```

## Current Limitations

- The packaged release currently targets 64-bit Windows.
- Some websites may require authentication, cookies, or additional yt-dlp
  configuration that is not yet exposed in the interface.
- Site changes can temporarily break downloads until yt-dlp is updated.
- Downloads are not automatically removed from disk.

## Legal

DropDL is a frontend for third-party tools and does not host or provide media.
Only download content you own or are authorized to access. You are responsible
for complying with applicable laws and the terms of the source website.

FFmpeg, yt-dlp, and other dependencies retain their respective
licenses. See [`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt) for details.
