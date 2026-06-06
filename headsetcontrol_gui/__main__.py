"""Entry point: `python -m headsetcontrol_gui`.

Enforces a single running instance: launching again just raises the window
of the instance that's already running (and never stacks up duplicate pollers
fighting over the USB device)."""

from __future__ import annotations

import os
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from . import backend
from .tray import HeadsetTray

SERVER_NAME = f"headsetcontrol-gui-{os.getuid()}"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("HeadsetControl GUI")
    # Tray app: don't quit when the window closes.
    app.setQuitOnLastWindowClosed(False)

    # --- single instance: if one is already running, ask it to show & exit ---
    probe = QLocalSocket()
    probe.connectToServer(SERVER_NAME)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return 0
    probe.abort()

    if backend.binary_path() is None:
        QMessageBox.critical(
            None,
            "headsetcontrol not found",
            "The 'headsetcontrol' command was not found on your PATH.\n\n"
            "Install it from https://github.com/Sapd/HeadsetControl and try again.",
        )
        return 1

    # Become the primary instance. removeServer clears a stale socket left by
    # a crashed previous run.
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    # --hidden / --tray: start minimized to the tray (used by autostart).
    start_hidden = "--hidden" in sys.argv or "--tray" in sys.argv
    tray = HeadsetTray(app, start_hidden=start_hidden)  # kept alive by QApplication

    def on_second_launch():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        tray.open_window()

    server.newConnection.connect(on_second_launch)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
