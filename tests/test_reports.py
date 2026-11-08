from io import BytesIO

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from pypdf import PdfReader

from apps.contractors.models import CheckSession
from apps.contractors.services import run_check
from apps.core.roles import ACCOUNTING, SECURITY
from apps.reports.pdf import build_report

pytestmark = pytest.mark.django_db


def pdf_text(content):
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    return " ".join(text.split())


def sign_in(client, django_user_model, role):
    user = django_user_model.objects.create_user("report_user", password="test-pass")
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def test_report_contains_cyrillic_snapshot_and_six_sources():
    session = run_check("0000000025")
    session.contractor.short_name = "Позднейшее название"
    session.contractor.save()
    content = build_report(session, show_details=True)
    text = pdf_text(content)
    assert content.startswith(b"%PDF-")
    assert "Тестстрой-2" in text and "Позднейшее название" not in text
    assert "ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ" in text and "100 из 100" in text
    assert "Организация ликвидирована" in text
    assert all(name in text for name in session.sources.values_list("source_name", flat=True))
    assert session.scoring_config and set(session.sources.values_list("mode", flat=True)) == {"mock"}


def test_report_missing_sources_and_legacy_provenance():
    session = run_check("0000000995")
    text = pdf_text(build_report(session, show_details=True))
    assert "Частичная проверка" in text and "данные не получены" in text
    old = CheckSession.objects.create(contractor=session.contractor, score=0, status="safe")
    text = pdf_text(build_report(old, show_details=True))
    assert "История источников отсутствует" in text and "не сохранены" in text


@pytest.mark.parametrize("role,details", [(ACCOUNTING, False), (SECURITY, True)])
def test_pdf_respects_role_and_disables_caching(client, django_user_model, role, details):
    user = sign_in(client, django_user_model, role)
    session = run_check("0000000025", user)
    response = client.get(reverse("reports:contractor_pdf", args=[session.pk]))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert "attachment;" in response["Content-Disposition"] and "no-store" in response["Cache-Control"]
    text = pdf_text(response.content)
    assert ("Организация ликвидирована" in text) is details
    assert "report_user" in text


def test_report_requires_login_and_role(client, django_user_model):
    session = run_check("0000000018")
    url = reverse("reports:contractor_pdf", args=[session.pk])
    assert client.get(url).status_code == 302
    user = django_user_model.objects.create_user("no_role")
    client.force_login(user)
    assert client.get(url).status_code == 403


def test_report_404_and_only_get(client, django_user_model):
    sign_in(client, django_user_model, SECURITY)
    assert client.get(reverse("reports:contractor_pdf", args=[999999])).status_code == 404
    assert client.post(reverse("reports:contractor_pdf", args=[1])).status_code == 405


def test_report_escapes_markup_and_handles_long_text():
    session = run_check("0000000025")
    session.factors = [{"points": 100, "text": "<b> & " + "длинноеслово" * 150, "source": "ЕГРЮЛ"}] * 30
    session.save()
    text = pdf_text(build_report(session, show_details=True))
    assert "<b> &" in text and "Страница 2" in text
