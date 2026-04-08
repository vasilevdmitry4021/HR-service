"""Генерация PDF резюме из нормализованного словаря (WeasyPrint)."""

from __future__ import annotations

import html
from typing import Any


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_resume_html(data: dict[str, Any]) -> str:
    title = _esc(str(data.get("title") or "Резюме"))
    full_name = _esc(str(data.get("full_name") or "—"))
    area = _esc(str(data.get("area") or "—"))
    age = data.get("age")
    exp_y = data.get("experience_years")
    age_s = _esc(str(age)) if age is not None else "—"
    exp_s = _esc(str(exp_y)) if exp_y is not None else "—"
    sal = data.get("salary") or {}
    amt = sal.get("amount") if isinstance(sal, dict) else None
    cur = (sal.get("currency") if isinstance(sal, dict) else None) or "RUR"
    if isinstance(amt, (int, float)) and not isinstance(amt, bool):
        n = int(amt)
        salary_line = f"{n:,}".replace(",", "\u00a0") + f" {_esc(str(cur))}"
    else:
        salary_line = "—"
    skills = data.get("skills") or []
    if isinstance(skills, list):
        skill_items = "".join(
            f"<li>{_esc(str(s))}</li>" for s in skills if s is not None
        )
    else:
        skill_items = ""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    body {{ font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
      font-size: 11pt; color: #111; margin: 24px; }}
    h1 {{ font-size: 18pt; margin: 0 0 8px 0; }}
    .muted {{ color: #555; font-size: 10pt; margin-bottom: 16px; }}
    h2 {{ font-size: 12pt; margin: 16px 0 8px 0; border-bottom: 1px solid #ccc; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
    td {{ padding: 4px 8px 4px 0; vertical-align: top; }}
    td:first-child {{ width: 38%; color: #555; }}
    ul {{ margin: 0; padding-left: 18px; }}
    .footer {{ margin-top: 32px; font-size: 9pt; color: #888; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="muted">{full_name} · {area}</p>
  <h2>Сводка</h2>
  <table>
    <tr><td>Возраст</td><td>{age_s}</td></tr>
    <tr><td>Опыт (лет)</td><td>{exp_s}</td></tr>
    <tr><td>Зарплата</td><td>{salary_line}</td></tr>
  </table>
  <h2>Навыки</h2>
  <ul>{skill_items or "<li>—</li>"}</ul>
  <p class="footer">Сформировано сервисом HR · данные из HeadHunter</p>
</body>
</html>
"""


def resume_html_to_pdf_bytes(data: dict[str, Any]) -> bytes:
    from weasyprint import HTML

    html_str = build_resume_html(data)
    return HTML(string=html_str, base_url=".").write_pdf()
