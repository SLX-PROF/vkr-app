import json
import time

import pytest
from django.core.exceptions import ValidationError

from apps.contractors import services
from apps.contractors.models import CheckSession, Contractor, SourceData
from apps.scrapers.base import BaseSource, SourceResult
from apps.scrapers.sources import ALL_SOURCES

pytestmark = pytest.mark.django_db

DEMO = json.loads(open("tests/fixtures/demo_contractors.json", encoding="utf-8").read())
EXPECTED_SCORE = {"0000000018": 0, "0000000025": 100, "0000000032": 80, "0000000040": 50,
                  "0000000057": 30, "0000000064": 50, "0000000071": 40, "0000000089": 50}


@pytest.mark.parametrize("item", DEMO, ids=lambda i: i["scenario"])
def test_demo_contractor_expected_status(item):
    session = services.run_check(item["inn"])
    assert session.status == item["expected_status"]
    assert session.score == EXPECTED_SCORE[item["inn"]]
    assert not session.is_partial
    assert session.sources.count() == 6


def test_run_check_saves_contractor_and_factors(django_user_model):
    user = django_user_model.objects.create_user("buh", password="x")
    session = services.run_check("0000000025", user)  # ликвидированная
    contractor = session.contractor
    assert session.initiator == user
    assert contractor.status == Contractor.Status.LIQUIDATED and contractor.short_name == "ООО «Тестстрой-2»"
    assert str(contractor.registration_date) == "2012-03-15" and contractor.egrul_updated_at
    assert session.factors[0]["code"] == "liquidated"
    assert SourceData.objects.filter(session=session, source_name="ЕГРЮЛ", status="success").exists()


def test_bankrupt_contractor_status():
    assert services.run_check("0000000032").contractor.status == Contractor.Status.BANKRUPT


def test_invalid_inn_rejected_before_any_request():
    with pytest.raises(ValidationError):
        services.run_check("1234567890")
    assert not CheckSession.objects.exists()


def test_one_failed_source_does_not_break_check(monkeypatch):
    """Падение ФССП: проверка идёт, правило ФССП не срабатывает, отчёт помечен как частичный."""
    def broken(self, query):
        raise RuntimeError("fssp down")

    fssp = [c for c in ALL_SOURCES if c.key == "FSSP"][0]
    monkeypatch.setattr(fssp, "fetch_mock", broken)
    session = services.run_check("0000000064")  # «много долгов ФССП», без ФССП баллов нет
    assert session.is_partial and session.score == 0 and session.status == "unknown"
    failed = session.sources.get(source_name="ФССП")
    assert failed.status == "error" and failed.data == {}
    assert session.sources.filter(status="success").count() == 5


def test_egrul_failure_keeps_existing_contractor_data(monkeypatch):
    services.run_check("0000000018")
    egrul = [c for c in ALL_SOURCES if c.key == "EGRUL"][0]
    monkeypatch.setattr(egrul, "fetch_mock", lambda self, q: (_ for _ in ()).throw(RuntimeError("down")))
    session = services.run_check("0000000018")
    assert session.is_partial and session.contractor.short_name == "ООО «Тестстрой-1»"


def test_unknown_inn_all_sources_unavailable_has_no_reliability_verdict():
    session = services.run_check("0000000995")  # синтетический ИНН без фикстур
    assert session.is_partial and session.score == 0
    assert session.status == "unknown"
    assert set(session.sources.values_list("status", flat=True)) == {"unavailable"}


# --- параллельность, лимит времени, замер ---------------------------------------

class Slow(BaseSource):
    domain = ""

    def __init__(self, key, delay):
        self.key, self.name, self.delay = key, key, delay

    def fetch(self, query):
        time.sleep(self.delay)
        return SourceResult(ok=True, data={"x": 1})


def test_sources_run_in_parallel(monkeypatch):
    slow = [lambda k=k: Slow(k, 0.5) for k in ("A", "B", "C", "D", "E", "F")]
    monkeypatch.setattr(services, "ALL_SOURCES", slow)
    start = time.monotonic()
    results = services.fetch_all("0000000018")
    assert time.monotonic() - start < 1.5 and len(results) == 6  # последовательно было бы 3 с


def test_total_budget_turns_slow_sources_into_timeout(monkeypatch):
    monkeypatch.setattr(services, "TOTAL_BUDGET", 0.3)
    monkeypatch.setattr(services, "ALL_SOURCES", [lambda: Slow("A", 1.0), lambda: Slow("B", 0)])
    results = {s.key: r for s, r in services.fetch_all("0000000018").items()}
    assert results["A"].status == "timeout" and results["B"].ok


def test_run_check_time_on_mock_sources(capsys):
    """Замер для docs/testing_report.md: `pytest -s -k time_on_mock`. Бюджет проекта — 60 с."""
    timings = []
    for item in DEMO:
        start = time.monotonic()
        services.run_check(item["inn"])
        timings.append(time.monotonic() - start)
    with capsys.disabled():
        print(f"\nrun_check, mock, {len(timings)} проверок: max={max(timings):.3f} с, "
              f"mean={sum(timings) / len(timings):.3f} с, total={sum(timings):.3f} с")
    assert max(timings) < services.TOTAL_BUDGET
