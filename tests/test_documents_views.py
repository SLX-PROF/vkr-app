import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.documents.models import DocumentVerification, PrimaryDocument

pytestmark = pytest.mark.django_db

GOOD = {"doc_type": "upd", "number": "17", "date": "2026-05-20", "inn": "0000000018", "amount": "1200000",
        "signer_name": "Образцов П.С.", "signer_position": "Генеральный директор"}


@pytest.fixture
def client_in(client, django_user_model):
    user = django_user_model.objects.create_user("buh", password="x")
    user.groups.add(Group.objects.get(name="Бухгалтерия"))
    client.force_login(user)
    return client


def test_login_required(client):
    response = client.get(reverse("documents:verify"))
    assert response.status_code == 302 and "login" in response["Location"]


def test_form_page_opens(client_in):
    assert "Сверить" in client_in.get(reverse("documents:verify")).content.decode()


def test_post_good_document_shows_green_result(client_in):
    response = client_in.post(reverse("documents:verify"), GOOD, follow=True)
    html = response.content.decode()
    assert "Соответствует" in html and "alert-success" in html


def test_post_foreign_signer_shows_warning(client_in):
    response = client_in.post(reverse("documents:verify"), {**GOOD, "signer_name": "Тестов И.И."}, follow=True)
    html = response.content.decode()
    assert "alert-warning" in html and "доверенность" in html


def test_invalid_inn_is_a_finding_not_a_form_error(client_in):
    response = client_in.post(reverse("documents:verify"), {**GOOD, "inn": "1234567890"}, follow=True)
    html = response.content.decode()
    assert "alert-danger" in html and "некорректен" in html
    assert PrimaryDocument.objects.count() == 1


def test_missing_requisites_are_findings_not_form_errors(client_in):
    data = {"doc_type": "ks2", "date": "2026-05-20", "inn": "0000000018"}
    html = client_in.post(reverse("documents:verify"), data, follow=True).content.decode()
    assert "Не указана сумма" in html and "Нет подписи" in html
    assert DocumentVerification.objects.count() == 1


def test_missing_date_stays_a_form_error(client_in):
    response = client_in.post(reverse("documents:verify"), {"doc_type": "upd"})
    assert response.status_code == 200 and PrimaryDocument.objects.count() == 0
