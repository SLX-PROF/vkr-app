from unittest.mock import Mock

import pytest

from apps.reports.scoring import calculate_risk_score
from apps.scrapers.cbr import CbrWarningSource
from apps.scrapers.transparent import normalize_unreliability
from tests.test_scoring import codes, sources


def test_mass_director_does_not_mean_unreliability():
    data = normalize_unreliability({"invalid": 0, "masruk": [{"cnt": 20}]})
    assert data["unreliable_director"] is False and data["unreliable_address"] is False


def test_general_flag_does_not_identify_director_or_address():
    data = normalize_unreliability({"invalid": 1, "masrukinvalid": 1})
    assert data["unreliable_details"] is True
    assert data["unreliable_director"] is None and data["unreliable_address"] is None
    assert codes(calculate_risk_score(sources(TRANSPARENT=data))) == ["unreliable_details"]


def test_explicit_address_and_director_notices_are_distinct_factors():
    data = normalize_unreliability({"invalid": 1,
                                   "НедСвАдресЮЛ": [{"ТекстНедАдресЮЛ": "Запись об адресе"}],
                                   "masruk": [{"invalid": "Запись о руководителе"}]})
    assert data["unreliable_address"] is True and data["unreliable_director"] is True
    result = calculate_risk_score(sources(TRANSPARENT=data))
    assert codes(result) == ["unreliable_address", "unreliable_director"]
    assert result.score == 70


def test_missing_flags_are_unknown():
    data = normalize_unreliability({})
    assert all(data[k] is None for k in ("unreliable_details", "unreliable_director", "unreliable_address"))


@pytest.mark.parametrize("inn,expected", [("0000000018", True), ("0000000025", False), (None, None)])
def test_cbr_requires_exact_inn(monkeypatch, inn, expected):
    source = CbrWarningSource(mode="web")
    answers = iter([{"Data": [{"id": 5}]}, {"Info": [{"inn": inn, "nameOrg": "Учебная организация"}],
                                           "Signs": [{"signRus": "Учебный признак"}]}])
    monkeypatch.setattr(source, "http", lambda *a, **kw: Mock(json=lambda: next(answers)))
    data = source.fetch_web("0000000018")
    assert data["found_by_inn"] is expected
    assert bool(data["unavailable_fields"]) is (expected is None)
    score = calculate_risk_score(sources(CBR=data))
    assert ("cbr_warning" in codes(score)) is (expected is True)


def test_empty_search_is_not_zsk_green(monkeypatch):
    source = CbrWarningSource(mode="web")
    monkeypatch.setattr(source, "http", lambda *a, **kw: Mock(json=lambda: {"Data": []}))
    data = source.fetch_web("0000000018")
    assert data["found_by_inn"] is False and "zsk" not in data


def test_changed_cbr_schema_is_unavailable(monkeypatch):
    source = CbrWarningSource(mode="web")
    monkeypatch.setattr(source, "http", lambda *a, **kw: Mock(json=lambda: {"error": "Ошибка"}))
    assert source.fetch("0000000018").status == "unavailable"
