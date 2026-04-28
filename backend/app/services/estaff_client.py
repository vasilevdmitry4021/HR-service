from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, TypedDict
from urllib.parse import urlparse

from app.services.integration_call_tracker import track_integration_call_async

import certifi
import httpx

from app.config import settings
from app.services.estaff_candidate_prepare import hh_normalized_resume_to_estaff_payload
from app.services.estaff_vocabulary import parse_get_voc_response

logger = logging.getLogger(__name__)

USER_AGENT = "HR-Service/1.0 (e-staff export)"


def _host_hint_for_message(server_name: str) -> str:
    s = server_name.strip()
    if not s:
        return "?"
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://"):
        netloc = urlparse(s).netloc
        return (netloc or s.replace("https://", "").replace("http://", ""))[:120]
    return s.split("/")[0].strip()[:120]


def _estaff_tls_verify() -> bool | str:
    if not settings.estaff_http_verify:
        return False
    return certifi.where()


def _estaff_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        verify=_estaff_tls_verify(),
        timeout=httpx.Timeout(30.0, connect=20.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        trust_env=True,
    )


def _user_message_for_request_error(exc: httpx.RequestError, server_name: str) -> str:
    host = _host_hint_for_message(server_name)
    detail = str(exc).lower()
    if "name or service not known" in detail or "getaddrinfo failed" in detail:
        return (
            f"Не удалось найти адрес сервера e-staff ({host}). "
            "Проверьте имя хоста в настройках и DNS на машине, где запущен backend (или в контейнере Docker)."
        )
    if "connection refused" in detail:
        return (
            f"Соединение с e-staff отклонено ({host}). "
            "Проверьте адрес, порт и доступность сервера из сети backend."
        )
    if "network is unreachable" in detail or "no route to host" in detail:
        return (
            f"Сеть недоступна до сервера e-staff ({host}). "
            "Проверьте VPN и маршрут с сервера приложения."
        )
    if "certificate verify failed" in detail or (
        "ssl" in detail and "cert" in detail
    ):
        return (
            "Не удалось проверить сертификат HTTPS сервера e-staff. "
            "Проверьте ESTAFF_HTTP_VERIFY или корпоративный корневой сертификат."
        )
    return (
        f"Ошибка сети при обращении к e-staff ({host}). "
        "Проверьте доступ с сервера backend (не из браузера): VPN, прокси, файрвол."
    )


class EStaffClientError(Exception):
    """Ошибка вызова API e-staff: код HTTP, сообщение для пользователя, детали для БД."""

    def __init__(
        self,
        status_code: int,
        user_message: str,
        detail_for_db: str,
    ):
        self.status_code = status_code
        self.user_message = user_message
        self.detail_for_db = detail_for_db
        super().__init__(user_message)


def build_estaff_base_url(server_name: str) -> str:
    """Базовый URL без /api.

    - URL со схемой — без изменений.
    - Полное имя хоста (есть точка, напр. krit.e-staff.ru) — https://…
    - Короткое имя стенда без точки (напр. krit) — https://krit.e-staff.ru
    """
    host = server_name.strip().rstrip("/")
    if not host:
        return "https://"
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    netloc = host.split("/", 1)[0]
    remainder = host[len(netloc) :]
    hostname, sep, port = netloc.partition(":")
    port_part = f":{port}" if sep else ""
    if "." not in hostname:
        hostname = f"{hostname}.e-staff.ru"
    return f"https://{hostname}{port_part}{remainder}".rstrip("/")


def _user_message_for_http_status(status_code: int) -> str:
    if status_code == 401:
        return (
            "Ошибка авторизации. Проверьте настройки подключения к e-staff."
        )
    if status_code == 403:
        return (
            "Недостаточно прав для выгрузки. Обратитесь к администратору e-staff."
        )
    if status_code == 404:
        return "Указанная вакансия не найдена в e-staff."
    if status_code == 409:
        return "Кандидат уже существует в e-staff."
    if status_code == 422:
        return (
            "Некорректные данные кандидата. Проверьте заполненность резюме."
        )
    if status_code == 429:
        return "Превышен лимит запросов к e-staff. Повторите попытку позже."
    if status_code in (500, 502, 503):
        return "Сервис e-staff временно недоступен. Повторите попытку позже."
    return "Не удалось выполнить выгрузку в e-staff."


def _truncate_detail(text: str, max_len: int = 4000) -> str:
    s = text.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _collapse_whitespace_for_user_message(text: str) -> str:
    s = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return " ".join(s.split())


def extract_estaff_error_message_for_user(
    parsed: Any,
    *,
    max_len: int = 400,
) -> str | None:
    """Достаёт короткое сообщение из JSON тела ошибки e-staff (для ответа пользователю и тестов)."""
    extracted: str | None = None
    if isinstance(parsed, str) and parsed.strip():
        extracted = parsed.strip()
    elif isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            m = err.get("message")
            if isinstance(m, str) and m.strip():
                extracted = m.strip()
        elif isinstance(err, str) and err.strip():
            extracted = err.strip()
        if not extracted:
            for key in ("message", "msg"):
                v = parsed.get(key)
                if isinstance(v, str) and v.strip():
                    extracted = v.strip()
                    break
        if not extracted:
            det = parsed.get("detail")
            if isinstance(det, str) and det.strip():
                extracted = det.strip()
    if not extracted:
        return None
    collapsed = _collapse_whitespace_for_user_message(extracted)
    if "<html" in collapsed.lower():
        return None
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1] + "…"
    return collapsed


def _user_message_from_estaff_http_error(
    status_code: int,
    parsed_err: Any,
) -> str:
    extracted = extract_estaff_error_message_for_user(parsed_err)
    if extracted:
        return extracted
    return _user_message_for_http_status(status_code)


class EstaffVacancyRow(TypedDict):
    id: str
    title: str
    subtitle: str | None


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if float(v).is_integer() else str(v)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _normalize_single_vacancy(obj: dict[str, Any]) -> EstaffVacancyRow | None:
    """Преобразует один объект из ответа e-staff в {id, title, subtitle}. Подстроить под OpenAPI заказчика при необходимости."""
    vid = None
    for key in ("id", "uuid", "vacancy_id", "external_id"):
        vid = _coerce_str(obj.get(key))
        if vid:
            break
    if not vid:
        return None
    title = (
        _coerce_str(obj.get("title"))
        or _coerce_str(obj.get("name"))
        or _coerce_str(obj.get("наименование"))
        or _coerce_str(obj.get("subject"))
        or vid
    )
    if not title:
        title = vid
    parts: list[str] = []
    num = _coerce_str(obj.get("number")) or _coerce_str(obj.get("номер"))
    if num:
        parts.append(f"№ {num}")
    client = obj.get("client")
    if isinstance(client, dict):
        cn = _coerce_str(client.get("name")) or _coerce_str(client.get("title"))
        if cn:
            parts.append(cn)
    elif isinstance(client, str) and client.strip():
        parts.append(client.strip())
    subtitle = " · ".join(parts) if parts else None
    return EstaffVacancyRow(id=vid, title=title, subtitle=subtitle)


def normalize_vacancies_payload(data: Any) -> list[EstaffVacancyRow]:
    """Достаёт список вакансий из типичных обёрток JSON (массив, data, items, results, vacancies)."""
    if isinstance(data, dict) and data.get("success") is False:
        return []
    raw_list: list[Any] = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for key in ("data", "items", "results", "vacancies", "rows"):
            inner = data.get(key)
            if isinstance(inner, list):
                raw_list = inner
                break
    out: list[EstaffVacancyRow] = []
    seen: set[str] = set()
    for el in raw_list:
        if not isinstance(el, dict):
            continue
        row = _normalize_single_vacancy(el)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    return out


_MOCK_VOC_DATA: dict[str, list[dict[str, Any]]] = {
    "locations": [
        {"id": 1, "name": "Москва"},
        {"id": 2, "name": "Санкт-Петербург"},
    ],
    "skill_types": [
        {"id": 10, "name": "Python"},
        {"id": 11, "name": "Django"},
    ],
    "countries": [{"id": "RU", "name": "Россия"}],
}


async def fetch_get_voc(
    server_name: str,
    api_token: str,
    voc_id: str,
    request: Any | None = None,
) -> list[dict[str, Any]]:
    """POST /api/base/get_voc — элементы справочника [{id, name}, ...]."""
    vid = (voc_id or "").strip()
    if not vid:
        raise EStaffClientError(
            422,
            "Не указан идентификатор справочника e-staff.",
            "empty voc id",
        )

    if settings.feature_use_mock_estaff:
        await asyncio.sleep(0.02)
        return list(_MOCK_VOC_DATA.get(vid, [{"id": 0, "name": f"mock-{vid}"}]))

    base = build_estaff_base_url(server_name)
    path = settings.estaff_get_voc_path.strip()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base.rstrip('/')}{path}"
    logger.debug("estaff_get_voc request url=%s voc_id=%s", url, vid)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {"voc": {"id": vid}}

    last_exc: EStaffClientError | None = None
    async with track_integration_call_async(request, "estaff", "fetch_get_voc") as _call:
        for attempt in range(3):
            try:
                async with _estaff_http_client() as client:
                    r = await client.post(url, headers=headers, json=body)
                if r.status_code in (500, 502, 503) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if r.is_success:
                    _call["status_code"] = r.status_code
                    try:
                        parsed = r.json()
                    except Exception:
                        raise EStaffClientError(
                            502,
                            "Некорректный ответ справочника e-staff.",
                            "invalid json get_voc",
                        ) from None
                    items = parse_get_voc_response(parsed)
                    if not items and isinstance(parsed, dict) and parsed.get("success") is not False:
                        logger.warning(
                            "estaff_get_voc_empty voc_id=%s keys=%s",
                            vid,
                            list(parsed.keys()) if isinstance(parsed, dict) else None,
                        )
                    return items
                text = r.text or ""
                try:
                    parsed_err = r.json()
                    err_body = json.dumps(parsed_err, ensure_ascii=False)
                except Exception:
                    parsed_err = None
                    err_body = _truncate_detail(text)
                user_msg = _user_message_from_estaff_http_error(
                    r.status_code,
                    parsed_err if parsed_err is not None else text,
                )
                _call["status_code"] = r.status_code
                raise EStaffClientError(
                    r.status_code,
                    user_msg,
                    _truncate_detail(f"HTTP {r.status_code} get_voc: {err_body}"),
                )
            except httpx.TimeoutException:
                last_exc = EStaffClientError(
                    504,
                    "Сервис e-staff не ответил вовремя. Повторите попытку позже.",
                    "timeout get_voc",
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                _call["error"] = "TimeoutException"
                raise last_exc from None
            except httpx.RequestError as exc:
                logger.warning(
                    "estaff_get_voc_request_error url=%s err=%s",
                    url,
                    exc,
                    exc_info=True,
                )
                last_exc = EStaffClientError(
                    502,
                    _user_message_for_request_error(exc, server_name),
                    _truncate_detail(str(exc)),
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                _call["error"] = "RequestError"
                raise last_exc from None
        if last_exc:
            raise last_exc
        raise EStaffClientError(500, "Не удалось получить справочник e-staff.", "unknown get_voc")


async def fetch_open_vacancies(
    server_name: str,
    api_token: str,
    *,
    min_start_date_iso: str,
    max_start_date_iso: str,
    request: Any | None = None,
) -> tuple[list[EstaffVacancyRow], float]:
    """POST /api/vacancy/find — список вакансий. Возвращает (список, длительность с)."""
    if settings.feature_use_mock_estaff:
        await asyncio.sleep(0.03)
        mock: list[EstaffVacancyRow] = [
            {"id": "mock-vac-1", "title": "Тестовая вакансия A", "subtitle": "№ 0001"},
            {"id": "mock-vac-2", "title": "Тестовая вакансия B", "subtitle": "№ 0002"},
            {"id": "mock-vac-3", "title": "Тестовая вакансия C", "subtitle": None},
        ]
        return mock, 0.03

    base = build_estaff_base_url(server_name)
    path = settings.estaff_vacancies_path.strip()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base.rstrip('/')}{path}"
    logger.debug("estaff_vacancy_find request url=%s", url)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    request_body: dict[str, Any] = {
        "filter": {
            "min_start_date": min_start_date_iso,
            "max_start_date": max_start_date_iso,
        },
        "field_names": ["name", "start_date", "user"],
    }
    t0 = time.perf_counter()
    last_exc: EStaffClientError | None = None
    async with track_integration_call_async(request, "estaff", "fetch_open_vacancies") as _call:
        for attempt in range(3):
            try:
                async with _estaff_http_client() as client:
                    r = await client.post(
                        url,
                        headers=headers,
                        json=request_body,
                    )
                if r.status_code in (500, 502, 503) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if r.is_success:
                    _call["status_code"] = r.status_code
                    try:
                        parsed = r.json()
                    except Exception:
                        raise EStaffClientError(
                            502,
                            "Некорректный ответ списка вакансий e-staff.",
                            "invalid json",
                        ) from None
                    rows = normalize_vacancies_payload(parsed)
                    return rows, time.perf_counter() - t0
                text = r.text or ""
                try:
                    parsed_err = r.json()
                    err_body = json.dumps(parsed_err, ensure_ascii=False)
                except Exception:
                    parsed_err = None
                    err_body = _truncate_detail(text)
                if r.status_code == 404:
                    user_msg = "Список вакансий в e-staff не найден. Проверьте путь API (ESTAFF_VACANCIES_PATH)."
                else:
                    user_msg = _user_message_from_estaff_http_error(
                        r.status_code,
                        parsed_err if parsed_err is not None else text,
                    )
                _call["status_code"] = r.status_code
                raise EStaffClientError(
                    r.status_code,
                    user_msg,
                    _truncate_detail(f"HTTP {r.status_code}: {err_body}"),
                )
            except httpx.TimeoutException:
                last_exc = EStaffClientError(
                    504,
                    "Сервис e-staff не ответил вовремя. Повторите попытку позже.",
                    "timeout",
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                _call["error"] = "TimeoutException"
                raise last_exc from None
            except httpx.RequestError as exc:
                logger.warning(
                    "estaff_vacancies_request_error url=%s err=%s",
                    url,
                    exc,
                    exc_info=True,
                )
                last_exc = EStaffClientError(
                    502,
                    _user_message_for_request_error(exc, server_name),
                    _truncate_detail(str(exc)),
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                _call["error"] = "RequestError"
                raise last_exc from None
        if last_exc:
            raise last_exc
        raise EStaffClientError(500, "Не удалось получить список вакансий e-staff.", "unknown")


def _extract_candidate_id_from_response(data: Any) -> str | None:
    if data is None:
        return None
    if isinstance(data, dict):
        for key in ("id", "candidate_id", "uuid"):
            v = data.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in ("id", "candidate_id"):
                v = inner.get(key)
                if v is not None and str(v).strip():
                    return str(v).strip()
    return None


def _extract_user_from_get_response(data: Any) -> dict[str, Any] | None:
    if data is None:
        return None
    if isinstance(data, dict):
        if data.get("success") is False:
            return None
        if isinstance(data.get("user"), dict):
            return data["user"]
        if isinstance(data.get("data"), dict):
            return data["data"]
        has_identity = any(
            isinstance(data.get(k), (str, int))
            for k in ("id", "login", "email", "name", "full_name")
        )
        if has_identity:
            return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
    return None


async def fetch_user_by_login(
    server_name: str,
    api_token: str,
    login: str,
) -> tuple[dict[str, Any] | None, float]:
    normalized_login = (login or "").strip()
    if not normalized_login:
        raise EStaffClientError(
            422,
            "Не указан логин пользователя e-staff.",
            "empty user login",
        )
    if settings.feature_use_mock_estaff:
        await asyncio.sleep(0.02)
        return {"id": "mock-user", "login": normalized_login, "name": "Mock User"}, 0.02

    base = build_estaff_base_url(server_name)
    path = settings.estaff_user_get_path.strip()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    t0 = time.perf_counter()
    last_exc: EStaffClientError | None = None
    for attempt in range(3):
        try:
            async with _estaff_http_client() as client:
                r = await client.post(
                    url,
                    headers=headers,
                    json={"user": {"login": normalized_login}},
                )
            if r.status_code == 404:
                return None, time.perf_counter() - t0
            if r.status_code in (500, 502, 503) and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if r.is_success:
                try:
                    parsed = r.json()
                except Exception:
                    raise EStaffClientError(
                        502,
                        "Некорректный ответ проверки пользователя e-staff.",
                        "invalid json user/get",
                    ) from None
                return _extract_user_from_get_response(parsed), time.perf_counter() - t0
            text = r.text or ""
            try:
                parsed_err = r.json()
                err_body = json.dumps(parsed_err, ensure_ascii=False)
            except Exception:
                parsed_err = None
                err_body = _truncate_detail(text)
            user_msg = _user_message_from_estaff_http_error(
                r.status_code,
                parsed_err if parsed_err is not None else text,
            )
            raise EStaffClientError(
                r.status_code,
                user_msg,
                _truncate_detail(f"HTTP {r.status_code} user/get: {err_body}"),
            )
        except httpx.TimeoutException:
            last_exc = EStaffClientError(
                504,
                "Сервис e-staff не ответил вовремя. Повторите попытку позже.",
                "timeout user/get",
            )
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise last_exc from None
        except httpx.RequestError as exc:
            last_exc = EStaffClientError(
                502,
                _user_message_for_request_error(exc, server_name),
                _truncate_detail(str(exc)),
            )
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise last_exc from None
    if last_exc:
        raise last_exc
    raise EStaffClientError(500, "Не удалось проверить логин e-staff.", "unknown user/get")


async def create_candidate_in_estaff(
    server_name: str,
    api_token: str,
    body: dict[str, Any],
    *,
    user_login: str,
    vacancy_id: str | None = None,
    request: Any | None = None,
) -> tuple[str | None, float]:
    """Создаёт кандидата в e-staff. Возвращает (id кандидата или None, длительность с)."""
    if settings.feature_use_mock_estaff:
        await asyncio.sleep(0.05)
        rid = str(
            body.get("email")
            or body.get("lastname")
            or body.get("firstname")
            or "mock",
        )
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in rid)[:40]
        return f"mock-estaff-{safe}", 0.05

    base = build_estaff_base_url(server_name)
    path = settings.estaff_create_candidate_path.strip()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base.rstrip('/')}{path}"
    logger.debug("estaff_candidate_add request url=%s", url)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    normalized_user_login = (user_login or "").strip()
    if not normalized_user_login:
        raise EStaffClientError(
            422,
            "Не указан логин пользователя e-staff.",
            "empty user login for candidate/add",
        )
    candidate_payload = dict(body)
    candidate_payload["user_login"] = normalized_user_login
    send_body: dict[str, Any] = {"candidate": candidate_payload}
    if vacancy_id and str(vacancy_id).strip():
        vid = str(vacancy_id).strip()
        try:
            send_body["vacancy"] = {"id": int(vid, 10)}
        except ValueError:
            raise EStaffClientError(
                422,
                "Некорректный идентификатор вакансии e-staff.",
                f"vacancy_id is not int: {vid!r}",
            ) from None

    last_exc: EStaffClientError | None = None
    t0 = time.perf_counter()
    async with track_integration_call_async(request, "estaff", "create_candidate") as _call:
        for attempt in range(3):
            try:
                async with _estaff_http_client() as client:
                    r = await client.post(
                        url,
                        json=send_body,
                        headers=headers,
                    )
                if r.status_code in (500, 502, 503) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if r.is_success:
                    _call["status_code"] = r.status_code
                    try:
                        parsed = r.json()
                    except Exception:
                        parsed = None
                    cid = _extract_candidate_id_from_response(parsed)
                    return cid, time.perf_counter() - t0
                text = r.text or ""
                try:
                    parsed_err = r.json()
                    err_body = json.dumps(parsed_err, ensure_ascii=False)
                except Exception:
                    parsed_err = None
                    err_body = _truncate_detail(text)
                user_msg = _user_message_from_estaff_http_error(
                    r.status_code,
                    parsed_err if parsed_err is not None else text,
                )
                _call["status_code"] = r.status_code
                raise EStaffClientError(
                    r.status_code,
                    user_msg,
                    _truncate_detail(f"HTTP {r.status_code}: {err_body}"),
                )
            except httpx.TimeoutException:
                last_exc = EStaffClientError(
                    504,
                    "Сервис e-staff не ответил вовремя. Повторите попытку позже.",
                    "timeout",
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                _call["error"] = "TimeoutException"
                raise last_exc from None
            except httpx.RequestError as exc:
                logger.warning(
                    "estaff_candidate_request_error url=%s err=%s",
                    url,
                    exc,
                    exc_info=True,
                )
                last_exc = EStaffClientError(
                    502,
                    _user_message_for_request_error(exc, server_name),
                    _truncate_detail(str(exc)),
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                _call["error"] = "RequestError"
                raise last_exc from None
        if last_exc:
            raise last_exc
        raise EStaffClientError(500, "Не удалось выполнить выгрузку в e-staff.", "unknown")
