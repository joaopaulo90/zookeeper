"""Setting up a brand-new unit over Bluetooth, from the phone, end to end.

Real: the phone app (zoo-mobile test build), the Bluetooth link, the jiboia
app on the unit, and the unit joining the test Wi-Fi.
Local stand-ins: zoo-server in test mode (no AWS), a test CA instead of AWS
IoT certificates, and a local broker instead of AWS IoT Core.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

FLOW = Path(__file__).parent / "flows" / "setup_unit.yaml"

# A site name has to be a valid MQTT topic segment (no spaces) -- see jiboia's MqttTopics.
SITE = "zookeeper-bench"
DISPLAY_NAME = "Bench unit"
GROUP = "bench"


def test_a_new_unit_is_set_up_over_ble_and_comes_online(config, zoo_server, broker, ca, unit, phone, test_dir):
    # Given a unit fresh from the factory: registered with zoo-server, its
    # serial stamped, never claimed by anyone, and advertising over Bluetooth.
    unit.reset(ca.ca_pem)
    serial = zoo_server.register_unit(unit.device_type, unit.factory_metadata())
    unit.stamp_test_serial(serial)
    zoo_server.mark_serial_stamped(serial)
    unit.restart_app()
    unit.wait_for_state(
        lambda s: s.serial == serial and s.env == "test" and not s.provisioned and s.provisioning == "Active",
        timeout=60,
        description="the unit to advertise for setup",
    )

    # ...and a phone with the app freshly installed and logged out.
    phone.reset_app(config.server_port)
    phone.reset_radios()

    # When the installer logs in and sets the unit up from the phone.
    phone.run_flow(
        FLOW,
        env={
            "IDENTIFIER": config.login_identifier,
            "CODE": config.login_code,
            "SERIAL": serial,
            "SITE": SITE,
            "WIFI_SSID": config.wifi_ssid,
            "WIFI_PASSWORD": config.wifi_password,
            "DISPLAY_NAME": DISPLAY_NAME,
            "GROUP": GROUP,
        },
        output_dir=test_dir / "maestro",
    )

    # Then zoo-server has the unit claimed by that account, at that site.
    token = zoo_server.login(config.login_identifier)
    row = zoo_server.unit(token, serial)
    assert row is not None, f"{serial} is not in the account's unit list"
    assert row["site"] == SITE
    assert row["provisioned_at"], "zoo-server never recorded the claim"
    assert row["site_pin"], "the site has no settings PIN"
    account = row["account_id"]

    # ...the unit holds exactly that identity and is connected to the broker...
    state = unit.wait_for_state(
        lambda s: s.provisioned and s.mqtt == "Connected" and s.provisioning == "Idle",
        timeout=120,
        description="the unit to join Wi-Fi and connect to the broker",
    )
    assert state.serial == serial
    assert state.env == "test"
    assert state.account == account
    assert state.site == SITE
    assert state.displayName == DISPLAY_NAME
    assert state.group == (GROUP if unit.role == "inside" else "")
    assert state.mqttHost == "localhost"
    assert state.mqttPort == config.broker_port
    assert state.clientCertificate
    assert state.pinSha256 == hashlib.sha256(row["site_pin"].encode()).hexdigest(), "the unit's PIN isn't the site's"

    # ...and the broker sees it: its retained status on its own topic.
    status = broker.wait_for_message(f"jiboia/test/{account}/{SITE}/{serial}/status", timeout=30)
    payload = status.json()
    assert payload.get("deviceId") == serial
    assert "phase" in payload, f"expected a live status, got {payload}"
