from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RequestLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: str
    query_id: str | None
    user_id: UUID | None
    user_email: str | None
    method: str
    route: str
    route_tag: str
    status_code: int
    duration_ms: int
    request_body_summary: dict[str, Any] | None
    response_summary: dict[str, Any] | None
    search_metrics: dict[str, Any] | None
    integration_calls: list[dict[str, Any]] | None
    error_type: str | None
    error_message: str | None
    created_at: datetime


class RequestLogListOut(BaseModel):
    items: list[RequestLogOut]
    total: int


class RouteTagStats(BaseModel):
    route_tag: str
    count: int
    error_count: int
    avg_duration_ms: float


class DayStats(BaseModel):
    date: date
    count: int
    error_count: int
    avg_duration_ms: float


class TopError(BaseModel):
    error_type: str
    error_message: str | None
    count: int


class IntegrationStats(BaseModel):
    system: str
    call_count: int
    avg_duration_ms: float
    error_rate: float


class RequestLogStatsOut(BaseModel):
    total_requests: int
    success_count: int
    error_count: int
    avg_duration_ms: float
    p95_duration_ms: float
    by_route_tag: list[RouteTagStats]
    by_day: list[DayStats]
    top_errors: list[TopError]
    integration_summary: list[IntegrationStats]


class RequestLogErrorGroupOut(BaseModel):
    error_type: str
    error_message: str | None
    count: int
    last_seen: datetime
    route_tags: list[str]
    affected_users_count: int


class RequestLogErrorsListOut(BaseModel):
    items: list[RequestLogErrorGroupOut]
    total: int


class RequestLogFilters(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    user_id: UUID | None = None
    route_tag: str | None = None
    error_type: str | None = None
    status_min: int | None = None
    status_max: int | None = None
    search: str | None = None
