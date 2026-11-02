"""A jiboia unit on USB, driven through its debug-build test hooks (see
hooks.md and jiboia's device/TestHooks.kt)."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .adb import Adb, Logcat
from .wait import TimeoutError_, wait_for

MAIN_ACTIVITY = "com.jiboia.doorbell.MainActivity"
PACKAGE_RE = re.compile(r"^com\.jiboia\.doorbell\.(outside|inside)(\.debug)?$")
NO_HOOKS = (
    "the unit didn't answer a test hook -- it needs a jiboia *debug* build from the "
    "zookeeper branch: run `just install-unit-app`"
)


@dataclass(frozen=True)
class UnitState:
    """What the unit reports through `test_dump_state` -- see TestHooks.dumpState."""

    raw: dict

    def __getattr__(self, name: str):
        try:
            return self.raw[name]
        except KeyError:
            raise AttributeError(name) from None


class Unit:
    def __init__(self, adb: Adb, logcat: Logcat):
        self.adb = adb
        self.logcat = logcat
        self.package = self._detect_package()

    def _detect_package(self) -> str:
        packages = [p for p in self.adb.installed_packages("com.jiboia.doorbell") if PACKAGE_RE.match(p)]
        if not packages:
            raise RuntimeError(
                "no jiboia app on the unit -- factory-install it first (jiboia's `just factory-cli`), "
                "then `just install-unit-app`"
            )
        debug = [p for p in packages if p.endswith(".debug")]
        if not debug:
            raise RuntimeError(f"the unit has {packages[0]}, a release build, which has no test hooks. {NO_HOOKS}")
        return debug[0]

    @property
    def role(self) -> str:
        return PACKAGE_RE.match(self.package).group(1)

    @property
    def device_type(self) -> str:
        """zoo-server's name for this role."""
        return "external" if self.role == "outside" else "internal"

    # --- low level ------------------------------------------------------------

    def _send(self, *extras: str) -> None:
        # A unique data URI stops Android treating this as the same intent as
        # the last one, which would drop the extras (see factory_cli.py).
        nonce = f"zookeeper://nonce/{time.time_ns()}"
        self.adb.shell("am", "start", "-n", f"{self.package}/{MAIN_ACTIVITY}", "-d", nonce, *extras)

    def _hook(self, extras: list[str], pattern: str, failure: str | None, timeout: float, description: str) -> re.Match[str]:
        mark = self.logcat.mark()
        self._send(*extras)
        regex = pattern if failure is None else f"(?:{pattern})|(?P<failed>{failure})"
        try:
            match = self.logcat.wait_for(regex, since=mark, timeout=timeout, description=description)
        except TimeoutError_:
            raise TimeoutError_(NO_HOOKS) from None
        if failure is not None and match.group("failed"):
            raise AssertionError(f"unit hook failed: {match.group(0)}")
        return match

    # --- test hooks -------------------------------------------------------------

    def reset(self, ca_pem: bytes) -> None:
        """Back to "never customer-provisioned", trusting this run's test CA."""
        self._hook(
            ["--ez", "test_reset", "true", "--es", "test_ca_pem_b64", base64.b64encode(ca_pem).decode()],
            r"TESTHOOK reset ok testCa=true",
            r"TESTHOOK reset failed.*",
            timeout=20,
            description="the unit to reset",
        )

    def stamp_test_serial(self, serial: str) -> None:
        """The factory's stamp-serial step, into the unit's `test` environment slot."""
        self._hook(
            ["--es", "stamp_serial", serial, "--es", "stamp_env", "test"],
            rf"Stamped Test with {re.escape(serial)}",
            r"refusing to stamp.*|stamp_serial requires.*",
            timeout=20,
            description="the unit to accept its test serial",
        )

    def restart_app(self) -> None:
        """A clean process, so everything picks up the new identity from scratch."""
        self.adb.shell("am", "force-stop", self.package)
        self.adb.shell("am", "start", "-n", f"{self.package}/{MAIN_ACTIVITY}")

    def state(self) -> UnitState:
        match = self._hook(
            ["--ez", "test_dump_state", "true"],
            r"TESTHOOK state (\{.*\})",
            None,
            timeout=15,
            description="the unit's state",
        )
        return UnitState(json.loads(match.group(1)))

    def wait_for_state(self, check, timeout: float, description: str) -> UnitState:
        last: list[UnitState] = []

        def matches():
            current = self.state()
            last[:] = [current]
            return current if check(current) else None

        try:
            return wait_for(matches, timeout=timeout, interval=2, description=description)
        except TimeoutError_ as error:
            raise TimeoutError_(f"{error}; last state: {last[0].raw if last else 'none'}") from None

    # --- factory metadata -------------------------------------------------------

    def factory_metadata(self) -> dict:
        """What zoo-server records at factory registration (same fields factory_cli collects)."""
        sdk = self.adb.getprop("ro.build.version.sdk")
        return {
            "model": self.adb.getprop("ro.product.model") or None,
            "manufacturer": self.adb.getprop("ro.product.manufacturer") or None,
            "product": self.adb.getprop("ro.product.name") or None,
            "device": self.adb.getprop("ro.product.device") or None,
            "sdkVersion": int(sdk) if sdk.isdigit() else None,
        }


def install_debug_app(adb: Adb, jiboia_repo: Path, role: str, java_home: str) -> None:
    """Builds and installs the unit's own role as a debug build (keeps its data and Device Owner status)."""
    flavour = role.capitalize()
    proc = subprocess.run(
        ["./gradlew", f":app:assemble{flavour}Debug", "-q"],
        cwd=jiboia_repo, capture_output=True, text=True, env={**os.environ, "JAVA_HOME": java_home},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"jiboia build failed:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}")
    apk = jiboia_repo / f"app/build/outputs/apk/{role}/debug/app-{role}-debug.apk"
    adb.run("install", "-r", str(apk), timeout=300)
