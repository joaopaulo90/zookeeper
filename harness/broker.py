"""A local Mosquitto broker standing in for AWS IoT Core: mutual TLS with the
run's test CA, every client identified by its certificate's CN."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .certs import RunCa
from .wait import wait_for


def _mosquitto_binary() -> str:
    for candidate in (shutil.which("mosquitto"), "/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto"):
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("mosquitto not found -- `brew install mosquitto`")


def port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


@dataclass
class MqttMessage:
    topic: str
    payload: str

    def json(self):
        return json.loads(self.payload)


class Broker:
    def __init__(self, ca: RunCa, port: int, run_dir: Path):
        self.ca = ca
        self.port = port
        self.run_dir = run_dir
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if not port_is_free(self.port):
            raise RuntimeError(f"port {self.port} is busy -- is another broker (or a previous run) still up?")
        conf = self.run_dir / "mosquitto.conf"
        conf.write_text(
            "\n".join(
                [
                    "per_listener_settings false",
                    "allow_anonymous false",
                    "persistence false",
                    f"listener {self.port} 127.0.0.1",
                    f"cafile {self.ca.ca_cert}",
                    f"certfile {self.ca.broker_cert}",
                    f"keyfile {self.ca.broker_key}",
                    "require_certificate true",
                    "use_identity_as_username true",
                    "log_dest stdout",
                    "log_type all",
                    "",
                ]
            )
        )
        self._log = (self.run_dir / "broker.log").open("w")
        self._proc = subprocess.Popen([_mosquitto_binary(), "-c", str(conf)], stdout=self._log, stderr=subprocess.STDOUT)
        wait_for(lambda: not port_is_free(self.port), timeout=10, interval=0.2, description="the broker to listen")

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._log.close()

    def _tls_args(self, cert: Path, key: Path) -> list[str]:
        return [
            "-h", "localhost", "-p", str(self.port),
            "--cafile", str(self.ca.ca_cert), "--cert", str(cert), "--key", str(key),
        ]

    def wait_for_message(self, topic: str, timeout: float, cert: Path | None = None, key: Path | None = None) -> MqttMessage:
        """The first message on `topic` (wildcards allowed) -- retained ones arrive at once."""
        proc = subprocess.run(
            ["mosquitto_sub", *self._tls_args(cert or self.ca.observer_cert, key or self.ca.observer_key),
             "-t", topic, "-C", "1", "-W", str(int(timeout)), "-v"],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            raise AssertionError(f"no message on {topic} within {timeout:.0f}s: {proc.stderr.strip()}")
        topic_seen, _, payload = proc.stdout.strip().partition(" ")
        return MqttMessage(topic_seen, payload)

    def publish(self, topic: str, payload: str, cert: Path, key: Path) -> None:
        proc = subprocess.run(
            ["mosquitto_pub", *self._tls_args(cert, key), "-t", topic, "-m", payload, "-r"],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"publish to {topic} failed: {proc.stderr.strip()}")
