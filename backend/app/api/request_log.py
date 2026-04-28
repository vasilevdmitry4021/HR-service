"""API для чтения журнала запросов. Доступен только администраторам системы."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_system_admin
from app.models.request_log import RequestLog
from app.models.user import User
from app.schemas.request_log import (
    DayStats,
    IntegrationStats,
    RequestLogErrorGroupOut,
    RequestLogErrorsListOut,
    RequestLogListOut,
    RequestLogOut,
    RequestLogStatsOut,
    RouteTagStats,
    TopError,
)

router = APIRouter(prefix="/request-log", tags=["request-log"])


def _normalize_date_to_upper_bound(date_to: datetime | None) -> datetime | None:
    """Для фильтра по дню включаем весь выбранный день, если время не указано."""
    if date_to is None:
        return None
    if date_to.timetz().replace(tzinfo=None) != time.min or date_to.microsecond != 0:
        return date_to
    return date_to + timedelta(days=1)


def _apply_date_filters(stmt: Any, date_from: datetime | None, date_to: datetime | None) -> Any:
    if date_from:
        stmt = stmt.where(RequestLog.created_at >= date_from)
    if date_to:
        normalized_date_to = _normalize_date_to_upper_bound(date_to)
        if normalized_date_to != date_to:
            stmt = stmt.where(RequestLog.created_at < normalized_date_to)
        else:
            stmt = stmt.where(RequestLog.created_at <= normalized_date_to)
    return stmt


@router.get("/stats", response_model=RequestLogStatsOut)
def get_request_log_stats(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_system_admin),
) -> RequestLogStatsOut:
    base = select(RequestLog)
    base = _apply_date_filters(base, date_from, date_to)

    rows = db.scalars(base).all()

    if not rows:
        return RequestLogStatsOut(
            total_requests=0,
            success_count=0,
            error_count=0,
            avg_duration_ms=0.0,
            p95_duration_ms=0.0,
            by_route_tag=[],
            by_day=[],
            top_errors=[],
            integration_summary=[],
        )

    total_requests = len(rows)
    success_count = sum(1 for r in rows if r.status_code < 400)
    error_count = total_requests - success_count
    durations = sorted(r.duration_ms for r in rows)
    avg_duration_ms = sum(durations) / total_requests
    p95_idx = max(0, int(total_requests * 0.95) - 1)
    p95_duration_ms = float(durations[p95_idx])

    by_route_tag = _calc_by_route_tag(rows)
    by_day = _calc_by_day(rows)
    top_errors = _calc_top_errors(rows)
    integration_summary = _calc_integration_summary(rows)

    return RequestLogStatsOut(
        total_requests=total_requests,
        success_count=success_count,
        error_count=error_count,
        avg_duration_ms=avg_duration_ms,
        p95_duration_ms=p95_duration_ms,
        by_route_tag=by_route_tag,
        by_day=by_day,
        top_errors=top_errors,
        integration_summary=integration_summary,
    )


def _calc_by_route_tag(rows: list[RequestLog]) -> list[RouteTagStats]:
    groups: dict[str, list[RequestLog]] = {}
    for r in rows:
        groups.setdefault(r.route_tag, []).append(r)
    result = []
    for tag, group in sorted(groups.items()):
        errors = sum(1 for r in group if r.status_code >= 400)
        avg_ms = sum(r.duration_ms for r in group) / len(group)
        result.append(RouteTagStats(
            route_tag=tag,
            count=len(group),
            error_count=errors,
            avg_duration_ms=avg_ms,
        ))
    return result


def _calc_by_day(rows: list[RequestLog]) -> list[DayStats]:
    from collections import defaultdict
    groups: dict[Any, list[RequestLog]] = defaultdict(list)
    for r in rows:
        day = r.created_at.date() if r.created_at else None
        if day:
            groups[day].append(r)
    result = []
    for day in sorted(groups.keys()):
        group = groups[day]
        errors = sum(1 for r in group if r.status_code >= 400)
        avg_ms = sum(r.duration_ms for r in group) / len(group)
        result.append(DayStats(
            date=day,
            count=len(group),
            error_count=errors,
            avg_duration_ms=avg_ms,
        ))
    return result


def _calc_top_errors(rows: list[RequestLog]) -> list[TopError]:
    from collections import Counter
    counter: Counter[tuple[str, str | None]] = Counter()
    for r in rows:
        if r.error_type:
            counter[(r.error_type, r.error_message)] += 1
    result = []
    for (error_type, error_message), count in counter.most_common(10):
        result.append(TopError(error_type=error_type, error_message=error_message, count=count))
    return result


def _calc_integration_summary(rows: list[RequestLog]) -> list[IntegrationStats]:
    from collections import defaultdict
    systems: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.integration_calls:
            for call in r.integration_calls:
                system = call.get("system")
                if system:
                    systems[system].append(call)
    result = []
    for system, calls in sorted(systems.items()):
        total = len(calls)
        durations = [c.get("duration_ms", 0) for c in calls]
        avg_ms = sum(durations) / total if total else 0.0
        errors = sum(
            1 for c in calls
            if c.get("status_code") and int(c.get("status_code", 0)) >= 400
        )
        error_rate = errors / total if total else 0.0
        result.append(IntegrationStats(
            system=system,
            call_count=total,
            avg_duration_ms=avg_ms,
            error_rate=error_rate,
        ))
    return result


@router.get("/errors", response_model=RequestLogErrorsListOut)
def get_request_log_errors(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    route_tag: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_system_admin),
) -> RequestLogErrorsListOut:
    stmt = select(RequestLog).where(RequestLog.error_type.isnot(None))
    stmt = _apply_date_filters(stmt, date_from, date_to)
    if route_tag:
        stmt = stmt.where(RequestLog.route_tag == route_tag)
    if error_type:
        stmt = stmt.where(RequestLog.error_type == error_type)

    rows = db.scalars(stmt.order_by(RequestLog.created_at.desc())).all()

    from collections import defaultdict
    groups: dict[tuple[str, str | None], list[RequestLog]] = defaultdict(list)
    for r in rows:
        key = (r.error_type or "", r.error_message)
        groups[key].append(r)

    items = []
    for (et, em), group in sorted(groups.items(), key=lambda x: -len(x[1])):
        last_seen = max(r.created_at for r in group)
        route_tags = sorted({r.route_tag for r in group})
        affected_users = len({r.user_id for r in group if r.user_id})
        items.append(RequestLogErrorGroupOut(
            error_type=et,
            error_message=em,
            count=len(group),
            last_seen=last_seen,
            route_tags=route_tags,
            affected_users_count=affected_users,
        ))

    return RequestLogErrorsListOut(items=items, total=len(items))


@router.get("", response_model=RequestLogListOut)
def list_request_log(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    route_tag: str | None = Query(default=None),
    status_min: int | None = Query(default=None),
    status_max: int | None = Query(default=None),
    error_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_system_admin),
) -> RequestLogListOut:
    stmt = select(RequestLog)
    stmt = _apply_date_filters(stmt, date_from, date_to)

    if user_id is not None:
        stmt = stmt.where(RequestLog.user_id == user_id)
    if route_tag:
        stmt = stmt.where(RequestLog.route_tag == route_tag)
    if status_min is not None:
        stmt = stmt.where(RequestLog.status_code >= status_min)
    if status_max is not None:
        stmt = stmt.where(RequestLog.status_code <= status_max)
    if error_type:
        stmt = stmt.where(RequestLog.error_type == error_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            RequestLog.request_id.ilike(like)
            | RequestLog.query_id.ilike(like)
            | RequestLog.user_email.ilike(like)
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.scalar(count_stmt) or 0)

    rows = db.scalars(
        stmt.order_by(RequestLog.created_at.desc()).offset(skip).limit(limit)
    ).all()

    return RequestLogListOut(
        items=[RequestLogOut.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{request_id}", response_model=RequestLogOut)
def get_request_log_entry(
    request_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_system_admin),
) -> RequestLogOut:
    row = db.scalars(
        select(RequestLog).where(RequestLog.request_id == request_id)
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Запись журнала с request_id='{request_id}' не найдена",
        )
    return RequestLogOut.model_validate(row)
