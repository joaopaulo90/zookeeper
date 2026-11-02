"""The phone running zoo-mobile's test build (`APP_ENV=test`), driven by Maestro."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .adb import Adb
from .config import ROOT

PACKAGE = "br.com.chacaraourico.zoo.mobile.test"
BUILD_DIR = ROOT / ".build"
APK = BUILD_DIR / "zoo-mobile-test.apk"

# Granted up front so no system dialog ever interrupts a flow.
PERMISSIONS = [
    "android.permission.BLUETOOTH_SCAN",
    "android.permission.BLUETOOTH_CONNECT",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.CAMERA",
]


def maestro_binary() -> str:
    for candidate in (shutil.which("maestro"), str(Path.home() / ".maestro/bin/maestro")):
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("maestro not found -- run `just setup` (it prints the install command)")


class Phone:
    def __init__(self, adb: Adb):
        self.adb = adb

    def install_app(self) -> None:
        if not APK.is_file():
            raise RuntimeError("the zoo-mobile test build is missing -- run `just build-phone-app`")
        self.adb.run("install", "-r", "-g", str(APK), timeout=300)

    def reset_app(self, server_port: int) -> None:
        """Fresh app data (logged out, no Wi-Fi cache), permissions granted,
        and `localhost:<server_port>` on the phone reaching the test zoo-server."""
        self.adb.shell("pm", "clear", PACKAGE)
        for permission in PERMISSIONS:
            self.adb.shell("pm", "grant", PACKAGE, permission, check=False)
        self.adb.reverse(server_port, server_port)

    def reset_radios(self) -> None:
        """Bluetooth off and on again -- which also drops Android's cached GATT
        tables, so every run connects from scratch -- and location on, which
        BLE and Wi-Fi scans need on some Android versions. Best effort: the
        commands differ a little between Android versions."""
        for args in (("cmd", "bluetooth_manager", "disable"), ("svc", "bluetooth", "disable")):
            if self.adb.run("shell", *args, check=False).returncode == 0:
                break
        time.sleep(3)
        for args in (("cmd", "bluetooth_manager", "enable"), ("svc", "bluetooth", "enable")):
            if self.adb.run("shell", *args, check=False).returncode == 0:
                break
        self.adb.run("shell", "cmd", "location", "set-location-enabled", "true", check=False)
        time.sleep(3)

    def wake_and_unlock(self) -> None:
        """Works when the phone has no secure lock screen -- see README."""
        self.adb.shell("input", "keyevent", "KEYCODE_WAKEUP", check=False)
        self.adb.shell("wm", "dismiss-keyguard", check=False)

    def run_flow(self, flow: Path, env: dict[str, str], output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        args = [maestro_binary(), "--device", self.adb.device, "test", str(flow)]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += ["--format", "junit", "--output", str(output_dir / "report.xml"), "--debug-output", str(output_dir)]
        with (output_dir / "maestro.log").open("w") as log:
            proc = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "MAESTRO_CLI_NO_ANALYTICS": "1"})
        if proc.returncode != 0:
            tail = (output_dir / "maestro.log").read_text()[-3000:]
            raise AssertionError(f"Maestro flow {flow.name} failed (screenshots in {output_dir}):\n{tail}")
