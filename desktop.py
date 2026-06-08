from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from contextlib import closing
from pathlib import Path

import pystray
import uvicorn
from PIL import Image, ImageDraw
from pystray import MenuItem

from app.main import FFMPEG_DIR, app

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DropDL"
LOG_FILE = APP_DIR / "dropdl.log"


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_file,
        filemode="w",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
        force=True,
    )


def log_unhandled(exc_type, exc_value, exc_traceback) -> None:
    logging.critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def show_startup_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{message}\n\nDetails were written to:\n{LOG_FILE}",
            "DropDL could not start",
            0x10,
        )


def available_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/health"


def wait_for_health(port: int, timeout: float = 15) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url(port), timeout=1) as response:
                data = json.load(response)
                if response.status == 200 and data.get("ok") is True:
                    return data
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"DropDL server did not become healthy: {last_error}")


def start_server(port: int) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        loop="asyncio",
        http="h11",
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    def run() -> None:
        try:
            server.run()
        except Exception:
            logging.exception("FastAPI server stopped unexpectedly")

    thread = threading.Thread(target=run, name="dropdl-server")
    thread.start()
    return server, thread


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)
    if thread.is_alive():
        logging.error("FastAPI server did not stop within five seconds")


def media_tool_versions() -> dict[str, str]:
    if not FFMPEG_DIR:
        raise RuntimeError("FFmpeg is not available.")

    versions: dict[str, str] = {}
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    for name in ("ffmpeg", "ffprobe"):
        executable = FFMPEG_DIR / f"{name}.exe"
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            check=True,
            creationflags=creation_flags,
            text=True,
            timeout=10,
        )
        versions[name] = completed.stdout.splitlines()[0]
    return versions


def tray_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), "#0d1426")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 6, 58, 58), radius=13, fill="#ff6258")
    draw.line((32, 17, 32, 40), fill="white", width=6)
    draw.line((22, 31, 32, 41, 42, 31), fill="white", width=6, joint="curve")
    draw.line((18, 48, 46, 48), fill="white", width=5)
    return image


def run_smoke_test(result_path: Path) -> int:
    port = available_port()
    logging.info("Starting packaged smoke test on port %s", port)
    result: dict[str, object]
    return_code = 1
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    try:
        server, thread = start_server(port)
        health = wait_for_health(port)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
            html = response.read().decode("utf-8")
        result = {
            "ok": True,
            "health": health,
            "media_tools": media_tool_versions(),
            "page_status": response.status,
            "title_present": "<title>DropDL</title>" in html,
            "frozen": bool(getattr(sys, "frozen", False)),
        }
        return_code = 0 if result["title_present"] else 1
    except Exception as exc:
        logging.exception("Packaged smoke test failed")
        result = {"ok": False, "error": str(exc)}
        return_code = 1
    finally:
        if server and thread:
            stop_server(server, thread)

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logging.info("Packaged smoke test finished with exit code %s", return_code)
    return return_code


def run_desktop() -> int:
    port = available_port()
    url = f"http://127.0.0.1:{port}"
    server, thread = start_server(port)
    try:
        wait_for_health(port)
        logging.info("DropDL started at %s", url)
    except Exception as exc:
        logging.exception("DropDL could not start")
        stop_server(server, thread)
        show_startup_error(str(exc))
        return 1

    icon: pystray.Icon

    def open_app() -> None:
        webbrowser.open(url)

    def exit_app() -> None:
        icon.stop()

    icon = pystray.Icon(
        "DropDL",
        tray_image(),
        "DropDL",
        menu=pystray.Menu(
            MenuItem("Open DropDL", open_app, default=True),
            MenuItem("Exit", exit_app),
        ),
    )
    threading.Timer(0.5, open_app).start()
    try:
        icon.run()
    except Exception as exc:
        logging.exception("System tray failed")
        show_startup_error(str(exc))
        return 1
    finally:
        stop_server(server, thread)
        logging.info("DropDL stopped")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_file = args.smoke_test.with_suffix(".log") if args.smoke_test else LOG_FILE
    configure_logging(log_file)
    sys.excepthook = log_unhandled
    if args.smoke_test:
        return run_smoke_test(args.smoke_test)
    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
