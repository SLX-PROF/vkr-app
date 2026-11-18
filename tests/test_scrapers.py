import json
import time

import pytest
import requests
from django.core.cache import cache
from django.test import RequestFactory

from apps.core.ratelimit import rate_limit
from apps.core.validators import is_valid_inn, is_valid_ogrn
from apps.scrapers import base
from apps.scrapers.base import BaseSource, SourceResult
from apps.scrapers.egrul import EgrulSource
from apps.scrapers.sources import ALL_SOURCES

FIXTURES = json.loads(open("tests/fixtures/demo_contractors.json", encoding="utf-8").read())
CLEAN_INN = FIXTURES[0]["inn"]


@pytest.fixture(autouse=True)
def _clean(settings, monkeypatch):
    cache.clear()
    base._last_request.clear()
    monkeypatch.setattr(base, "MIN_INTERVAL", 0)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def fake_requests(monkeypatch, *payloads):
    """Подменяет requests.request: отдаёт payloads по очереди, запоминает вызовы."""
    calls = []
    queue = list(payloads)

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)

    monkeypatch.setattr(requests, "request", fake)
    return calls


# --- фикстуры -------------------------------------------------------------

def test_eight_synthetic_contractors():
    assert len(FIXTURES) == 8
    assert {f["expected_status"] for f in FIXTURES} == {"safe", "risky", "dangerous"}


@pytest.mark.parametrize("item", FIXTURES, ids=lambda f: f["inn"])
def test_fixture_inn_valid_but_not_real(item):
    egrul = json.loads(open(f"tests/fixtures/egrul/{item['inn']}.json", encoding="utf-8").read())
    assert is_valid_inn(item["inn"]) and is_valid_ogrn(egrul["ogrn"])
    # Регион «00» не существует: реальной организации с таким ИНН/ОГРН быть не может
    assert item["inn"][:2] == "00" and egrul["ogrn"][3:5] == "00"


@pytest.mark.parametrize("source_cls", ALL_SOURCES, ids=lambda c: c.key)
@pytest.mark.parametrize("item", FIXTURES, ids=lambda f: f["inn"])
def test_mock_mode_returns_fixture(source_cls, item):
    result = source_cls().fetch(item["inn"])
    assert result.ok and result.status == "success" and result.data


def test_clean_and_liquidated_differ():
    assert EgrulSource().fetch(FIXTURES[0]["inn"]).data["status"] == "active"
    assert EgrulSource().fetch(FIXTURES[1]["inn"]).data["status"] == "liquidated"


# --- контракт fetch -------------------------------------------------------

def test_unknown_inn_is_unavailable_not_exception():
    result = EgrulSource().fetch("0000099999")
    assert isinstance(result, SourceResult) and not result.ok and result.status == "unavailable"


def test_exception_inside_provider_becomes_error_result():
    class Broken(BaseSource):
        key = "EGRUL"

        def fetch_mock(self, query):
            raise ValueError("boom")

    result = Broken().fetch("1")
    assert not result.ok and result.status == "error" and "boom" in result.error


def test_timeout_status(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    fake_requests(monkeypatch, requests.Timeout())
    result = EgrulSource().fetch(CLEAN_INN)
    assert result.status == "timeout"


def test_modes_not_implemented_are_unavailable(settings):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "FSSP": "web"}
    result = [s for s in ALL_SOURCES if s.key == "FSSP"][0]().fetch(CLEAN_INN)
    assert result.status == "unavailable"


# --- ЕГРЮЛ: web -----------------------------------------------------------

WEB_ROW = {"c": 'ООО "ТЕСТ"', "g": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР: Тестов Иван Иванович", "i": CLEAN_INN, "n": "ОБЩЕСТВО ТЕСТ",
           "o": "1000000000018", "r": "23.10.2002"}


def test_egrul_web_parses_rows(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    fake_requests(monkeypatch, {"t": "tok", "captchaRequired": False}, {"rows": [WEB_ROW]})
    result = EgrulSource().fetch(CLEAN_INN)
    assert result.ok
    assert result.data["director_name"] == "Тестов Иван Иванович"
    assert result.data["director_position"] == "Генеральный директор"
    assert result.data["registration_date"] == "2002-10-23"
    assert result.data["status"] == "active"


def test_egrul_web_terminated_is_liquidated(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    fake_requests(monkeypatch, {"t": "tok"}, {"rows": [{**WEB_ROW, "e": "01.01.2020"}]})
    assert EgrulSource().fetch(CLEAN_INN).data["status"] == "liquidated"


def test_legacy_ogrn_assignment_is_not_company_creation_date(monkeypatch):
    fake_requests(monkeypatch, {"t": "tok"}, {"rows": [{**WEB_ROW, "o": "1027700348070"}]})
    data = EgrulSource(mode="web").fetch(CLEAN_INN).data
    assert data["registration_date"] is None
    assert data["ogrn_assigned_date"] == "2002-10-23"


def test_explicit_mode_does_not_change_other_requests(settings, monkeypatch):
    original = settings.SOURCE_MODES.copy()
    fake_requests(monkeypatch, {"captchaRequired": True})
    assert EgrulSource(mode="web").fetch(CLEAN_INN).status == "unavailable"
    assert EgrulSource(mode="mock").fetch(CLEAN_INN).ok
    assert settings.SOURCE_MODES == original


def test_egrul_web_captcha_is_unavailable(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    calls = fake_requests(monkeypatch, {"captchaRequired": True})
    result = EgrulSource().fetch(CLEAN_INN)
    assert result.status == "unavailable" and "CAPTCHA" in result.error
    assert len(calls) == 1  # дальше CAPTCHA не идём


def test_user_agent_and_timeout_sent(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    calls = fake_requests(monkeypatch, {"captchaRequired": True})
    EgrulSource().fetch(CLEAN_INN)
    kwargs = calls[0][2]
    assert kwargs["timeout"] == 15 and "ValdexCheck" in kwargs["headers"]["User-Agent"]


# --- ЕГРЮЛ: api -----------------------------------------------------------

def test_egrul_api_without_key_is_unavailable(settings):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "api"}
    settings.EGRUL_API_KEY = ""
    assert EgrulSource().fetch(CLEAN_INN).status == "unavailable"


def test_egrul_api_parses_dadata(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "api"}
    settings.EGRUL_API_KEY = "k"
    payload = {"suggestions": [{"data": {
        "inn": CLEAN_INN, "ogrn": "1000000000018", "okved": "41.20",
        "name": {"full_with_opf": "ООО Тест", "short_with_opf": "ООО Тест"},
        "management": {"name": "Тестов И.И.", "post": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР"},
        "address": {"value": "г Тестоград"},
        "state": {"status": "LIQUIDATED", "registration_date": 1035331200000},
    }}]}
    calls = fake_requests(monkeypatch, payload)
    result = EgrulSource().fetch(CLEAN_INN)
    assert result.data["status"] == "liquidated"
    assert result.data["registration_date"] == "2002-10-23"
    assert calls[0][2]["headers"]["Authorization"] == "Token k"


# --- кэш и частота --------------------------------------------------------


def test_user_agent_can_be_sent_as_http_header(settings):
    assert settings.SOURCE_USER_AGENT.encode("ascii")

def test_result_cached_for_second_call(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    calls = fake_requests(monkeypatch, {"t": "tok"}, {"rows": [WEB_ROW]})
    first = EgrulSource().fetch(CLEAN_INN)
    second = EgrulSource().fetch(CLEAN_INN)  # без кэша очередь payloads уже пуста и вызов упал бы
    assert first.ok and second.ok and len(calls) == 2


def test_failed_result_not_cached(settings, monkeypatch):
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "web"}
    fake_requests(monkeypatch, {"captchaRequired": True}, {"t": "tok"}, {"rows": [WEB_ROW]})
    assert not EgrulSource().fetch(CLEAN_INN).ok
    assert EgrulSource().fetch(CLEAN_INN).ok


def test_throttle_one_request_per_second_per_domain(monkeypatch):
    monkeypatch.setattr(base, "MIN_INTERVAL", 0.2)
    start = time.monotonic()
    base.throttle("a.example")
    base.throttle("a.example")
    base.throttle("b.example")  # другой домен — без ожидания
    assert 0.2 <= time.monotonic() - start < 0.4


def test_scraper_log_written(settings, caplog):
    with caplog.at_level("INFO", logger="scrapers"):
        EgrulSource().fetch(CLEAN_INN)
    assert f"inn={CLEAN_INN}" in caplog.text and "status=success" in caplog.text


# --- rate limit эндпоинта -------------------------------------------------

def test_endpoint_rate_limit_five_per_minute():
    @rate_limit(limit=5, window=60)
    def view(request):
        from django.http import HttpResponse
        return HttpResponse("ok")

    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")
    assert [view(request).status_code for _ in range(6)] == [200] * 5 + [429]
    other = RequestFactory().get("/", REMOTE_ADDR="10.0.0.2")
    assert view(other).status_code == 200
