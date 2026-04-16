from __future__ import annotations

import json
from typing import Any

import httpx

# (type, value) из ответа HH → человекочитаемое сообщение
HH_API_ERRORS: dict[tuple[str, str], str] = {
    ("api_access_payment", "action_must_be_payed"): (
        "Требуется оплата услуги доступа к базе резюме на HeadHunter"
    ),
    ("resumes", "view_limit_exceeded"): "Превышен дневной лимит просмотров резюме",
    ("resumes", "quota_exceeded"): "Превышена квота просмотров, установленная менеджеру",
    ("resumes", "no_available_service"): "Не хватает услуг для просмотра резюме",
    ("resumes", "cant_view_contacts"): "Нет прав на просмотр контактов",
    ("oauth", "bad_authorization"): "Токен HeadHunter недействителен — подключите аккаунт заново",
    ("oauth", "token_expired"): "Срок действия токена HeadHunter истёк — обновите подключение",
    ("oauth", "token_revoked"): "Доступ HeadHunter отозван — выполните повторное подключение",
    ("captcha_required", "captcha_required"): "HeadHunter требует пройти проверку (капчу). Повторите позже",
}

HH_VIEW_LIMIT_EXCEEDED_MESSAGE = HH_API_ERRORS[("resumes", "view_limit_exceeded")]


def _parse_hh_json_errors(body: Any) -> list[tuple[str, str]]:
    if not isinstance(body, dict):
        return []
    errors = body.get("errors")
    if not isinstance(errors, list):
        return []
    out: list[tuple[str, str]] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        t = str(err.get("type", ""))
        v = str(err.get("value", ""))
        if t and v:
            out.append((t, v))
    return out


def message_for_hh_error_response(response: httpx.Response) -> str | None:
    """Извлекает сообщение по телу ошибки HH или None."""
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    pairs = _parse_hh_json_errors(data)
    for pair in pairs:
        if pair in HH_API_ERRORS:
            return HH_API_ERRORS[pair]
    if pairs:
        t, v = pairs[0]
        return f"Ошибка HeadHunter ({t}): {v}"
    if isinstance(data, dict):
        desc = data.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    return None


def classify_hh_http_status(response: httpx.Response) -> tuple[int, str]:
    """
    Возвращает (предлагаемый HTTP-код клиенту, detail).
    """
    custom = message_for_hh_error_response(response)
    status = response.status_code

    if status == 401:
        msg = custom or "Авторизация HeadHunter не принята — проверьте токен"
        return 401, msg
    if status == 403:
        return 403, custom or "Нет доступа к базе резюме (проверьте оплату и права на HH)"
    if status == 404:
        return 404, custom or "Ресурс не найден в HeadHunter"
    if status == 429:
        return 429, custom or "Превышен лимит запросов к HeadHunter"
    if status == 400:
        return 400, custom or "Некорректные параметры запроса к HeadHunter"
    if status >= 500:
        return 503, custom or "HeadHunter временно недоступен"

    return 503, custom or "HeadHunter API недоступен"


def is_daily_view_limit_error(detail: str | None) -> bool:
    """True, если detail указывает на суточный лимит просмотров резюме HH."""
    if not isinstance(detail, str):
        return False
    normalized = detail.strip().lower()
    if not normalized:
        return False
    return (
        HH_VIEW_LIMIT_EXCEEDED_MESSAGE.lower() in normalized
        or "view_limit_exceeded" in normalized
    )
