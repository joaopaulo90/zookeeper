"""Bench settings: which devices are plugged in, the test Wi-Fi, and where the
sibling repos live. Read from `config.local.toml` (see config.example.toml).

Device and Wi-Fi settings are only required by tests that use them, so the
backend-only checks run without any of it."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.local.toml"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    raw: dict
    zoo_repo: Path
    jiboia_repo: Path
    broker_port: int
    server_port: int
    login_identifier: str
    login_code: str
    java_home: str

    @property
    def zoo_server_dir(self) -> Path:
        return self.zoo_repo / "zoo-server"

    @property
    def zoo_mobile_dir(self) -> Path:
        return self.zoo_repo / "zoo-mobile"

    def require(self, section: str, key: str) -> str:
        value = self.raw.get(section, {}).get(key)
        if value is None or value == "":
            raise ConfigError(f"{CONFIG_PATH.name}: [{section}] {key} is required for this test -- run `just init`")
        return str(value)

    @property
    def unit_device(self) -> str:
        return self.require("devices", "unit")

    @property
    def phone_device(self) -> str:
        return self.require("devices", "phone")

    @property
    def wifi_ssid(self) -> str:
        return self.require("wifi", "ssid")

    @property
    def wifi_password(self) -> str:
        return self.require("wifi", "password")


def load(path: Path = CONFIG_PATH) -> Config:
    raw = tomllib.loads(path.read_text()) if path.is_file() else {}

    def repo(key: str, default: str) -> Path:
        value = raw.get("repos", {}).get(key, default)
        resolved = (ROOT / value).resolve()
        if not resolved.is_dir():
            raise ConfigError(f"[repos] {key} = {value!r} is not a directory")
        return resolved

    return Config(
        raw=raw,
        zoo_repo=repo("zoo", "../zoo"),
        jiboia_repo=repo("jiboia", "../jiboia"),
        broker_port=int(raw.get("ports", {}).get("broker", 8883)),
        # Fixed by zoo-server's own test-mode config (src/config.rs).
        server_port=4002,
        login_identifier=raw.get("login", {}).get("identifier", "zookeeper@example.com"),
        login_code=str(raw.get("login", {}).get("code", "123456")),
        java_home=raw.get("tools", {}).get("java_home", "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"),
    )
