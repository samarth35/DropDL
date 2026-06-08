from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import download_range_func
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
STATIC_DIR = BASE_DIR / "static"


def user_download_dir() -> Path:
    configured = os.environ.get("DROPDL_DOWNLOAD_DIR")
    if configured:
        return Path(configured).expanduser()
    if getattr(sys, "frozen", False):
        return Path.home() / "Downloads" / "DropDL"
    return Path(__file__).resolve().parent.parent / "downloads"


def ffmpeg_dir() -> Path | None:
    bundled = BASE_DIR / "ffmpeg"
    if (bundled / "ffmpeg.exe").is_file():
        return bundled
    executable = shutil.which("ffmpeg")
    return Path(executable).parent if executable else None


DOWNLOAD_DIR = user_download_dir()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_DIR = ffmpeg_dir()

app = FastAPI(title="DropDL", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class URLRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class DownloadRequest(URLRequest):
    mode: str = "video"
    quality: str = "best"
    audio_format: str = "mp3"
    subtitles: bool = False
    trim_enabled: bool = False
    start_time: float | None = Field(default=None, ge=0)
    end_time: float | None = Field(default=None, gt=0)


@dataclass
class DownloadJob:
    id: str
    url: str
    mode: str
    status: str = "queued"
    title: str = "Preparing download"
    thumbnail: str | None = None
    progress: float = 0
    speed: str = ""
    eta: str = ""
    filename: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


jobs: dict[str, DownloadJob] = {}
jobs_lock = threading.Lock()


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "Enter a valid http(s) media URL.")
    return value


def clean_info(info: dict[str, Any]) -> dict[str, Any]:
    entries = info.get("entries")
    if entries:
        first = next((entry for entry in entries if entry), {})
        return {
            "title": info.get("title") or "Playlist",
            "thumbnail": first.get("thumbnail"),
            "uploader": info.get("uploader") or first.get("uploader"),
            "duration": first.get("duration"),
            "playlist_count": info.get("playlist_count") or len(entries),
            "is_playlist": True,
        }
    return {
        "title": info.get("title") or "Untitled media",
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "playlist_count": None,
        "is_playlist": False,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "ffmpeg": FFMPEG_DIR is not None,
        "download_dir": str(DOWNLOAD_DIR),
        "active_jobs": sum(job.status in {"queued", "downloading"} for job in jobs.values()),
    }


@app.post("/api/info")
async def media_info(request: URLRequest) -> dict[str, Any]:
    url = validate_url(request.url)

    def extract() -> dict[str, Any]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "playlistend": 50,
        }
        if FFMPEG_DIR:
            options["ffmpeg_location"] = str(FFMPEG_DIR)
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(extract)
        return clean_info(info)
    except Exception as exc:
        raise HTTPException(400, f"Could not read that URL: {exc}") from exc


def format_selector(mode: str, quality: str) -> str:
    if mode == "audio":
        return "bestaudio/best"
    heights = {"1080": 1080, "720": 720, "480": 480, "360": 360}
    if quality in heights:
        height = heights[quality]
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
    return "bestvideo+bestaudio/best"


def validate_trim(request: DownloadRequest) -> None:
    if not request.trim_enabled:
        request.start_time = None
        request.end_time = None
        return
    if request.start_time is None:
        request.start_time = 0
    if request.end_time is None:
        raise HTTPException(400, "Enter an end time for the selected clip.")
    if request.end_time <= request.start_time:
        raise HTTPException(400, "End time must be later than start time.")
    if request.end_time - request.start_time < 0.25:
        raise HTTPException(400, "The selected clip must be at least 0.25 seconds long.")


def update_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            for key, value in changes.items():
                setattr(job, key, value)


def run_download(job_id: str, request: DownloadRequest) -> None:
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def hook(data: dict[str, Any]) -> None:
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            progress = round(downloaded * 100 / total, 1) if total else 0
            update_job(
                job_id,
                status="downloading",
                progress=progress,
                speed=re.sub(r"\x1b\[[0-9;]*m", "", data.get("_speed_str") or "").strip(),
                eta=re.sub(r"\x1b\[[0-9;]*m", "", data.get("_eta_str") or "").strip(),
            )
        elif status == "finished":
            update_job(job_id, status="processing", progress=100, speed="", eta="")

    options: dict[str, Any] = {
        "format": format_selector(request.mode, request.quality),
        "outtmpl": str(job_dir / "%(title).180B [%(id)s].%(ext)s"),
        "noplaylist": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
    }
    if FFMPEG_DIR:
        options["ffmpeg_location"] = str(FFMPEG_DIR)
    if request.trim_enabled:
        options.update(
            {
                "download_ranges": download_range_func(
                    None,
                    [(request.start_time or 0, request.end_time)],
                ),
                "force_keyframes_at_cuts": True,
            }
        )
    if request.subtitles:
        options.update({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en", "en.*"]})
    if request.mode == "audio":
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": request.audio_format,
                "preferredquality": "192",
            }
        ]
    else:
        options["merge_output_format"] = "mp4"

    try:
        update_job(job_id, status="downloading")
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(request.url, download=True)
            title = info.get("title") or "Downloaded media"
            thumbnail = info.get("thumbnail")

        candidates = [
            path
            for path in job_dir.iterdir()
            if path.is_file() and path.suffix.lower() not in {".part", ".ytdl", ".vtt", ".srt", ".json"}
        ]
        if not candidates:
            raise RuntimeError("The download completed but no media file was found.")
        output = max(candidates, key=lambda path: path.stat().st_mtime)
        update_job(
            job_id,
            status="complete",
            progress=100,
            title=title,
            thumbnail=thumbnail,
            filename=output.name,
        )
    except Exception as exc:
        update_job(job_id, status="error", error=str(exc))


@app.post("/api/download")
async def create_download(request: DownloadRequest) -> dict[str, str]:
    request.url = validate_url(request.url)
    if request.mode not in {"video", "audio"}:
        raise HTTPException(400, "Mode must be video or audio.")
    if request.audio_format not in {"mp3", "m4a", "opus", "wav"}:
        raise HTTPException(400, "Unsupported audio format.")
    validate_trim(request)

    job_id = uuid.uuid4().hex
    job = DownloadJob(id=job_id, url=request.url, mode=request.mode)
    with jobs_lock:
        jobs[job_id] = job
    threading.Thread(target=run_download, args=(job_id, request), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Download job not found.")
        return asdict(job)


@app.get("/api/jobs/{job_id}/file")
async def download_file(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.status != "complete" or not job.filename:
            raise HTTPException(404, "Completed file not found.")
        filename = job.filename

    job_dir = (DOWNLOAD_DIR / job_id).resolve()
    file_path = (job_dir / filename).resolve()
    if job_dir not in file_path.parents or not file_path.is_file():
        raise HTTPException(404, "File not found.")
    return FileResponse(file_path, filename=file_path.name, media_type="application/octet-stream")
