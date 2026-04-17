from __future__ import annotations



from app.services.hh_filter_mapper import (
    infer_professional_role,
    merge_resume_search_params,
    resume_search_text_for_hh,
)
from app.services.hh_query_planner import HHQueryPlan





def test_resume_search_text_prefers_structured_terms() -> None:

    parsed = {

        "text": "Найди команду из 5 человек, PMP и архитектор",

        "position_keywords": ["Руководитель проекта", "Архитектор"],

        "skills": ["PMP", "микросервисная архитектура"],

    }

    t = resume_search_text_for_hh(parsed)

    assert t is not None

    assert "Найди команду" not in t

    assert "PMP" in t

    assert "Руководитель проекта" in t





def test_resume_search_text_falls_back_to_raw() -> None:

    parsed = {"text": "  Python разработчик  ", "position_keywords": [], "skills": []}

    assert resume_search_text_for_hh(parsed) == "Python разработчик"





def test_merge_uses_structured_hh_text() -> None:

    parsed = {

        "text": "Длинный разговорный запрос про команду",

        "position_keywords": ["Менеджер"],

        "skills": ["SQL"],

    }

    m = merge_resume_search_params(parsed, None, page=0, per_page=20)

    assert m["text"] == "Менеджер SQL"


def test_resume_search_text_prefers_hard_skills_over_legacy_skills() -> None:
    parsed = {
        "position_keywords": ["Системный аналитик"],
        "skills": ["микросервисы", "вайбкодинг"],
        "hard_skills": ["микросервисы"],
    }
    text = resume_search_text_for_hh(parsed)
    assert text is not None
    assert "микросервисы" in text
    assert "вайбкодинг" not in text


def test_resume_search_text_uses_semantic_canonical_equivalents() -> None:
    parsed = {
        "position_keywords": ["Python developer"],
        "must_skills": [
            {
                "canonical": "курсорить",
                "search_equivalents": ["AI-assisted coding", "Copilot"],
            }
        ],
        "should_skills": [],
    }
    text = resume_search_text_for_hh(parsed)
    assert text is not None
    assert "курсорить" not in text
    assert "AI-assisted coding" in text


def test_merge_prefers_query_plan_text() -> None:
    parsed = {"text": "legacy", "position_keywords": ["Менеджер"], "skills": ["SQL"]}
    plan = HHQueryPlan(label="primary", text='("System Analyst" OR "Системный аналитик")', priority=100)
    m = merge_resume_search_params(parsed, None, page=0, per_page=20, query_plan=plan)
    assert m["text"] == plan.text


def test_merge_indexed_text_fields_when_search_field_enabled(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings
    monkeypatch.setattr(fm_settings, "hh_query_use_search_field", True)

    parsed = {"text": "test"}
    plan = HHQueryPlan(
        label="primary",
        text='"Analyst" AND "Python"',
        priority=100,
        search_field="text",
        groups=(("role", '"Analyst"'), ("must_0", '"Python"')),
        parts=(("position", '"Analyst"'), ("skill", '"Python"')),
    )
    m = merge_resume_search_params(parsed, None, page=0, per_page=20, query_plan=plan)
    assert "text" not in m
    assert m["text.0.field"] == "position"
    assert m["text.0.text"] == '"Analyst"'
    assert m["text.1.field"] == "skill"
    assert m["text.1.text"] == '"Python"'


def test_merge_flat_text_when_search_field_disabled(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings
    monkeypatch.setattr(fm_settings, "hh_query_use_search_field", False)

    parsed = {"text": "test"}
    plan = HHQueryPlan(
        label="primary",
        text='"Analyst" AND "Python"',
        priority=100,
        search_field=None,
        groups=(("role", '"Analyst"'), ("must_0", '"Python"')),
        parts=(("everywhere", '"Analyst"'), ("everywhere", '"Python"')),
    )
    m = merge_resume_search_params(parsed, None, page=0, per_page=20, query_plan=plan)
    assert m["text"] == plan.text
    assert "text.0.field" not in m


def test_infer_professional_role_exact_match_priority(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings

    monkeypatch.setattr(fm_settings, "hh_auto_professional_role_map", "10=аналитик|системный аналитик;96=разработчик")
    parsed = {"position_keywords": ["Системный аналитик"], "must_position": ["Аналитик"]}
    assert infer_professional_role(parsed) == 10


def test_infer_professional_role_partial_match(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings

    monkeypatch.setattr(fm_settings, "hh_auto_professional_role_map", "10=бизнес-аналитик;96=разработчик")
    parsed = {"position_keywords": ["Senior бизнес-аналитик CRM"], "must_position": []}
    assert infer_professional_role(parsed) == 10


def test_merge_uses_inferred_professional_role_when_enabled(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings

    monkeypatch.setattr(fm_settings, "feature_hh_auto_professional_role", True)
    monkeypatch.setattr(fm_settings, "hh_auto_professional_role_map", "10=аналитик|data analyst")
    parsed = {"position_keywords": ["Data Analyst"], "must_position": []}
    params = merge_resume_search_params(parsed, None, page=0, per_page=20)
    assert params["professional_role"] == 10


def test_merge_explicit_professional_role_has_priority(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings

    monkeypatch.setattr(fm_settings, "feature_hh_auto_professional_role", True)
    monkeypatch.setattr(fm_settings, "hh_auto_professional_role_map", "10=аналитик")
    parsed = {"position_keywords": ["аналитик"], "must_position": []}
    params = merge_resume_search_params(
        parsed,
        {"professional_role": 96},
        page=0,
        per_page=20,
    )
    assert params["professional_role"] == 96


