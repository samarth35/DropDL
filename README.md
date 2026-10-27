# DropDL

DropDL is a portable Windows interface for
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp). It downloads video or audio,
supports quality and subtitle options, and can save only a selected section
of a video.

The app runs entirely on the local computer. It does not upload links or
media to a hosted DropDL server.

## Run This Checkout

On Windows, double-click **Start DropDL.cmd**. The launcher prepares the
Python environment and opens the web interface in your default browser.
Keep the launcher window open while downloading; press Ctrl+C there to stop.

Running from source requires standard Windows Python 3.11 or newer and an
internet connection for the first setup. Later launches reuse the installed
dependencies. A broken environment is backed up and rebuilt automatically
when a suitable Python installation is available.

FFmpeg and FFprobe enable audio conversion, clips, and merging high-quality
video. DropDL checks both tools in `vendor/ffmpeg` or on `PATH`. Basic video
downloads remain available without them. The packaged Windows release
described below already includes these tools.

## Download

Download `DropDL-Windows.zip` from the
[latest GitHub release](https://github.com/samarth35/DropDL/releases/latest),
extract it, and open `DropDL.exe`.

### No additional software required

The Windows release is self-contained. It already includes:

- FFmpeg and FFprobe
- yt-dlp
- Python and the required Python packages

Users **do not need to install FFmpeg, Python, or yt-dlp**, and no changes to
the Windows `PATH` environment variable are required.

Extract the ZIP before running the application and keep the complete
`DropDL-Windows` folder together. Do not move `DropDL.exe` out of that folder;
it relies on the bundled files in `_internal`.

Quick start:

1. Download `DropDL-Windows.zip`.
2. Select **Extract all** in Windows.
3. Open the extracted `DropDL-Windows` folder.
4. Run `DropDL.exe`.

Downloaded files are stored in:

```text
%USERPROFILE%\Downloads\DropDL
```

Windows SmartScreen may warn about an unsigned application. Code signing is
not currently configured for this project.

## Features

- Download video at the best available quality or a selected maximum height
- Extract audio as MP3, M4A, Opus, or WAV
- Inspect title, uploader, duration, and thumbnail before downloading
- Download a precise time range instead of the complete media
- Download individual videos or playlists
- Save English subtitles when available
- Show progress, speed, ETA, and post-processing status
- Queue up to 20 downloads, with two running at a time
- Restore download history and reconnect to active jobs after a page refresh
- Keep history across app restarts and report interrupted downloads
- Save playlists and subtitle files together as a ZIP
- Reopen the interface from the Windows notification area
- Run on localhost, with automatic fallback when the preferred port is busy

## Timeline Selection

Enable **Download a specific part**, then enter a start and end time. DropDL
accepts seconds, `MM:SS`, or `HH:MM:SS`:

```text
90
01:30
01:02:30
```

Accurate cuts may require FFmpeg to re-encode around the selected boundaries,
so a short clip can still take some time to process.
If a source rejects direct range downloads, DropDL retries by downloading
the source and trimming it locally. This fallback uses additional bandwidth
and disk space. Subtitle files retain their source timestamps.

## Desktop Runtime

`DropDL.exe` starts FastAPI and Uvicorn inside the same desktop process on an
available `127.0.0.1` port. It then opens the interface in the default browser.
Closing the browser does not stop active downloads; use the DropDL tray menu
to reopen or exit the app.

The desktop build does not use pywebview, Python.NET, or a separately installed
browser runtime.

## Release Verification

Every Windows build must pass two automated runtime checks before its ZIP is
created:

1. Start the frozen executable from the PyInstaller output folder.
2. Create the release ZIP, extract that exact archive, and start its executable.

Both checks request `/api/health`, load the real HTML interface, confirm the
process is frozen, confirm bundled FFmpeg is available, and verify clean
shutdown. A release contains:

```text
DropDL-Windows.zip
DropDL-Windows.sha256
DropDL-Windows.proof.json
```

To verify a downloaded archive in PowerShell:

```powershell
Get-FileHash .\DropDL-Windows.zip -Algorithm SHA256
Get-Content .\DropDL-Windows.sha256
```

The hashes must match.

## Development From Source

The following requirements apply only to developers running the source code,
not to users downloading the Windows release:

- Windows 10 or Windows 11
- Windows Python 3.11+ (64-bit Python 3.12 for building the desktop package)
- FFmpeg and FFprobe on `PATH` or in `vendor/ffmpeg` for audio and clips

```powershell
git clone https://github.com/samarth35/DropDL.git
cd DropDL
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

The interface opens automatically, normally at <http://127.0.0.1:8000>.
A second launch reopens the running app. If another application occupies
port 8000, DropDL selects a free port and prints its address.

Useful options:

```powershell
# Set up without starting the server
.\run.ps1 -SetupOnly
# Update installed packages within the pinned requirements
.\run.ps1 -Update
# Select a different port and open the browser yourself
.\run.ps1 -Port 8080 -NoBrowser
# Use a particular Python installation
.\run.ps1 -Python "C:\Path\To\Python312\python.exe"
```

For an existing Python environment, `python -m app` starts the same browser
interface on Windows, macOS, or Linux after installing `requirements.txt`.
Set `DROPDL_DOWNLOAD_DIR` to use a different download folder. Saved history
is kept alongside each download in `job.json`; remove a job's folder to
remove its saved files and history, then restart DropDL.

Playlist mode is explicit and limited to the first 50 items. With playlist
mode off, a video link containing a playlist downloads just that video;
a standalone playlist link downloads its first item. Clips apply to one
video at a time. Requested quality limits are respected; if the source has
no matching format, the download reports an error.

Run checks with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Media checks generate a short local sample and test video download, MP3
conversion, clipping, and file delivery. They require FFmpeg and FFprobe.
Website-specific authentication and restrictions still depend on the source.

## Build The Windows Package

Use 64-bit Python 3.12 and pass a shared FFmpeg `bin` directory when FFmpeg is
not already on `PATH`:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1 `
  -Python "C:\Path\To\Python312\python.exe" `
  -FfmpegBin "C:\Path\To\ffmpeg\bin" `
  -RecreateEnvironment
```

The script installs the locked Windows dependencies, builds with PyInstaller,
runs both packaged smoke tests, and writes the verified release artifacts to
`outputs`.

Tags matching `v*` run the same script in GitHub Actions and attach the ZIP,
checksum, and proof file to a GitHub Release. A failed runtime check prevents
the release step from running.

## Project Structure

```text
app/
  main.py                    API, yt-dlp jobs, trimming, and file delivery
static/
  index.html                 Browser interface
  styles.css                 Application styling
  app.js                     UI state and API requests
.github/workflows/
  release-windows.yml        Verified Windows release workflow
desktop.py                   Tray launcher and local server lifecycle
DropDL.spec                  PyInstaller configuration
build-windows.ps1            Reproducible packaging and release tests
run.ps1                      Development launcher
Start DropDL.cmd             Double-click browser launcher for Windows
requirements.txt             Direct runtime dependencies
requirements-build.txt       Direct packaging dependencies
requirements-windows.lock    Complete pinned Windows build environment
THIRD_PARTY_NOTICES.txt      Dependency and FFmpeg notices
```

Generated directories such as `.venv-build`, `vendor`, `work`, and `outputs`
are intentionally excluded from Git.

## Limitations

- Releases currently target 64-bit Windows only.
- Some websites require authentication or browser cookies that the interface
  does not yet expose.
- Website changes can require a newer yt-dlp release.
- The executable is not code-signed.

## Legal

Only download content you own or are authorized to access. You are responsible
for complying with applicable law and the source website's terms.

Third-party components retain their own licenses. See
[`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt).
