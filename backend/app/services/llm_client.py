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

SYSTEM_PROMPT = """Ты — ассистент для парсинга HR-запросов в фильтры поиска резюме на hh.ru.
Твоя задача: извлечь параметры, которые помогут найти релевантных кандидатов, но не сделают поиск слишком узким.

ВАЖНО:
- Извлекай только явно указанные требования.
- Не добавляй предполагаемые skills, industry и другие параметры.
- Исключение: для position_keywords добавляй разумные рус/англ варианты и частые названия той же роли на hh.ru (3-5 вариантов), чтобы не сузить поиск.
- Цель — сформировать полезные фильтры для поиска резюме, не потеряв релевантных кандидатов.

Верни ТОЛЬКО валидный JSON (без markdown, без текста до/после):
{
  "skills": [],
  "must_position": [],
  "must_skills": [{"canonical": "", "intent_strength": "required|preferred|signal", "query_confidence": 0.0}],
  "should_skills": [{"canonical": "", "intent_strength": "required|preferred|signal", "query_confidence": 0.0}],
  "semantic_skills": [{"canonical": "", "intent_strength": "required|preferred|signal", "query_confidence": 0.0}],
  "soft_signals": [],
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

- skills: только явно указанные профессиональные навыки, технологии, инструменты, компетенции.
  * IT: Python, Java, Docker, React, PostgreSQL, Kafka, микросервисы
  * Юристы: арбитраж, договорная работа, корпоративное право
  * Бухгалтеры: МСФО, налоговый учёт, 1С, бюджетирование
  * HR: подбор персонала, кадровое делопроизводство, C&B
  * Менеджеры: Agile, Scrum, управление проектами
  Не добавляй синонимы и смежные навыки, если их нет в запросе.

- industry: только отрасль / домен бизнеса, где нужен опыт кандидата.
  Примеры: IT, retail, finance, банки, телеком, строительство, недвижимость, медицина, производство.
  "в области ИТ", "в сфере ритейла", "опыт в банках" -> industry, НЕ skills.
  Если отрасль упомянута как контекст компании, а не требование к опыту кандидата, не заполняй industry.

- position_keywords: основная должность + 2-4 разумных варианта той же роли на hh.ru.
  Допустимы: рус/англ вариант, частые синонимы, близкие формулировки той же профессии.
  Недопустимо: добавлять другой профиль или расширять до смежной, но другой профессии.

- must_position: жёсткая роль (основная должность) и 2-4 синонима; дублирует основную роль для boolean-планировщика.
- semantic_skills: основной семантический массив навыков. Для каждого навыка:
  canonical — каноническая профессиональная формулировка;
  intent_strength — required|preferred|signal по намерению пользователя;
  query_confidence — уверенность в интерпретации 0..1.
- must_skills / should_skills: backward-compatible поля; заполняй на основе semantic_skills.
  ВАЖНО: разговорные маркеры ("вайбкодинг", "курсорить", "микрачи") не превращай автоматически в must.
- soft_signals: только низкая уверенность/шум/сигналы без жёсткого требования.

- experience_years_min: "2 года", "от 3 лет", "3+ года" -> число (2, 3)
- experience_years_max: "до 5 лет", "3-5 лет" -> 5
- age_min: "от 25 лет" -> 25
- age_max: "до 35 лет" -> 35
- region: город (Москва, Санкт-Петербург, Казань и т.д.)
- gender: "male" / "female" только если явно указан пол

Примеры:

"Юрист с опытом арбитражных дел в области ИТ" ->
{"skills":["арбитраж","арбитражные дела"],"experience_years_min":null,"experience_years_max":null,"region":null,"position_keywords":["юрист","lawyer","юрисконсульт"],"gender":null,"industry":["IT"],"age_min":null,"age_max":null}

"Бухгалтер со знанием МСФО, опыт в банковской сфере от 3 лет" ->
{"skills":["МСФО"],"experience_years_min":3,"experience_years_max":null,"region":null,"position_keywords":["бухгалтер","accountant","главный бухгалтер"],"gender":null,"industry":["finance","банки"],"age_min":null,"age_max":null}

"Системный аналитик с опытом работы с микросервисами, 2 года, Москва" ->
{"skills":["микросервисы"],"experience_years_min":2,"experience_years_max":null,"region":"Москва","position_keywords":["системный аналитик","system analyst","systems analyst","бизнес-аналитик"],"gender":null,"industry":[],"age_min":null,"age_max":null}

"Java developer 5+ лет, Spring Boot, до 40 лет" ->
{"skills":["Java","Spring Boot"],"experience_years_min":5,"experience_years_max":null,"region":null,"position_keywords":["java developer","java разработчик","backend developer","разработчик Java"],"gender":null,"industry":[],"age_min":null,"age_max":40}

"HR-менеджер с опытом подбора IT-специалистов" ->
{"skills":["подбор IT-специалистов"],"experience_years_min":null,"experience_years_max":null,"region":null,"position_keywords":["HR-менеджер","HR manager","IT recruiter","рекрутер"],"gender":null,"industry":["IT"],"age_min":null,"age_max":null}

Ответ — только JSON."""

_gigachat_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}
_logged_config_source: str | None = None


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
    prescore_mode: str
    rerank_endpoint: str
    rerank_model: str
    rerank_api_key: str | None
    rerank_timeout_seconds: float
    rerank_batch_size: int


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


def _log_llm_config_source(source: str, cfg: LLMRuntimeConfig) -> None:
    global _logged_config_source
    if _logged_config_source == source:
        return
    logger.info(
        "LLM runtime config source: %s (provider=%s, model=%s, endpoint=%s)",
        source,
        cfg.provider,
        cfg.model,
        mask_endpoint(cfg.endpoint),
    )
    _logged_config_source = source


def get_llm_config(db: Session | None) -> LLMRuntimeConfig:
    """Эффективная конфигурация: учётные данные LLM из БД; батчи и топ-N — из настроек сервера."""
    stored: dict[str, Any] | None = None
    if db is not None:
        stored = _stored_llm_dict(db)

    env_endpoint = (settings.internal_llm_endpoint or "").strip()
    env_key = (settings.internal_llm_api_key or "ollama").strip() or "ollama"
    env_model = (settings.internal_llm_model or "llama3.2").strip() or "llama3.2"
    env_fast = (settings.llm_fast_model or "qwen2.5:7b").strip() or "qwen2.5:7b"
    env_prescore_mode = (settings.prescore_mode or "chat_legacy").strip() or "chat_legacy"
    env_rerank_endpoint = (settings.rerank_endpoint or "").strip()
    env_rerank_model = (settings.rerank_model or "qwen3-vl-embedding-2b").strip() or "qwen3-vl-embedding-2b"
    env_rerank_api_key = (settings.rerank_api_key or "").strip() or None
    env_rerank_timeout = max(1.0, float(settings.rerank_timeout_seconds or 30.0))
    env_rerank_batch_size = max(1, min(500, int(settings.rerank_batch_size or 200)))

    env_cfg = LLMRuntimeConfig(
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
        prescore_mode=env_prescore_mode if env_prescore_mode in {"chat_legacy", "rerank"} else "chat_legacy",
        rerank_endpoint=env_rerank_endpoint,
        rerank_model=env_rerank_model,
        rerank_api_key=env_rerank_api_key,
        rerank_timeout_seconds=env_rerank_timeout,
        rerank_batch_size=env_rerank_batch_size,
    )
    env_priority = bool(settings.llm_runtime_env_priority)
    env_ready = bool(env_endpoint)
    if env_priority and env_ready:
        _log_llm_config_source("env", env_cfg)
        return env_cfg

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
        prescore_mode_raw = str(stored.get("prescore_mode") or env_prescore_mode).strip()
        prescore_mode = prescore_mode_raw if prescore_mode_raw in {"chat_legacy", "rerank"} else "chat_legacy"
        rerank_endpoint = (str(stored.get("rerank_endpoint") or env_rerank_endpoint)).strip()
        rerank_model = (str(stored.get("rerank_model") or env_rerank_model)).strip() or env_rerank_model
        rerank_api_key_raw = stored.get("rerank_api_key")
        rerank_api_key = (
            str(rerank_api_key_raw).strip()
            if isinstance(rerank_api_key_raw, str) and str(rerank_api_key_raw).strip()
            else env_rerank_api_key
        )
        rerank_timeout_raw = stored.get("rerank_timeout_seconds")
        try:
            rerank_timeout_seconds = max(
                1.0,
                float(rerank_timeout_raw),
            ) if rerank_timeout_raw is not None else env_rerank_timeout
        except (TypeError, ValueError):
            rerank_timeout_seconds = env_rerank_timeout
        rerank_batch_raw = stored.get("rerank_batch_size")
        try:
            rerank_batch_size = max(
                1,
                min(500, int(rerank_batch_raw)),
            ) if rerank_batch_raw is not None else env_rerank_batch_size
        except (TypeError, ValueError):
            rerank_batch_size = env_rerank_batch_size

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

        cfg = LLMRuntimeConfig(
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
            prescore_mode=prescore_mode,
            rerank_endpoint=rerank_endpoint,
            rerank_model=rerank_model,
            rerank_api_key=rerank_api_key,
            rerank_timeout_seconds=rerank_timeout_seconds,
            rerank_batch_size=rerank_batch_size,
        )
        _log_llm_config_source("db", cfg)
        return cfg

    source = "env_fallback" if env_ready else "default_env"
    _log_llm_config_source(source, env_cfg)
    return env_cfg


def mask_endpoint(url: str) -> str:
    u = (url or "").strip()
    if len(u) <= 16:
        return u or ""
    return u[:10] + "…" + u[-6:]


def llm_connection_configured(db: Session | None) -> bool:
    cfg = get_llm_config(db)
    return llm_connection_configured_runtime(cfg)


def llm_connection_configured_runtime(cfg: LLMRuntimeConfig) -> bool:
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
    runtime_config: LLMRuntimeConfig | None = None,
) -> str | None:
    """Унифицированный вызов чата; model по умолчанию — основная модель из конфигурации."""
    cfg = runtime_config or get_llm_config(db)
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
    runtime_config: LLMRuntimeConfig | None = None,
) -> str | None:
    """Один пользовательский промпт (как в анализе резюме)."""
    return call_llm_chat(
        db,
        [{"role": "user", "content": user_prompt}],
        model=model,
        format_json=format_json,
        timeout=timeout,
        runtime_config=runtime_config,
    )


def call_rerank(
    query: str,
    documents: list[str],
    *,
    model: str | None = None,
    timeout: float | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]] | None:
    """Вызов rerank endpoint; возвращает список объектов с index/relevance_score."""
    cfg = get_llm_config(db)
    endpoint = (cfg.rerank_endpoint or "").strip()
    if not endpoint:
        return None
    docs = [str(x) for x in documents]
    if not docs:
        return []
    m = (model or cfg.rerank_model or "").strip() or cfg.rerank_model
    payload: dict[str, Any] = {
        "model": m,
        "query": str(query or ""),
        "documents": docs,
        "top_n": len(docs),
    }
    headers = {"Content-Type": "application/json"}
    token = (cfg.rerank_api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req_timeout = float(timeout or cfg.rerank_timeout_seconds or 30.0)
    try:
        with httpx.Client(timeout=max(1.0, req_timeout)) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("Rerank request failed: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results")
    if not isinstance(results, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("relevance_score")
        try:
            idx_i = int(idx)
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        normalized.append({"index": idx_i, "relevance_score": score_f})
    return normalized


def call_llm_for_json_object(
    db: Session | None,
    user_prompt: str,
    *,
    model: str | None = None,
    timeout: float = 60.0,
    runtime_config: LLMRuntimeConfig | None = None,
) -> dict[str, Any] | None:
    raw = call_llm_user_prompt(
        db,
        user_prompt,
        model=model,
        format_json=True,
        timeout=timeout,
        runtime_config=runtime_config,
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
        "must_position": [],
        "must_skills": [],
        "should_skills": [],
        "soft_signals": [],
        "hard_skills": [],
        "risky_skills": [],
        "risky_demoted_to_should": 0,
        "risky_demoted_to_soft": 0,
        "semantic_jargon_terms_total": 0,
        "semantic_terms_promoted_to_should": 0,
        "semantic_terms_promoted_to_must": 0,
        "semantic_terms_demoted_to_soft": 0,
        "semantic_profile": [],
        "skill_risk_profile": [],
        "experience_years_min": None,
        "experience_years_max": None,
        "region": None,
        "position_keywords": [],
        "gender": None,
        "industry": [],
        "age_min": None,
        "age_max": None,
    }


def _normalize_skill_groups(raw_groups: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_groups, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    synonyms_enabled = bool(settings.feature_skill_synonyms_enabled)
    intent_aliases = {
        "must": "required",
        "required": "required",
        "hard": "required",
        "should": "preferred",
        "preferred": "preferred",
        "nice_to_have": "preferred",
        "optional": "preferred",
        "soft": "signal",
        "signal": "signal",
    }
    for item in raw_groups:
        canonical = ""
        synonyms: list[str] = []
        search_equivalents: list[str] = []
        intent_strength: str | None = None
        query_confidence: float | None = None
        if isinstance(item, dict):
            canonical = str(item.get("canonical") or "").strip()
            if synonyms_enabled:
                raw_syn = item.get("synonyms")
                if isinstance(raw_syn, list):
                    synonyms = [str(s).strip() for s in raw_syn if str(s).strip()]
                raw_eq = item.get("search_equivalents")
                if isinstance(raw_eq, list):
                    search_equivalents = [str(s).strip() for s in raw_eq if str(s).strip()]
            raw_intent = str(item.get("intent_strength") or "").strip().lower()
            intent_strength = intent_aliases.get(raw_intent)
            raw_conf = item.get("query_confidence")
            if isinstance(raw_conf, (int, float)):
                query_confidence = float(raw_conf)
                if query_confidence > 1.0:
                    query_confidence = query_confidence / 100.0
                query_confidence = max(0.0, min(1.0, query_confidence))
        elif isinstance(item, str):
            canonical = item.strip()
        if not canonical:
            continue
        key = canonical.lower()
        if key in seen:
            continue
        seen.add(key)
        syn_seen: set[str] = set()
        clean_synonyms: list[str] = []
        clean_equivalents: list[str] = []
        for syn in [*synonyms, *search_equivalents]:
            syn_key = syn.lower()
            if syn_key == key or syn_key in syn_seen:
                continue
            syn_seen.add(syn_key)
            clean_synonyms.append(syn)
            clean_equivalents.append(syn)
        skill_obj: dict[str, Any] = {
            "canonical": canonical,
            "synonyms": clean_synonyms,
            "search_equivalents": clean_equivalents,
        }
        if intent_strength:
            skill_obj["intent_strength"] = intent_strength
        if query_confidence is not None:
            skill_obj["query_confidence"] = round(query_confidence, 3)
        out.append(skill_obj)
    return out


_RISKY_SKILL_PATTERNS = (
    re.compile(r"\b(вайб|vibe)\w*\b", re.IGNORECASE),
    re.compile(r"\b(ai\s*pair|pair\s*programming)\b", re.IGNORECASE),
    re.compile(r"\b(copilot|cursor\s*ide|курсор\w*)\b", re.IGNORECASE),
    re.compile(r"\b(rockstar|ninja|guru|evangelist)\b", re.IGNORECASE),
)
_HAS_LETTERS_RE = re.compile(r"[a-zа-яё]", re.IGNORECASE)


def _score_skill_hard_confidence(canonical: str, synonyms: list[str]) -> float:
    text = str(canonical or "").strip()
    norm = text.lower()
    score = 0.55
    if not text:
        return 0.0
    if not _HAS_LETTERS_RE.search(text):
        return 0.0
    if any(rx.search(norm) for rx in _RISKY_SKILL_PATTERNS):
        score -= 0.45
    if len(text) < 2 or len(text) > 64:
        score -= 0.25
    if " " not in text and "/" not in text:
        score += 0.1
    if synonyms:
        score += 0.1
        if any(2 <= len(str(s).strip()) <= 48 for s in synonyms):
            score += 0.05
    else:
        score -= 0.05
    return max(0.0, min(1.0, score))


def _merge_skill_groups(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    synonyms_enabled = bool(settings.feature_skill_synonyms_enabled)
    for bucket in groups:
        for item in bucket:
            canonical = str(item.get("canonical") or "").strip()
            if not canonical:
                continue
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)
            skill_obj: dict[str, Any] = {
                "canonical": canonical,
                "synonyms": (
                    [str(s).strip() for s in (item.get("synonyms") or []) if str(s).strip()]
                    if synonyms_enabled
                    else []
                ),
            }
            search_equivalents = (
                [str(s).strip() for s in (item.get("search_equivalents") or []) if str(s).strip()]
                if synonyms_enabled
                else []
            )
            if search_equivalents:
                skill_obj["search_equivalents"] = search_equivalents
            intent_strength = str(item.get("intent_strength") or "").strip()
            if intent_strength:
                skill_obj["intent_strength"] = intent_strength
            query_confidence = item.get("query_confidence")
            if isinstance(query_confidence, (int, float)):
                skill_obj["query_confidence"] = round(max(0.0, min(1.0, float(query_confidence))), 3)
            out.append(skill_obj)
    return out


def _split_hard_and_risky(
    groups: list[dict[str, Any]],
    *,
    source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    hard: list[dict[str, Any]] = []
    risky: list[dict[str, Any]] = []
    profile: list[dict[str, Any]] = []
    synonyms_enabled = bool(settings.feature_skill_synonyms_enabled)
    for item in groups:
        canonical = str(item.get("canonical") or "").strip()
        synonyms = (
            [str(s).strip() for s in (item.get("synonyms") or []) if str(s).strip()]
            if synonyms_enabled
            else []
        )
        search_equivalents = (
            [str(s).strip() for s in (item.get("search_equivalents") or []) if str(s).strip()]
            if synonyms_enabled
            else []
        )
        if not canonical:
            continue
        llm_conf = item.get("query_confidence")
        confidence = _score_skill_hard_confidence(canonical, [*synonyms, *search_equivalents])
        if isinstance(llm_conf, (int, float)):
            confidence = 0.6 * confidence + 0.4 * max(0.0, min(1.0, float(llm_conf)))
        target = hard if confidence >= 0.55 else risky
        target.append(
            {
                "canonical": canonical,
                "synonyms": synonyms,
                "search_equivalents": search_equivalents,
                "intent_strength": item.get("intent_strength"),
                "query_confidence": item.get("query_confidence"),
            }
        )
        profile.append(
            {
                "canonical": canonical,
                "hard_confidence": round(confidence, 3),
                "risk": "hard" if confidence >= 0.55 else "risky",
                "source": source,
            }
        )
    return hard, risky, profile


def _normalize_llm_output(raw: dict[str, Any]) -> dict[str, Any]:
    skills = raw.get("skills")
    if not isinstance(skills, list):
        skills = []
    skills = [str(s).strip() for s in skills if s]

    must_position = raw.get("must_position")
    if not isinstance(must_position, list):
        must_position = []
    must_position = [str(p).strip() for p in must_position if str(p).strip()]

    must_skills = _normalize_skill_groups(raw.get("must_skills"))
    should_skills = _normalize_skill_groups(raw.get("should_skills"))
    semantic_skills = _normalize_skill_groups(raw.get("semantic_skills"))

    if semantic_skills:
        sem_must: list[dict[str, Any]] = []
        sem_should: list[dict[str, Any]] = []
        sem_soft: list[str] = []
        semantic_profile: list[dict[str, Any]] = []
        synonyms_enabled = bool(settings.feature_skill_synonyms_enabled)
        for skill in semantic_skills:
            canonical = str(skill.get("canonical") or "").strip()
            if not canonical:
                continue
            equivalents = (
                [
                    str(x).strip()
                    for x in (skill.get("search_equivalents") or skill.get("synonyms") or [])
                    if str(x).strip()
                ]
                if synonyms_enabled
                else []
            )
            intent = str(skill.get("intent_strength") or "preferred").strip().lower()
            confidence_raw = skill.get("query_confidence")
            confidence = (
                max(0.0, min(1.0, float(confidence_raw)))
                if isinstance(confidence_raw, (int, float))
                else 0.5
            )
            is_risky = any(rx.search(canonical.lower()) for rx in _RISKY_SKILL_PATTERNS)
            normalized_skill = {
                "canonical": canonical,
                "synonyms": list(skill.get("synonyms") or []) if synonyms_enabled else [],
                "search_equivalents": equivalents,
                "intent_strength": intent,
                "query_confidence": round(confidence, 3),
            }
            if intent == "signal" or confidence < 0.3:
                sem_soft.append(canonical)
                target = "soft"
            elif intent == "required" and confidence >= 0.62 and (not is_risky or confidence >= 0.82):
                sem_must.append(normalized_skill)
                target = "must"
            else:
                sem_should.append(normalized_skill)
                target = "should"
            semantic_profile.append(
                {
                    "canonical": canonical,
                    "intent_strength": intent,
                    "query_confidence": round(confidence, 3),
                    "target_bucket": target,
                    "equivalents_count": len(equivalents),
                    "is_risky_term": is_risky,
                }
            )
        must_skills = _merge_skill_groups(must_skills, sem_must)
        should_skills = _merge_skill_groups(should_skills, sem_should)
    else:
        semantic_profile = []
        sem_soft = []

    soft_signals = raw.get("soft_signals")
    if not isinstance(soft_signals, list):
        soft_signals = []
    soft_signals = [str(s).strip() for s in soft_signals if str(s).strip()]
    if sem_soft:
        soft_signals = list(dict.fromkeys([*soft_signals, *sem_soft]))

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

    exp_max = raw.get("experience_years_max")
    if exp_max is not None and not isinstance(exp_max, (int, float)):
        exp_max = None
    if exp_max is not None:
        exp_max = int(exp_max)

    age_min = raw.get("age_min")
    if age_min is not None and not isinstance(age_min, (int, float)):
        age_min = None
    if age_min is not None:
        age_min = int(age_min)

    age_max = raw.get("age_max")
    if age_max is not None and not isinstance(age_max, (int, float)):
        age_max = None
    if age_max is not None:
        age_max = int(age_max)

    hard_must, risky_must, must_profile = _split_hard_and_risky(must_skills, source="must_skills")
    hard_should, risky_should, should_profile = _split_hard_and_risky(
        should_skills,
        source="should_skills",
    )
    fallback_groups = [{"canonical": s, "synonyms": []} for s in skills]
    hard_fallback: list[dict[str, Any]] = []
    risky_fallback: list[dict[str, Any]] = []
    fallback_profile: list[dict[str, Any]] = []
    if not must_skills and fallback_groups:
        hard_fallback, risky_fallback, fallback_profile = _split_hard_and_risky(
            fallback_groups,
            source="skills_fallback",
        )

    demoted_to_should = len(risky_must) + len(risky_fallback)
    demoted_to_soft = sum(
        1
        for item in (must_profile + should_profile + fallback_profile)
        if item["risk"] == "risky" and float(item["hard_confidence"]) < 0.2
    )
    risky_soft = [
        item["canonical"]
        for item in (must_profile + should_profile + fallback_profile)
        if item["risk"] == "risky" and float(item["hard_confidence"]) < 0.2
    ]
    risky_soft_set = {x.lower() for x in risky_soft}
    should_skills = _merge_skill_groups(
        hard_should,
        risky_should,
        risky_must,
        [x for x in risky_fallback if x["canonical"].lower() not in risky_soft_set],
    )
    must_skills = _merge_skill_groups(hard_must, hard_fallback)
    if risky_soft:
        soft_signals = list(dict.fromkeys([*soft_signals, *risky_soft]))

    if not must_position:
        must_position = list(pos_kw)
    canonical_skills = [x["canonical"] for x in must_skills + should_skills]
    if skills:
        skills = list(dict.fromkeys([*skills, *canonical_skills]))
    else:
        skills = canonical_skills

    hard_skills = [x["canonical"] for x in _merge_skill_groups(hard_must, hard_should, hard_fallback)]
    risky_skills = [x["canonical"] for x in _merge_skill_groups(risky_must, risky_should, risky_fallback)]

    semantic_promoted_to_must = sum(1 for row in semantic_profile if row["target_bucket"] == "must")
    semantic_promoted_to_should = sum(1 for row in semantic_profile if row["target_bucket"] == "should")
    semantic_demoted_to_soft = sum(1 for row in semantic_profile if row["target_bucket"] == "soft")

    return {
        "skills": skills,
        "must_position": must_position,
        "must_skills": must_skills,
        "should_skills": should_skills,
        "soft_signals": soft_signals,
        "hard_skills": hard_skills,
        "risky_skills": risky_skills,
        "risky_demoted_to_should": demoted_to_should,
        "risky_demoted_to_soft": demoted_to_soft,
        "semantic_jargon_terms_total": sum(1 for row in semantic_profile if row["is_risky_term"]),
        "semantic_terms_promoted_to_should": semantic_promoted_to_should,
        "semantic_terms_promoted_to_must": semantic_promoted_to_must,
        "semantic_terms_demoted_to_soft": semantic_demoted_to_soft,
        "semantic_profile": semantic_profile,
        "skill_risk_profile": must_profile + should_profile + fallback_profile,
        "experience_years_min": exp_min,
        "experience_years_max": exp_max,
        "region": region,
        "position_keywords": pos_kw,
        "gender": gender,
        "industry": industry,
        "age_min": age_min,
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
