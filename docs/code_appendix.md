# Модули для приложения к ВКР

- apps/contractors/models.py и apps/documents/models.py — предметная модель.
- apps/contractors/migrations/0001–0005 — создание и развитие схемы БД.
- apps/contractors/services.py — параллельная проверка, транзакция, сохранение результатов.
- apps/scrapers/base.py — контракт источника, кеш, таймауты и ограничения частоты.
- apps/scrapers/egrul.py — ЕГРЮЛ в режимах mock/api/web, поиск по ИНН и ОГРН.
- apps/reports/scoring.py — правила и границы оценки.
- apps/documents/verification.py — сравнение ФИО, дат и реквизитов.
- apps/reports/pdf.py и views.py — генерация и выдача PDF с контролем прав.
- apps/core/roles.py — разграничение доступа.
- tests/test_final_workflow.py — интеграционные сценарии и проверки исправленных ошибок.

Включать только необходимые листинги; не включать .env, пароли, журналы с реальными данными,
виртуальную среду, сторонние библиотеки или двоичные файлы шрифтов.
