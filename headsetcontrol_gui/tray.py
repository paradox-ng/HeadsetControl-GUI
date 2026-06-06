"""Tray + app controller. The tray menu is intentionally minimal (battery +
Open + Quit); all real controls live in the ControlWindow."""

from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import backend
from .backend import DeviceState, HeadsetControlError
from .window import ControlWindow, battery_icon

POLL_MS = 60_000  # refresh battery / connection once a minute
APPLY_DEBOUNCE_MS = 250  # wait for the slider to settle before calling the CLI


class HeadsetTray:
    def __init__(self, app: QApplication, start_hidden: bool = False):
        self.app = app
        self.settings = QSettings("headsetcontrol-gui", "headsetcontrol-gui")
        # Persisted desired state - the CLI can't tell us the real values.
        self.sidetone = int(self.settings.value("sidetone", 0))
        self.lights = self.settings.value("lights", True, type=bool)
        self.tray_visible = self.settings.value("tray_visible", True, type=bool)
        self.restore_on_startup = self.settings.value(
            "restore_on_startup", True, type=bool
        )
        self.state = DeviceState()
        # Tracks connection edges so we can re-apply settings on (re)connect.
        self._was_connected = False

        self.app_icon = QIcon.fromTheme("audio-headset")
        if self.app_icon.isNull():
            self.app_icon = QIcon.fromTheme("audio-headphones")

        # Window
        self.window = ControlWindow()
        self.window.set_controls(
            self.sidetone, self.lights, self.tray_visible, self.restore_on_startup
        )
        self.window.sidetoneChanged.connect(self._queue_sidetone)
        self.window.lightsToggled.connect(self._toggle_lights)
        self.window.playNotification.connect(self._play_notification)
        self.window.trayVisibilityChanged.connect(self._set_tray_visible)
        self.window.restoreOnStartupChanged.connect(self._set_restore_on_startup)
        self.window.refreshRequested.connect(self.refresh)
        self.window.quitRequested.connect(self.app.quit)

        # Tray. Some environments (notably vanilla GNOME, which dropped tray
        # support) have no system tray at all - detect that so we never hide
        # the app where it can't be reached.
        self.tray_supported = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray = QSystemTrayIcon(self.app_icon)
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.window.set_tray_supported(self.tray_supported)
        self.window.tray_available = self._tray_active()
        self.tray.setVisible(self._tray_active())

        # Debounce sidetone applies so dragging doesn't spam the CLI.
        self._pending_sidetone: int | None = None
        self._sidetone_timer = QTimer()
        self._sidetone_timer.setSingleShot(True)
        self._sidetone_timer.timeout.connect(self._flush_sidetone)

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)

        self.refresh()

        if not start_hidden:
            # Normal launch: show the window.
            self.open_window()
        elif not self._tray_active():
            # Asked to start hidden, but there's no active tray to live in
            # (toggle off, or no tray at all e.g. vanilla GNOME). There's
            # nothing to show and nowhere to hide, so just exit.
            QTimer.singleShot(0, self.app.quit)

    def _tray_active(self) -> bool:
        """The tray is only usable if the environment supports it AND the user
        hasn't hidden it."""
        return self.tray_supported and self.tray_visible

    # ----- state -----
    def refresh(self):
        try:
            self.state = backend.read_state()
        except HeadsetControlError as exc:
            self.state = DeviceState(connected=False, error=str(exc))
        # Re-apply saved settings when the headset (re)connects - the device
        # forgets them when powered off and the CLI can't read them back.
        if (
            self.restore_on_startup
            and self.state.connected
            and not self._was_connected
        ):
            self._apply_saved_settings()
        self._was_connected = self.state.connected
        self._update_tray()
        self.window.set_state(self.state)

    def _apply_saved_settings(self):
        """Push the persisted sidetone/lights to the device. Errors are
        swallowed - a flaky device will get another chance on the next
        reconnect, and we don't want a popup on every boot."""
        try:
            if self.state.has_lights:
                backend.set_lights(self.lights)
            if self.state.has_sidetone:
                backend.set_sidetone(self.sidetone)
        except HeadsetControlError:
            pass

    def _update_tray(self):
        s = self.state
        if not s.connected:
            self.tray.setToolTip("Headset: disconnected")
        else:
            parts = [s.product or s.name or "Headset"]
            if s.has_battery and s.battery_level is not None:
                charge = " ⚡" if s.charging else ""
                parts.append(f"{s.battery_level}%{charge}")
            self.tray.setToolTip(" - ".join(parts))
            # Tray icon reflects battery when known, else the headset icon.
            if s.has_battery and s.battery_level is not None:
                self.tray.setIcon(battery_icon(s.battery_level, s.charging))
            else:
                self.tray.setIcon(self.app_icon)
        self._rebuild_menu()

    def _rebuild_menu(self):
        self.menu.clear()
        s = self.state
        if not s.connected:
            header = QAction("Headset disconnected", self.menu)
        else:
            label = s.product or s.name or "Headset"
            if s.has_battery and s.battery_level is not None:
                charge = "  ⚡" if s.charging else ""
                label = f"{label}   ·   {s.battery_level}%{charge}"
            header = QAction(label, self.menu)
            if s.has_battery and s.battery_level is not None:
                header.setIcon(battery_icon(s.battery_level, s.charging))
        header.setEnabled(False)
        self.menu.addAction(header)
        self.menu.addSeparator()

        open_action = QAction("Open", self.menu)
        open_action.triggered.connect(self.open_window)
        self.menu.addAction(open_action)

        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(quit_action)

    # ----- window -----
    def open_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason):
        # Left-click (Trigger) opens the window; so does double-click.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_window()

    # ----- actions -----
    def _toggle_lights(self, on: bool):
        try:
            backend.set_lights(on)
        except HeadsetControlError as exc:
            self._error("Lights", exc)
            return
        self.lights = on
        self.settings.setValue("lights", on)

    def _queue_sidetone(self, level: int):
        self._pending_sidetone = level
        self._sidetone_timer.start(APPLY_DEBOUNCE_MS)

    def _flush_sidetone(self):
        if self._pending_sidetone is None:
            return
        level = self._pending_sidetone
        self._pending_sidetone = None
        try:
            backend.set_sidetone(level)
        except HeadsetControlError as exc:
            self._error("Sidetone", exc)
            return
        self.sidetone = level
        self.settings.setValue("sidetone", level)

    def _play_notification(self, sound_id: int):
        try:
            backend.play_notification(sound_id)
        except HeadsetControlError as exc:
            self._error("Notification sound", exc)

    def _set_restore_on_startup(self, enabled: bool):
        self.restore_on_startup = enabled
        self.settings.setValue("restore_on_startup", enabled)

    def _set_tray_visible(self, visible: bool):
        self.tray_visible = visible
        self.settings.setValue("tray_visible", visible)
        self.window.tray_available = self._tray_active()
        self.tray.setVisible(self._tray_active())
        # If the tray is being hidden, keep the window reachable.
        if not self._tray_active():
            self.open_window()

    def _error(self, what: str, exc: Exception):
        QMessageBox.warning(self.window, f"{what} failed", str(exc))
