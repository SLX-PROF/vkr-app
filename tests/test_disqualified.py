from datetime import date

import pytest

from apps.scrapers.base import SourceUnavailable
from apps.scrapers.disqualified import normalize_registry

TODAY = date(2026, 11, 8)
INN = "0000000018"
NAME = "Образцов Пётр Сергеевич"


def entry(**changes):
    return {"ФИО": NAME, "ИННОрг": INN, "ДатаНачДискв": "01.01.2026",
            "ДатаКонДискв": "31.12.2026", **changes}


def test_active_record_needs_name_company_and_period():
    value = normalize_registry({"data": [entry()], "rowCount": 1}, INN, NAME, TODAY)
    assert value["found"] and not value["unavailable_fields"]


@pytest.mark.parametrize("changes", [{"ИННОрг": "0000000025"}, {"ДатаКонДискв": None}])
def test_ambiguous_match_is_not_confirmed(changes):
    value = normalize_registry({"data": [entry(**changes)], "rowCount": 1}, INN, NAME, TODAY)
    assert not value["found"] and value["possible_matches"] == 1 and value["unavailable_fields"]


def test_expired_period_is_not_active_disqualification():
    value = normalize_registry({"data": [entry(ДатаКонДискв="01.01.2025")], "rowCount": 1}, INN, NAME, TODAY)
    assert not value["found"] and not value["possible_matches"]


def test_empty_result_and_incomplete_response_differ():
    assert not normalize_registry({"data": [], "rowCount": 0}, INN, NAME, TODAY)["found"]
    with pytest.raises(SourceUnavailable):
        normalize_registry({}, INN, NAME, TODAY)


def test_truncated_results_are_partial():
    assert normalize_registry({"data": [], "rowCount": 51}, INN, NAME, TODAY)["unavailable_fields"]
