from __future__ import annotations

import socket
import threading
import time
import webbrowser
from contextlib import closing

import pystray
import uvicorn
from PIL import Image, ImageDraw
from pystray import MenuItem

from app.main import app


def available_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(port: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("DropDL could not start its local server.")


def tray_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), "#0d1426")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 6, 58, 58), radius=13, fill="#ff6258")
    draw.line((32, 17, 32, 40), fill="white", width=6)
    draw.line((22, 31, 32, 41, 42, 31), fill="white", width=6, joint="curve")
    draw.line((18, 48, 46, 48), fill="white", width=5)
    return image


def main() -> None:
    port = available_port()
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    icon: pystray.Icon

    def open_app() -> None:
        webbrowser.open(url)

    def stop_app() -> None:
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "DropDL",
        tray_image(),
        "DropDL",
        menu=pystray.Menu(
            MenuItem("Open DropDL", open_app, default=True),
            MenuItem("Exit", stop_app),
        ),
    )
    tray_thread = threading.Thread(target=icon.run, name="dropdl-tray", daemon=True)
    tray_thread.start()
    threading.Thread(target=lambda: (wait_for_server(port), open_app()), daemon=True).start()
    server.run()
    icon.stop()


if __name__ == "__main__":
    main()
