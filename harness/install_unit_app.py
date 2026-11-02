"""`just install-unit-app`: builds jiboia's debug app for whichever role the
unit already runs, from the jiboia repo's current checkout, and installs it
over the existing one -- keeping its data and Device Owner status."""

from __future__ import annotations

import re
import sys

from . import config as config_module
from .adb import Adb
from .unit import install_debug_app


def main() -> int:
    config = config_module.load()
    adb = Adb(config.unit_device, "unit")
    adb.ensure_ready()
    roles = {
        match.group(1)
        for package in adb.installed_packages("com.jiboia.doorbell")
        if (match := re.match(r"^com\.jiboia\.doorbell\.(outside|inside)", package))
    }
    if len(roles) != 1:
        print(
            "Expected exactly one jiboia role installed on the unit, found: "
            f"{sorted(roles) or 'none'}. Factory-install it first with jiboia's `just factory-cli`.",
            file=sys.stderr,
        )
        return 1
    role = roles.pop()
    print(f"Building and installing jiboia's {role} debug app on {config.unit_device}...")
    install_debug_app(adb, config.jiboia_repo, role, config.java_home)
    print("Installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
