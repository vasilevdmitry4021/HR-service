# EStaff_Vacancy_API

**Дата создания:** (обновлено 15.08.2025)

Интерфейс для работы с вакансиями в e-staff.

Вызовы осуществляются по адресу `http(s)://[serverName:port]/api/vacancy/[methodName]` через протокол HTTP, метод **POST**, с параметрами в JSON в теле запроса.

---

## Метод `find`

Метод интерфейса, который мне необходим.

Позволяет найти вакансию по заданным параметрам.

### Формат запроса

```http
POST /api/vacancy/find HTTP/1.1
Authorization: Bearer [token]
Content-Type: application/json
```

```json
{
  "filter": {
    "min_start_date": "2025-08-15T07:53:32.595Z",
    "max_start_date": "2025-08-15T07:53:32.595Z",
    "state_id": "string",
    "user_id": 0
  },
  "field_names": ["name", "start_date", "user"]
}
```

\*2 — обязательно наличие как минимум любого из этих полей.

### Параметры запроса

| Параметр         | Описание                                               |
| ---------------- | ------------------------------------------------------ |
| `min_start_date` | Начиная с даты открытия \*2                            |
| `max_start_date` | Заканчивая датой открытия \*2                          |
| `state_id`       | Текущий статус (ID из справочника vacancy_states) \*2  |
| `user_id`        | Внутренний идентификатор пользователя \*2              |
| `field_names`    | Идентификаторы возвращаемых полей (необязательное поле) |

### Формат ответа

```http
HTTP/1.1 200 OK
Server: SP-XML
Content-Type: application/json
```

```json
{
  "vacancies": [
    {
      "id": 0,
      "name": "string",
      "start_date": "2025-08-15T07:53:32.595Z",
      "user": {
        "id": 0,
        "person": {
          "id": 0,
          "lastname": "string",
          "firstname": "string",
          "middlename": "string",
          "code": "string",
          "eid": "string"
        }
      }
    }
  ],
  "success": true
}
```

### Параметры ответа

| Параметр     | Описание                          |
| ------------ | --------------------------------- |
| `id`         | Внутренний идентификатор вакансии |
| `name`       | Наименование                      |
| `start_date` | Дата открытия                     |
| `user`       | Информация о пользователе         |

---

## Метод `get`

Позволяет получить информацию о вакансии.

### Формат запроса

```http
POST /api/vacancy/get HTTP/1.1
Authorization: Bearer [token]
Content-Type: application/json
```

```json
{
  "vacancy": {
    "id": 0
  },
  "field_names": [
    "name",
    "start_date",
    "work_start_date",
    "division_id",
    "division_name",
    "division_code",
    "position_id",
    "position_name",
    "position_code"
  ]
}
```

### Параметры запроса

| Параметр      | Описание                                                 |
| ------------- | -------------------------------------------------------- |
| `id`          | Идентификатор вакансии                                   |
| `field_names` | Идентификаторы возвращаемых полей (необязательное поле) |

### Формат ответа

```http
HTTP/1.1 200 OK
Server: SP-XML
Content-Type: application/json
```

```json
{
  "vacancy": {
    "id": 0,
    "name": "string",
    "code": "string",
    "state_id": "string"
  },
  "success": true
}
```

### Параметры ответа

| Параметр   | Описание                                                |
| ---------- | ------------------------------------------------------- |
| `id`       | Идентификатор вакансии (ID из внутреннего справочника) |
| `name`     | Наименование                                            |
| `code`     | Номер                                                   |
| `state_id` | Текущий статус (ID из справочника vacancy_states)       |

---

# EStaff_Candidate_API

**Дата создания:** (обновлено 27.01.2026)

**Контекст в источнике (навигация):** Действующий, Страницы, Таблицы, Настройки, Экспорт в PDF

Интерфейс для работы с кандидатами в e-staff.

**Интерфейс**

Вызовы осуществляются по адресу `http(s)://[serverName:port]/api/candidate/[methodName]` через протокол HTTP, метод **POST**, с параметрами в JSON в теле запроса.

---

## Метод `add`

Позволяет добавить кандидата в базу.

### Формат запроса

```http
POST /api/candidate/add HTTP/1.1
Authorization: Bearer [token]
Content-Type: application/json
```

```json
{
  "candidate": {
    "lastname": "string",
    "firstname": "string",
    "middlename": "string",
    "birth_date": "2025-08-15T12:30:47.791Z",
    "gender_id": 0,
    "country_id": "string",
    "location_id": "string",
    "city_name": "string",
    "metro_station_id": "string",
    "time_zone": 0,
    "job_search_location_id": ["string"],
    "mobile_phone": "string",
    "home_phone": "string",
    "email": "string",
    "email2": "string",
    "skype": "string",
    "desired_position_name": "string",
    "exp_years": 0,
    "salary": 0,
    "educ_type_id": 0,
    "prev_educations": [
      {
        "end_year": 0,
        "org_name": "string",
        "department_name": "string",
        "speciality_name": "string"
      }
    ],
    "prev_jobs": [
      {
        "start_year": 0,
        "start_month": 0,
        "end_year": 0,
        "end_month": 0,
        "org_name": "string",
        "org_location_name": "string",
        "position_name": "string",
        "comment": "string"
      }
    ],
    "marital_status_id": 0,
    "children_num": 0,
    "skills": [
      {
        "type_id": "string",
        "level_id": 0,
        "comment": "string"
      }
    ],
    "passport": {
      "number": "string",
      "issue_date": "2025-08-15T12:30:47.791Z",
      "issue_org": "string"
    },
    "csd": {},
    "attachments": [
      {
        "type_id": "string",
        "content_type": "string",
        "html_data": "string",
        "file_name": "string",
        "base64_data": "string"
      }
    ],
    "entrance_type_id": "string",
    "source_id": "string",
    "inet_uid": "string",
    "agency_org_id": 0,
    "agency_end_date": "2025-08-15T12:30:47.791Z",
    "state_id": "string",
    "user_id": 0,
    "user_login": "string",
    "group_id": 0
  },
  "vacancy": {
    "id": 0
  }
}
```

\*1 — обязательное поле.

\*2 — обязательно наличие как минимум любого из этих полей.

### Параметры объекта `candidate`

| Параметр                 | Описание                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------ |
| `lastname`               | Фамилия                                                                                          |
| `firstname`              | Имя \*1                                                                                          |
| `middlename`             | Отчество                                                                                         |
| `birth_date`             | Дата рождения                                                                                    |
| `gender_id`              | Пол (0 – муж., 1 – жен.)                                                                         |
| `country_id`             | Страна (ID из справочника countries)                                                             |
| `location_id`            | Регион (ID из справочника locations; игнорируется при использовании city_name)                   |
| `city_name`              | Город (формирует location_id при совпадении с регионом внутреннего справочника)                  |
| `metro_station_id`       | Станция метро (ID из справочника metro_stations)                                                |
| `time_zone`              | Часовой пояс                                                                                     |
| `job_search_location_id` | Регион поиска работы (ID из справочника locations)                                               |
| `mobile_phone`           | Моб. телефон \*2                                                                                 |
| `home_phone`             | Альт. телефон                                                                                    |
| `email`                  | E-Mail \*2                                                                                       |
| `email2`                 | E-Mail 2                                                                                         |
| `skype`                  | Skype                                                                                            |
| `desired_position_name`  | Предполагаемая должность                                                                         |
| `exp_years`              | Стаж                                                                                             |
| `salary`                 | Уровень з/п                                                                                      |
| `educ_type_id`           | Образование (1 - среднее, 2 - среднее профессиональное, 3 - неоконченное высшее, 4 - высшее)     |
| `marital_status_id`      | Идентификатор семейного положения (1 – не женат (не замужем), 2 – женат (замужем), 3 – разведен(а), 4 – незарегистрированный брак) |
| `children_num`           | Дети                                                                                             |
| `entrance_type_id`       | Способ занесения (ID из справочника candidate_entrance_types)                                    |
| `source_id`              | Источник поступления (ID из справочника candidate_sources)                                       |
| `inet_uid`               | Идентификатор резюме из внешней системы                                                          |
| `agency_org_id`          | Закреплен за агентством (Внутренний идентификатор организации)                                   |
| `agency_end_date`        | Закреплен до                                                                                     |
| `state_id`               | Статус кандидата (ID из справочника candidate_states)                                            |
| `user_id`                | Внутренний идентификатор пользователя                                                            |
| `user_login`             | Логин пользователя (игнорируется при использовании user_id)                                      |
| `group_id`               | Внутренний идентификатор группы                                                                  |

### Информация о блоке Образование (`prev_educations`)

| Параметр          | Описание             |
| ----------------- | -------------------- |
| `end_year`        | Год окончания\*1     |
| `org_name`        | Учебное заведение\*1 |
| `department_name` | Специальность        |
| `speciality_name` | Специальность        |

### Информация о блоке Места работы (`prev_jobs`)

| Параметр        | Описание                         |
| --------------- | -------------------------------- |
| `start_year`    | Год начала\*1                    |
| `start_month`   | Месяц начала\*1                  |
| `end_year`      | Год окончания                    |
| `end_month`     | Месяц окончания                  |
| `org_name`      | Компания\*1                      |
| `position_name` | Должность\*1                     |
| `comment`       | Обязанности, основные достижения |

### Информация о блоке Навыки (`skills`)

| Параметр   | Описание                                 |
| ---------- | ---------------------------------------- |
| `type_id`  | Навык (ID из справочника skill_types)\*1 |
| `level_id` | Уровень                                  |
| `comment`  | Примечание                               |

### Информация о блоке Паспорт (`passport`)

| Параметр     | Описание               |
| ------------ | ---------------------- |
| `number`     | Серия и номер паспорта |
| `issue_date` | Дата выдачи            |
| `issue_org`  | Кем выдан              |

### Информация о блоке Доп. поля (`csd`)

| Параметр       | Описание                |
| -------------- | ----------------------- |
| `cs_elem_xxxx` | Идентификатор доп. поля |

### Информация о блоке Приложения (`attachments`)

| Параметр       | Описание                                                 |
| -------------- | -------------------------------------------------------- |
| `type_id`      | Тип приложения (ID из справочника card_attachment_types) |
| `content_type` | Тип приложения (text/html)                               |
| `html_data`    | Данные приложения в формате HTML                         |
| `file_name`    | Название файла                                           |
| `base64_data`  | Бинарные данные закодированные в base64                  |

### Информация о блоке Вакансия (`vacancy`)\*1

| Параметр | Описание                          |
| -------- | --------------------------------- |
| `id`     | Внутренний идентификатор вакансии |

### Формат ответа

```http
HTTP/1.1 200 OK
Server: SP-XML
Content-Type: application/json
```

```json
{
  "candidate": {
    "id": 0
  },
  "success": true
}
```

### Параметры ответа

| Параметр | Описание                             |
| -------- | ------------------------------------ |
| `id`     | Идентификатор добавленного кандидата |

---

## Метод `get_voc`

Позволяет получить содержимое справочника по идентификатору.

### Формат запроса

```http
POST /api/base/get_voc HTTP/1.1
Authorization: Bearer [token]
Content-Type: application/json
```

```json
{
  "voc": {
    "id": "string"
  }
}
```

### Параметры запроса

| Параметр | Описание                    |
| -------- | --------------------------- |
| `id`     | Идентификатор справочника   |

### Формат ответа

```http
HTTP/1.1 200 OK
Server: SP-XML
Content-Type: application/json
```

```json
{
  "voc_name": [
    {
      "id": 0,
      "name": "string"
    }
  ],
  "success": true
}
```

### Параметры ответа

| Параметр | Описание                 |
| -------- | ------------------------ |
| `id`     | Идентификатор элемента   |
| `name`   | Наименование             |

---

# EStaff_User_API

Вызовы осуществляются по адресу `http(s)://[serverName:port]/api/user/[methodName]` через протокол HTTP, метод **POST**, с параметрами в JSON в теле запроса.

При генерации ключа доступа потребуется активация специального разрешения «Управление пользователями».

## Метод `get`

Позволяет получить информацию о пользователе по его логину или идентификатору.

### Формат запроса

```http
POST /api/user/get HTTP/1.1
Authorization: Bearer [token]
Content-Type: application/json
```

```json
{
  "user": {
    "id": 0,
    "login": "string"
  }
}
```

\*2 — обязательно наличие любого из этих полей.

### Параметры запроса

| Параметр | Описание                        |
| -------- | ------------------------------- |
| `login`  | Логин пользователя \*2          |
| `id`     | Идентификатор пользователя \*2  |

### Формат ответа

```http
HTTP/1.1 200 OK
Server: SP-XML
Content-Type: application/json
```

```json
{
  "user": {
    "id": 0,
    "login": "string",
    "is_active": true,
    "lastname": "string",
    "firstname": "string",
    "middlename": "string",
    "access_role_id": "string",
    "main_group_id": 0,
    "is_recruiter": true,
    "is_hiring_manager": false,
    "person_id": 0,
    "comment": "string"
  },
  "success": true
}
```

### Параметры ответа

| Параметр           | Описание                                                   |
| ------------------ | ---------------------------------------------------------- |
| `id`               | Идентификатор пользователя                                 |
| `login`            | Логин пользователя                                         |
| `is_active`        | Разрешен доступ в систему                                  |
| `lastname`         | Фамилия                                                    |
| `firstname`        | Имя                                                        |
| `middlename`       | Отчество                                                   |
| `access_role_id`   | Идентификатор уровня доступа (ID из справочника access_roles) |
| `main_group_id`    | Идентификатор группы                                       |
| `is_recruiter`      | Роль Рекрутер                                               |
| `is_hiring_manager` | Роль Нанимающий менеджер                                    |
| `is_active`         | Разрешен доступ в систему                                   |
| `person_id`         | Идентификатор сотрудника                                    |
| `comment`           | Комментарий                                                 |
