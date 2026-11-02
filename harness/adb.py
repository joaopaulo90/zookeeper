"""A thin `adb -s <device>` wrapper, plus a logcat capture the harness can
wait on without ever clearing the device's log buffer."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .wait import TimeoutError_, wait_for


def adb_path() -> str:
    found = shutil.which("adb")
    if found:
        return found
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "Library/Android/sdk"))
    candidate = sdk / "platform-tools/adb"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("adb not found -- install Android platform-tools or set ANDROID_SDK_ROOT")


class DeviceNotReady(RuntimeError):
    pass


class Adb:
    def __init__(self, device: str, label: str):
        self.device = device
        self.label = label
        self._adb = adb_path()

    def run(self, *args: str, check: bool = True, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [self._adb, "-s", self.device, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"adb ({self.label}) {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc

    def shell(self, *args: str, check: bool = True, timeout: float = 60) -> str:
        return self.run("shell", *args, check=check, timeout=timeout).stdout

    def ensure_ready(self) -> None:
        proc = subprocess.run([self._adb, "devices"], capture_output=True, text=True)
        states = dict(
            line.split()[:2] for line in proc.stdout.splitlines()[1:] if len(line.split()) >= 2
        )
        state = states.get(self.device)
        if state is None:
            raise DeviceNotReady(f"the {self.label} ({self.device}) is not connected over USB")
        if state == "unauthorized":
            raise DeviceNotReady(
                f"the {self.label} ({self.device}) hasn't authorized this computer -- "
                "accept the USB debugging prompt on its screen"
            )
        if state != "device":
            raise DeviceNotReady(f"the {self.label} ({self.device}) is in state {state!r}")

    def getprop(self, name: str) -> str:
        return self.shell("getprop", name).strip()

    def reverse(self, device_port: int, host_port: int) -> None:
        """Makes `localhost:<device_port>` on the device reach `localhost:<host_port>` here."""
        self.run("reverse", f"tcp:{device_port}", f"tcp:{host_port}")

    def installed_packages(self, prefix: str) -> list[str]:
        out = self.shell("pm", "list", "packages", prefix)
        return [line.removeprefix("package:").strip() for line in out.splitlines() if line.startswith("package:")]


class Logcat:
    """Streams a device's logcat into a file for the whole test, so waits can
    look at "everything logged since this point" by file offset."""

    def __init__(self, adb: Adb, path: Path):
        self.adb = adb
        self.path = path
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w")
        self._proc = subprocess.Popen(
            [self.adb._adb, "-s", self.adb.device, "logcat", "-v", "threadtime", "-T", "1"],
            stdout=self._file,
            stderr=subprocess.STDOUT,
        )
        time.sleep(0.5)

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._file.close()

    def mark(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0

    def wait_for(self, pattern: str, since: int, timeout: float, description: str) -> re.Match[str]:
        regex = re.compile(pattern)

        def found():
            with self.path.open("r", errors="replace") as handle:
                handle.seek(since)
                for line in handle:
                    match = regex.search(line)
                    if match:
                        return match
            return None

        try:
            return wait_for(found, timeout=timeout, interval=0.5, description=description)
        except TimeoutError_ as error:
            raise TimeoutError_(f"{error} (see {self.path})") from None
