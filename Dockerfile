FROM python:3.12-slim AS gost-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake libssl-dev git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v3.0.5 --recurse-submodules --shallow-submodules https://github.com/gost-engine/engine.git /src/gost \
    && test "$(git -C /src/gost rev-parse HEAD)" = "09fdd535fae018815651f34af6462fc280c3002e" \
    && cmake -S /src/gost -B /src/gost/build -DCMAKE_BUILD_TYPE=Release -DOPENSSL_ROOT_DIR=/usr \
        -DOPENSSL_INCLUDE_DIR=/usr/include \
        -DOPENSSL_CRYPTO_LIBRARY=/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/libcrypto.so \
        -DOPENSSL_SSL_LIBRARY=/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/libssl.so \
        -DOPENSSL_ENGINES_DIR=/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/engines-3 \
    && cmake --build /src/gost/build --parallel 2

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings.prod
WORKDIR /app
COPY --from=gost-build /src/gost/build/bin/gost.so /usr/local/lib/gost.so
ENV SIGNATURE_OPENSSL_ENGINE=/usr/local/lib/gost.so
RUN apt-get update && apt-get install -y --no-install-recommends openssl poppler-utils tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
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
