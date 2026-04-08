"""Модуль словарей синонимов навыков, должностей и связанных технологий."""

import re
from typing import Any

from rapidfuzz import fuzz

# Синонимы технологий и навыков: ключ -> множество эквивалентных вариантов
SKILL_SYNONYMS: dict[str, set[str]] = {
    # Микросервисы
    "микросервисы": {"microservices", "micro-service", "micro service", "msa", "микросервисная архитектура"},
    "микро-сервисы": {"microservices", "micro-service", "micro service", "msa"},
    "microservices": {"микросервисы", "micro-service", "micro service", "msa"},
    "msa": {"микросервисы", "microservices", "микросервисная архитектура"},

    # Языки программирования
    "python": {"питон", "пайтон", "py"},
    "питон": {"python", "py"},
    "пайтон": {"python", "py"},
    "javascript": {"js", "ecmascript", "es6", "es2015"},
    "js": {"javascript", "ecmascript"},
    "typescript": {"ts"},
    "ts": {"typescript"},
    "java": {"джава"},
    "c#": {"csharp", "c sharp", "си шарп"},
    "csharp": {"c#", "c sharp"},
    "c++": {"cpp", "си плюс плюс"},
    "cpp": {"c++"},
    "golang": {"go", "go lang"},
    "go": {"golang"},

    # Базы данных
    "postgresql": {"postgres", "postgre sql", "постгрес", "pg"},
    "postgres": {"postgresql", "постгрес", "pg"},
    "mysql": {"my sql", "мускул"},
    "mongodb": {"mongo", "монго"},
    "mongo": {"mongodb"},
    "redis": {"редис"},
    "clickhouse": {"click house", "кликхаус"},
    "elasticsearch": {"elastic", "es", "эластик"},
    "elastic": {"elasticsearch"},
    "sql": {"structured query language", "скуэль"},
    "nosql": {"no sql", "non-relational", "нереляционные бд"},
    "oracle": {"oracle db", "оракл"},
    "mssql": {"ms sql", "sql server", "microsoft sql"},

    # Брокеры сообщений и очереди
    "kafka": {"apache kafka", "кафка"},
    "rabbitmq": {"rabbit mq", "rabbit", "рэббит"},
    "activemq": {"active mq"},

    # ERP и корпоративные системы
    "sap": {"сап"},
    "sap erp": {"sap", "сап erp", "сап ерп"},
    "1c": {"1с", "одинэс", "1c erp", "1с erp"},
    "1с": {"1c", "1c erp"},
    "bitrix": {"битрикс", "1c-bitrix", "1с-битрикс"},
    "bitrix24": {"битрикс24", "б24"},

    # Инструменты документирования и управления
    "confluence": {"конфлюенс"},
    "jira": {"джира"},
    "swagger": {"openapi", "open api"},
    "openapi": {"swagger", "open api"},
    "postman": {"постман"},

    # Методологии моделирования
    "bpmn": {"business process model"},
    "uml": {"unified modeling language"},
    "plantuml": {"plant uml"},
    "draw.io": {"drawio", "diagrams.net"},
    "miro": {"миро"},

    # DevOps и инфраструктура
    "kubernetes": {"k8s", "kube", "кубернетес", "кубер"},
    "k8s": {"kubernetes", "kube"},
    "docker": {"docker container", "контейнеризация", "докер"},
    "контейнеризация": {"docker", "containers"},
    "ci/cd": {"cicd", "ci cd", "continuous integration"},
    "cicd": {"ci/cd", "ci cd"},
    "jenkins": {"дженкинс"},
    "gitlab ci": {"gitlab-ci", "gitlab ci/cd"},
    "github actions": {"gh actions"},
    "terraform": {"терраформ"},
    "ansible": {"ансибл"},
    "grafana": {"графана"},
    "kibana": {"кибана"},
    "prometheus": {"прометеус"},

    # Фреймворки и библиотеки
    "react": {"reactjs", "react.js", "реакт"},
    "reactjs": {"react", "react.js"},
    "vue": {"vuejs", "vue.js", "вью"},
    "angular": {"ангуляр"},
    "node.js": {"nodejs", "node", "node js", "нода"},
    "nodejs": {"node.js", "node"},
    "spring": {"spring boot", "spring framework"},
    "django": {"джанго"},
    "fastapi": {"fast api"},
    "flask": {"фласк"},
    ".net": {"dotnet", "dot net", "дотнет"},
    "dotnet": {".net", "dot net"},

    # ML/AI
    "machine learning": {"ml", "машинное обучение"},
    "ml": {"machine learning", "машинное обучение"},
    "машинное обучение": {"machine learning", "ml"},
    "deep learning": {"dl", "глубокое обучение"},
    "neural network": {"нейросеть", "нейронная сеть", "nn"},
    "tensorflow": {"tf"},
    "pytorch": {"torch"},

    # API и интеграции
    "rest": {"rest api", "restful", "рест"},
    "rest api": {"rest", "restful api"},
    "grpc": {"g rpc"},
    "soap": {"соап"},
    "graphql": {"graph ql"},
    "websocket": {"ws", "вебсокет"},

    # Методологии разработки
    "agile": {"аджайл", "гибкая методология"},
    "scrum": {"скрам"},
    "kanban": {"канбан"},
    "waterfall": {"водопад", "каскадная модель"},

    # Системы контроля версий
    "git": {"git version control", "гит"},
    "github": {"гитхаб"},
    "gitlab": {"гитлаб"},
    "bitbucket": {"битбакет"},

    # Операционные системы
    "linux": {"unix", "gnu linux", "линукс"},
    "windows": {"виндовс", "win"},

    # Облачные платформы
    "aws": {"amazon web services", "amazon aws"},
    "azure": {"microsoft azure", "ms azure"},
    "gcp": {"google cloud", "google cloud platform"},

    # Тестирование
    "unit testing": {"юнит тесты", "модульное тестирование"},
    "integration testing": {"интеграционное тестирование"},
    "selenium": {"селениум"},
    "pytest": {"пайтест"},
    "junit": {"джунит"},

    # Data Engineering
    "airflow": {"apache airflow", "апач airflow"},
    "apache airflow": {"airflow"},
    "spark": {"apache spark", "pyspark", "спарк"},
    "apache spark": {"spark", "pyspark"},
    "pyspark": {"spark", "apache spark"},
    "dbt": {"data build tool", "dbt core"},
    "snowflake": {"snowflake db", "сноуфлейк"},
    "databricks": {"databricks platform", "датабрикс"},
    "kafka streams": {"kafka stream", "streams api"},
    "flink": {"apache flink", "флинк"},
    "apache flink": {"flink"},

    # ML/AI расширенно
    "huggingface": {"hugging face", "hf", "transformers"},
    "hugging face": {"huggingface", "transformers"},
    "langchain": {"lang chain"},
    "mlflow": {"ml flow", "млфлоу"},
    "kubeflow": {"kube flow", "kubeflow pipelines"},
    "onnx": {"open neural network exchange"},

    # AWS детально
    "lambda": {"aws lambda", "λ function", "serverless lambda"},
    "aws lambda": {"lambda"},
    "ec2": {"amazon ec2", "elastic compute"},
    "s3": {"amazon s3", "simple storage service"},
    "ecs": {"amazon ecs", "elastic container service"},
    "eks": {"amazon eks", "elastic kubernetes service"},
    "fargate": {"aws fargate"},
    "cloudwatch": {"amazon cloudwatch", "cw"},

    # Azure детально
    "aks": {"azure kubernetes service", "azure k8s"},
    "blob storage": {"azure blob", "azure storage blob"},
    "azure blob": {"blob storage"},

    # Fintech
    "pci dss": {"pci-dss", "payment card industry"},
    "swift": {"swift network", "swift messaging"},
    "iso 20022": {"iso20022", "xml financial"},
    "banking api": {"open banking", "банковское api"},

    # Mobile
    "flutter": {"flutter sdk", "флаттер"},
    "react native": {"react-native", "rn", "реакт натив"},
    "kotlin multiplatform": {"kmp", "kotlin mpp"},
    "swiftui": {"swift ui"},

    # Тестирование расширенно
    "allure": {"allure framework", "аллюр"},
    "testit": {"test it", "тестит"},
    "k6": {"k6.io", "grafana k6"},
    "locust": {"locust.io", "локуст"},
    "gatling": {"gatling tool", "гатлинг"},

    # Безопасность
    "oauth": {"oauth2", "o-auth", "open authorization"},
    "oauth2": {"oauth", "oidc"},
    "jwt": {"json web token", "j w t"},
    "keycloak": {"key cloak"},
    "vault": {"hashicorp vault", "hvault"},
    "sso": {"single sign-on", "single sign on"},
    "ldap": {"active directory ldap", "openldap"},
}

# Синонимы должностей: ключ -> множество эквивалентных вариантов
POSITION_SYNONYMS: dict[str, set[str]] = {
    # Аналитики
    "системный аналитик": {"system analyst", "systems analyst", "са", "сис аналитик"},
    "system analyst": {"системный аналитик", "systems analyst"},
    "systems analyst": {"системный аналитик", "system analyst"},
    "бизнес-аналитик": {"business analyst", "ba", "бизнес аналитик"},
    "business analyst": {"бизнес-аналитик", "ba"},
    "ba": {"business analyst", "бизнес-аналитик"},
    "продуктовый аналитик": {"product analyst", "аналитик продукта"},
    "data analyst": {"аналитик данных", "дата аналитик"},
    "аналитик данных": {"data analyst", "дата аналитик"},

    # Разработчики
    "разработчик": {"developer", "dev", "programmer", "девелопер"},
    "developer": {"разработчик", "dev", "programmer"},
    "программист": {"developer", "programmer", "разработчик"},
    "programmer": {"программист", "developer", "разработчик"},
    "backend разработчик": {"backend developer", "бэкенд разработчик", "back-end developer"},
    "backend developer": {"backend разработчик", "бэкенд разработчик"},
    "frontend разработчик": {"frontend developer", "фронтенд разработчик", "front-end developer"},
    "frontend developer": {"frontend разработчик", "фронтенд разработчик"},
    "fullstack разработчик": {"fullstack developer", "фуллстек разработчик", "full-stack developer"},
    "fullstack developer": {"fullstack разработчик", "full stack developer"},

    # Инженеры
    "инженер": {"engineer"},
    "engineer": {"инженер"},
    "software engineer": {"программный инженер", "инженер-программист"},
    "data engineer": {"инженер данных", "дата инженер", "de"},
    "инженер данных": {"data engineer", "дата инженер", "de"},

    # Архитекторы
    "архитектор": {"architect", "solution architect"},
    "architect": {"архитектор"},
    "solution architect": {"архитектор решений", "солюшн архитектор"},
    "системный архитектор": {"system architect", "systems architect"},

    # Менеджеры
    "менеджер проекта": {"project manager", "pm", "руководитель проекта", "проджект менеджер"},
    "project manager": {"менеджер проекта", "pm", "проджект"},
    "pm": {"project manager", "менеджер проекта"},
    "product manager": {"продакт менеджер", "менеджер продукта", "продакт"},
    "продакт менеджер": {"product manager", "менеджер продукта"},
    "product owner": {"владелец продукта", "po", "продакт оунер"},
    "po": {"product owner", "владелец продукта"},
    "team lead": {"тимлид", "руководитель команды", "тех лид"},
    "тимлид": {"team lead", "tech lead", "руководитель команды"},
    "tech lead": {"технический лидер", "тех лид", "тимлид"},

    # Тестировщики
    "тестировщик": {"tester", "qa", "qa engineer", "qa инженер"},
    "qa": {"тестировщик", "qa engineer", "quality assurance", "qa инженер"},
    "qa engineer": {"тестировщик", "qa", "инженер по тестированию"},
    "автотестировщик": {"automation qa", "qa automation", "автоматизатор тестирования"},
    "automation qa": {"автотестировщик", "qa automation"},

    # DevOps и инфраструктура
    "devops": {"dev ops", "sre", "девопс", "devops engineer"},
    "devops engineer": {"devops", "девопс инженер"},
    "sre": {"devops", "site reliability", "site reliability engineer"},
    "системный администратор": {"system administrator", "sysadmin", "сисадмин"},
    "sysadmin": {"системный администратор", "system administrator"},

    # Data Science
    "data scientist": {"дата сайентист", "специалист по данным", "ds"},
    "ds": {"data scientist", "дата сайентист"},
    "ml engineer": {"machine learning engineer", "инженер машинного обучения", "мл инженер"},
    "machine learning engineer": {"ml engineer", "мл инженер", "инженер машинного обучения"},

    # Дизайнеры
    "ux designer": {"ux дизайнер", "дизайнер интерфейсов"},
    "ui designer": {"ui дизайнер", "дизайнер интерфейсов"},
    "ux/ui designer": {"ux ui дизайнер", "ui ux дизайнер"},
    "product designer": {"продуктовый дизайнер", "продакт дизайнер"},

    # Data-роли
    "analytics engineer": {"аналитический инженер", "инженер аналитики"},
    "bi developer": {"bi разработчик", "разработчик bi", "business intelligence developer"},
    "dwh developer": {"разработчик dwh", "dwh engineer", "инженер хранилища данных"},

    # ML-роли
    "mlops engineer": {"ml ops engineer", "инженер mlops"},
    "ai engineer": {"инженер ии", "ai developer"},
    "research engineer": {"инженер-исследователь", "research scientist engineer"},

    # Platform / инфраструктура
    "platform engineer": {"инженер платформы", "platform developer"},
    "infrastructure engineer": {"инженер инфраструктуры", "инфраструктурный инженер"},
    "cloud engineer": {"облачный инженер", "инженер облачных решений"},

    # Security
    "security engineer": {"инженер информационной безопасности", "инженер иб"},
    "appsec": {"application security", "безопасность приложений"},
    "devsecops": {"dev sec ops", "security devops"},
    "penetration tester": {"pentester", "pentest", "тестировщик на проникновение"},
}

# Связанные технологии: набор навыков в резюме -> неявные навыки
# Ключ - кортеж из навыков (lowercase), значение - неявный навык
TECHNOLOGY_IMPLIES: dict[tuple[str, ...], set[str]] = {
    # Микросервисы
    ("docker", "kubernetes"): {"микросервисы", "microservices", "контейнеризация"},
    ("docker", "k8s"): {"микросервисы", "microservices", "контейнеризация"},
    ("kubernetes", "docker"): {"микросервисы", "microservices"},
    ("k8s", "docker"): {"микросервисы", "microservices"},
    ("rabbitmq", "redis"): {"микросервисы", "microservices", "распределенные системы"},
    ("kafka", "docker"): {"микросервисы", "microservices", "распределенные системы"},
    ("kafka",): {"распределенные системы", "очереди сообщений", "event-driven"},
    ("rabbitmq",): {"очереди сообщений", "распределенные системы"},
    ("grpc",): {"микросервисы", "api"},
    ("api gateway",): {"микросервисы", "api"},

    # API и интеграции
    ("rest api",): {"api", "интеграции", "http"},
    ("rest",): {"api", "http"},
    ("soap",): {"api", "интеграции", "xml"},
    ("graphql",): {"api"},
    ("swagger",): {"api", "документация api"},
    ("openapi",): {"api", "документация api"},
    ("postman",): {"api", "тестирование api"},

    # Базы данных
    ("postgresql",): {"sql", "базы данных", "реляционные бд"},
    ("postgres",): {"sql", "базы данных", "реляционные бд"},
    ("mysql",): {"sql", "базы данных", "реляционные бд"},
    ("oracle",): {"sql", "базы данных", "реляционные бд"},
    ("mssql",): {"sql", "базы данных", "реляционные бд"},
    ("mongodb",): {"nosql", "базы данных"},
    ("redis",): {"nosql", "кэширование", "базы данных"},
    ("elasticsearch",): {"поиск", "nosql", "базы данных"},
    ("clickhouse",): {"аналитика", "olap", "базы данных"},

    # DevOps
    ("jenkins",): {"ci/cd", "автоматизация"},
    ("gitlab ci",): {"ci/cd", "автоматизация"},
    ("github actions",): {"ci/cd", "автоматизация"},
    ("terraform",): {"infrastructure as code", "iac", "облака"},
    ("ansible",): {"автоматизация", "configuration management"},
    ("grafana", "prometheus"): {"мониторинг", "observability"},
    ("grafana",): {"мониторинг", "визуализация"},
    ("kibana",): {"мониторинг", "логирование", "elk"},
    ("prometheus",): {"мониторинг", "метрики"},

    # Моделирование и документация
    ("bpmn",): {"моделирование процессов", "бизнес-анализ"},
    ("uml",): {"моделирование", "проектирование"},
    ("confluence",): {"документация", "управление знаниями"},
    ("jira",): {"управление задачами", "agile"},

    # Методологии
    ("scrum",): {"agile"},
    ("kanban",): {"agile"},
    ("agile",): {"гибкая методология"},

    # ERP системы
    ("sap",): {"erp", "корпоративные системы"},
    ("sap erp",): {"erp", "корпоративные системы", "sap"},
    ("1c",): {"erp", "корпоративные системы", "автоматизация учета"},
    ("1с",): {"erp", "корпоративные системы", "автоматизация учета"},

    # Облака
    ("aws",): {"облачные технологии", "cloud"},
    ("azure",): {"облачные технологии", "cloud"},
    ("gcp",): {"облачные технологии", "cloud"},

    # Фреймворки -> языки
    ("django",): {"python", "backend"},
    ("fastapi",): {"python", "backend", "api"},
    ("flask",): {"python", "backend"},
    ("spring",): {"java", "backend"},
    ("spring boot",): {"java", "backend", "микросервисы"},
    (".net",): {"c#", "backend"},
    ("react",): {"javascript", "frontend"},
    ("vue",): {"javascript", "frontend"},
    ("angular",): {"typescript", "frontend"},
    ("node.js",): {"javascript", "backend"},

    # Data Engineering и DWH
    ("dbt", "snowflake"): {"data engineering", "etl", "dwh", "sql"},
    ("dbt",): {"data engineering", "etl", "sql", "analytics"},
    ("snowflake",): {"dwh", "cloud", "sql", "data warehouse"},
    ("databricks",): {"spark", "data engineering", "cloud", "ml"},
    ("airflow",): {"data engineering", "orchestration", "etl", "python"},
    ("apache airflow",): {"data engineering", "orchestration", "etl"},
    ("spark",): {"data engineering", "big data", "python", "scala"},
    ("apache spark",): {"data engineering", "big data"},
    ("flink",): {"stream processing", "data engineering", "big data"},
    ("kafka streams",): {"kafka", "stream processing", "data engineering"},

    # ML/AI
    ("langchain",): {"llm", "ai", "python", "rag"},
    ("huggingface",): {"ml", "python", "nlp", "transformers"},
    ("hugging face",): {"ml", "python", "nlp"},
    ("mlflow",): {"mlops", "ml", "experiment tracking"},
    ("kubeflow",): {"mlops", "kubernetes", "ml", "pipelines"},
    ("onnx",): {"ml", "deployment", "inference"},
    ("pytorch",): {"ml", "deep learning", "python"},
    ("tensorflow",): {"ml", "deep learning", "python"},

    # Mobile
    ("flutter",): {"mobile", "dart", "кроссплатформенная разработка"},
    ("react native",): {"mobile", "javascript", "react"},
    ("kotlin multiplatform",): {"kotlin", "mobile", "кроссплатформенная разработка"},
    ("swiftui",): {"mobile", "swift", "ios"},

    # Облако AWS/Azure
    ("lambda",): {"serverless", "aws", "cloud"},
    ("aws lambda",): {"serverless", "aws", "cloud"},
    ("ec2",): {"aws", "cloud", "compute"},
    ("s3",): {"aws", "cloud", "storage"},
    ("eks",): {"kubernetes", "aws", "cloud"},
    ("aks",): {"kubernetes", "azure", "cloud"},
    ("blob storage",): {"azure", "cloud", "storage"},

    # Fintech / security tooling
    ("pci dss",): {"fintech", "compliance", "security"},
    ("iso 20022",): {"fintech", "banking", "payments"},
    ("oauth",): {"security", "api", "authentication"},
    ("jwt",): {"security", "api", "authentication"},
    ("keycloak",): {"sso", "identity", "security"},
    ("vault",): {"secrets", "security", "devops"},

    # Тестирование нагрузки
    ("k6",): {"performance testing", "load testing"},
    ("locust",): {"performance testing", "load testing", "python"},
    ("gatling",): {"performance testing", "load testing"},
    ("allure",): {"тестирование", "отчётность", "qa"},
}


def _normalize(s: str) -> str:
    return s.lower().strip()


def _resolve_synonyms(
    value: str, synonyms_dict: dict[str, set[str]]
) -> set[str]:
    """Возвращает множество всех синонимов для указанного значения."""
    norm = _normalize(value)
    result: set[str] = {norm}
    for key, synonyms in synonyms_dict.items():
        if norm == _normalize(key) or norm in {_normalize(s) for s in synonyms}:
            result.add(_normalize(key))
            result.update(_normalize(s) for s in synonyms)
    return result


def expand_skill(skill: str) -> set[str]:
    """
    Расширяет навык всеми известными синонимами.
    Возвращает множество строк в lowercase.
    """
    return _resolve_synonyms(skill, SKILL_SYNONYMS)


def expand_position(position: str) -> set[str]:
    """
    Расширяет должность всеми известными синонимами.
    Возвращает множество строк в lowercase.
    """
    return _resolve_synonyms(position, POSITION_SYNONYMS)


def infer_implicit_skills(skills: list[str]) -> set[str]:
    """
    Определяет неявные навыки на основе связанных технологий.
    Например, docker + kubernetes подразумевают опыт с микросервисами.
    Возвращает множество дополнительных навыков в lowercase.
    """
    norm_skills = {_normalize(s) for s in skills if s}
    inferred: set[str] = set()
    for (tech_tuple, implied) in TECHNOLOGY_IMPLIES.items():
        norm_tuple = tuple(_normalize(t) for t in tech_tuple)
        if all(t in norm_skills for t in norm_tuple):
            inferred.update(_normalize(i) for i in implied)
    return inferred


def expand_skills_for_matching(skills: list[str]) -> set[str]:
    """
    Расширяет список навыков синонимами и неявными навыками.
    Используется для сопоставления требований и резюме.
    """
    result: set[str] = set()
    for skill in skills:
        if skill:
            result.update(expand_skill(skill))
    result.update(infer_implicit_skills(skills))
    return result


# Список ключевых слов для извлечения из текста (lowercase)
EXTRACTABLE_SKILLS: set[str] = {
    # Языки программирования
    "python", "java", "javascript", "typescript", "c#", "c++", "go", "golang",
    "ruby", "php", "scala", "kotlin", "swift", "rust", "r", "perl", "lua",
    "clojure", "erlang", "elixir", "haskell", "f#", "groovy", "dart",
    # Базы данных
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "clickhouse", "oracle", "mssql", "sql server", "cassandra", "neo4j",
    "dynamodb", "couchbase", "mariadb", "sqlite", "firebird", "cockroachdb",
    "timescaledb", "influxdb", "greenplum", "vertica", "teradata",
    # Брокеры сообщений
    "kafka", "rabbitmq", "activemq", "nats", "zeromq", "pulsar", "amazon sqs",
    # Data Engineering
    "airflow", "apache airflow", "spark", "apache spark", "hadoop", "hive",
    "presto", "trino", "flink", "apache flink", "dbt", "dagster", "prefect",
    "luigi", "oozie", "nifi", "apache nifi", "beam", "apache beam",
    # Data Warehouses & Lakes
    "snowflake", "databricks", "bigquery", "redshift", "synapse", "data lake",
    "delta lake", "iceberg", "hudi", "parquet", "avro",
    # ML/AI platforms
    "mlflow", "kubeflow", "sagemaker", "vertex ai", "mlops", "feature store",
    "weights and biases", "wandb", "neptune", "comet",
    # DevOps и инфраструктура
    "docker", "kubernetes", "k8s", "jenkins", "gitlab", "github", "terraform",
    "ansible", "grafana", "prometheus", "kibana", "nginx", "apache",
    "pulumi", "cloudformation", "helm", "argocd", "spinnaker", "tekton",
    "vault", "consul", "istio", "envoy", "linkerd",
    # Фреймворки
    "react", "vue", "angular", "django", "flask", "fastapi", "spring",
    "spring boot", "node.js", "express", ".net", "rails",
    # API и протоколы
    "rest api", "rest", "grpc", "soap", "graphql", "websocket",
    # ERP и корпоративные системы
    "sap", "sap erp", "1c", "1с", "bitrix", "bitrix24",
    # Инструменты
    "jira", "confluence", "swagger", "openapi", "postman", "git",
    # Моделирование
    "bpmn", "uml", "plantuml", "draw.io", "miro",
    # Методологии
    "agile", "scrum", "kanban",
    # Облака
    "aws", "azure", "gcp", "google cloud",
    # ML/AI
    "tensorflow", "pytorch", "keras", "scikit-learn", "pandas", "numpy",
    # Мониторинг
    "elk", "datadog", "splunk", "zabbix",
    # Тестирование
    "selenium", "pytest", "junit", "testng", "cypress", "allure", "testit",
    "k6", "locust", "gatling",
    # ML/AI доп.
    "huggingface", "hugging face", "langchain", "onnx",
    # Mobile
    "flutter", "react native", "kotlin multiplatform", "swiftui",
    # Fintech / compliance
    "pci dss", "swift", "iso 20022", "banking api",
    # Security
    "oauth", "oauth2", "jwt", "keycloak", "sso", "ldap",
    # AWS / Azure сервисы
    "lambda", "aws lambda", "ec2", "s3", "ecs", "eks", "fargate", "cloudwatch",
    "aks", "blob storage", "azure blob",
    "kafka streams",
}


def extract_skills_from_text(text: str) -> set[str]:
    """
    Извлекает известные навыки из произвольного текста (описание опыта, "о себе").
    Возвращает множество найденных навыков в lowercase.
    """
    if not text or not isinstance(text, str):
        return set()

    text_lower = text.lower()
    found: set[str] = set()

    for skill in EXTRACTABLE_SKILLS:
        skill_variants = [skill]
        if skill in SKILL_SYNONYMS:
            skill_variants.extend(SKILL_SYNONYMS[skill])

        for variant in skill_variants:
            variant_lower = variant.lower()
            if len(variant_lower) < 2:
                continue
            if variant_lower in text_lower:
                if len(variant_lower) <= 3:
                    pattern = r'\b' + re.escape(variant_lower) + r'\b'
                    if re.search(pattern, text_lower):
                        found.add(skill)
                        break
                else:
                    found.add(skill)
                    break

    return found


def extract_skills_from_resume(resume: dict[str, Any]) -> set[str]:
    """
    Извлекает навыки из всех текстовых полей резюме:
    - skills (теги)
    - about (о себе)
    - work_experience[].description (описание опыта)
    """
    all_skills: set[str] = set()

    tags = resume.get("skills") or []
    if isinstance(tags, list):
        for tag in tags:
            if tag and isinstance(tag, str):
                all_skills.add(_normalize(tag))

    about = resume.get("about")
    if about and isinstance(about, str):
        all_skills.update(extract_skills_from_text(about))

    work_exp = resume.get("work_experience") or []
    if isinstance(work_exp, list):
        for job in work_exp:
            if not isinstance(job, dict):
                continue
            desc = job.get("description")
            if desc and isinstance(desc, str):
                all_skills.update(extract_skills_from_text(desc))

    return all_skills


def _is_known_skill(wanted_norm: str) -> bool:
    if wanted_norm in {_normalize(k) for k in SKILL_SYNONYMS}:
        return True
    return any(
        wanted_norm in {_normalize(s) for s in syns}
        for syns in SKILL_SYNONYMS.values()
    )


def fuzzy_skill_match(wanted: str, have_skills: set[str], threshold: int = 75) -> bool:
    """
    Проверяет, есть ли навык wanted среди have_skills с учётом:
    1. Точного совпадения (с синонимами)
    2. Вхождения подстроки
    3. Нечёткого сравнения (rapidfuzz) для навыков вне словаря

    threshold: минимальный token_set_ratio (0–100) для нечёткого совпадения.
    """
    wanted_norm = _normalize(wanted)
    if not wanted_norm:
        return False

    wanted_expanded = expand_skill(wanted)
    if wanted_expanded & have_skills:
        return True

    for have in have_skills:
        if wanted_norm in have or have in wanted_norm:
            return True

    is_known = _is_known_skill(wanted_norm)
    if not is_known and len(wanted_norm) >= 3:
        for have in have_skills:
            if len(have) >= 3:
                if fuzz.token_set_ratio(wanted_norm, have) >= threshold:
                    return True
                if fuzz.partial_ratio(wanted_norm, have) >= 85:
                    return True

    return False


def get_resume_text_blob(resume: dict[str, Any]) -> str:
    """
    Собирает весь текст из резюме для поиска неизвестных навыков.
    """
    parts: list[str] = []

    title = resume.get("title")
    if title and isinstance(title, str):
        parts.append(title)

    tags = resume.get("skills") or []
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags if t)

    about = resume.get("about")
    if about and isinstance(about, str):
        parts.append(about)

    work_exp = resume.get("work_experience") or []
    if isinstance(work_exp, list):
        for job in work_exp:
            if not isinstance(job, dict):
                continue
            pos = job.get("position")
            if pos and isinstance(pos, str):
                parts.append(pos)
            desc = job.get("description")
            if desc and isinstance(desc, str):
                parts.append(desc)

    return " ".join(parts).lower()


def skill_in_text(skill: str, text_blob: str) -> bool:
    """
    Проверяет наличие навыка в тексте (точное или частичное вхождение).
    Для коротких навыков (<=3 символа) требует границы слова.
    """
    skill_norm = _normalize(skill)
    if not skill_norm or not text_blob:
        return False

    skill_variants = [skill_norm]
    skill_variants.extend(_normalize(s) for s in expand_skill(skill_norm))

    for variant in skill_variants:
        if len(variant) <= 3:
            pattern = r'\b' + re.escape(variant) + r'\b'
            if re.search(pattern, text_blob):
                return True
        elif variant in text_blob:
            return True

    return False
