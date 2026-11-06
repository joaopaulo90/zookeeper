"""Checks the local backend on its own, with no devices: the identity
test-mode zoo-server hands out is one the local broker accepts. If this
fails, every hardware test would too, for reasons that have nothing to do
with the hardware."""

from __future__ import annotations

import base64
import json

from harness.certs import p12_to_pem


def test_an_identity_issued_by_test_zoo_server_is_accepted_by_the_broker(config, zoo_server, broker, test_dir):
    token = zoo_server.login("backend-check@example.com")
    serial = zoo_server.register_unit("external", {"model": "Bench", "sdkVersion": 30})
    zoo_server.mark_serial_stamped(serial)

    bundle = zoo_server.call("POST", "/zoo/units/provision", {"serialNumber": serial, "site": "bench"}, token)

    assert bundle["endpoint"] == "localhost"
    assert bundle["port"] == config.broker_port
    p12 = base64.b64decode(bundle["certificateP12Base64"])
    cert, key = p12_to_pem(p12, bundle["bundlePassword"], test_dir, "unit")
    topic = f"jiboia/test/{bundle['account']}/bench/{serial}/status"
    broker.publish(topic, json.dumps({"device_id": serial, "phase": "idle"}), cert, key)

    message = broker.wait_for_message(topic, timeout=10)
    assert message.json() == {"device_id": serial, "phase": "idle"}

