# zookeeper -- integration tests across jiboia, zoo-server and zoo-mobile.
# Run `just` to list recipes. See README.md.

python := ".venv/bin/python"
java_home := `python3 -c "import tomllib,pathlib;p=pathlib.Path('config.local.toml');c=tomllib.loads(p.read_text()) if p.exists() else {};print(c.get('tools',{}).get('java_home','/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home'))"`
zoo := `python3 -c "import tomllib,pathlib;p=pathlib.Path('config.local.toml');c=tomllib.loads(p.read_text()) if p.exists() else {};print(c.get('repos',{}).get('zoo','../zoo'))"`

default:
    just --list

# Create config.local.toml from the example (devices, test Wi-Fi).
init:
    @test -f config.local.toml && echo "config.local.toml already exists" || (cp config.example.toml config.local.toml && echo "Created config.local.toml -- fill in the devices and Wi-Fi")

# Install Maestro (drives the phone app), unless it's already installed.
setup-prerequisite:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v maestro >/dev/null 2>&1 || [ -x "$HOME/.maestro/bin/maestro" ]; then
      echo "maestro: already installed"
      exit 0
    fi
    curl -fsSL "https://get.maestro.mobile.dev" | bash
    echo "Installed in ~/.maestro/bin. Open a new shell (or add it to PATH) to use it directly."

# Python environment, and a check for every tool the tests need.
setup:
    #!/usr/bin/env bash
    set -uo pipefail
    python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && echo "python: ok"
    missing=0
    check() { if command -v "$1" >/dev/null 2>&1 || [ -x "$2" ]; then echo "$1: ok"; else echo "$1: MISSING -- $3"; missing=1; fi; }
    check adb "$HOME/Library/Android/sdk/platform-tools/adb" "install Android platform-tools"
    check mosquitto /opt/homebrew/sbin/mosquitto "brew install mosquitto"
    check mosquitto_sub /opt/homebrew/bin/mosquitto_sub "brew install mosquitto"
    check openssl /opt/homebrew/bin/openssl "brew install openssl"
    check cargo "$HOME/.cargo/bin/cargo" "install Rust (rustup)"
    check maestro "$HOME/.maestro/bin/maestro" "just setup-prerequisite"
    check npm /opt/homebrew/bin/npm "brew install node"
    exit $missing

# List what's plugged in over USB (to fill in config.local.toml).
devices:
    adb devices -l

# Build zoo-mobile's test APK (rerun after zoo-mobile changes).
build-phone-app:
    ./scripts/build_phone_app.sh "$(cd {{zoo}} && pwd)/zoo-mobile" "{{java_home}}"

# Build jiboia's debug app for the unit's role and install it on the unit (rerun after jiboia changes).
install-unit-app:
    {{python}} -m harness.install_unit_app

# Every test (needs the devices for the hardware ones).
test *args:
    {{python}} -m pytest {{args}}

# Only the backend check -- no devices needed.
test-backend:
    {{python}} -m pytest suites/backend

# Only the Bluetooth setup test.
test-ble-setup:
    {{python}} -m pytest suites/provisioning/test_ble_setup.py
