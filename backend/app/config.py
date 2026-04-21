from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://hr:hr@localhost:5432/hr_service"

    secret_key: str = "change-me-in-production"
    # production — строгие проверки (например TOKEN_ENCRYPTION_KEY); development по умолчанию
    environment: str = "development"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"

    token_encryption_key: str = ""

    hh_client_id: str = ""
    hh_client_secret: str = ""
    hh_redirect_uri: str = "http://localhost:8000/api/v1/hh/callback"

    yandex_client_id: str = ""
    yandex_client_secret: str = ""
    yandex_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/yandex/callback"

    vk_client_id: str = ""
    vk_client_secret: str = ""
    vk_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/vk/callback"
    vk_oauth_base_url: str = "https://id.vk.com"
    # MAX (мессенджер): в документации platform-api.max.ru описан API ботов с токеном приложения;
    # сценария OAuth2 «вход пользователя на сайт» в открытом доступе нет — отдельный провайдер не подключён.

    feature_use_mock_llm: bool = True
    feature_use_mock_hh: bool = True
    feature_use_mock_social_oauth: bool = False
    feature_use_mock_estaff: bool = False

    # Пути относительно базового URL (полный хост в настройках, например krit.e-staff.ru)
    estaff_create_candidate_path: str = "/api/candidate/add"
    # POST /api/user/get — проверка существования пользователя по логину
    estaff_user_get_path: str = "/api/user/get"
    # POST /api/vacancy/find — см. документацию e-staff
    estaff_vacancies_path: str = "/api/vacancy/find"
    # Проверка TLS при вызове e-staff (false только для отладки / внутренний CA)
    estaff_http_verify: bool = True
    # Добавлять к тексту ошибки 502 краткую техническую причину (только для отладки)
    estaff_expose_error_detail: bool = False
    estaff_vacancies_cache_ttl_seconds: int = 120
    # POST /api/base/get_voc — справочники для разрешения id
    estaff_get_voc_path: str = "/api/base/get_voc"
    estaff_voc_cache_ttl_seconds: int = 600
    estaff_voc_cache_max_entries: int = 128
    # Если HH не отдаёт ФИО и контакты (ограничения тарифа), подставить значения в поля eStaff.
    estaff_fio_placeholder_enabled: bool = False
    estaff_fio_placeholder_firstname: str = "Имя не указано"
    estaff_fio_placeholder_lastname: str = "Фамилия не указана"
    estaff_fio_placeholder_middlename: str = ""
    estaff_contact_placeholder_email: str = "nocontact@placeholder.invalid"
    estaff_contact_placeholder_mobile: str = "+70000000000"

    # Публичный базовый URL фронтенда для абсолютной ссылки в HTML-вложении выгрузки (без завершающего /)
    hr_public_base_url: str = ""
    # type_id типа вложения из справочника card_attachment_types в e-staff (HTML-блок HR)
    estaff_hr_bundle_attachment_type_id: str = ""

    # LLM (OpenAI/Ollama compatible API)
    internal_llm_endpoint: str = ""
    internal_llm_api_key: str = "ollama"
    internal_llm_model: str = "llama3.2"
    llm_runtime_env_priority: bool = True
    feature_pdf_export: bool = False
    feature_llm_resume_analysis: bool = True
    llm_relevance_threshold: int = 60

    # LLM детальный анализ (батч на снимке)
    llm_search_batch_size: int = 10
    llm_detailed_top_n: int = 15

    # Быстрый LLM pre-screening (лёгкая модель, числовая оценка)
    llm_fast_model: str = "qwen2.5:7b"
    # Меньшие батчи надёжнее для тяжёлых моделей (полный JSON-массив по всем строкам).
    llm_fast_batch_size: int = 5
    # Дозапрос, если в батче не пришла оценка
    llm_prescore_refill_enabled: bool = True
    llm_prescore_refill_max_llm_calls: int = 500
    llm_prescore_refill_batch_size: int = 5
    llm_prescore_refill_max_seconds: float = 30.0

    # Кэш LLM после поиска (карточка с тем же ?q= без повторного вызова модели)
    llm_analysis_cache_ttl_seconds: int = 7200
    llm_analysis_cache_max_entries: int = 2000

    # Снимок выдачи поиска (пагинация без повторных запросов к HH/LLM)
    search_snapshot_ttl_seconds: int = 3600
    search_snapshot_max_per_user: int = 8
    # Пустая строка — хранение снимков в памяти процесса; для нескольких реплик укажите Redis
    redis_url: str = ""

    # POST /search/parse/debug — сырой ответ LLM (по умолчанию выключено; при включении — только админы)
    feature_search_parse_debug: bool = False
    feature_hh_boolean_query: bool = False
    search_max_resumes_fetch_per_search: int = 1000
    search_hh_page_size: int = 50
    search_recall_target_min: int = 60
    # Для запросов с зафиксированным регионом допустим меньший recall-порог.
    search_recall_target_min_with_area: int = 40
    search_recall_target_max: int = 300
    search_max_recall: int = 300
    search_bonus_share_max: float = 0.2
    search_bonus_guard_top_n: int = 30
    # Глобальный флаг: при false навыки обрабатываются только по canonical без синонимов/эквивалентов.
    feature_skill_synonyms_enabled: bool = False
    skill_synonyms_ttl_days: int = 30
    skill_synonyms_per_canonical_max: int = 8
    hh_query_use_search_field: bool = False
    hh_query_relax_max_steps: int = 3
    hh_query_relax_max_steps_with_area: int = 2
    hh_query_max_text_length: int = 1500
    feature_hh_auto_professional_role: bool = False
    hh_professional_roles_timeout_seconds: float = 3.0
    hh_professional_roles_cache_ttl_seconds: int = 900
    # Формат: "10=аналитик|business analyst;96=разработчик|developer"
    hh_auto_professional_role_map: str = ""
    # Максимум резюме с подгрузкой полных данных (опыт, «о себе») на этапе evaluate
    evaluate_max_enrich_resumes: int = 0
    evaluate_enrich_concurrency: int = 5
    evaluate_progress_ttl_seconds: int = 1800
    evaluate_interactive_top_n: int = 60
    # Бюджет времени фаз pre-score:
    # > 0 — ограничение в секундах, <= 0 — без ограничения по времени.
    llm_prescore_interactive_max_seconds: float = 120.0
    llm_prescore_background_max_seconds: float = 900.0
    llm_prescore_refill_min_gain: int = 1
    llm_prescore_recovery_enabled: bool = True
    llm_prescore_single_retry_max_attempts: int = 3
    llm_prescore_recovery_max_depth: int = 10
    llm_prescore_partial_status_on_timeout: bool = True
    llm_prescore_single_timeout_seconds: float = 240.0
    llm_prescore_enable_fallback: bool = False
    llm_prescore_fallback_min_score: int = 20
    llm_prescore_fallback_max_score: int = 95
    llm_prescore_fallback_weight_skills: float = 0.4
    llm_prescore_fallback_weight_position: float = 0.25
    llm_prescore_fallback_weight_experience: float = 0.2
    llm_prescore_fallback_weight_region: float = 0.15

    # Пост-фильтрация по точным числовым границам из parsed
    strict_numeric_filters: bool = True
    strict_filter_mode: str = "hide"  # hide | demote
    # true: пустой title не отсекается в position-фильтре; false: strict-режим требует title
    strict_position_allow_empty_title: bool = True

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Глобальные секреты (HH-приложение, e-staff, LLM): PUT только при is_admin у пользователя
    # или совпадении email / id со списками ниже. При settings_admin_only=false любой
    # авторизованный пользователь может записывать (только для локальной разработки).
    feature_settings_write: bool = True
    settings_admin_only: bool = True
    settings_admin_emails: str = ""
    settings_admin_user_ids: str = ""
    # Устарело: не используется для выдачи супер-прав.
    # Оставлено только для обратной совместимости конфигов/окружений.
    super_settings_admin_email: str = ""

    # true — не связывать OAuth с существующим пользователем по email, если у него задан пароль
    social_oauth_strict_email_link: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def _hh_credentials_dict_from_db(db: Session) -> dict[str, Any] | None:
    from sqlalchemy import select

    from app.models.system_settings import SystemSettings
    from app.services import encryption

    row = db.scalars(
        select(SystemSettings).where(SystemSettings.key == "hh_credentials")
    ).first()
    if not row:
        return None
    try:
        data = encryption.decrypt_json(row.encrypted_value)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def get_hh_credentials_from_db(db: Session) -> tuple[str, str] | None:
    """Возвращает (client_id, client_secret) из БД или None."""
    data = _hh_credentials_dict_from_db(db)
    if not data:
        return None
    cid = data.get("client_id")
    sec = data.get("client_secret")
    if isinstance(cid, str) and isinstance(sec, str) and cid.strip() and sec.strip():
        return cid.strip(), sec.strip()
    return None


def get_hh_oauth_payload_from_db(db: Session) -> dict[str, Any] | None:
    """Расшифрованные сохранённые поля OAuth-приложения HH (если есть)."""
    return _hh_credentials_dict_from_db(db)


def _estaff_credentials_dict_from_db(db: Session) -> dict[str, Any] | None:
    from sqlalchemy import select

    from app.models.system_settings import SystemSettings
    from app.services import encryption

    row = db.scalars(
        select(SystemSettings).where(SystemSettings.key == "estaff_credentials")
    ).first()
    if not row:
        return None
    try:
        data = encryption.decrypt_json(row.encrypted_value)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def get_estaff_credentials_from_db(db: Session) -> tuple[str, str] | None:
    """Возвращает (server_name, api_token) из БД или None."""
    data = _estaff_credentials_dict_from_db(db)
    if not data:
        return None
    server = data.get("server_name")
    token = data.get("api_token")
    if (
        isinstance(server, str)
        and isinstance(token, str)
        and server.strip()
        and token.strip()
    ):
        return server.strip(), token.strip()
    return None


settings = Settings()
