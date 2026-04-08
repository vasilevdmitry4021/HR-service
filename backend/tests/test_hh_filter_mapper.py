from __future__ import annotations



from app.services.hh_filter_mapper import merge_resume_search_params, resume_search_text_for_hh





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


