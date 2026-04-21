from __future__ import annotations



from app.services.hh_filter_mapper import (
    infer_professional_roles,
    infer_professional_role,
    merge_resume_search_params,
    resolve_professional_roles,
    resolve_area_priority,
    resume_search_text_for_hh,
)
from app.services.hh_client import HHProfessionalRoleReference
from app.services.hh_query_planner import HHQueryPlan


def _professional_role_reference() -> HHProfessionalRoleReference:
    return HHProfessionalRoleReference(
        id_to_name={
            10: "Системный аналитик",
            11: "Бизнес-аналитик",
            12: "BI-аналитик, аналитик данных",
            96: "Программист, разработчик",
        },
        normalized_role_name_to_ids={
            "системный аналитик": (10,),
            "system analyst": (10,),
            "бизнес-аналитик": (11,),
            "business analyst": (11,),
            "bi-аналитик аналитик данных": (12,),
            "data analyst": (12,),
            "программист разработчик": (96,),
        },
    )





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

    assert m["text"] == "SQL"


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


def test_resume_search_text_uses_semantic_canonical_only() -> None:
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
    assert "курсорить" in text
    assert "AI-assisted coding" not in text


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
        groups=(("role", '"Analyst"'), ("skills", '"Python"')),
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
        groups=(("role", '"Analyst"'), ("skills", '"Python"')),
        parts=(("everywhere", '"Analyst"'), ("everywhere", '"Python"')),
    )
    m = merge_resume_search_params(parsed, None, page=0, per_page=20, query_plan=plan)
    assert m["text"] == plan.text
    assert "text.0.field" not in m


def test_infer_professional_role_exact_match_priority() -> None:
    reference = _professional_role_reference()
    parsed = {"position_keywords": ["Системный аналитик"], "must_position": ["Аналитик"]}
    assert infer_professional_role(parsed, reference) == 10


def test_infer_professional_roles_for_generic_analyst_returns_multiple_ids() -> None:
    reference = _professional_role_reference()
    parsed = {"position_keywords": ["Аналитик"], "must_position": []}
    assert infer_professional_roles(parsed, reference) == [10, 11, 12]


def test_infer_professional_role_partial_match() -> None:
    reference = _professional_role_reference()
    parsed = {"position_keywords": ["Senior бизнес-аналитик CRM"], "must_position": []}
    assert infer_professional_role(parsed, reference) == 11


def test_merge_uses_inferred_professional_role_when_enabled(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings

    monkeypatch.setattr(fm_settings, "feature_hh_auto_professional_role", True)
    reference = _professional_role_reference()
    parsed = {"position_keywords": ["Data Analyst"], "must_position": []}
    params = merge_resume_search_params(
        parsed,
        None,
        page=0,
        per_page=20,
        professional_roles_reference=reference,
    )
    assert params["professional_role"] == [12]


def test_merge_explicit_professional_role_has_priority(monkeypatch) -> None:
    from app.services.hh_filter_mapper import settings as fm_settings

    monkeypatch.setattr(fm_settings, "feature_hh_auto_professional_role", True)
    reference = _professional_role_reference()
    parsed = {"position_keywords": ["аналитик"], "must_position": []}
    params = merge_resume_search_params(
        parsed,
        {"professional_role": 96},
        page=0,
        per_page=20,
        professional_roles_reference=reference,
    )
    assert params["professional_role"] == 96


def test_resolve_professional_roles_returns_debug_payload() -> None:
    reference = _professional_role_reference()
    parsed = {"position_keywords": ["аналитик"], "must_position": []}
    role_ids, debug = resolve_professional_roles(parsed, reference)
    assert role_ids == [10, 11, 12]
    assert any(item.get("strategy") == "canonical_analyst_fanout" for item in debug)


def test_merge_uses_or_operator_for_mass_mode() -> None:
    parsed = {
        "position_keywords": ["Системный аналитик"],
        "skills": ["Kafka", "микросервисы"],
    }
    params = merge_resume_search_params(parsed, None, page=0, per_page=20, search_mode="mass")
    assert params["text"] == "Kafka OR микросервисы"


def test_merge_region_alias_spb_maps_to_area_2() -> None:
    parsed = {"region": "СПб"}
    params = merge_resume_search_params(parsed, None, page=0, per_page=20)
    assert params["area"] == [2]


def test_merge_region_alias_piter_maps_to_area_2() -> None:
    parsed = {"region": "Питер"}
    params = merge_resume_search_params(parsed, None, page=0, per_page=20)
    assert params["area"] == [2]


def test_resolve_area_priority_prefers_filter_panel_over_parsed_region() -> None:
    parsed = {"region": "Москва"}
    area, source = resolve_area_priority(parsed, {"area": 2})
    assert area == [2]
    assert source == "panel"


def test_resolve_area_priority_accepts_multiple_panel_areas() -> None:
    parsed = {"region": "Москва"}
    area, source = resolve_area_priority(parsed, {"area": [2, 1, 2]})
    assert area == [2, 1]
    assert source == "panel"

