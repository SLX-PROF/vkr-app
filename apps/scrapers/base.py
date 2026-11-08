"""Единый интерфейс источников данных и общая «вежливость» к ним.

Исключения внутри провайдера наружу не пробрасываются: fetch() всегда возвращает SourceResult.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger("scrapers")

CACHE_TTL = 24 * 3600  # результат по связке источник + ИНН хранится 24 часа
MIN_INTERVAL = 1.0  # не чаще одного запроса в секунду на домен

_last_request = {}
_lock = threading.Lock()


class SourceUnavailable(Exception):
    """Источник недоступен: CAPTCHA, нет ключа API, режим не реализован."""


@dataclass
class SourceResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""
    elapsed: float = 0.0
    status: str = "success"  # success | error | timeout | unavailable (как в SourceData.Status)


def throttle(domain: str) -> None:
    """Выдерживает паузу не менее MIN_INTERVAL между запросами к одному домену (потокобезопасно)."""
    with _lock:
        now = time.monotonic()
        slot = max(now, _last_request.get(domain, 0) + MIN_INTERVAL)
        _last_request[domain] = slot
    while (remaining := slot - time.monotonic()) > 0:
        time.sleep(remaining)


class BaseSource:
    cache_version = 1
    name = ""  # человекочитаемое имя («ЕГРЮЛ»), хранится в SourceData.source_name
    key = ""  # ключ настройки SOURCE_MODE_<KEY> и имя каталога фикстур в нижнем регистре
    domain = ""

    def __init__(self, mode=None, source_modes=None):
        self._mode = mode
        self.source_modes = source_modes or settings.SOURCE_MODES

    @property
    def mode(self):
        return getattr(self, "_mode", None) or settings.SOURCE_MODES[self.key]

    def fetch(self, query: str) -> SourceResult:
        """query — ИНН. Режим берётся из настройки SOURCE_MODES[key]."""
        mode = self.mode
        cache_key = f"source:{self.key}:v{self.cache_version}:{mode}:{query}"
        if mode != "mock":
            cached = cache.get(cache_key)
            if cached:
                log.info("source=%s inn=%s mode=%s status=cache", self.name, query, mode)
                return cached
        start = time.monotonic()
        try:
            result = SourceResult(ok=True, data=getattr(self, f"fetch_{mode}")(query))
        except SourceUnavailable as exc:
            result = SourceResult(ok=False, error=str(exc), status="unavailable")
        except requests.Timeout:
            error = f"Источник не ответил за {settings.SOURCE_TIMEOUT} с"
            result = SourceResult(ok=False, error=error, status="timeout")
        except requests.HTTPError as exc:
            restricted = exc.response is not None and exc.response.status_code in (401, 403, 410, 429)
            result = SourceResult(ok=False, error="Источник ограничил доступ" if restricted else str(exc),
                                  status="unavailable" if restricted else "error")
        except Exception as exc:  # noqa: BLE001 — по контракту ошибка источника не должна ломать проверку
            result = SourceResult(ok=False, error=f"{type(exc).__name__}: {exc}", status="error")
        result.elapsed = round(time.monotonic() - start, 3)
        if result.ok and mode != "mock":
            cache.set(cache_key, result, CACHE_TTL)
        log.info("source=%s inn=%s mode=%s status=%s elapsed=%.3f %s",
                 self.name, query, mode, result.status, result.elapsed, result.error)
        return result

    def fetch_mock(self, query: str) -> dict:
        path = settings.FIXTURES_DIR / self.key.lower() / f"{query}.json"
        if not path.exists():
            raise SourceUnavailable(f"Нет тестовых данных для ИНН {query}")
        return json.loads(path.read_text(encoding="utf-8"))

    def fetch_api(self, query: str) -> dict:
        raise SourceUnavailable(f"Источник «{self.name}»: режим api не реализован")

    def fetch_web(self, query: str) -> dict:
        raise SourceUnavailable(f"Источник «{self.name}»: режим web не реализован")

    def http(self, method: str, url: str, domain: str = "", **kwargs) -> requests.Response:
        """HTTP-запрос с таймаутом, честным User-Agent и ограничением частоты на домен."""
        throttle(domain or self.domain)
        headers = {"User-Agent": settings.SOURCE_USER_AGENT, **kwargs.pop("headers", {})}
        session = kwargs.pop("session", None)
        requester = session.request if session is not None else requests.request
        timeout = kwargs.pop("timeout", settings.SOURCE_TIMEOUT)
        response = requester(method, url, headers=headers, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
