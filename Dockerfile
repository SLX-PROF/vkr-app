FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings.prod
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY manage.py ./
COPY apps/ apps/
COPY config/ config/
COPY static/ static/
COPY templates/ templates/
COPY tests/fixtures/ tests/fixtures/
RUN useradd --uid 10001 --create-home appuser && mkdir -p logs staticfiles media && chown -R appuser:appuser /app
USER appuser
RUN DJANGO_SECRET_KEY=static-build-only python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "90", "--access-logfile", "-", "--error-logfile", "-"]
