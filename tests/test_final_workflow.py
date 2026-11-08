import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.contractors import services
from apps.contractors.models import CheckSession, SourceData
from apps.core.admin_mixins import _cell
from apps.core.roles import SECURITY
from apps.documents.models import PrimaryDocument
from apps.documents.verification import verify_document
from apps.scrapers.egrul import EgrulSource
from tests.test_reports import pdf_text

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("value", ["+1+1", "=SUM(A1)", " @SUM(A1)", "-1+2"])
def test_csv_does_not_execute_formulas(value):
    class Row:
        name = value
    assert _cell(Row(), "name") == "'" + value


def test_unreadable_signer_is_not_treated_as_match():
    services.run_check("0000000018")
    document = PrimaryDocument.objects.create(
        doc_type="upd", number="1", date=datetime.date(2026, 5, 20), inn="0000000018",
        signer_name="123...", signer_position="Директор", amount=Decimal("1"))
    result = verify_document(document)
    assert result.name_match == "no_data" and result.signer_is_director is None
    assert result.verdict == "warning" and result.issues[0]["code"] == "SIGNER_UNREADABLE"
    document.amount = -1
    assert "AMOUNT_INVALID" in {x["code"] for x in verify_document(document).issues}


def test_database_enforces_score_and_single_source():
    session = services.run_check("0000000018")
    with pytest.raises(IntegrityError), transaction.atomic():
        CheckSession.objects.filter(pk=session.pk).update(score=101)
    with pytest.raises(IntegrityError), transaction.atomic():
        SourceData.objects.create(session=session, source_name="ЕГРЮЛ", status="success")


def test_rogue_provider_exception_does_not_abort_other_sources(monkeypatch):
    class Broken:
        def fetch(self, query):
            raise RuntimeError("unexpected")
    monkeypatch.setattr(services, "ALL_SOURCES", [Broken])
    results = services.fetch_all("0000000018")
    assert next(iter(results.values())).status == "error"


def test_start_time_is_captured_before_collection(monkeypatch):
    original = services.fetch_all
    observed = []
    def fetch(inn):
        observed.append(services.timezone.now())
        return original(inn)
    monkeypatch.setattr(services, "fetch_all", fetch)
    session = services.run_check("0000000018")
    assert session.started_at <= observed[0]


def test_full_inn_card_document_pdf_scenario(client, django_user_model):
    user = django_user_model.objects.create_user("workflow", password="test")
    user.groups.add(Group.objects.get(name=SECURITY))
    client.force_login(user)
    response = client.post(reverse("check"), {"query": "0000000018"}, follow=True)
    assert response.status_code == 200 and "Скачать PDF" in response.content.decode()
    session = CheckSession.objects.get()
    response = client.post(reverse("documents:verify"), {
        "doc_type": "upd", "number": "17", "date": "2026-05-20", "inn": "0000000018",
        "signer_name": "Образцов П.С.", "signer_position": "Директор", "amount": "100"}, follow=True)
    assert "Соответствует" in response.content.decode()
    response = client.get(reverse("reports:contractor_pdf", args=[session.pk]))
    assert response.status_code == 200 and "Тестстрой-1" in pdf_text(response.content)


def test_new_ogrn_can_be_resolved_before_first_check(client, django_user_model):
    user = django_user_model.objects.create_user("ogrn")
    user.groups.add(Group.objects.get(name=SECURITY))
    client.force_login(user)
    response = client.post(reverse("check"), {"query": "1000000000010"}, follow=True)
    assert response.status_code == 200 and CheckSession.objects.get().contractor.inn == "0000000018"
    assert not EgrulSource().fetch("1000000000998").ok
