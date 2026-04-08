"""Централизованный клиент LLM: провайдеры из БД (приоритет) или из переменных окружения."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.system_settings import SystemSettings
from app.schemas.llm import LLMProvider
from app.services import encryption

logger = logging.getLogger(__name__)

LLM_CREDENTIALS_KEY = "llm_credentials"

SYSTEM_PROMPT = """Ты — ассистент для парсинга HR-запросов. Извлеки параметры из текста.

ВАЖНО: Извлекай ТОЛЬКО то, что ЯВНО указано в запросе. НЕ добавляй связанные термины, синонимы или предположения.

Верни ТОЛЬКО валидный JSON (без markdown, без текста до/после):
{
  "skills": [],
  "experience_years_min": null,
  "experience_years_max": null,
  "region": null,
  "position_keywords": [],
  "gender": null,
  "industry": [],
  "age_min": null,
  "age_max": null
}

Правила извлечения:

- skills: профессиональные навыки и компетенции кандидата, ЯВНО указанные в запросе.
  * Для IT-позиций: технологии, языки программирования, фреймворки (Python, Java, Docker, React, PostgreSQL)
  * Для юристов: области права (арбитраж, корпоративное право, судебные дела, договорная работа)
  * Для бухгалтеров: направления учёта (налоговый учёт, МСФО, 1С, бюджетирование)
  * Для HR: направления работы (подбор персонала, кадровое делопроизводство, C&B)
  * Для менеджеров: методологии и области (управление проектами, Agile, Scrum)
  НЕ добавляй навыки, которые не упомянуты в запросе!

- industry: отрасль, в которой должен иметь опыт кандидат.
  Примеры: IT, retail, finance, банки, телеком, строительство, недвижимость, медицина, производство.
  "в области ИТ", "в сфере ритейла", "опыт в банках" -> это industry, НЕ skills!

- position_keywords: должность на русском И английском.
  Примеры: ["юрист", "lawyer"], ["бухгалтер", "accountant"], ["разработчик", "developer"]

- experience_years_min: "2 года", "от 3 лет", "3+ года" -> число (2, 3)
- experience_years_max: "до 5 лет", "3-5 лет" -> 5
- age_min: "от 25 лет" -> 25
- age_max: "до 35 лет" -> 35
- region: город (Москва, Санкт-Петербург, Казань и т.д.)
- gender: "male" / "female" только если явно указан пол

Примеры:

"Юрист с опытом арбитражных дел в области ИТ" ->
{"skills":["арбитраж","арбитражные дела"],"experience_years_min":null,"experience_years_max":null,"region":null,"position_keywords":["юрист","lawyer"],"gender":null,"industry":["IT"],"age_min":null,"age_max":null}

"Бухгалтер со знанием МСФО, опыт в банковской сфере от 3 лет" ->
{"skills":["МСФО"],"experience_years_min":3,"experience_years_max":null,"region":null,"position_keywords":["бухгалтер","accountant"],"gender":null,"industry":["finance","банки"],"age_min":null,"age_max":null}

"Системный аналитик с опытом работы с микросервисами, 2 года, Москва" ->
{"skills":["микросервисы"],"experience_years_min":2,"experience_years_max":null,"region":"Москва","position_keywords":["системный аналитик","system analyst"],"gender":null,"industry":[],"age_min":null,"age_max":null}

"Java developer 5+ лет, Spring Boot, до 40 лет" ->
{"skills":["Java","Spring Boot"],"experience_years_min":5,"experience_years_max":null,"region":null,"position_keywords":["разработчик","developer"],"gender":null,"industry":[],"age_min":null,"age_max":40}

"HR-менеджер с опытом подбора IT-специалистов" ->
{"skills":["подбор персонала"],"experience_years_min":null,"experience_years_max":null,"region":null,"position_keywords":["HR-менеджер","HR manager"],"gender":null,"industry":["IT"],"age_min":null,"age_max":null}

Ответ — только JSON."""

_gigachat_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    endpoint: str
    api_key: str | None
    model: str
    fast_model: str
    folder_id: str | None
    client_id: str | None
    client_secret: str | None
    scope: str | None
    llm_search_batch_size: int
    llm_fast_batch_size: int
    llm_detailed_top_n: int


def _stored_llm_dict(db: Session) -> dict[str, Any] | None:
    row = db.scalars(
        select(SystemSettings).where(SystemSettings.key == LLM_CREDENTIALS_KEY)
    ).first()
    if not row:
        return None
    try:
        data = encryption.decrypt_json(row.encrypted_value)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def get_llm_credentials_from_db(db: Session) -> dict[str, Any] | None:
    """Расшифрованные настройки LLM из БД (или None)."""
    return _stored_llm_dict(db)


def _default_provider_env(endpoint: str) -> str:
    ep = (endpoint or "").lower()
    if "/api/chat" in ep or "/api/generate" in ep:
        return LLMProvider.OLLAMA.value
    return LLMProvider.OPENAI_COMPATIBLE.value


def get_llm_config(db: Session | None) -> LLMRuntimeConfig:
    """Эффективная конфигурация: учётные данные LLM из БД; батчи и топ-N — из настроек сервера."""
    stored: dict[str, Any] | None = None
    if db is not None:
        stored = _stored_llm_dict(db)

    env_endpoint = (settings.internal_llm_endpoint or "").strip()
    env_key = (settings.internal_llm_api_key or "ollama").strip() or "ollama"
    env_model = (settings.internal_llm_model or "llama3.2").strip() or "llama3.2"
    env_fast = (settings.llm_fast_model or "qwen2.5:7b").strip() or "qwen2.5:7b"

    if stored:
        prov = str(stored.get("provider") or _default_provider_env(str(stored.get("endpoint") or "")))
        endpoint = (str(stored.get("endpoint") or "")).strip() or env_endpoint
        api_key = stored.get("api_key")
        if isinstance(api_key, str):
            api_key = api_key.strip() or None
        else:
            api_key = None
        model = (str(stored.get("model") or env_model)).strip() or env_model
        fast_raw = stored.get("fast_model")
        fast_model = (
            (str(fast_raw).strip() if fast_raw else "") or env_fast
        )
        folder_id = stored.get("folder_id")
        folder_id = str(folder_id).strip() if isinstance(folder_id, str) and folder_id.strip() else None
        cid = stored.get("client_id")
        cid = str(cid).strip() if isinstance(cid, str) and cid.strip() else None
        csec = stored.get("client_secret")
        csec = str(csec).strip() if isinstance(csec, str) and csec.strip() else None
        scope = stored.get("scope")
        scope = str(scope).strip() if isinstance(scope, str) and scope.strip() else None

        llm_search_batch_size = max(
            1, min(50, int(settings.llm_search_batch_size or 10))
        )
        llm_fast_batch_size = max(
            1, min(50, int(settings.llm_fast_batch_size or 5))
        )
        llm_detailed_top_n = max(
            1, min(50, int(settings.llm_detailed_top_n or 15))
        )

        if prov == LLMProvider.GIGACHAT.value:
            api_key = None
        elif prov == LLMProvider.YANDEX_GPT.value and not api_key:
            api_key = env_key if env_key != "ollama" else None

        return LLMRuntimeConfig(
            provider=prov,
            endpoint=endpoint,
            api_key=api_key or (None if prov == LLMProvider.GIGACHAT.value else env_key),
            model=model,
            fast_model=fast_model,
            folder_id=folder_id,
            client_id=cid,
            client_secret=csec,
            scope=scope,
            llm_search_batch_size=max(1, min(50, llm_search_batch_size)),
            llm_fast_batch_size=max(1, min(50, llm_fast_batch_size)),
            llm_detailed_top_n=max(1, min(50, llm_detailed_top_n)),
        )

    return LLMRuntimeConfig(
        provider=_default_provider_env(env_endpoint),
        endpoint=env_endpoint,
        api_key=env_key,
        model=env_model,
        fast_model=env_fast,
        folder_id=None,
        client_id=None,
        client_secret=None,
        scope=None,
        llm_search_batch_size=max(1, min(50, int(settings.llm_search_batch_size or 10))),
        llm_fast_batch_size=max(1, min(50, int(settings.llm_fast_batch_size or 5))),
        llm_detailed_top_n=max(1, min(50, int(settings.llm_detailed_top_n or 15))),
    )


def mask_endpoint(url: str) -> str:
    u = (url or "").strip()
    if len(u) <= 16:
        return u or ""
    return u[:10] + "…" + u[-6:]


def llm_connection_configured(db: Session | None) -> bool:
    cfg = get_llm_config(db)
    if not (cfg.endpoint or "").strip():
        return False
    if cfg.provider == LLMProvider.YANDEX_GPT.value:
        return bool(cfg.api_key and cfg.folder_id)
    if cfg.provider == LLMProvider.GIGACHAT.value:
        return bool(cfg.client_id and cfg.client_secret)
    return True


def _content_from_openai_style(data: dict[str, Any]) -> str:
    content = ""
    if "message" in data:
        content = data.get("message", {}).get("content", "")
    if not content and "response" in data:
        content = data.get("response", "")
    if not content and "choices" in data:
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
    return content if isinstance(content, str) else ""


def _content_from_yandex(data: dict[str, Any]) -> str:
    alts = data.get("alternatives") or data.get("result", {}).get("alternatives")
    if isinstance(alts, list) and alts:
        msg = alts[0].get("message") if isinstance(alts[0], dict) else None
        if isinstance(msg, dict):
            t = msg.get("text")
            if isinstance(t, str):
                return t
    return ""


def _gigachat_access_token(cfg: LLMRuntimeConfig) -> str | None:
    global _gigachat_cache
    now = time.time()
    if (
        _gigachat_cache.get("token")
        and float(_gigachat_cache.get("expires_at") or 0) > now + 45
    ):
        return str(_gigachat_cache["token"])

    cid = cfg.client_id or ""
    csec = cfg.client_secret or ""
    if not cid or not csec:
        return None
    basic = base64.b64encode(f"{cid}:{csec}".encode()).decode("ascii")
    scope = (cfg.scope or "GIGACHAT_API_PERS").strip()
    try:
        with httpx.Client(timeout=60.0, verify=True) as client:
            r = client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "RqUID": str(uuid.uuid4()),
                    "Authorization": f"Basic {basic}",
                },
                content=f"scope={scope}&grant_type=client_credentials",
            )
            r.raise_for_status()
            payload = r.json()
    except Exception as e:
        logger.warning("GigaChat OAuth failed: %s", e)
        return None

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        return None
    expires_in = 1500.0
    if isinstance(payload, dict):
        try:
            expires_in = float(payload.get("expires_in", 1500))
        except (TypeError, ValueError):
            pass
    _gigachat_cache = {
        "token": token,
        "expires_at": now + max(60.0, expires_in),
    }
    return token


def _call_yandex(
    cfg: LLMRuntimeConfig,
    messages: list[dict[str, str]],
    model: str,
    *,
    format_json: bool,
    timeout: float,
) -> str | None:
    _ = format_json
    if not cfg.api_key or not cfg.folder_id:
        return None
    model_uri = model if model.startswith("gpt://") else f"gpt://{cfg.folder_id}/{model}"
    yandex_messages: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role") or "user"
        text = m.get("content") or ""
        yandex_messages.append({"role": role, "text": text})

    body: dict[str, Any] = {
        "modelUri": model_uri,
        "completionOptions": {
            "stream": False,
            "temperature": 0.2,
            "maxTokens": 8000,
        },
        "messages": yandex_messages,
    }
    headers = {
        "Authorization": f"Api-Key {cfg.api_key}",
        "Content-Type": "application/json",
        "x-folder-id": cfg.folder_id,
    }
    ep = (cfg.endpoint or "").strip() or (
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(ep, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("YandexGPT request failed: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    return _content_from_yandex(data) or None


def _call_gigachat(
    cfg: LLMRuntimeConfig,
    messages: list[dict[str, str]],
    model: str,
    *,
    format_json: bool,
    timeout: float,
) -> str | None:
    token = _gigachat_access_token(cfg)
    if not token:
        return None
    openai_messages = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in messages
    ]
    body: dict[str, Any] = {
        "model": model,
        "messages": openai_messages,
        "stream": False,
    }
    if format_json:
        body["response_format"] = {"type": "json_object"}
    ep = (cfg.endpoint or "").strip() or (
        "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(ep, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("GigaChat request failed: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    return _content_from_openai_style(data) or None


def _call_openai_compatible(
    cfg: LLMRuntimeConfig,
    messages: list[dict[str, str]],
    model: str,
    *,
    format_json: bool,
    timeout: float,
) -> str | None:
    endpoint = (cfg.endpoint or "").strip()
    if not endpoint:
        return None
    api_key = cfg.api_key or "ollama"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
    }
    if format_json:
        body["format"] = "json"

    def _post(url: str, json_body: dict[str, Any]) -> httpx.Response:
        with httpx.Client(timeout=timeout) as client:
            return client.post(url, json=json_body, headers=headers)

    try:
        if "/api/generate" in endpoint:
            # одиночный prompt из messages
            parts = [f"{m['role']}: {m['content']}" for m in messages]
            prompt = "\n\n".join(parts)
            gen_body: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
            if format_json:
                gen_body["format"] = "json"
            r = _post(endpoint, gen_body)
        else:
            r = _post(endpoint, body)
            if r.status_code == 404 and "/api/chat" in endpoint:
                base = endpoint.replace("/api/chat", "")
                alt_url = f"{base}/api/generate"
                parts = [f"{m['role']}: {m['content']}" for m in messages]
                prompt = "\n\n".join(parts)
                gen_body = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                }
                if format_json:
                    gen_body["format"] = "json"
                r = _post(alt_url, gen_body)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("LLM request failed: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    return _content_from_openai_style(data) or None


def call_llm_chat(
    db: Session | None,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    format_json: bool = False,
    timeout: float = 90.0,
) -> str | None:
    """Унифицированный вызов чата; model по умолчанию — основная модель из конфигурации."""
    cfg = get_llm_config(db)
    m = (model or cfg.model or "").strip() or cfg.model
    if not m:
        return None

    if cfg.provider == LLMProvider.YANDEX_GPT.value:
        return _call_yandex(cfg, messages, m, format_json=format_json, timeout=timeout)
    if cfg.provider == LLMProvider.GIGACHAT.value:
        return _call_gigachat(cfg, messages, m, format_json=format_json, timeout=timeout)
    return _call_openai_compatible(
        cfg, messages, m, format_json=format_json, timeout=timeout
    )


def call_llm_user_prompt(
    db: Session | None,
    user_prompt: str,
    *,
    model: str | None = None,
    format_json: bool = False,
    timeout: float = 90.0,
) -> str | None:
    """Один пользовательский промпт (как в анализе резюме)."""
    return call_llm_chat(
        db,
        [{"role": "user", "content": user_prompt}],
        model=model,
        format_json=format_json,
        timeout=timeout,
    )


def call_llm_for_json_object(
    db: Session | None,
    user_prompt: str,
    *,
    model: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any] | None:
    raw = call_llm_user_prompt(
        db, user_prompt, model=model, format_json=True, timeout=timeout
    )
    if not raw:
        return None
    parsed = _extract_json(raw)
    return parsed


def test_llm_connection(db: Session | None) -> tuple[bool, str, int | None]:
    """Проверка соединения; возвращает (успех, сообщение, время мс)."""
    if not llm_connection_configured(db):
        return False, "Не заданы обязательные параметры подключения к модели", None
    cfg = get_llm_config(db)
    t0 = time.perf_counter()
    text = call_llm_chat(
        db,
        [
            {
                "role": "user",
                "content": 'Ответь одним словом: "ok" (латиницей, без кавычек).',
            }
        ],
        model=cfg.model,
        format_json=False,
        timeout=45.0,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if text and str(text).strip():
        return True, "Соединение установлено, получен ответ модели", elapsed_ms
    return False, "Пустой ответ или ошибка при обращении к модели", elapsed_ms


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _empty_parsed() -> dict[str, Any]:
    return {
        "skills": [],
        "experience_years_min": None,
        "region": None,
        "position_keywords": [],
        "gender": None,
        "industry": [],
        "age_max": None,
    }


def _normalize_llm_output(raw: dict[str, Any]) -> dict[str, Any]:
    skills = raw.get("skills")
    if not isinstance(skills, list):
        skills = []
    skills = [str(s).strip() for s in skills if s]

    exp_min = raw.get("experience_years_min")
    if exp_min is not None and not isinstance(exp_min, (int, float)):
        exp_min = None
    if exp_min is not None:
        exp_min = int(exp_min)

    region = raw.get("region")
    if region is not None and not isinstance(region, str):
        region = None
    if isinstance(region, str) and not region.strip():
        region = None

    pos_kw = raw.get("position_keywords")
    if not isinstance(pos_kw, list):
        pos_kw = []
    pos_kw = [str(p).strip() for p in pos_kw if p]

    gender = raw.get("gender")
    if gender not in ("male", "female"):
        gender = None

    industry = raw.get("industry")
    if not isinstance(industry, list):
        industry = []
    industry = [str(i).strip() for i in industry if i]

    age_max = raw.get("age_max")
    if age_max is not None and not isinstance(age_max, (int, float)):
        age_max = None
    if age_max is not None:
        age_max = int(age_max)

    return {
        "skills": skills,
        "experience_years_min": exp_min,
        "region": region,
        "position_keywords": pos_kw,
        "gender": gender,
        "industry": industry,
        "age_max": age_max,
    }


def parse_query_via_llm(query: str, db: Session | None = None) -> dict[str, Any]:
    if not llm_connection_configured(db):
        logger.debug("LLM not configured")
        return _empty_parsed()

    cfg = get_llm_config(db)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query.strip()},
    ]
    content = call_llm_chat(
        db,
        messages,
        model=cfg.model,
        format_json=True,
        timeout=180.0,
    )
    if not content:
        return _empty_parsed()
    parsed = _extract_json(content)
    if not parsed:
        logger.warning("LLM returned invalid JSON")
        return _empty_parsed()
    return _normalize_llm_output(parsed)


def debug_raw_llm_response(query: str, db: Session | None = None) -> dict[str, Any]:
    if not llm_connection_configured(db):
        return {"ok": False, "status_code": None, "raw": {}, "error": "LLM not configured"}

    cfg = get_llm_config(db)
    endpoint = (cfg.endpoint or "").strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query.strip()},
    ]

    try:
        if cfg.provider == LLMProvider.YANDEX_GPT.value:
            text = _call_yandex(
                cfg, messages, cfg.model, format_json=True, timeout=180.0
            )
            return {
                "ok": bool(text),
                "status_code": 200 if text else None,
                "raw": {"content": text or ""},
                "error": None if text else "empty",
            }
        if cfg.provider == LLMProvider.GIGACHAT.value:
            text = _call_gigachat(
                cfg, messages, cfg.model, format_json=True, timeout=180.0
            )
            return {
                "ok": bool(text),
                "status_code": 200 if text else None,
                "raw": {"content": text or ""},
                "error": None if text else "empty",
            }
        api_key = cfg.api_key or "ollama"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        body = {
            "model": cfg.model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "stream": False,
            "format": "json",
        }
        with httpx.Client(timeout=180.0) as client:
            r = client.post(endpoint, json=body, headers=headers)
            raw = r.json() if r.content else {}
            if r.status_code != 200:
                return {
                    "ok": False,
                    "status_code": r.status_code,
                    "raw": raw,
                    "error": r.text[:500] if r.text else str(r.status_code),
                }
            return {"ok": True, "status_code": r.status_code, "raw": raw, "error": None}
    except Exception as e:
        logger.warning("LLM debug request failed: %s", e)
        return {"ok": False, "status_code": None, "raw": {}, "error": str(e)}
