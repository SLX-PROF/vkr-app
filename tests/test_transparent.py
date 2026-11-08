from unittest.mock import Mock

import pytest

from apps.reports.scoring import calculate_risk_score
from apps.scrapers.base import SourceUnavailable
from apps.scrapers.transparent import TransparentBusinessSource, normalize_company
from tests.test_scoring import sources

INN = "0000000018"


def payload():
    return {"vyp": {"ИНН": INN, "sschr": 4, "sschr_yearcode": 2025,
                    "revenuesum": 100000, "form1_yearcode": 2025, "masruk": [{"cnt": "1"}]},
            "masaddress": [{"cnt": "2"}],
            "arrear": [{"yearcode": 2026, "periodcode": 9, "arrearsum": 0},
                       {"yearcode": 2026, "periodcode": 10, "arrearsum": 10, "finesum": 500},
                       {"yearcode": 2026, "periodcode": 10, "arrearsum": 2.50, "penaltysum": 20}]}


def test_latest_period_and_no_double_counting():
    data = normalize_company(payload(), INN)
    assert data["tax_debt_amount"] == 12.50 and data["tax_debt_period"] == [2026, 10]
    assert data["avg_headcount"] == 4 and data["revenue"] == 100000
    assert not data["unavailable_fields"]


def test_absence_of_figures_is_not_zero():
    data = normalize_company({"vyp": {"ИНН": INN}, "masaddress": [],
                              "arrear": [{"yearcode": 2026, "periodcode": 10, "empty": 1}]}, INN)
    assert data["avg_headcount"] is None and data["tax_debt_amount"] is None
    result = calculate_risk_score(sources(TRANSPARENT=data))
    assert result.status == "unknown" and result.partial
    assert result.incomplete == ["Прозрачный бизнес"]


def test_headcount_and_revenue_must_refer_to_same_year():
    value = payload()
    value["vyp"]["sschr_yearcode"] = 2024
    data = normalize_company(value, INN)
    assert data["avg_headcount"] is None and data["revenue"] is None


def test_exact_inn_required():
    with pytest.raises(SourceUnavailable):
        normalize_company(payload(), "0000000025")


@pytest.mark.parametrize("registered", ["2002-02-04", "04.02.2002"])
def test_creation_date_and_registry_enrichment(registered):
    value = payload()
    value["vyp"].update({"ДатаРег": registered, "АдресРФ": "г. Москва", "КодОКВЭД": "43.29"})
    data = normalize_company(value, INN)
    assert data["registration_date"] == "2002-02-04"
    assert data["address"] == "г. Москва" and data["okved_main"] == "43.29"


def test_web_protocol_returns_normalized_data(monkeypatch):
    source = TransparentBusinessSource(mode="web")
    responses = iter([{"id": "search", "captchaRequired": False},
                      {"ul": {"data": [{"inn": INN, "token": "company"}]}},
                      {"id": "request", "token": "company", "captchaRequired": False}, payload()])
    monkeypatch.setattr(source, "http", lambda *a, **kw: Mock(json=lambda: next(responses)))
    monkeypatch.setattr("apps.scrapers.transparent.time.sleep", lambda n: None)
    result = source.fetch(INN)
    assert result.ok and result.data["tax_debt_amount"] == 12.50


def test_captcha_stops_without_attempting_bypass(monkeypatch):
    source = TransparentBusinessSource(mode="web")
    http = Mock(return_value=Mock(json=lambda: {"captchaRequired": True}))
    monkeypatch.setattr(source, "http", http)
    assert source.fetch(INN).status == "unavailable"
    assert http.call_count == 1
