from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.reports.observations import source_evidence, source_observations
from apps.reports.scoring import calculate_risk_score
from apps.scrapers.base import SourceUnavailable
from apps.scrapers.ofdata import EfrsbSource, FsspSource, KadSource
from tests.test_scoring import codes, sources

INN = "0000000018"
COMPANY = {"ИНН": INN, "НаимСокр": "ООО «Учебный пример»", "ЮрАдрес": "г. Тестовый, ул. Учебная, д. 1"}


@pytest.fixture(autouse=True)
def configured(settings, _clear_cache):
    settings.OFDATA_API_KEY = "synthetic-private-key"
    settings.OFDATA_DAILY_LIMIT = 90


def answer(rows, pages=1, current=1, **data):
    return {"company": COMPANY, "data": {"Записи": rows, "СтрВсего": pages, "СтрТекущ": current, **data},
            "meta": {"status": "ok"}}


def setup_http(monkeypatch, source, *answers):
    queue = iter(answers)
    http = Mock(side_effect=lambda *a, **kw: Mock(json=lambda: next(queue)))
    monkeypatch.setattr(source, "http", http)
    return http


def debt(number="1/26/00000-ИП", **changes):
    return {"ИспПрНомер": number, "ДолжНаим": COMPANY["НаимСокр"],
            "ДолжАдрес": COMPANY["ЮрАдрес"], "ОстЗадолж": 120001.25, **changes}


def case(number="А00-1/2026", **changes):
    return {"Номер": number, "Дата": timezone.localdate().isoformat(),
            "Ист": [], "Ответ": [{"ИНН": INN}], "СуммИск": 50000000, **changes}


def test_key_required_and_no_network_without_it(settings, monkeypatch):
    settings.OFDATA_API_KEY = ""
    source = FsspSource(mode="api")
    http = setup_http(monkeypatch, source)
    assert source.fetch(INN).status == "unavailable"
    http.assert_not_called()


def test_live_profile_uses_api_when_key_present(settings):
    assert all(cls(mode="web").mode == "api" for cls in (FsspSource, EfrsbSource, KadSource))
    assert FsspSource(mode="mock").mode == "mock"
    settings.OFDATA_API_KEY = ""
    assert FsspSource(mode="web").mode == "web"


def test_key_sent_in_post_body_only(monkeypatch):
    source = FsspSource(mode="api")
    http = setup_http(monkeypatch, source, answer([]))
    assert source.fetch(INN).ok
    args, kwargs = http.call_args
    assert args[0] == "POST" and "key" not in args[1]
    assert kwargs["data"]["key"] == "synthetic-private-key"


def test_wrong_inn_rejected(monkeypatch):
    source = FsspSource(mode="api")
    payload = answer([])
    payload["company"] = {**COMPANY, "ИНН": "0000000025"}
    setup_http(monkeypatch, source, payload)
    assert source.fetch(INN).status == "unavailable"


def test_api_error_does_not_expose_key(monkeypatch):
    source = FsspSource(mode="api")
    setup_http(monkeypatch, source, {"meta": {"status": "error", "message": "synthetic-private-key"}})
    result = source.fetch(INN)
    assert result.status == "unavailable" and "synthetic-private-key" not in result.error


def test_local_quota_stops_calls(settings, monkeypatch):
    settings.OFDATA_DAILY_LIMIT = 1
    source = FsspSource(mode="api")
    http = setup_http(monkeypatch, source, answer([]))
    assert source.fetch_api(INN)["total_debt"] == 0
    with pytest.raises(SourceUnavailable, match="суточный лимит"):
        source.fetch_api(INN)
    assert http.call_count == 1


def test_remote_quota_accounted_for(settings, monkeypatch):
    settings.OFDATA_DAILY_LIMIT = 90
    source = FsspSource(mode="api")
    payload = answer([])
    payload["meta"]["today_request_count"] = 90
    http = setup_http(monkeypatch, source, payload)
    source.fetch_api(INN)
    with pytest.raises(SourceUnavailable, match="суточный лимит"):
        source.fetch_api(INN)
    assert http.call_count == 1


def test_fssp_exact_company_and_remaining_debt(monkeypatch):
    source = FsspSource(mode="api")
    setup_http(monkeypatch, source, answer([debt(СумДолг=500000)]))
    data = source.fetch_api(INN)
    assert data["total_debt"] == 120001.25
    assert data["active_proceedings"] is None and data["unavailable_fields"] == ["active_proceedings"]
    assert codes(calculate_risk_score(sources(FSSP=data))) == ["debt_large"]


@pytest.mark.parametrize("changes", [{"ДолжАдрес": "другой адрес"}, {"ДолжНаим": "ООО «Другая компания»"}])
def test_fssp_fuzzy_candidate_not_counted(monkeypatch, changes):
    source = FsspSource(mode="api")
    setup_http(monkeypatch, source, answer([debt(**changes)]))
    data = source.fetch_api(INN)
    assert data["total_debt"] is None and len(data["candidate_records"]) == 1
    assert calculate_risk_score(sources(FSSP=data)).score == 0


def test_fssp_deduplicates_and_marks_incomplete(monkeypatch):
    source = FsspSource(mode="api")
    setup_http(monkeypatch, source, answer([debt()], pages=2), answer([debt()], pages=2, current=2))
    data = source.fetch_api(INN)
    assert data["total_debt"] is None and data["confirmed_debt_lower_bound"] == 120001.25
    assert "не менее" in calculate_risk_score(sources(FSSP=data)).factors[0].text


@pytest.mark.parametrize("bad", [None, "нет данных", -10, "NaN", "Infinity"])
def test_bad_debt_not_replaced_by_zero(monkeypatch, bad):
    source = FsspSource(mode="api")
    setup_http(monkeypatch, source, answer([debt(ОстЗадолж=bad)]))
    data = source.fetch_api(INN)
    assert data["total_debt"] is None and "total_debt" in data["unavailable_fields"]


def test_bankruptcy_messages_not_current_procedure(monkeypatch):
    source = EfrsbSource(mode="api")
    setup_http(monkeypatch, source, {"data": {"ИНН": INN, "ЕФРСБ": [
        {"Тип": "Сообщение о завершении процедуры", "Дата": "2020-01-01", "Дело": "А00-1/2020"}]},
        "meta": {"status": "ok"}})
    data = source.fetch_api(INN)
    assert data["has_bankruptcy_messages"] and data["bankruptcy"] is None
    assert "bankruptcy" not in codes(calculate_risk_score(sources(EFRSB=data)))


def test_omitted_bankruptcy_field_is_not_empty_registry(monkeypatch):
    source = EfrsbSource(mode="api")
    setup_http(monkeypatch, source, {"data": {"ИНН": INN}, "meta": {"status": "ok"}})
    assert source.fetch(INN).status == "unavailable"


def test_kad_counts_period_and_never_uses_claim_as_loss(monkeypatch):
    source = KadSource(mode="api")
    http = setup_http(monkeypatch, source, answer([case()], ЗапВсего=1))
    data = source.fetch_api(INN)
    assert data["cases_last_year"] == 1 and data["lost_cases_amount"] is None
    assert "lost_large" not in codes(calculate_risk_score(sources(KAD=data)))
    assert http.call_args.kwargs["data"]["date_from"] == data["period_start"]


@pytest.mark.parametrize("changes", [{"Ответ": [{"ИНН": "0000000025"}]},
                                     {"Дата": "2000-01-01"}, {"Дата": "плохая дата"},
                                     {"Дата": (timezone.localdate() + timedelta(days=1)).isoformat()}])
def test_kad_wrong_company_or_date_not_counted(monkeypatch, changes):
    source = KadSource(mode="api")
    setup_http(monkeypatch, source, answer([case(**changes)], ЗапВсего=1))
    data = source.fetch_api(INN)
    assert data["cases_last_year"] is None and len(data["candidate_records"]) == 1


def test_pagination_cap_does_not_report_partial_as_complete(monkeypatch):
    source = KadSource(mode="api")
    setup_http(monkeypatch, source, *(answer([case(str(i))], pages=4, current=i, ЗапВсего=4) for i in range(1, 4)))
    data = source.fetch_api(INN)
    assert data["cases_last_year"] is None and data["confirmed_cases_lower_bound"] == 3


def test_cache_avoids_repeated_paid_or_limited_requests(monkeypatch):
    source = FsspSource(mode="api")
    http = setup_http(monkeypatch, source, answer([]))
    assert source.fetch(INN).ok and source.fetch(INN).ok
    assert http.call_count == 1
    cache.clear()


def test_incomplete_kad_keeps_confirmed_lower_bound_risk():
    data = {"cases_last_year": None, "confirmed_cases_lower_bound": 11,
            "lost_cases_amount": None, "unavailable_fields": ["cases_last_year", "lost_cases_amount"]}
    result = calculate_risk_score(sources(KAD=data))
    assert codes(result) == ["many_cases"] and "не менее 11" in result.factors[0].text
    assert result.partial


def test_source_evidence_has_safe_links_and_separate_candidates():
    source = SimpleNamespace(status="success", source_name="КАД Арбитр", data={
        "provider": "Офдата", "primary_url": "https://kad.arbitr.ru/", "cases_last_year": None,
        "confirmed_cases_lower_bound": 1, "records": [case(UUID="00000000-0000-0000-0000-000000000001")],
        "candidate_records": [case(UUID="javascript:alert(1)")]})
    block = source_evidence([source])[0]
    assert block["total"] == 2 and block["rows"][0]["url"].startswith("https://kad.arbitr.ru/Card/")
    assert block["rows"][1]["url"] == "" and "требует проверки" in block["rows"][1]["text"]
    assert "итог не установлен" in source_observations([source])[-1]["text"]


def test_registry_notice_is_displayed_without_asserting_current_bankruptcy():
    source = SimpleNamespace(status="success", source_name="ЕФРСБ", data={
        "provider": "Офдата", "primary_url": "https://bankrot.fedresurs.ru/", "messages": [
            {"Тип": "Завершение процедуры", "Дата": "2020-01-01", "Дело": "А00-1/2020"}]})
    assert source_evidence([source])[0]["rows"][0]["title"] == "Завершение процедуры"
    assert "1" in source_observations([source])[-1]["text"]


@pytest.mark.django_db
def test_api_sources_saved_and_reported_with_role_protection(settings, monkeypatch, client, django_user_model):
    from django.contrib.auth.models import Group
    from django.urls import reverse

    from apps.contractors.services import run_check
    from apps.core.roles import ACCOUNTING, SECURITY
    from apps.scrapers.ofdata import OfdataSource
    from tests.test_reports import pdf_text

    def http(self, method, url, **kwargs):
        if url.endswith("enforcements"):
            payload = answer([debt()])
        elif url.endswith("legal-cases"):
            payload = answer([case(UUID="00000000-0000-0000-0000-000000000001")], ЗапВсего=1)
        else:
            payload = {"data": {"ИНН": INN, "ЕФРСБ": [
                {"Тип": "Учебная публикация ЕФРСБ", "Дата": "2020-01-01", "Дело": "А00-1/2020"}]},
                "meta": {"status": "ok"}}
        return Mock(json=lambda: payload)

    monkeypatch.setattr(OfdataSource, "http", http)
    modes = {**settings.SOURCE_MODES, "FSSP": "api", "EFRSB": "api", "KAD": "api"}
    session = run_check(INN, source_modes=modes)
    assert session.is_demo and session.is_partial and session.status == "risky"
    assert session.sources.filter(mode="api", status="success").count() == 3
    assert session.contractor.status != "bankrupt"
    user = django_user_model.objects.create_user("api_source_reader")
    client.force_login(user)
    for role, visible in ((SECURITY, True), (ACCOUNTING, False)):
        user.groups.set([Group.objects.get(name=role)])
        page = client.get(reverse("contractor_card", args=[session.contractor_id]))
        text = page.content.decode()
        assert ("Учебная публикация ЕФРСБ" in text) is visible
        assert ("Принадлежность требует проверки" not in text)
        pdf = client.get(reverse("reports:contractor_pdf", args=[session.pk]))
        assert ("Учебная публикация ЕФРСБ" in pdf_text(pdf.content)) is visible
