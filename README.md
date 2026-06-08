# DropDL

A Windows desktop interface for `yt-dlp`, built with FastAPI and pywebview.

## Download

Download the latest ready-to-run Windows build from
[GitHub Releases](../../releases/latest).

Extract `DropDL-Windows.zip`, then open `DropDL.exe`. Python, yt-dlp,
FFmpeg, and terminal commands are not required.

## Features

- Video and audio downloads
- Quality and audio-format selection
- Timeline cropping with start and end timestamps
- Download progress, speed, and ETA
- Optional English subtitles
- Bundled FFmpeg in packaged builds

## Development

Requirements:

- Windows 10 or 11
- Python 3.11+
- FFmpeg available on `PATH`

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Open <http://127.0.0.1:8000>.

## Build The Desktop App

Install FFmpeg on the build machine, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

Or provide its `bin` directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1 `
  -FfmpegBin "C:\path\to\ffmpeg\bin"
```

The portable app is created at:

```text
outputs\DropDL-Windows\DropDL.exe
outputs\DropDL-Windows.zip
```

Distribute the complete `DropDL-Windows` folder. End users do not need Python, yt-dlp, FFmpeg, or terminal commands. Downloads are saved to `Downloads\DropDL`.

## Notes

- Crop times accept seconds, `MM:SS`, or `HH:MM:SS`.
- Only download media you are authorized to access.
- Third-party licensing information is in `THIRD_PARTY_NOTICES.txt`.

## Publishing A Release

Push a version tag to trigger the Windows release workflow:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions builds the desktop app and attaches `DropDL-Windows.zip`
to the release automatically.
