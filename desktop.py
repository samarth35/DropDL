from __future__ import annotations

import socket
import threading
import time
import webbrowser
from contextlib import closing
from tkinter import Button, Label, Tk

import uvicorn

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
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="dropdl-server", daemon=True)
    thread.start()
    wait_for_server(port)

    root = Tk()
    root.title("DropDL")
    root.geometry("360x180")
    root.resizable(False, False)
    root.configure(background="#0d1426")

    Label(
        root,
        text="DropDL is running",
        font=("Segoe UI", 16, "bold"),
        foreground="white",
        background="#0d1426",
    ).pack(pady=(24, 5))
    Label(
        root,
        text="The downloader opens in your web browser.",
        font=("Segoe UI", 10),
        foreground="#bac2d2",
        background="#0d1426",
    ).pack()
    Button(
        root,
        text="Open DropDL",
        command=lambda: webbrowser.open(url),
        font=("Segoe UI", 10, "bold"),
        width=18,
        background="#ff6258",
        foreground="white",
        activebackground="#e84c44",
        activeforeground="white",
        borderwidth=0,
        cursor="hand2",
    ).pack(pady=20)

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=3)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", stop)
    root.after(250, lambda: webbrowser.open(url))
    root.mainloop()


if __name__ == "__main__":
    main()
