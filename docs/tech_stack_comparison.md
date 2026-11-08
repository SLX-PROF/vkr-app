# Обоснование технологического стека

| Задача | Варианты | Выбор и причина |
|---|---|---|
| Веб-приложение | Django / FastAPI / Flask | Django: ORM, миграции, формы, авторизация и admin в одном проекте. FastAPI удобен для API, Flask требует подбор дополнительных компонентов |
| База данных | PostgreSQL / MySQL / SQLite | PostgreSQL: транзакции, связи, jsonb; SQLite не соответствует условию проекта и не поддерживает используемый DISTINCT ON |
| Обращение к источникам | Requests + BeautifulSoup / Playwright / Selenium | Requests для HTTP/JSON ЕГРЮЛ; HTML-библиотека предусмотрена зависимостями; браузер не нужен текущему провайдеру. Playwright используется для проверки интерфейса |
| Интерфейс | Django templates / отдельное SPA | Серверные шаблоны и Bootstrap: меньше компонентов для поддержки, формы и сессии Django |
| PDF | ReportLab / WeasyPrint | ReportLab: локальные шрифты, переносы таблиц, без системного HTML-движка |

Сравнение качественное, привязано к задачам этой ИС; измеренные показатели производительности
разных фреймворков не заявляются. Python выбран по плану-заданию, Django и PostgreSQL — по ТЗ.

Официальная документация (проверена 08.11.2026):
- https://docs.djangoproject.com/en/5.2/topics/db/models/
- https://fastapi.tiangolo.com/
- https://flask.palletsprojects.com/en/stable/
- https://www.postgresql.org/docs/16/datatype-json.html
- https://www.postgresql.org/docs/16/ddl-constraints.html
- https://docs.reportlab.com/reportlab/userguide/
