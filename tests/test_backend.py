"""Tests for the CLI wrapper.

The star here is _child_env(). The bug it guards against is invisible in
development: unfrozen, _child_env() returns None and the child simply inherits
our environment, which is correct and works everywhere. It only bites when
frozen AND running on a distro whose libstdc++ is newer than the AppImage's
ubuntu-22.04 build base - a combination that exists on end users' machines and
nowhere in CI. So if someone drops the env= argument from _run(), every local
run and every CI build still passes and the tray silently reports a working
headset as "disconnected". These tests are the only thing that would catch it.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

from headsetcontrol_gui import backend

# Real `headsetcontrol -o json` output (api_version 1.4), trimmed to the
# fields the GUI reads. Pinned so a CLI schema change fails loudly here.
SAMPLE_JSON = """
{
  "name": "HeadsetControl",
  "api_version": "1.4",
  "device_count": 1,
  "devices": [
    {
      "status": "success",
      "device": "Corsair Headset Device",
      "vendor": "Corsair",
      "product": "CORSAIR VOID ELITE Wireless Gaming Dongle",
      "capabilities_str": ["sidetone", "battery", "notification sound", "lights"],
      "battery": {"status": "BATTERY_AVAILABLE", "level": 80, "time_to_empty_min": 576}
    }
  ]
}
"""


@pytest.fixture
def frozen(monkeypatch):
    """Pretend we're running from the PyInstaller/AppImage bundle."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)


# ----- _child_env -----
def test_unfrozen_inherits_environment(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert backend._child_env() is None


def test_frozen_drops_bundled_library_path(frozen, monkeypatch):
    """The real-world case: PyInstaller sets LD_LIBRARY_PATH with no _ORIG
    counterpart, so the variable must be removed outright."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_XXXX/usr/bin/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    env = backend._child_env()

    assert "LD_LIBRARY_PATH" not in env


def test_frozen_restores_the_users_original_value(frozen, monkeypatch):
    """If the user had their own LD_LIBRARY_PATH, PyInstaller stashed it in
    _ORIG and the child must get that back - not our bundle, not nothing."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_XXXX/usr/bin/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/mylibs")

    env = backend._child_env()

    assert env["LD_LIBRARY_PATH"] == "/opt/mylibs"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_frozen_handles_ld_preload_too(frozen, monkeypatch):
    monkeypatch.setenv("LD_PRELOAD", "/tmp/.mount_XXXX/usr/bin/_internal/libfoo.so")
    monkeypatch.delenv("LD_PRELOAD_ORIG", raising=False)

    assert "LD_PRELOAD" not in backend._child_env()


def test_frozen_with_nothing_set_is_not_an_error(frozen, monkeypatch):
    for var in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH_ORIG", "LD_PRELOAD_ORIG"):
        monkeypatch.delenv(var, raising=False)

    env = backend._child_env()

    assert isinstance(env, dict)


def test_child_env_does_not_mutate_our_own_environment(frozen, monkeypatch):
    """We must sanitize a copy - clobbering os.environ would break Qt, which
    needs the bundled libs for the GUI process itself."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_XXXX/usr/bin/_internal")
    import os

    backend._child_env()

    assert os.environ["LD_LIBRARY_PATH"] == "/tmp/.mount_XXXX/usr/bin/_internal"


def test_run_passes_the_sanitized_env_to_the_child(frozen, monkeypatch):
    """The regression guard: _run() must actually hand the env to subprocess.
    Without this, _child_env() could be perfect and still never applied."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_XXXX/usr/bin/_internal")
    monkeypatch.setattr(backend, "binary_path", lambda: "/usr/bin/headsetcontrol")
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    backend._run(["-o", "json"])

    assert seen["env"] is not None, "_run() dropped the sanitized environment"
    assert "LD_LIBRARY_PATH" not in seen["env"]


# ----- read_state -----
def _fake_cli(monkeypatch, stdout="", stderr="", returncode=0):
    monkeypatch.setattr(
        backend,
        "_run",
        lambda *a, **k: subprocess.CompletedProcess(["headsetcontrol"], returncode, stdout, stderr),
    )


def test_read_state_parses_current_cli_output(monkeypatch):
    _fake_cli(monkeypatch, stdout=SAMPLE_JSON)

    state = backend.read_state()

    assert state.connected
    assert state.battery_level == 80
    assert state.has_sidetone and state.has_lights and state.has_battery
    assert state.has_notification
    assert not state.charging


def test_cli_failure_is_reported_not_silently_disconnected(monkeypatch):
    """The original bug's signature: the CLI dies before printing JSON. That
    must surface as an error, not as an innocent 'no headset'."""
    _fake_cli(
        monkeypatch,
        stdout="",
        stderr="libstdc++.so.6: version `GLIBCXX_3.4.32' not found",
        returncode=1,
    )

    state = backend.read_state()

    assert not state.connected
    assert "GLIBCXX" in state.error


def test_no_devices_is_a_plain_disconnect(monkeypatch):
    _fake_cli(monkeypatch, stdout='{"device_count": 0, "devices": []}')

    state = backend.read_state()

    assert not state.connected
    assert state.error == ""


def test_unparseable_output_is_reported(monkeypatch):
    _fake_cli(monkeypatch, stdout="not json at all")

    state = backend.read_state()

    assert not state.connected
    assert state.error


# ----- structural guards -----
def test_only_backend_shells_out():
    """Every CLI call must go through _run(), which is where the environment
    gets sanitized. A subprocess call elsewhere would bypass the fix."""
    package = pathlib.Path(backend.__file__).parent
    offenders = []
    for path in sorted(package.glob("*.py")):
        if path.name == "backend.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] == "subprocess" for name in names):
                offenders.append(path.name)

    assert not offenders, f"{offenders} shell out directly; route via backend._run()"
