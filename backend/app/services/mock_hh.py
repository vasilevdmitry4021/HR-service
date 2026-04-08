"""Synthetic resumes for development when FEATURE_USE_MOCK_HH is enabled."""

from __future__ import annotations

from typing import Any

from app.schemas.search_filters import ResumeSearchFilters

_MOCK_DB: list[dict[str, Any]] | None = None


def mock_resume_database() -> list[dict[str, Any]]:
    global _MOCK_DB
    if _MOCK_DB is not None:
        return _MOCK_DB
    _MOCK_DB = [
        {
            "id": "mock-1",
            "hh_resume_id": "hh-mock-001",
            "title": "Java Developer",
            "full_name": "Иванов Иван",
            "age": 28,
            "experience_years": 5,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 200000, "currency": "RUR"},
            "skills": ["Java", "Spring Boot", "PostgreSQL", "Kafka"],
            "area": "Москва",
            "about_html": (
                "<p>Ищу интересные проекты в системной разработке.</p>"
                "<p><strong>Стек:</strong> Java, Kotlin, Spring Boot, Kafka.</p>"
            ),
            "education_block": {
                "level": {"name": "Высшее образование"},
                "primary": [
                    {
                        "name": "Университет",
                        "organization": "Московский институт",
                        "result": "Прикладная математика",
                        "year": 2015,
                        "education_level": {"name": "Высшее образование"},
                    }
                ],
                "additional": [],
            },
            "experience": [
                {
                    "start": "2023-12-01",
                    "end": "2025-05-01",
                    "company": "Selecty",
                    "area": {"name": "Москва"},
                    "industries": [{"name": "Услуги для бизнеса"}],
                    "position": "Java-разработчик",
                    "description": (
                        "<p>Работа для крупного банка через аккредитованного партнёра. "
                        "Проект истории операций и «Гарантия доставки».</p>"
                        "<p><strong>Задачи:</strong></p><ul>"
                        "<li>Проектирование и ввод новых сервисов</li>"
                        "<li>Рефакторинг под новую архитектуру</li>"
                        "<li>Настройка k8s и сопровождение релизов</li></ul>"
                        "<p><strong>Стек:</strong> Java, Spring Boot, Kafka, PostgreSQL</p>"
                    ),
                },
                {
                    "start": "2020-06-01",
                    "end": "2023-11-01",
                    "company": "ООО Ромашка",
                    "position": "Инженер-программист",
                    "description": "Поддержка внутренних сервисов учёта.",
                },
            ],
        },
        {
            "id": "mock-2",
            "hh_resume_id": "hh-mock-002",
            "title": "Senior Python Engineer",
            "full_name": "Петрова Анна",
            "age": 32,
            "experience_years": 7,
            "gender": "female",
            "area_id": 2,
            "salary": {"amount": 280000, "currency": "RUR"},
            "skills": ["Python", "Django", "FastAPI", "PostgreSQL"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-3",
            "hh_resume_id": "hh-mock-003",
            "title": "Full-stack разработчик",
            "full_name": "Сидоров Пётр",
            "age": 26,
            "experience_years": 3,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 160000, "currency": "RUR"},
            "skills": ["JavaScript", "TypeScript", "React", "Node.js"],
            "area": "Москва",
        },
        {
            "id": "mock-4",
            "hh_resume_id": "hh-mock-004",
            "title": "Go Developer",
            "full_name": "Козлов Михаил",
            "age": 30,
            "experience_years": 4,
            "gender": "male",
            "area_id": 3,
            "salary": {"amount": 220000, "currency": "RUR"},
            "skills": ["Go", "Kubernetes", "gRPC", "PostgreSQL"],
            "area": "Екатеринбург",
        },
        {
            "id": "mock-5",
            "hh_resume_id": "hh-mock-005",
            "title": "Руководитель проекта",
            "full_name": "Смирнова Елена",
            "age": 38,
            "experience_years": 10,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 250000, "currency": "RUR"},
            "skills": ["PMP", "Agile", "Scrum", "Jira", "Confluence"],
            "area": "Москва",
        },
        {
            "id": "mock-6",
            "hh_resume_id": "hh-mock-006",
            "title": "Project Manager",
            "full_name": "Волков Андрей",
            "age": 42,
            "experience_years": 15,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 320000, "currency": "RUR"},
            "skills": ["PMP", "Prince2", "Agile", "SAFe", "Risk Management"],
            "area": "Москва",
        },
        {
            "id": "mock-7",
            "hh_resume_id": "hh-mock-007",
            "title": "Менеджер проектов",
            "full_name": "Орлова Мария",
            "age": 35,
            "experience_years": 8,
            "gender": "female",
            "area_id": 2,
            "salary": {"amount": 220000, "currency": "RUR"},
            "skills": ["PMP", "Scrum", "Kanban", "MS Project"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-8",
            "hh_resume_id": "hh-mock-008",
            "title": "Архитектор решений",
            "full_name": "Федоров Дмитрий",
            "age": 40,
            "experience_years": 12,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 350000, "currency": "RUR"},
            "skills": ["микросервисная архитектура", "microservices", "Kubernetes", "Docker", "Java", "Spring Boot"],
            "area": "Москва",
        },
        {
            "id": "mock-9",
            "hh_resume_id": "hh-mock-009",
            "title": "Системный архитектор",
            "full_name": "Новикова Ольга",
            "age": 36,
            "experience_years": 9,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 300000, "currency": "RUR"},
            "skills": ["microservices", "Kafka", "PostgreSQL", "Redis", "event-driven architecture"],
            "area": "Москва",
        },
        {
            "id": "mock-10",
            "hh_resume_id": "hh-mock-010",
            "title": "IT-архитектор",
            "full_name": "Кузнецов Сергей",
            "age": 45,
            "experience_years": 18,
            "gender": "male",
            "area_id": 3,
            "salary": {"amount": 400000, "currency": "RUR"},
            "skills": ["микросервисная архитектура", "Docker", "Kubernetes", "gRPC", "Go", "Domain-Driven Design"],
            "area": "Екатеринбург",
        },
        {
            "id": "mock-11",
            "hh_resume_id": "hh-mock-011",
            "title": "Бизнес-аналитик",
            "full_name": "Алексеева Ксения",
            "age": 29,
            "experience_years": 4,
            "gender": "female",
            "area_id": 4,
            "salary": {"amount": 190000, "currency": "RUR"},
            "skills": ["BPMN", "UML", "SQL", "Jira", "Confluence", "User Stories"],
            "area": "Казань",
        },
        {
            "id": "mock-12",
            "hh_resume_id": "hh-mock-012",
            "title": "Data Analyst",
            "full_name": "Морозов Артём",
            "age": 24,
            "experience_years": 2,
            "gender": "male",
            "area_id": 2,
            "salary": {"amount": 140000, "currency": "RUR"},
            "skills": ["Python", "SQL", "pandas", "Tableau", "Excel", "A/B-тесты"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-13",
            "hh_resume_id": "hh-mock-013",
            "title": "BI-аналитик",
            "full_name": "Жукова Дарья",
            "age": 33,
            "experience_years": 6,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 240000, "currency": "RUR"},
            "skills": ["Power BI", "SQL", "DAX", "ETL", "ClickHouse", "Apache Airflow"],
            "area": "Москва",
        },
        {
            "id": "mock-14",
            "hh_resume_id": "hh-mock-014",
            "title": "Продуктовый аналитик",
            "full_name": "Егоров Никита",
            "age": 27,
            "experience_years": 3,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 210000, "currency": "RUR"},
            "skills": ["Amplitude", "SQL", "Python", "метрики", "воронки", "Looker"],
            "area": "Москва",
        },
        {
            "id": "mock-15",
            "hh_resume_id": "hh-mock-015",
            "title": "UX-дизайнер",
            "full_name": "Соколова Виктория",
            "age": 31,
            "experience_years": 5,
            "gender": "female",
            "area_id": 2,
            "salary": {"amount": 200000, "currency": "RUR"},
            "skills": ["Figma", "исследования", "прототипирование", "Usability", "Design System"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-16",
            "hh_resume_id": "hh-mock-016",
            "title": "UI/UX дизайнер",
            "full_name": "Романов Илья",
            "age": 23,
            "experience_years": 1,
            "gender": "male",
            "area_id": 3,
            "salary": {"amount": 95000, "currency": "RUR"},
            "skills": ["Figma", "Adobe XD", "мобильный дизайн", "адаптивная вёрстка", "UI Kit"],
            "area": "Екатеринбург",
        },
        {
            "id": "mock-17",
            "hh_resume_id": "hh-mock-017",
            "title": "Product Designer",
            "full_name": "Кравцова Полина",
            "age": 34,
            "experience_years": 7,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 270000, "currency": "RUR"},
            "skills": ["Figma", "продуктовая стратегия", "CJM", "A/B-тесты", "дизайн-системы"],
            "area": "Москва",
        },
        {
            "id": "mock-18",
            "hh_resume_id": "hh-mock-018",
            "title": "Frontend-разработчик (React)",
            "full_name": "Беляев Константин",
            "age": 28,
            "experience_years": 4,
            "gender": "male",
            "area_id": 5,
            "salary": {"amount": 185000, "currency": "RUR"},
            "skills": ["React", "TypeScript", "Redux Toolkit", "Webpack", "Jest", "CSS"],
            "area": "Нижний Новгород",
        },
        {
            "id": "mock-19",
            "hh_resume_id": "hh-mock-019",
            "title": "Vue.js разработчик",
            "full_name": "Тихонов Максим",
            "age": 25,
            "experience_years": 2,
            "gender": "male",
            "area_id": 6,
            "salary": {"amount": 150000, "currency": "RUR"},
            "skills": ["Vue.js", "Nuxt", "JavaScript", "Pinia", "REST API", "Tailwind CSS"],
            "area": "Краснодар",
        },
        {
            "id": "mock-20",
            "hh_resume_id": "hh-mock-020",
            "title": "Angular-разработчик",
            "full_name": "Громова Екатерина",
            "age": 36,
            "experience_years": 8,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 260000, "currency": "RUR"},
            "skills": ["Angular", "TypeScript", "RxJS", "NgRx", "Karma", "Jasmine"],
            "area": "Москва",
        },
        {
            "id": "mock-21",
            "hh_resume_id": "hh-mock-021",
            "title": "PHP-разработчик",
            "full_name": "Данилов Руслан",
            "age": 30,
            "experience_years": 5,
            "gender": "male",
            "area_id": 2,
            "salary": {"amount": 175000, "currency": "RUR"},
            "skills": ["PHP", "Laravel", "MySQL", "Redis", "REST", "Docker"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-22",
            "hh_resume_id": "hh-mock-022",
            "title": "Ruby on Rails разработчик",
            "full_name": "Степанова Алина",
            "age": 32,
            "experience_years": 6,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 230000, "currency": "RUR"},
            "skills": ["Ruby", "Rails", "RSpec", "PostgreSQL", "Sidekiq", "Heroku"],
            "area": "Москва",
        },
        {
            "id": "mock-23",
            "hh_resume_id": "hh-mock-023",
            "title": ".NET разработчик",
            "full_name": "Николаев Павел",
            "age": 39,
            "experience_years": 10,
            "gender": "male",
            "area_id": 2,
            "salary": {"amount": 290000, "currency": "RUR"},
            "skills": ["C#", ".NET", "ASP.NET Core", "Entity Framework", "SQL Server", "Azure"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-24",
            "hh_resume_id": "hh-mock-024",
            "title": "iOS-разработчик (Swift)",
            "full_name": "Осипов Глеб",
            "age": 29,
            "experience_years": 4,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 240000, "currency": "RUR"},
            "skills": ["Swift", "UIKit", "SwiftUI", "Combine", "XCTest", "CI/CD"],
            "area": "Москва",
        },
        {
            "id": "mock-25",
            "hh_resume_id": "hh-mock-025",
            "title": "Android-разработчик (Kotlin)",
            "full_name": "Воробьёва Юлия",
            "age": 26,
            "experience_years": 3,
            "gender": "female",
            "area_id": 4,
            "salary": {"amount": 195000, "currency": "RUR"},
            "skills": ["Kotlin", "Jetpack Compose", "Coroutines", "Room", "Retrofit", "Gradle"],
            "area": "Казань",
        },
        {
            "id": "mock-26",
            "hh_resume_id": "hh-mock-026",
            "title": "Flutter-разработчик",
            "full_name": "Хасанов Тимур",
            "age": 27,
            "experience_years": 2,
            "gender": "male",
            "area_id": 7,
            "salary": {"amount": 170000, "currency": "RUR"},
            "skills": ["Flutter", "Dart", "Bloc", "Firebase", "REST", "Git"],
            "area": "Удалённо",
        },
        {
            "id": "mock-27",
            "hh_resume_id": "hh-mock-027",
            "title": "React Native разработчик",
            "full_name": "Лебедев Станислав",
            "age": 31,
            "experience_years": 5,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 225000, "currency": "RUR"},
            "skills": ["React Native", "TypeScript", "Redux", "Native Modules", "Metro", "Jest"],
            "area": "Москва",
        },
        {
            "id": "mock-28",
            "hh_resume_id": "hh-mock-028",
            "title": "DevOps-инженер",
            "full_name": "Макаров Денис",
            "age": 34,
            "experience_years": 6,
            "gender": "male",
            "area_id": 2,
            "salary": {"amount": 255000, "currency": "RUR"},
            "skills": ["Kubernetes", "Terraform", "Ansible", "GitLab CI", "Prometheus", "Grafana"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-29",
            "hh_resume_id": "hh-mock-029",
            "title": "SRE",
            "full_name": "Фролова Инна",
            "age": 30,
            "experience_years": 4,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 265000, "currency": "RUR"},
            "skills": ["SLO/SLI", "Kubernetes", "Linux", "Python", "on-call", "incident management"],
            "area": "Москва",
        },
        {
            "id": "mock-30",
            "hh_resume_id": "hh-mock-030",
            "title": "QA Automation Engineer",
            "full_name": "Кириллов Арсений",
            "age": 27,
            "experience_years": 3,
            "gender": "male",
            "area_id": 3,
            "salary": {"amount": 165000, "currency": "RUR"},
            "skills": ["Python", "Pytest", "Selenium", "Playwright", "API testing", "CI/CD"],
            "area": "Екатеринбург",
        },
        {
            "id": "mock-31",
            "hh_resume_id": "hh-mock-031",
            "title": "Руководитель отдела тестирования",
            "full_name": "Павлова Наталья",
            "age": 41,
            "experience_years": 8,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 245000, "currency": "RUR"},
            "skills": ["тест-стратегия", "Jira", "ручное тестирование", "управление командой", "регрессия"],
            "area": "Москва",
        },
        {
            "id": "mock-32",
            "hh_resume_id": "hh-mock-032",
            "title": "Специалист по информационной безопасности",
            "full_name": "Сафонов Игорь",
            "age": 35,
            "experience_years": 5,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 230000, "currency": "RUR"},
            "skills": ["SIEM", "pentest basics", "ISO 27001", "сети", "аудит", "SOC"],
            "area": "Москва",
        },
        {
            "id": "mock-33",
            "hh_resume_id": "hh-mock-033",
            "title": "Сетевой инженер",
            "full_name": "Тарасов Владимир",
            "age": 44,
            "experience_years": 12,
            "gender": "male",
            "area_id": 8,
            "salary": {"amount": 210000, "currency": "RUR"},
            "skills": ["Cisco", "routing", "VPN", "firewall", "BGP", "мониторинг"],
            "area": "Новосибирск",
        },
        {
            "id": "mock-34",
            "hh_resume_id": "hh-mock-034",
            "title": "Администратор БД (PostgreSQL)",
            "full_name": "Ефимова Светлана",
            "age": 37,
            "experience_years": 9,
            "gender": "female",
            "area_id": 2,
            "salary": {"amount": 235000, "currency": "RUR"},
            "skills": ["PostgreSQL", "репликация", "бэкапы", "оптимизация запросов", "Patroni", "Linux"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-35",
            "hh_resume_id": "hh-mock-035",
            "title": "Data Engineer",
            "full_name": "Зайцев Роман",
            "age": 28,
            "experience_years": 4,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 250000, "currency": "RUR"},
            "skills": ["Python", "Spark", "Kafka", "dbt", "Airflow", "Snowflake"],
            "area": "Москва",
        },
        {
            "id": "mock-36",
            "hh_resume_id": "hh-mock-036",
            "title": "ML Engineer",
            "full_name": "Васильева Марина",
            "age": 26,
            "experience_years": 3,
            "gender": "female",
            "area_id": 2,
            "salary": {"amount": 220000, "currency": "RUR"},
            "skills": ["Python", "PyTorch", "scikit-learn", "MLflow", "Docker", "CUDA"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-37",
            "hh_resume_id": "hh-mock-037",
            "title": "Технический писатель",
            "full_name": "Комаров Олег",
            "age": 31,
            "experience_years": 2,
            "gender": "male",
            "area_id": 4,
            "salary": {"amount": 120000, "currency": "RUR"},
            "skills": ["документация API", "Markdown", "Confluence", "Swagger", "редактура", "английский B2"],
            "area": "Казань",
        },
        {
            "id": "mock-38",
            "hh_resume_id": "hh-mock-038",
            "title": "Scrum Master",
            "full_name": "Богданова Евгения",
            "age": 33,
            "experience_years": 6,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 200000, "currency": "RUR"},
            "skills": ["Scrum", "фасилитация", "метрики команды", "Jira", "ретроспективы", "Agile"],
            "area": "Москва",
        },
        {
            "id": "mock-39",
            "hh_resume_id": "hh-mock-039",
            "title": "Product Owner",
            "full_name": "Шестаков Алексей",
            "age": 36,
            "experience_years": 7,
            "gender": "male",
            "area_id": 2,
            "salary": {"amount": 270000, "currency": "RUR"},
            "skills": ["бэклог", "приоритизация", "roadmap", "Stakeholders", "Agile", "аналитика"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-40",
            "hh_resume_id": "hh-mock-040",
            "title": "Team Lead (Backend)",
            "full_name": "Рыбаков Виктор",
            "age": 38,
            "experience_years": 11,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 320000, "currency": "RUR"},
            "skills": ["Go", "PostgreSQL", "управление командой", "code review", "архитектура", "Kubernetes"],
            "area": "Москва",
        },
        {
            "id": "mock-41",
            "hh_resume_id": "hh-mock-041",
            "title": "Встраиваемые системы (C/C++)",
            "full_name": "Поляков Андрей",
            "age": 35,
            "experience_years": 8,
            "gender": "male",
            "area_id": 5,
            "salary": {"amount": 205000, "currency": "RUR"},
            "skills": ["C", "C++", "RTOS", "STM32", "CAN", "отладка"],
            "area": "Нижний Новгород",
        },
        {
            "id": "mock-42",
            "hh_resume_id": "hh-mock-042",
            "title": "Программист 1С",
            "full_name": "Мельникова Татьяна",
            "age": 40,
            "experience_years": 11,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 195000, "currency": "RUR"},
            "skills": ["1С:Предприятие", "БСП", "запросы", "интеграции", "ERP", "обмен данными"],
            "area": "Москва",
        },
        {
            "id": "mock-43",
            "hh_resume_id": "hh-mock-043",
            "title": "Salesforce-администратор",
            "full_name": "Коваленко Дмитрий",
            "age": 29,
            "experience_years": 4,
            "gender": "male",
            "area_id": 2,
            "salary": {"amount": 185000, "currency": "RUR"},
            "skills": ["Salesforce", "Apex basics", "Flows", "Reports", "CRM", "интеграции"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-44",
            "hh_resume_id": "hh-mock-044",
            "title": "Unity-разработчик",
            "full_name": "Назаров Кирилл",
            "age": 25,
            "experience_years": 3,
            "gender": "male",
            "area_id": 3,
            "salary": {"amount": 155000, "currency": "RUR"},
            "skills": ["Unity", "C#", "геймдизайн", "шейдеры", "оптимизация", "Git"],
            "area": "Екатеринбург",
        },
        {
            "id": "mock-45",
            "hh_resume_id": "hh-mock-045",
            "title": "HR IT / People Analytics",
            "full_name": "Литвинова Оксана",
            "age": 32,
            "experience_years": 5,
            "gender": "female",
            "area_id": 1,
            "salary": {"amount": 175000, "currency": "RUR"},
            "skills": ["HRIS", "SQL", "Excel", "отчётность", "онбординг", "аналитика кадров"],
            "area": "Москва",
        },
        {
            "id": "mock-46",
            "hh_resume_id": "hh-mock-046",
            "title": "Системный администратор Linux",
            "full_name": "Гусев Сергей",
            "age": 37,
            "experience_years": 9,
            "gender": "male",
            "area_id": 6,
            "salary": {"amount": 145000, "currency": "RUR"},
            "skills": ["Linux", "Bash", "Nginx", "Zabbix", "backup", "виртуализация"],
            "area": "Краснодар",
        },
        {
            "id": "mock-47",
            "hh_resume_id": "hh-mock-047",
            "title": "Rust-разработчик",
            "full_name": "Чернов Евгений",
            "age": 28,
            "experience_years": 2,
            "gender": "male",
            "area_id": 7,
            "salary": {"amount": 200000, "currency": "RUR"},
            "skills": ["Rust", "Tokio", "WebAssembly", "PostgreSQL", "REST", "Git"],
            "area": "Удалённо",
        },
        {
            "id": "mock-48",
            "hh_resume_id": "hh-mock-048",
            "title": "Junior Web-разработчик",
            "full_name": "Семёнова Алёна",
            "age": 22,
            "experience_years": 0,
            "gender": "female",
            "area_id": 2,
            "salary": {"amount": 80000, "currency": "RUR"},
            "skills": ["HTML", "CSS", "JavaScript", "React basics", "Git", "Figma"],
            "area": "Санкт-Петербург",
        },
        {
            "id": "mock-49",
            "hh_resume_id": "hh-mock-049",
            "title": "Blockchain / Web3 разработчик",
            "full_name": "Давыдов Марат",
            "age": 30,
            "experience_years": 3,
            "gender": "male",
            "area_id": 1,
            "salary": {"amount": 280000, "currency": "RUR"},
            "skills": ["Solidity", "Ethereum", "Hardhat", "TypeScript", "smart contracts", "Web3.js"],
            "area": "Москва",
        },
        {
            "id": "mock-50",
            "hh_resume_id": "hh-mock-050",
            "title": "Системный аналитик",
            "full_name": "Романенко Ирина",
            "age": 39,
            "experience_years": 10,
            "gender": "female",
            "area_id": 8,
            "salary": {"amount": 215000, "currency": "RUR"},
            "skills": ["интеграции", "SOAP", "REST", "JSON", "XML", "Postman", "Swagger"],
            "area": "Новосибирск",
        },
    ]
    for row in _MOCK_DB:
        hid = str(row.get("hh_resume_id") or row.get("id") or "").strip()
        if hid:
            row.setdefault("hh_resume_url", f"https://hh.ru/resume/{hid}")
    return _MOCK_DB


def resume_dict_as_hh_api_resume(row: dict[str, Any]) -> dict[str, Any]:
    """Приводит поля мока к виду, совместимому с разбором ответа api.hh.ru/resumes/{id}."""
    fn, ln = "", ""
    full = str(row.get("full_name") or "").strip()
    if full:
        parts = full.split(None, 1)
        fn = parts[0]
        ln = parts[1] if len(parts) > 1 else ""
    rid = str(row.get("id") or row.get("hh_resume_id") or "")
    out: dict[str, Any] = {
        "id": rid,
        "title": row.get("title") or "",
        "first_name": fn,
        "last_name": ln,
        "age": row.get("age"),
        "area": {"name": row.get("area") or ""},
        "total_experience": {"months": int(row.get("experience_years") or 0) * 12},
        "skill_set": [{"name": s} for s in (row.get("skills") or [])],
        "salary": row.get("salary"),
    }
    alt = row.get("alternate_url")
    if isinstance(alt, str) and alt.strip():
        out["alternate_url"] = alt.strip()
    if row.get("experience"):
        out["experience"] = row["experience"]
    ah = row.get("about_html")
    if isinstance(ah, str) and ah.strip():
        out["skills"] = ah.strip()
    edu = row.get("education_block")
    if isinstance(edu, dict) and edu:
        out["education"] = edu
    return out


def get_resume_by_id(resume_id: str) -> dict[str, Any] | None:
    for r in mock_resume_database():
        if r["id"] == resume_id or r["hh_resume_id"] == resume_id:
            return r
    return None


def filter_resumes(
    items: list[dict[str, Any]],
    parsed: dict[str, Any],
    filters: ResumeSearchFilters | dict[str, Any] | None,
    merged_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out = list(items)
    mp = merged_params or {}

    if parsed.get("skills"):
        wanted = {s.lower() for s in parsed["skills"]}
        out = [
            r
            for r in out
            if wanted.intersection({s.lower() for s in r.get("skills", [])})
            or not wanted
        ]

    if parsed.get("region"):
        reg = str(parsed["region"]).lower()
        out = [r for r in out if reg in str(r.get("area", "")).lower()] or out

    pos_kw = parsed.get("position_keywords")
    if pos_kw:
        keywords_lower = [k.lower() for k in pos_kw]
        out = [
            r for r in out
            if any(kw in (r.get("title") or "").lower() for kw in keywords_lower)
        ]

    sf = mp.get("salary_from")
    if sf is not None:
        out = [r for r in out if (r.get("salary") or {}).get("amount", 0) >= int(sf)]

    st = mp.get("salary_to")
    if st is not None:
        out = [r for r in out if (r.get("salary") or {}).get("amount", 0) <= int(st)]

    exp_key = mp.get("experience")
    if exp_key:
        exp_map = {
            "noExperience": (0, 0),
            "between1And3": (1, 3),
            "between3And6": (3, 6),
            "moreThan6": (6, 99),
        }
        if exp_key in exp_map:
            lo, hi = exp_map[exp_key]
            out = [r for r in out if lo <= r.get("experience_years", 0) <= hi]

    g = mp.get("gender")
    if g in ("male", "female"):
        out = [r for r in out if r.get("gender") == g]

    af = mp.get("age_from")
    at = mp.get("age_to")
    if af is not None:
        out = [r for r in out if r.get("age") is not None and r["age"] >= int(af)]
    if at is not None:
        out = [r for r in out if r.get("age") is not None and r["age"] <= int(at)]

    aid = mp.get("area")
    if aid is not None:
        out = [r for r in out if r.get("area_id") == int(aid)]

    return out
