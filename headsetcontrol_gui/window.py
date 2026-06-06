"""The control window - the real UI. The tray menu stays minimal (DBusMenu
can't host widgets like sliders), and everything interactive lives here."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .backend import DeviceState

SIDETONE_MAX = 128


def level_to_percent(level: int) -> int:
    return round(level / SIDETONE_MAX * 100)


def percent_to_level(percent: int) -> int:
    return round(percent / 100 * SIDETONE_MAX)


def battery_icon(level: int | None, charging: bool) -> QIcon:
    """Pick a themed battery icon for the given level. Tries Plasma's numeric
    names first, then generic freedesktop names, so it works across themes."""
    if level is None:
        return QIcon.fromTheme("battery-missing")

    level = max(0, min(100, level))
    rounded = int(round(level / 10.0) * 10)  # 0,10,...,100
    suffix = "-charging" if charging else ""

    if level >= 80:
        generic = "battery-full"
    elif level >= 55:
        generic = "battery-good"
    elif level >= 30:
        generic = "battery-low"
    elif level >= 10:
        generic = "battery-caution"
    else:
        generic = "battery-empty"

    candidates = [
        f"battery-{rounded:03d}{suffix}",    # Breeze/Plasma: battery-090-charging
        f"battery-level-{rounded}{suffix}",  # some icon themes
        f"{generic}{suffix}",                # fd.o: battery-good-charging
        generic,
        "battery",
    ]
    for name in candidates:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


def _hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


class ControlWindow(QWidget):
    sidetoneChanged = Signal(int)       # absolute level 0-128
    lightsToggled = Signal(bool)
    playNotification = Signal(int)      # sound id
    trayVisibilityChanged = Signal(bool)
    restoreOnStartupChanged = Signal(bool)
    refreshRequested = Signal()
    quitRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeadsetControl")
        self.setWindowIcon(QIcon.fromTheme("audio-headset"))
        self.setMinimumWidth(360)
        # When a tray icon is available, closing hides to tray instead of quitting.
        self.tray_available = True

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # --- header: device name + battery ---
        self.title_label = QLabel("Headset")
        font = self.title_label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 1)
        self.title_label.setFont(font)

        self.battery_icon_label = QLabel()
        self.battery_text_label = QLabel("")
        battery_row = QHBoxLayout()
        battery_row.setSpacing(6)
        battery_row.addWidget(self.battery_icon_label)
        battery_row.addWidget(self.battery_text_label)
        battery_row.addStretch()

        root.addWidget(self.title_label)
        root.addLayout(battery_row)
        root.addWidget(_hline())

        # --- controls ---
        self.controls_box = QGroupBox("Controls")
        controls = QVBoxLayout(self.controls_box)
        controls.setSpacing(8)

        # Sidetone
        self.sidetone_box = QWidget()
        st_layout = QVBoxLayout(self.sidetone_box)
        st_layout.setContentsMargins(0, 0, 0, 0)
        st_header = QHBoxLayout()
        st_header.addWidget(QLabel("Sidetone"))
        st_header.addStretch()
        self.sidetone_value = QLabel("0%")
        st_header.addWidget(self.sidetone_value)
        self.sidetone_slider = QSlider(Qt.Horizontal)
        self.sidetone_slider.setRange(0, SIDETONE_MAX)
        self.sidetone_slider.valueChanged.connect(self._on_sidetone)
        st_layout.addLayout(st_header)
        st_layout.addWidget(self.sidetone_slider)
        controls.addWidget(self.sidetone_box)

        # Lights
        self.lights_check = QCheckBox("Lights")
        self.lights_check.toggled.connect(self.lightsToggled)
        controls.addWidget(self.lights_check)

        # Notification sound
        self.notification_box = QWidget()
        n_layout = QHBoxLayout(self.notification_box)
        n_layout.setContentsMargins(0, 0, 0, 0)
        n_layout.addWidget(QLabel("Notification sound"))
        n_layout.addStretch()
        for sound_id in (0, 1):
            btn = QPushButton(f"Sound {sound_id}")
            btn.clicked.connect(lambda _=False, sid=sound_id: self.playNotification.emit(sid))
            n_layout.addWidget(btn)
        controls.addWidget(self.notification_box)

        root.addWidget(self.controls_box)

        # --- settings ---
        settings_box = QGroupBox("Settings")
        s_layout = QVBoxLayout(settings_box)
        self.tray_check = QCheckBox("Show tray icon")
        self.tray_check.toggled.connect(self.trayVisibilityChanged)
        s_layout.addWidget(self.tray_check)
        self.restore_check = QCheckBox("Re-apply saved settings on startup")
        self.restore_check.toggled.connect(self.restoreOnStartupChanged)
        s_layout.addWidget(self.restore_check)
        root.addWidget(settings_box)

        # --- bottom buttons ---
        # No Quit button by design: closing the window quits when there's no
        # tray, and quits from the tray menu when there is one.
        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refreshRequested)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(refresh_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def set_tray_supported(self, supported: bool):
        """Grey out the tray toggle where no system tray exists (e.g. vanilla
        GNOME), so the option doesn't look broken."""
        self.tray_check.setEnabled(supported)
        if not supported:
            self.tray_check.setToolTip(
                "No system tray detected in this desktop. On GNOME, install the "
                "AppIndicator extension to enable it."
            )

    # ----- updates from the controller -----
    def set_state(self, state: DeviceState):
        if state.connected:
            self.title_label.setText(state.product or state.name or "Headset")
        else:
            self.title_label.setText("Headset disconnected")

        if state.connected and state.has_battery and state.battery_level is not None:
            icon = battery_icon(state.battery_level, state.charging)
            self.battery_icon_label.setPixmap(icon.pixmap(22, 22))
            charge = "  ⚡ charging" if state.charging else ""
            self.battery_text_label.setText(f"{state.battery_level}%{charge}")
        else:
            self.battery_icon_label.clear()
            self.battery_text_label.setText("" if state.connected else "-")

        self.sidetone_box.setVisible(not state.connected or state.has_sidetone)
        self.lights_check.setVisible(not state.connected or state.has_lights)
        self.notification_box.setVisible(not state.connected or state.has_notification)

        # Disable interactive controls when nothing is connected.
        self.controls_box.setEnabled(state.connected)

    def set_controls(
        self,
        sidetone: int,
        lights: bool,
        tray_visible: bool,
        restore_on_startup: bool,
    ):
        widgets = (
            self.sidetone_slider,
            self.lights_check,
            self.tray_check,
            self.restore_check,
        )
        for w in widgets:
            w.blockSignals(True)
        self.sidetone_slider.setValue(sidetone)
        self.sidetone_value.setText(f"{level_to_percent(sidetone)}%")
        self.lights_check.setChecked(lights)
        self.tray_check.setChecked(tray_visible)
        self.restore_check.setChecked(restore_on_startup)
        for w in widgets:
            w.blockSignals(False)

    # ----- internal -----
    def _on_sidetone(self, level: int):
        self.sidetone_value.setText(f"{level_to_percent(level)}%")
        self.sidetoneChanged.emit(level)

    def closeEvent(self, event):
        # With a tray icon, closing just hides the window (app keeps running).
        # Without one, the window is the only access point, so closing quits.
        if self.tray_available:
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.quitRequested.emit()
