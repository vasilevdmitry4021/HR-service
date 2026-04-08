"""Эвристическая классификация: похоже ли сообщение на резюме."""

from __future__ import annotations

import re

from telegram_ingestion.config import TELEGRAM_RESUME_CLASSIFIER_MIN_SCORE

_RESUME_HINTS = (
    "резюме",
    "cv",
    "curriculum",
    "опыт работы",
    "опыт:",
    "навыки",
    "стек",
    "github.com",
    "linkedin",
    "telegram:",
    "whatsapp",
    "mailto:",
    "желаемая должность",
    "зарплат",
)


def classify_resume_text(text: str) -> tuple[bool, float]:
    raw = (text or "").strip()
    if len(raw) < 50:
        return False, 0.0
    low = raw.lower()
    hits = sum(1 for h in _RESUME_HINTS if h in low)
    digits = len(re.findall(r"\d", raw))
    score = min(
        1.0,
        hits * 0.12 + (0.15 if "@" in raw else 0) + (0.08 if digits >= 3 else 0),
    )
    ok = score >= TELEGRAM_RESUME_CLASSIFIER_MIN_SCORE
    return ok, score
