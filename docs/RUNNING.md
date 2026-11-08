# Запуск и проверка приложения

## Windows
Из папки приложения в PowerShell (Python 3.11+ и работающая PostgreSQL либо Docker):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
docker compose up -d db
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Копируйте .env.example только при первом запуске: существующий .env не перезаписывать.
Вместо Docker можно указать параметры своего PostgreSQL в .env. Для текущей локальной проверки
используется отдельная БД на 127.0.0.1:55432; эта настройка не переносится в архив приложения.
Запуск на macOS/Linux приведён в README. Проверка Docker в этой среде не выполнялась.

## Демо и PDF
Демо-пользователи и пароли перечислены в README. `seed_demo` пересоздаёт восемь синтетических
контрагентов, их историю и документы; не используйте их идентификаторы для реальных записей.
В карточке нажмите «Скачать PDF». Для прежнего сеанса откройте «История проверок и отчёты».
Бухгалтер получает сводный отчёт, СБ/юристы и администратор — также факторы риска.
PDF строится по сохранённому сеансу без повторных внешних запросов.

## Проверки
```powershell
.\.venv\Scripts\python.exe -m pytest --cov=apps --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location).Path '.playwright'
.\.venv\Scripts\python.exe -m playwright install chromium --only-shell
.\.venv\Scripts\python.exe scripts\take_screenshots.py
```
Для scripts/browser_smoke.py запустите приложение на порту 8765 (или задайте BASE_URL).
Скрипт использует только демонстрационные учётные записи и проверяет загрузку PDF.

## Ограничения
Mock включён по умолчанию для всех источников. У ЕГРЮЛ реализованы api (DaData с ключом) и web;
остальные источники в api/web возвращают unavailable. Ключи не предоставлены.
Условия использования источников нужно проверить перед реальной эксплуатацией; CAPTCHA не обходится.
Сверка введённых полей не проверяет подпись, доверенность и действительность сделки.
Кеш и ограничение частоты рассчитаны на один процесс; для нескольких серверов нужен общий кеш.
Внешняя промышленная эксплуатация и внедрение в ООО «Валдэкс» не подтверждены.
