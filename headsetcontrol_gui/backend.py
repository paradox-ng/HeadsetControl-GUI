"""Thin wrapper around the `headsetcontrol` CLI.

The CLI is the backend: we read state via `headsetcontrol -o json` and apply
settings by shelling out to the relevant flags. Note that HeadsetControl only
*reports* battery + capabilities in JSON - it does not report the current
sidetone level or light state, so the GUI must remember what it last set.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field


class HeadsetControlError(Exception):
    """Raised when the headsetcontrol binary is missing or a command fails."""


@dataclass
class DeviceState:
    connected: bool = False
    name: str = ""
    product: str = ""
    capabilities: list[str] = field(default_factory=list)
    battery_status: str = ""  # BATTERY_AVAILABLE / BATTERY_CHARGING / BATTERY_UNAVAILABLE
    battery_level: int | None = None
    error: str = ""

    @property
    def has_sidetone(self) -> bool:
        return "sidetone" in self.capabilities

    @property
    def has_lights(self) -> bool:
        return "lights" in self.capabilities

    @property
    def has_battery(self) -> bool:
        return "battery" in self.capabilities

    @property
    def has_notification(self) -> bool:
        return "notification sound" in self.capabilities

    @property
    def charging(self) -> bool:
        return self.battery_status == "BATTERY_CHARGING"


def binary_path() -> str | None:
    return shutil.which("headsetcontrol")


def _run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    path = binary_path()
    if not path:
        raise HeadsetControlError(
            "headsetcontrol not found on PATH. Install it first "
            "(https://github.com/Sapd/HeadsetControl)."
        )
    try:
        return subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise HeadsetControlError("headsetcontrol timed out") from exc


def read_state() -> DeviceState:
    """Query the first supported device. Never raises for 'no device' - that
    is a normal state reflected by DeviceState.connected == False."""
    proc = _run(["-o", "json"])
    raw = proc.stdout.strip()
    if not raw:
        return DeviceState(connected=False, error=proc.stderr.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return DeviceState(connected=False, error="Could not parse CLI output")

    devices = data.get("devices") or []
    if not devices:
        return DeviceState(connected=False)

    dev = devices[0]
    state = DeviceState(
        connected=dev.get("status") == "success",
        name=dev.get("device", ""),
        product=dev.get("product", ""),
        capabilities=dev.get("capabilities_str", []),
    )
    battery = dev.get("battery") or {}
    state.battery_status = battery.get("status", "")
    level = battery.get("level")
    state.battery_level = level if isinstance(level, int) and level >= 0 else None
    return state


def set_sidetone(level: int) -> None:
    level = max(0, min(128, int(level)))
    proc = _run(["-s", str(level)])
    if proc.returncode != 0:
        raise HeadsetControlError(proc.stderr.strip() or "Failed to set sidetone")


def set_lights(on: bool) -> None:
    proc = _run(["-l", "1" if on else "0"])
    if proc.returncode != 0:
        raise HeadsetControlError(proc.stderr.strip() or "Failed to set lights")


def play_notification(sound_id: int) -> None:
    """Play a notification sound on the headset. Valid IDs are device-specific."""
    proc = _run(["-n", str(int(sound_id))])
    if proc.returncode != 0:
        raise HeadsetControlError(
            proc.stderr.strip() or "Failed to play notification sound"
        )
