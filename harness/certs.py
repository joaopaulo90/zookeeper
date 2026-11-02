"""A throwaway certificate authority per test run.

- zoo-server (test mode) signs every unit's client certificate with it.
- The local broker presents a server certificate signed by it, and only
  accepts clients whose certificate it signed.
- The unit is told to trust it (debug builds only -- see jiboia's TestHooks).
- The harness gets its own client certificate, to watch the broker.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunCa:
    ca_cert: Path
    ca_key: Path
    broker_cert: Path
    broker_key: Path
    observer_cert: Path
    observer_key: Path

    @property
    def ca_pem(self) -> bytes:
        return self.ca_cert.read_bytes()


def _openssl(*args: str) -> None:
    proc = subprocess.run(["openssl", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"openssl {args[0]} failed: {proc.stderr.strip()}")


def _sign(directory: Path, name: str, subject: str, ca_cert: Path, ca_key: Path, extensions: str) -> tuple[Path, Path]:
    key = directory / f"{name}.key"
    csr = directory / f"{name}.csr"
    cert = directory / f"{name}.crt"
    ext = directory / f"{name}.ext"
    ext.write_text(extensions)
    _openssl("genrsa", "-out", str(key), "2048")
    _openssl("req", "-new", "-key", str(key), "-subj", subject, "-out", str(csr))
    _openssl(
        "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
        "-CAcreateserial", "-days", "7", "-extfile", str(ext), "-out", str(cert),
    )
    return cert, key


def create(directory: Path) -> RunCa:
    directory.mkdir(parents=True, exist_ok=True)
    ca_cert = directory / "ca.crt"
    ca_key = directory / "ca.key"
    _openssl(
        "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "7",
        "-subj", "/CN=zookeeper test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout", str(ca_key), "-out", str(ca_cert),
    )
    # The unit reaches the broker as `localhost` (through `adb reverse`), and
    # jiboia checks the broker's hostname, so the certificate must name it.
    broker_cert, broker_key = _sign(
        directory, "broker", "/CN=localhost", ca_cert, ca_key,
        "subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n",
    )
    observer_cert, observer_key = _sign(
        directory, "observer", "/CN=zookeeper-observer", ca_cert, ca_key,
        "extendedKeyUsage=clientAuth\n",
    )
    return RunCa(ca_cert, ca_key, broker_cert, broker_key, observer_cert, observer_key)


def p12_to_pem(p12: bytes, password: str, directory: Path, name: str) -> tuple[Path, Path]:
    """Splits a unit's PKCS#12 bundle (legacy 3DES, as zoo-server builds it for
    Android 10) into PEM files the mosquitto CLI tools can use."""
    directory.mkdir(parents=True, exist_ok=True)
    bundle = directory / f"{name}.p12"
    bundle.write_bytes(p12)
    cert = directory / f"{name}.crt"
    key = directory / f"{name}.key"
    env = {**os.environ, "P12_PASS": password}
    for flag, out in (("-clcerts", cert), ("-nocerts", key)):
        proc = subprocess.run(
            ["openssl", "pkcs12", "-legacy", "-in", str(bundle), flag, "-nodes",
             "-passin", "env:P12_PASS", "-out", str(out)],
            capture_output=True, text=True, env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"could not open the unit's p12 bundle: {proc.stderr.strip()}")
    return cert, key
