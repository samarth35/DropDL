from __future__ import annotations

import socket
import threading
import time
from contextlib import closing

import uvicorn
import webview

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


def main() -> None:
    port = available_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="dropdl-server", daemon=True)
    thread.start()
    wait_for_server(port)

    window = webview.create_window(
        "DropDL",
        f"http://127.0.0.1:{port}",
        width=1240,
        height=900,
        min_size=(820, 650),
        background_color="#0d1426",
    )

    def stop_server() -> None:
        server.should_exit = True
        thread.join(timeout=3)

    window.events.closed += stop_server
    webview.start(gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
