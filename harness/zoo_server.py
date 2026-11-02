"""zoo-server in test mode (`ENV=test`, see zoo-server's src/test_mode.rs),
started fresh for every run with an empty database, plus a small API client.

The database is seeded through zoo-server's own endpoints -- the same
factory calls jiboia's factory_cli makes -- rather than by writing rows
directly, so the seeding can't drift from what the server really accepts."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .broker import port_is_free
from .certs import RunCa
from .wait import wait_for


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, path: str):
        super().__init__(f"{path} -> HTTP {status}: {body}")
        self.status = status


class ZooServer:
    def __init__(self, server_dir: Path, run_dir: Path, ca: RunCa, port: int, broker_port: int, login_code: str):
        self.server_dir = server_dir
        self.run_dir = run_dir
        self.ca = ca
        self.port = port
        self.broker_port = broker_port
        self.login_code = login_code
        self.base_url = f"http://127.0.0.1:{port}"
        self._proc: subprocess.Popen | None = None

    @property
    def binary(self) -> Path:
        return self.server_dir / "target/debug/zoo-server"

    def _env(self) -> dict[str, str]:
        return {
            **os.environ,
            "ENV": "test",
            "RUST_LOG": os.environ.get("RUST_LOG", "info"),
            "ZOO_TEST_SQLITE_PATH": str(self.run_dir / "zoo.sqlite3"),
            "ZOO_TEST_CA_CERT": str(self.ca.ca_cert),
            "ZOO_TEST_CA_KEY": str(self.ca.ca_key),
            "ZOO_TEST_MQTT_HOST": "localhost",
            "ZOO_TEST_MQTT_PORT": str(self.broker_port),
            "ZOO_TEST_LOGIN_CODE": self.login_code,
            "ZOO_TEST_DEBUG_REPORTS_DIR": str(self.run_dir / "debug-reports"),
        }

    def build(self) -> None:
        proc = subprocess.run(["cargo", "build", "--quiet"], cwd=self.server_dir, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"zoo-server failed to build:\n{proc.stderr[-4000:]}")

    def start(self) -> None:
        if not port_is_free(self.port):
            raise RuntimeError(f"port {self.port} is busy -- is a test zoo-server from a previous run still up?")
        self.build()
        self._log = (self.run_dir / "zoo-server.log").open("w")
        self._proc = subprocess.Popen([str(self.binary)], cwd=self.run_dir, env=self._env(), stdout=self._log, stderr=subprocess.STDOUT)

        def listening():
            if self._proc.poll() is not None:
                raise RuntimeError(f"zoo-server exited early -- see {self.run_dir / 'zoo-server.log'}")
            return not port_is_free(self.port)

        wait_for(listening, timeout=30, interval=0.3, description="zoo-server to listen")

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=10)
            self._log.close()

    # --- API ------------------------------------------------------------------

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"content-type": "application/json", **({"authorization": f"Bearer {token}"} if token else {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, error.read().decode(errors="replace"), path) from None

    def factory_token(self) -> str:
        proc = subprocess.run([str(self.binary), "factory-token"], env=self._env(), capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    def login(self, identifier: str) -> str:
        """Logs in through the real auth endpoints with the fixed test-mode code."""
        challenge = self.call("POST", "/zoo/auth/start", {"identifier": identifier})["challenge"]
        verified = self.call("POST", "/zoo/auth/verify", {"identifier": identifier, "code": self.login_code, "challenge": challenge})
        return verified["token"]

    def register_unit(self, device_type: str, phone: dict) -> str:
        """Factory step 1: mints a serial for a new unit (status `pending`)."""
        token = self.factory_token()
        return self.call("POST", "/zoo/units/new", {"deviceType": device_type, "phone": phone}, token)["serialNumber"]

    def mark_serial_stamped(self, serial: str) -> None:
        """Factory step 2: the serial reached the unit (status `ready`)."""
        self.call("POST", "/zoo/units/serial-stamped", {"serialNumber": serial}, self.factory_token())

    def units(self, token: str) -> list[dict]:
        return self.call("GET", "/zoo/units", token=token)

    def unit(self, token: str, serial: str) -> dict | None:
        return next((unit for unit in self.units(token) if unit["serial_number"] == serial), None)
