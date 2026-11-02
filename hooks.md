# Test hooks

What each product repo exposes for these tests. zookeeper uses only what's
listed here, never a repo's internals, so a repo can change anything else
freely. Changing anything below means updating zookeeper in step.

All of it lives on each repo's `zookeeper` branch for now.

## jiboia (debug builds only)

Sent as extras on `MainActivity`'s launch intent:

```
adb shell am start -n <package>/com.jiboia.doorbell.MainActivity -d zookeeper://nonce/<unique> <extras>
```

The unique `-d` URI matters: without it Android treats a repeat command as
the same intent and drops its extras. Each command answers with one logcat
line, tag `TestHooks` (or `MainActivity` for the factory commands).

| Extras | Does | Answers |
|---|---|---|
| `--ez test_reset true --es test_ca_pem_b64 <base64 PEM>` | Factory-resets customer state (client certificate, Wi-Fi, peers, config), forgets the `test` environment's serial, trusts the given CA for the broker | `TESTHOOK reset ok testCa=true` or `TESTHOOK reset failed: ...` |
| `--es stamp_serial <serial> --es stamp_env test` | The factory stamp step, into the `test` slot (also makes it active) | `Stamped Test with <serial>` |
| `--ez test_dump_state true` | Reports the unit's state | `TESTHOOK state {json}` |

`test_dump_state` JSON fields: `role`, `env`, `serial`, `provisioned`,
`account`, `site`, `displayName`, `group`, `mqttHost`, `mqttPort`,
`clientCertificate`, `pinSha256` (never the PIN itself), `online`,
`provisioning` (`Idle`/`Starting`/`Active`/`Applying`/`Failed`), `mqtt`
(`Disabled`/`Connecting`/`Connected`/`Reconnecting`/`Failed`).

The `test` environment slot is the only one that can be cleared. dev,
staging and prod serials are never touched. After a test the unit is left on
the `test` environment; switch back with jiboia's `just factory-cli set-env`.

Source: jiboia `device/TestHooks.kt`, `MainActivity.handleDebugIntent`,
`mqtt/MqttTlsMaterial.kt` (test CA trust).

## zoo-server (`ENV=test`)

A local-only mode with no AWS at all. Settings, all environment variables:

| Variable | Meaning |
|---|---|
| `ZOO_TEST_CA_CERT`, `ZOO_TEST_CA_KEY` | CA that signs every unit's client certificate (required) |
| `ZOO_TEST_MQTT_HOST`, `ZOO_TEST_MQTT_PORT` | Broker the identity bundle points at (default `localhost:8883`) |
| `ZOO_TEST_LOGIN_CODE` | The login code for every identifier (default `123456`) |
| `ZOO_TEST_SQLITE_PATH` | Database file (default `./data/test/zoo.sqlite3`) |
| `ZOO_TEST_DEBUG_REPORTS_DIR` | Where debug reports go instead of S3 |

Listens on `127.0.0.1:4002`. `zoo-server factory-token` with `ENV=test`
prints a factory token without AWS. Every endpoint is the real one.

Source: zoo-server `src/test_mode.rs`, and the `test_mode` branches in
`src/web.rs` and `src/main.rs`.

## zoo-mobile (`APP_ENV=test`)

- Package `br.com.chacaraourico.zoo.mobile.test`, so it never replaces a
  dev or prod install.
- API at `http://localhost:4002` (`ZOO_TEST_API_URL` at build time to change).
  Plain HTTP is allowed in this build only.
- The Scan screen takes a typed serial (`test-serial-input`,
  `test-serial-submit`) instead of opening the camera.
- `testID`s the flows rely on: `login-identifier`, `verify-code`,
  `site-name`, `wifi-ssid`, `wifi-password`, `display-name`, `group-name`.

Source: zoo-mobile `app.config.ts`, `src/screens/setup/ScanScreen.tsx`.
