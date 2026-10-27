from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from yt_dlp.utils import download_range_func

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
STATIC_DIR = BASE_DIR / "static"
ACTIVE_STATES = {"queued", "downloading", "processing"}
MAX_PENDING = 20
PLAYLIST_LIMIT = 50
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v", ".ts",
                    ".mp3", ".m4a", ".opus", ".wav", ".ogg", ".aac", ".flac", ".weba"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".lrc", ".ttml", ".srv1", ".srv2", ".srv3", ".json3"}
logger = logging.getLogger(__name__)


def user_download_dir() -> Path:
    configured = os.environ.get("DROPDL_DOWNLOAD_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / "Downloads" / "DropDL"


def ffmpeg_dir() -> Path | None:
    for folder in (BASE_DIR / "ffmpeg", BASE_DIR / "vendor" / "ffmpeg"):
        if (folder / "ffmpeg.exe").is_file() and (folder / "ffprobe.exe").is_file():
            return folder
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg and ffprobe and Path(ffmpeg).parent == Path(ffprobe).parent:
        return Path(ffmpeg).parent
    return None


DOWNLOAD_DIR = user_download_dir()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_DIR = ffmpeg_dir()
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dropdl")
app = FastAPI(title="DropDL", version="1.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def local_requests(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        if origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "Open DropDL on this device to start a download."}, status_code=403)
    return await call_next(request)


class URLRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    url: str = Field(min_length=8, max_length=4096)


class DownloadRequest(URLRequest):
    mode: Literal["video", "audio"] = "video"
    quality: Literal["best", "1080", "720", "480", "360"] = "best"
    audio_format: Literal["mp3", "m4a", "opus", "wav"] = "mp3"
    subtitles: bool = False
    playlist: bool = False
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
    files: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)


jobs: dict[str, DownloadJob] = {}
jobs_lock = threading.RLock()


def persist_job(job: DownloadJob) -> None:
    folder = DOWNLOAD_DIR / job.id
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "job.json.tmp"
    temporary.write_text(json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")
    temporary.replace(folder / "job.json")


def load_history() -> None:
    for manifest in DOWNLOAD_DIR.glob("*/job.json"):
        if not re.fullmatch(r"[a-f0-9]{32}", manifest.parent.name):
            continue
        try:
            job = DownloadJob(**json.loads(manifest.read_text(encoding="utf-8")))
            if job.id != manifest.parent.name:
                continue
            if job.status in ACTIVE_STATES:
                job.status = "error"
                job.error = "DropDL stopped before this download finished. Start it again to retry."
                persist_job(job)
            if job.status == "complete" and (
                not job.filename or Path(job.filename).name != job.filename
                or not (manifest.parent / job.filename).is_file()
            ):
                job.status = "error"
                job.error = "The saved file has been moved or deleted. Download it again."
            jobs[job.id] = job
        except (OSError, ValueError, TypeError):
            logger.warning("Could not restore download history from %s", manifest)


load_history()


def validate_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlparse(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
        parsed.port  # Reject malformed ports before sending the URL to yt-dlp.
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(400, "Enter a valid http(s) media URL without embedded credentials.")
    return value


def clean_info(info: dict[str, Any]) -> dict[str, Any]:
    entries = info.get("entries")
    is_playlist = entries is not None
    entries = list(entries or [])
    first = next((entry for entry in entries if entry), {}) if is_playlist else info
    return {
        "title": info.get("title") or "Untitled media",
        "thumbnail": info.get("thumbnail") or first.get("thumbnail"),
        "uploader": info.get("uploader") or first.get("uploader") or first.get("channel"),
        "duration": None if is_playlist else info.get("duration"),
        "playlist_count": (info.get("playlist_count") or len(entries)) if is_playlist else None,
        "is_playlist": is_playlist,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    with jobs_lock:
        active = sum(job.status in ACTIVE_STATES for job in jobs.values())
    return {"ok": True, "app": "DropDL", "version": app.version, "ffmpeg": FFMPEG_DIR is not None,
            "download_dir": str(DOWNLOAD_DIR), "active_jobs": active}


@app.post("/api/info")
async def media_info(request: URLRequest) -> dict[str, Any]:
    url = validate_url(request.url)

    def extract() -> dict[str, Any]:
        options = {"quiet": True, "no_warnings": True, "skip_download": True,
                   "extract_flat": "in_playlist", "playlistend": PLAYLIST_LIMIT,
                   "noplaylist": True, "socket_timeout": 30}
        if FFMPEG_DIR:
            options["ffmpeg_location"] = str(FFMPEG_DIR)
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(extract)
        if not info:
            raise ValueError("No media was found at this URL.")
        return clean_info(info)
    except Exception as exc:
        raise HTTPException(400, f"Could not read that URL: {exc}") from exc


def format_selector(mode: str, quality: str, has_ffmpeg: bool = True) -> str:
    if mode == "audio":
        return "bestaudio/best"
    limit = f"[height<={quality}]" if quality != "best" else ""
    if not has_ffmpeg:
        return f"best{limit}"
    return f"bestvideo{limit}+bestaudio/best{limit}"


def validate_trim(request: DownloadRequest) -> None:
    if not request.trim_enabled:
        request.start_time = request.end_time = None
        return
    if request.playlist:
        raise HTTPException(400, "Turn off playlist download to trim a single video.")
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
            changed_status = changes.get("status", job.status) != job.status
            for key, value in changes.items():
                setattr(job, key, value)
            if changed_status:
                try:
                    persist_job(job)
                except OSError:
                    logger.exception("Could not save download history")


def trim_local_media(job_dir: Path, request: DownloadRequest) -> None:
    """Fallback for sources that cannot be seeked by FFmpeg over HTTP."""
    for source in sorted(job_dir.iterdir()):
        if source.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        suffix = source.suffix if request.mode == "audio" else ".mp4"
        temporary = source.with_name(source.stem + ".clip" + suffix)
        destination = source.with_suffix(suffix)
        executable = FFMPEG_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        command = [str(executable), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-ss", str(request.start_time or 0), "-i", str(source),
                   "-t", str(request.end_time - (request.start_time or 0))]
        if request.mode == "video":
            command += ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart"]
        else:
            codecs = {"mp3": "libmp3lame", "m4a": "aac", "opus": "libopus", "wav": "pcm_s16le"}
            command += ["-vn", "-c:a", codecs[request.audio_format]]
        completed = subprocess.run(command + [str(temporary)], capture_output=True, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                   timeout=3600)
        if completed.returncode or not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError(f"Could not trim the downloaded media: {completed.stderr[-800:]}")
        temporary.replace(destination)
        if source != destination:
            source.unlink()


def run_download(job_id: str, request: DownloadRequest) -> None:
    job_dir = DOWNLOAD_DIR / job_id

    def hook(data: dict[str, Any]) -> None:
        info = data.get("info_dict") or {}
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            update_job(job_id, status="downloading", title=info.get("title") or "Downloading media",
                       thumbnail=info.get("thumbnail"), progress=round(downloaded * 100 / total, 1) if total else 0,
                       speed=re.sub(r"\x1b\[[0-9;]*m", "", data.get("_speed_str") or "").strip(),
                       eta=re.sub(r"\x1b\[[0-9;]*m", "", data.get("_eta_str") or "").strip())
        elif data.get("status") == "finished":
            update_job(job_id, status="processing", progress=100, speed="", eta="")

    options: dict[str, Any] = {
        "format": format_selector(request.mode, request.quality, FFMPEG_DIR is not None),
        "outtmpl": str(job_dir / "%(title).180B [%(id)s].%(ext)s"),
        "noplaylist": not request.playlist,
        "playlistend": PLAYLIST_LIMIT if request.playlist else 1,
        "restrictfilenames": True, "windowsfilenames": True,
        "progress_hooks": [hook], "quiet": True, "no_warnings": True,
        "socket_timeout": 30, "retries": 3, "fragment_retries": 3,
    }
    if FFMPEG_DIR:
        options["ffmpeg_location"] = str(FFMPEG_DIR)
    if request.trim_enabled:
        options.update({"download_ranges": download_range_func(None, [(request.start_time or 0, request.end_time)]),
                        "force_keyframes_at_cuts": True})
    if request.subtitles:
        options.update({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en", "en.*"]})
    if request.mode == "audio":
        options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": request.audio_format,
                                      "preferredquality": "192"}]
    elif FFMPEG_DIR:
        options["merge_output_format"] = "mp4"

    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        update_job(job_id, status="downloading")
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(request.url, download=True)
        except yt_dlp.utils.DownloadError:
            if not request.trim_enabled:
                raise
            update_job(job_id, status="downloading", progress=0, title="Downloading source for a reliable clip")
            options.pop("download_ranges", None)
            options.pop("force_keyframes_at_cuts", None)
            options.update({"overwrites": True, "continuedl": False})
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(request.url, download=True)
            update_job(job_id, status="processing", progress=100, speed="", eta="")
            trim_local_media(job_dir, request)
        if not info:
            raise RuntimeError("No downloadable media was found.")
        media = sorted(path for path in job_dir.iterdir() if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS)
        if not media:
            raise RuntimeError("The download completed but no media file was found.")
        files = media + sorted(path for path in job_dir.iterdir() if path.is_file() and path.suffix.lower() in SUBTITLE_EXTENSIONS)
        output = media[0]
        if len(files) > 1:
            update_job(job_id, status="processing", progress=100, speed="", eta="")
            output = job_dir / "DropDL-files.zip"
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                for path in files:
                    archive.write(path, arcname=path.name)
        update_job(job_id, status="complete", progress=100, speed="", eta="",
                   title=info.get("title") or "Downloaded media", thumbnail=info.get("thumbnail"),
                   filename=output.name, files=[path.name for path in files])
    except Exception as exc:
        update_job(job_id, status="error", speed="", eta="", error=str(exc))


@app.post("/api/download", status_code=202)
async def create_download(request: DownloadRequest) -> dict[str, str]:
    request.url = validate_url(request.url)
    validate_trim(request)
    if FFMPEG_DIR is None and (request.mode == "audio" or request.trim_enabled):
        raise HTTPException(400, "FFmpeg and ffprobe are required for audio conversion and clips. Install them and restart DropDL.")
    with jobs_lock:
        if sum(job.status in ACTIVE_STATES for job in jobs.values()) >= MAX_PENDING:
            raise HTTPException(429, "The queue is full. Wait for a download to finish.")
        job_id = uuid.uuid4().hex
        job = DownloadJob(id=job_id, url=request.url, mode=request.mode)
        try:
            persist_job(job)
        except OSError as exc:
            raise HTTPException(503, "Cannot write to the download folder. Check its permissions and available space.") from exc
        jobs[job_id] = job
        executor.submit(run_download, job_id, request)
    return {"job_id": job_id}


@app.get("/api/jobs")
async def job_history() -> list[dict[str, Any]]:
    with jobs_lock:
        return [asdict(job) for job in sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)[:100]]


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
        raise HTTPException(404, "File not found. It may have been moved or deleted.")
    return FileResponse(file_path, filename=file_path.name, media_type="application/octet-stream")
