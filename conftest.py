"""Shared fixtures. Everything a test needs is set up here, fresh, so any
test can run at any time with nobody around:

- session-wide: a new test CA, a local MQTT broker and zoo-server in test
  mode with an empty database (all under runs/<timestamp>/);
- per test: the unit and the phone on USB, each with its log captured into
  the test's own folder.

A test then seeds exactly the state it starts from (see each test)."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

from harness import certs
from harness import config as config_module
from harness.adb import Adb, Logcat
from harness.broker import Broker
from harness.config import ROOT
from harness.phone import Phone
from harness.unit import Unit
from harness.zoo_server import ZooServer


@pytest.fixture(scope="session")
def config():
    return config_module.load()


@pytest.fixture(scope="session")
def run_dir() -> Path:
    path = ROOT / "runs" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    latest = ROOT / "runs" / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(path.name)
    return path


@pytest.fixture
def test_dir(run_dir, request) -> Path:
    path = run_dir / re.sub(r"[^\w.-]+", "_", request.node.name)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def ca(run_dir):
    return certs.create(run_dir / "certs")


@pytest.fixture(scope="session")
def broker(ca, config, run_dir):
    broker = Broker(ca, config.broker_port, run_dir)
    broker.start()
    yield broker
    broker.stop()


@pytest.fixture(scope="session")
def zoo_server(ca, config, run_dir):
    server = ZooServer(config.zoo_server_dir, run_dir, ca, config.server_port, config.broker_port, config.login_code)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def unit(config, test_dir):
    """The jiboia unit on USB, reaching the local broker at `localhost` through `adb reverse`."""
    adb = Adb(config.unit_device, "unit")
    adb.ensure_ready()
    logcat = Logcat(adb, test_dir / "unit-logcat.txt")
    logcat.start()
    unit = Unit(adb, logcat)
    adb.reverse(config.broker_port, config.broker_port)
    yield unit
    logcat.stop()


@pytest.fixture
def phone(config, test_dir):
    """The phone on USB, with the zoo-mobile test build installed."""
    adb = Adb(config.phone_device, "phone")
    adb.ensure_ready()
    logcat = Logcat(adb, test_dir / "phone-logcat.txt")
    logcat.start()
    phone = Phone(adb)
    phone.install_app()
    phone.wake_and_unlock()
    yield phone
    logcat.stop()
