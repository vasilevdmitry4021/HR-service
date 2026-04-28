"""Middleware для автоматической записи каждого HTTP-запроса в журнал."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_SKIP_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
_SKIP_PREFIXES = ("/docs/", "/openapi", "/static", "/api/v1/request-log")
_TRACKED_EXACT_PATHS = {
    ("POST", "/api/v1/search"): "search",
    ("POST", "/api/v1/search/parse"): "parse",
}
_TRACKED_SEARCH_SUFFIXES = {
    "/evaluate": "evaluate",
    "/evaluate/start": "evaluate",
    "/analyze": "analyze",
    "/analyze/start": "analyze",
}
_CANDIDATE_ANALYZE_RE = re.compile(r"^/api/v1/candidates/[^/]+/analyze$")


def _should_skip(path: str) -> bool:
    if path in _SKIP_PATHS:
        return True
    for prefix in _SKIP_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _tracked_route_tag(method: str, path: str) -> str | None:
    route_tag = _TRACKED_EXACT_PATHS.get((method.upper(), path))
    if route_tag:
        return route_tag

    if method.upper() != "POST":
        return None

    if path.startswith("/api/v1/search/"):
        for suffix, suffix_tag in _TRACKED_SEARCH_SUFFIXES.items():
            if path.endswith(suffix):
                return suffix_tag

    if _CANDIDATE_ANALYZE_RE.match(path):
        return "analyze"

    return None


def _route_tag(path: str) -> str:
    if "/parse" in path:
        return "parse"
    if "/evaluate" in path:
        return "evaluate"
    if "/analyze" in path:
        return "analyze"
    stripped = path.rstrip("/")
    if stripped == "/api/v1/search":
        return "search"
    if "/estaff/export" in path:
        return "estaff_export"
    if "/estaff/vacancies" in path:
        return "estaff_vacancies"
    if path.startswith("/api/v1/llm"):
        return "llm_settings"
    if path.startswith("/api/v1/auth"):
        return "auth"
    return "other"


def _classify_error_type(status_code: int, error_type_from_state: str | None) -> str | None:
    if error_type_from_state:
        return error_type_from_state
    if status_code < 400:
        return None
    if status_code in (401, 403):
        return "hh_permission"
    if status_code == 429:
        return "hh_rate_limit"
    if status_code >= 500:
        return "internal"
    return None


def _safe_state(request: Request, attr: str, default: Any = None) -> Any:
    try:
        val = getattr(request.state, attr, default)
        return val if val is not None else default
    except Exception:
        return default


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        route_tag = _tracked_route_tag(request.method, path)
        if _should_skip(path) or route_tag is None:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        t0 = time.perf_counter()

        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            asyncio.get_running_loop().run_in_executor(
                None,
                _write_log,
                request,
                request_id,
                request.method,
                path,
                route_tag,
                status_code,
                duration_ms,
            )

        return response


def _write_log(
    request: Request,
    request_id: str,
    method: str,
    path: str,
    route_tag: str,
    status_code: int,
    duration_ms: int,
) -> None:
    try:
        from app.services.request_log_writer import write_request_log

        user_id = _safe_state(request, "user_id")
        user_email = _safe_state(request, "user_email")
        query_id = _safe_state(request, "query_id")
        search_metrics = _safe_state(request, "search_metrics")
        request_body_summary = _safe_state(request, "request_body_summary")
        response_summary = _safe_state(request, "response_summary")
        integration_calls = _safe_state(request, "integration_calls")
        error_type_state = _safe_state(request, "error_type")
        error_message_state = _safe_state(request, "error_message")

        error_type = _classify_error_type(status_code, error_type_state)

        write_request_log(
            request_id=request_id,
            query_id=query_id,
            user_id=user_id,
            user_email=user_email,
            method=method,
            route=path,
            route_tag=route_tag,
            status_code=status_code,
            duration_ms=duration_ms,
            request_body_summary=request_body_summary,
            response_summary=response_summary,
            search_metrics=search_metrics,
            integration_calls=integration_calls,
            error_type=error_type,
            error_message=error_message_state,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Ошибка записи в request_log: request_id=%s path=%s", request_id, path
        )
