from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.__main__ import is_dropdl, open_when_ready
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class OtherAppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"[]")

    def log_message(self, *args):
        pass


class LauncherTests(unittest.TestCase):
    def test_busy_port_falls_back_and_second_launch_reuses_app(self):
        with tempfile.TemporaryDirectory(prefix="dropdl-launch-") as directory:
            other = ThreadingHTTPServer(("127.0.0.1", 0), OtherAppHandler)
            threading.Thread(target=other.serve_forever, daemon=True).start()
            self.addCleanup(other.server_close)
            self.addCleanup(other.shutdown)
            self.assertFalse(is_dropdl(f"http://127.0.0.1:{other.server_port}"))
            env = {**os.environ, "DROPDL_DOWNLOAD_DIR": directory}
            process = subprocess.Popen(
                [sys.executable, "-m", "app", "--no-browser", "--port", str(other.server_port)],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            output = queue.Queue()
            def read_output():
                for line in process.stdout:
                    output.put(line)
            threading.Thread(target=read_output, daemon=True).start()
            try:
                deadline = time.monotonic() + 30
                url = None
                while time.monotonic() < deadline:
                    try:
                        line = output.get(timeout=1)
                    except queue.Empty:
                        continue
                    match = re.search(r"DropDL: (http://127\.0\.0\.1:\d+)", line)
                    if match:
                        url = match.group(1)
                        break
                self.assertIsNotNone(url, "Launcher did not print its URL")
                self.assertNotEqual(int(url.rsplit(":", 1)[1]), other.server_port)
                while not is_dropdl(url) and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertTrue(is_dropdl(url))
                with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
                    self.assertEqual(json.load(response)["download_dir"], str(Path(directory).resolve()))
                second = subprocess.run(
                    [sys.executable, "-m", "app", "--no-browser", "--port", url.rsplit(":", 1)[1]],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertIn("already running", second.stdout)
                with patch("app.__main__.webbrowser.open") as open_browser:
                    open_when_ready(url)
                    open_browser.assert_called_once_with(url)
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stdout.close()

    def test_invalid_port_has_actionable_error(self):
        result = subprocess.run([sys.executable, "-m", "app", "--port", "65536", "--no-browser"], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertIn("between 0 and 65535", result.stderr)


if __name__ == "__main__":
    unittest.main()
