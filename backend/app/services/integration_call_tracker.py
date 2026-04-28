"""Контекстные менеджеры для трекинга вызовов внешних систем.

Позволяют накапливать список вызовов в request.state.integration_calls
для последующей записи в журнал запросов.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Generator


def _append_call(request: Any, entry: dict[str, Any]) -> None:
    try:
        if not hasattr(request.state, "integration_calls") or request.state.integration_calls is None:
            request.state.integration_calls = []
        request.state.integration_calls.append(entry)
    except Exception:
        pass


@contextmanager
def track_integration_call(
    request: Any,
    system: str,
    operation: str,
) -> Generator[dict[str, Any], None, None]:
    """Синхронный контекстный менеджер трекинга вызова внешней системы.

    Пример:
        with track_integration_call(request, "hh", "search_resumes") as call:
            result = do_hh_call()
            call["status_code"] = result.status_code
    """
    entry: dict[str, Any] = {
        "system": system,
        "operation": operation,
        "duration_ms": None,
        "status_code": None,
        "cached": False,
        "error": None,
    }
    t0 = time.perf_counter()
    try:
        yield entry
        entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        if entry["error"] is None:
            entry["error"] = type(exc).__name__
        raise
    finally:
        if request is not None:
            _append_call(request, entry)


@asynccontextmanager
async def track_integration_call_async(
    request: Any,
    system: str,
    operation: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Асинхронный контекстный менеджер трекинга вызова внешней системы.

    Пример:
        async with track_integration_call_async(request, "hh", "fetch_resume") as call:
            result = await do_async_hh_call()
            call["status_code"] = 200
    """
    entry: dict[str, Any] = {
        "system": system,
        "operation": operation,
        "duration_ms": None,
        "status_code": None,
        "cached": False,
        "error": None,
    }
    t0 = time.perf_counter()
    try:
        yield entry
        entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        entry["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        if entry["error"] is None:
            entry["error"] = type(exc).__name__
        raise
    finally:
        if request is not None:
            _append_call(request, entry)
