from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class TimeoutError_(AssertionError):
    """A wait that ran out of time. An AssertionError so pytest reports it as a test failure."""


def wait_for(check: Callable[[], T | None], timeout: float, interval: float, description: str) -> T:
    """Calls `check` until it returns something truthy, or fails after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            result = check()
            if result:
                return result
        except Exception as error:  # keep polling; report the last error if time runs out
            last_error = error
        if time.monotonic() >= deadline:
            detail = f" (last error: {last_error})" if last_error else ""
            raise TimeoutError_(f"timed out after {timeout:.0f}s waiting for {description}{detail}")
        time.sleep(interval)
