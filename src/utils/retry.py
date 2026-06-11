from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_retry(
    func: Callable[[], T],
    retries: int = 3,
    delay_seconds: float = 1.0,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except retry_exceptions as exc:  # pragma: no cover - exercised via callers
            last_error = exc
            if attempt == retries:
                raise
            time.sleep(delay_seconds * attempt)
    assert last_error is not None
    raise last_error
