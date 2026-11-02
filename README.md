# zookeeper

Integration tests across jiboia (the doorbell units), zoo-server and
zoo-mobile, on real hardware, with nobody watching. Each test sets up the
exact state it starts from, so any test can run at any time.

**Real:** the phone app, Bluetooth, the jiboia app on the unit, the unit
joining Wi-Fi, MQTT over mutual TLS.
**Local stand-ins:** zoo-server in test mode (no AWS), a throwaway test CA
instead of AWS IoT certificates, a local Mosquitto broker instead of AWS IoT
Core.

## Tests

| Test | Needs | Checks |
|---|---|---|
| `suites/provisioning/test_ble_setup.py` | unit + phone | A brand-new unit is set up over Bluetooth from the phone, joins Wi-Fi and comes online at the broker |
| `suites/backend/test_backend.py` | nothing | The local backend works on its own: an identity from test zoo-server is accepted by the broker |

## What a run does

For the Bluetooth setup test:

1. Creates a new test CA, starts a local broker and zoo-server in test mode
   with an empty database (`runs/<timestamp>/`).
2. Resets the unit (test hook): no customer state, trusts the test CA.
3. Registers a new unit with zoo-server through the factory endpoints,
   stamps that serial on the unit, restarts its app and waits until it
   advertises over Bluetooth.
4. Clears the phone app's data, grants its permissions, restarts Bluetooth.
5. Maestro drives the phone: log in, type the serial (instead of scanning
   the QR), site, Wi-Fi, display name, group, and waits for "Unit set up."
6. Checks all three sides: zoo-server has the claim, the unit holds the same
   identity and PIN and is connected, and the broker has the unit's status.

Both devices reach this computer over USB (`adb reverse`): the phone for
zoo-server, the unit for the broker. Neither needs to be on this computer's
network.

Logs, unit/phone logcat and Maestro screenshots end up in
`runs/latest/<test name>/`.

## One-time setup

1. `just setup-prerequisite` to install Maestro, then `just setup`. It
   creates the Python environment and lists any other missing tool.
2. Check out the `zookeeper` branch in `../zoo` and `../jiboia` (they hold
   the test hooks -- see [hooks.md](hooks.md)).
3. `just init`, then fill in `config.local.toml`: both devices' adb serials
   (`just devices`) and a Wi-Fi network the unit can join.
4. **The unit:** factory-installed as usual (jiboia's `just factory-cli`),
   then `just install-unit-app` to put the debug build with the test hooks
   on it. Rerun after jiboia changes.
5. **The phone:** USB debugging on and authorized, no secure lock screen
   (or Developer options > Stay awake while charging), then
   `just build-phone-app`. Rerun after zoo-mobile changes; the first build
   is slow.

## Running

```
just test               # everything
just test-ble-setup     # the Bluetooth setup test
just test-backend       # no devices needed
```

## Layout

```
conftest.py     fixtures: CA, broker, zoo-server, unit, phone
harness/        the pieces those fixtures use
suites/         tests, grouped by area; Maestro flows next to their tests
hooks.md        what each product repo exposes for these tests
```

## Notes

- After a run the unit stays on its `test` environment. Switch back with
  jiboia's `just factory-cli set-env`.
- The Wi-Fi password is typed by Maestro, so stick to plain ASCII.
