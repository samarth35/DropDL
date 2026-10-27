from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import_root = tempfile.TemporaryDirectory(prefix="dropdl-import-")
os.environ["DROPDL_DOWNLOAD_DIR"] = import_root.name
from app import main  # noqa: E402


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="dropdl-test-")
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)
        self.patch = patch.object(main, "DOWNLOAD_DIR", self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        with main.jobs_lock:
            main.jobs.clear()
        self.client = TestClient(main.app, base_url="http://127.0.0.1")

    def new_job(self, **kwargs):
        job = main.DownloadJob(id=uuid.uuid4().hex, url="https://example.com/media.mp4", mode="video", **kwargs)
        with main.jobs_lock:
            main.jobs[job.id] = job
        main.persist_job(job)
        return job

    def test_page_and_health(self):
        self.assertIn("<title>DropDL</title>", self.client.get("/").text)
        self.assertEqual(self.client.get("/api/health").json()["app"], "DropDL")
        self.assertEqual(self.client.get("/static/icon.svg").status_code, 200)

    def test_invalid_urls_do_not_start_workers(self):
        with patch.object(main.executor, "submit") as submit:
            for url in ("file:///private.mp4", "https://[broken", "https://user:secret@example.com/a", "https://example.com:wrong/a"):
                with self.subTest(url=url):
                    self.assertEqual(self.client.post("/api/download", json={"url": url}).status_code, 400)
            submit.assert_not_called()

    def test_invalid_options_and_nonfinite_times(self):
        for payload in ({"quality": "9999"}, {"mode": "bogus"}, {"audio_format": "exe"}, {"end_time": "Infinity"}):
            with self.subTest(payload=payload):
                result = self.client.post("/api/download", json={"url": "https://example.com/a", **payload})
                self.assertEqual(result.status_code, 422)

    def test_bad_clip_ranges(self):
        for options in ({}, {"start_time": 5, "end_time": 4}, {"start_time": 1, "end_time": 1.1}, {"playlist": True, "end_time": 5}):
            with self.subTest(options=options):
                result = self.client.post("/api/download", json={"url": "https://example.com/a", "trim_enabled": True, **options})
                self.assertEqual(result.status_code, 400)

    def test_missing_ffmpeg_fails_before_queueing(self):
        with patch.object(main, "FFMPEG_DIR", None), patch.object(main.executor, "submit") as submit:
            result = self.client.post("/api/download", json={"url": "https://example.com/a", "mode": "audio"})
            self.assertEqual(result.status_code, 400)
            self.assertIn("FFmpeg", result.json()["detail"])
            submit.assert_not_called()
        self.assertEqual(main.format_selector("video", "720", False), "best[height<=720]")
        self.assertNotIn("/best", main.format_selector("video", "720").replace("/best[height<=720]", ""))

    def test_queue_limit_and_processing_count(self):
        for _ in range(main.MAX_PENDING):
            self.new_job(status="processing")
        self.assertEqual(self.client.get("/api/health").json()["active_jobs"], main.MAX_PENDING)
        with patch.object(main.executor, "submit") as submit:
            self.assertEqual(self.client.post("/api/download", json={"url": "https://example.com/a"}).status_code, 429)
            submit.assert_not_called()

    def test_cross_origin_and_rebinding_requests(self):
        result = self.client.post("/api/download", json={"url": "https://example.com/a"}, headers={"Origin": "https://unrelated.example"})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "unrelated.example"}).status_code, 400)

    def test_history_survives_restart_and_marks_interrupted(self):
        complete = self.new_job(status="complete", filename="sample.mp4", title="Saved sample")
        (self.directory / complete.id / "sample.mp4").write_bytes(b"media")
        interrupted = self.new_job(status="processing")
        main.jobs.clear()
        main.load_history()
        history = self.client.get("/api/jobs").json()
        self.assertEqual(len(history), 2)
        self.assertEqual(main.jobs[complete.id].status, "complete")
        self.assertEqual(main.jobs[interrupted.id].status, "error")
        self.assertIn("stopped", main.jobs[interrupted.id].error)

    def test_missing_saved_file_is_reported(self):
        job = self.new_job(status="complete", filename="moved.mp4")
        main.jobs.clear()
        main.load_history()
        self.assertEqual(main.jobs[job.id].status, "error")
        self.assertEqual(self.client.get(f"/api/jobs/{job.id}/file").status_code, 404)

    def test_file_delivery_blocks_traversal(self):
        job = self.new_job(status="complete", filename="../secret.txt")
        (self.directory / "secret.txt").write_text("private")
        self.assertEqual(self.client.get(f"/api/jobs/{job.id}/file").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/unknown").status_code, 404)

    def test_playlist_and_subtitles_are_all_in_zip(self):
        job = self.new_job()
        folder = self.directory / job.id

        class FakeDownloader:
            def __init__(self, options):
                self.options = options
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, url, download):
                (folder / "first.mp4").write_bytes(b"first")
                (folder / "second.mp4").write_bytes(b"second")
                (folder / "first.en.vtt").write_text("WEBVTT\n")
                (folder / "unfinished.mp4.part").write_bytes(b"partial")
                return {"title": "Two videos"}

        with patch.object(main.yt_dlp, "YoutubeDL", FakeDownloader):
            main.run_download(job.id, main.DownloadRequest(url=job.url, playlist=True, subtitles=True))
        self.assertEqual(main.jobs[job.id].status, "complete")
        response = self.client.get(f"/api/jobs/{job.id}/file")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"first.mp4", "second.mp4", "first.en.vtt"})

    def test_worker_error_is_visible_and_saved(self):
        job = self.new_job()
        with patch.object(main.yt_dlp, "YoutubeDL", side_effect=RuntimeError("Source unavailable")):
            main.run_download(job.id, main.DownloadRequest(url=job.url))
        saved = json.loads((self.directory / job.id / "job.json").read_text())
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["error"], "Source unavailable")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(main.FFMPEG_DIR, "FFmpeg and ffprobe are needed for media integration checks")
class MediaIntegrationTests(unittest.TestCase):
    setUp = DownloadTests.setUp

    def test_real_video_audio_and_clip(self):
        executable = main.FFMPEG_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        probe = main.FFMPEG_DIR / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        source = self.directory / "sample.mp4"
        subprocess.run([str(executable), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, timeout=30)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(self.directory)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/sample.mp4"
        self.assertEqual(self.client.post("/api/info", json={"url": url}).status_code, 200)
        for options, extension, duration in [({}, ".mp4", 5), ({"mode": "audio"}, ".mp3", 5), ({"trim_enabled": True, "start_time": 1, "end_time": 3}, ".mp4", 2), ({"mode": "audio", "trim_enabled": True, "start_time": 1, "end_time": 3}, ".mp3", 2)]:
            with self.subTest(options=options):
                result = self.client.post("/api/download", json={"url": url, **options})
                self.assertEqual(result.status_code, 202, result.text)
                job_id = result.json()["job_id"]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    job = self.client.get(f"/api/jobs/{job_id}").json()
                    if job["status"] in {"complete", "error"}:
                        break
                    time.sleep(0.1)
                self.assertEqual(job["status"], "complete", job)
                self.assertTrue(job["filename"].endswith(extension), job)
                self.assertGreater(len(self.client.get(f"/api/jobs/{job_id}/file").content), 1000)
                output = self.directory / job_id / job["filename"]
                measured = subprocess.check_output([str(probe), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(output)], text=True, timeout=10)
                self.assertAlmostEqual(float(measured), duration, delta=0.3)


if __name__ == "__main__":
    unittest.main()
