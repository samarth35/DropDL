"""Start DropDL in a browser, reusing a running instance when possible."""
from __future__ import annotations

import argparse
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn


def is_dropdl(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1) as response:
            data = json.load(response)
            return isinstance(data, dict) and data.get("app") == "DropDL"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_when_ready(url: str) -> None:
    for _ in range(100):
        if is_dropdl(url):
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DropDL locally and open your browser.")
    parser.add_argument("--port", type=int, default=8000, help="Preferred port; 0 chooses any free port.")
    parser.add_argument("--no-browser", action="store_true", help="Run without opening a browser tab.")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", args.port))
        except OSError:
            existing = f"http://127.0.0.1:{args.port}"
            if is_dropdl(existing):
                print(f"DropDL is already running: {existing}", flush=True)
                if not args.no_browser:
                    webbrowser.open(existing)
                return
            sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        print(f"\nDropDL: {url}\nKeep this window open. Press Ctrl+C to stop.\n", flush=True)
        if not args.no_browser:
            threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
        server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", log_level="info", access_log=False))
        server.run(sockets=[sock])


if __name__ == "__main__":
    main()
