import datetime

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.contractors.models import CheckSession, Contractor, SourceData
from apps.contractors.services import run_check
from apps.core.roles import ACCOUNTING, ADMIN, SECURITY

pytestmark = pytest.mark.django_db

DIRECTOR_MASS = "0000000057"   # массовый руководитель и адрес: факторы +20 и +10
CLEAN = "0000000018"
FACTOR_TEXT = "Массовый руководитель"


def make_user(django_user_model, name, group=None, **extra):
    user = django_user_model.objects.create_user(name, password="pw", **extra)
    if group:
        user.groups.add(Group.objects.get(name=group))
    return user


@pytest.fixture
def accountant(django_user_model):
    client = Client()  # отдельный клиент: роли в одном тесте не должны делить сессию
    client.force_login(make_user(django_user_model, "buh", ACCOUNTING))
    return client


@pytest.fixture
def security(django_user_model):
    client = Client()  # отдельный клиент: роли в одном тесте не должны делить сессию
    client.force_login(make_user(django_user_model, "sb", SECURITY))
    return client


@pytest.fixture
def admin(django_user_model):
    client = Client()  # отдельный клиент: роли в одном тесте не должны делить сессию
    client.force_login(make_user(django_user_model, "adm", ADMIN, is_staff=True, is_superuser=True))
    return client


@pytest.fixture
def card_pk():
    return run_check(DIRECTOR_MASS).contractor.pk


# --- вход ---------------------------------------------------------------------------------------

def test_groups_created_by_migration():
    assert set(Group.objects.values_list("name", flat=True)) >= {ACCOUNTING, SECURITY, ADMIN}


def test_login_logout(client, django_user_model):
    make_user(django_user_model, "buh", ACCOUNTING)
    assert client.get(reverse("login")).status_code == 200
    assert client.post(reverse("login"), {"username": "buh", "password": "bad"}).status_code == 200
    assert client.post(reverse("login"), {"username": "buh", "password": "pw"}).status_code == 302
    assert client.get(reverse("dashboard")).status_code == 200
    client.post(reverse("logout"))
    assert client.get(reverse("dashboard")).status_code == 302


# --- доступ по ролям -----------------------------------------------------------------------------

@pytest.mark.parametrize("url_name, args", [
    ("dashboard", []), ("contractor_card", [1]), ("documents:verify", []), ("documents:result", [1])])
def test_anonymous_redirected_to_login(client, url_name, args):
    response = client.get(reverse(url_name, args=args))
    assert response.status_code == 302 and response["Location"].startswith("/login/")


def test_anonymous_cannot_post_check(client):
    assert client.post(reverse("check"), {"query": CLEAN}).status_code == 302


def test_user_without_role_gets_403(client, django_user_model):
    client.force_login(make_user(django_user_model, "nobody"))
    for name in ("dashboard", "documents:verify"):
        assert client.get(reverse(name)).status_code == 403
    assert client.post(reverse("check"), {"query": CLEAN}).status_code == 403


@pytest.mark.parametrize("role_client", ["accountant", "security", "admin"])
def test_every_role_sees_dashboard_and_document_form(role_client, request):
    client = request.getfixturevalue(role_client)
    assert client.get(reverse("dashboard")).status_code == 200
    assert client.get(reverse("documents:verify")).status_code == 200


def test_accountant_card_has_no_factor_details(accountant, card_pk):
    html = accountant.get(reverse("contractor_card", args=[card_pk])).content.decode()
    assert FACTOR_TEXT not in html and "Массовый адрес" not in html
    assert "доступны сотрудникам СБ и юристов" in html
    assert "Рискованный" in html and "30" in html  # статус и балл видны


@pytest.mark.parametrize("role_client", ["security", "admin"])
def test_security_and_admin_see_factors_with_source_links(role_client, request, card_pk):
    html = request.getfixturevalue(role_client).get(reverse("contractor_card", args=[card_pk])).content.decode()
    assert FACTOR_TEXT in html and "Массовый адрес" in html
    assert 'href="https://pb.nalog.ru"' in html and "+20" in html


def test_admin_site_only_for_staff(accountant, security, admin):
    assert admin.get("/admin/").status_code == 200
    for other in (accountant, security):
        assert other.get("/admin/").status_code == 302  # не staff — на вход в админку


def test_nav_shows_admin_link_only_for_staff(admin, accountant):
    assert "Админка" in admin.get(reverse("dashboard")).content.decode()
    assert "Админка" not in accountant.get(reverse("dashboard")).content.decode()


# --- дашборд -------------------------------------------------------------------------------------

def test_dashboard_empty_state(accountant):
    html = accountant.get(reverse("dashboard")).content.decode()
    assert "Проверок пока нет" in html and "Быстрая проверка" in html


def test_dashboard_lists_only_ten_latest_and_badges_have_text(accountant):
    contractor = Contractor.objects.create(inn=CLEAN)
    for status, score in [("safe", 0), ("risky", 40), ("dangerous", 90)] * 4:
        CheckSession.objects.create(contractor=contractor, status=status, score=score)
    response = accountant.get(reverse("dashboard"))
    assert len(response.context["recent"]) == 10
    html = response.content.decode()
    for text in ("Безопасен", "Рискованный", "Опасный"):
        assert f">{text}</span>" in html


def test_dashboard_month_stats_use_latest_check_per_contractor(accountant):
    a, b = Contractor.objects.create(inn=CLEAN), Contractor.objects.create(inn=DIRECTOR_MASS)
    old = CheckSession.objects.create(contractor=a, status="dangerous", score=90)
    CheckSession.objects.filter(pk=old.pk).update(started_at=timezone.now() - datetime.timedelta(days=5))
    CheckSession.objects.create(contractor=a, status="safe", score=0)   # последняя проверка a
    CheckSession.objects.create(contractor=b, status="risky", score=40)
    month_plus = timezone.now() - datetime.timedelta(days=45)  # вне окна статистики
    CheckSession.objects.filter(contractor=b).update(started_at=month_plus)
    stats = {key: count for key, _, count in accountant.get(reverse("dashboard")).context["stats"]}
    assert stats == {"safe": 1, "risky": 0, "dangerous": 0, "unknown": 0}


# --- быстрая проверка и rate limit -----------------------------------------------------------------

def test_quick_check_by_inn_redirects_to_card(accountant):
    response = accountant.post(reverse("check"), {"query": f" {DIRECTOR_MASS} "})
    contractor = Contractor.objects.get(inn=DIRECTOR_MASS)
    assert response.status_code == 302 and response["Location"] == reverse("contractor_card", args=[contractor.pk])
    assert contractor.checks.get().initiator.username == "buh"


def test_quick_check_by_known_ogrn(accountant):
    run_check(CLEAN)
    ogrn = Contractor.objects.get(inn=CLEAN).ogrn
    response = accountant.post(reverse("check"), {"query": ogrn})
    assert response.status_code == 302 and "/contractors/" in response["Location"]
    assert Contractor.objects.get(inn=CLEAN).checks.count() == 2


def test_quick_check_unknown_ogrn_asks_for_inn(accountant):
    prefix = "100000000099"
    ogrn = prefix + str(int(prefix) % 11 % 10)  # корректный ОГРН, которого нет ни в БД, ни в источнике
    response = accountant.post(reverse("check"), {"query": ogrn}, follow=True)
    assert "введите его ИНН" in response.content.decode() and not CheckSession.objects.exists()


@pytest.mark.parametrize("query", ["", "123", "1234567890", "abc"])
def test_quick_check_invalid_input_shows_message(accountant, query):
    response = accountant.post(reverse("check"), {"query": query}, follow=True)
    assert "Введите корректный ИНН" in response.content.decode() and not CheckSession.objects.exists()


def test_check_requires_post(accountant):
    assert accountant.get(reverse("check")).status_code == 405


def test_check_rate_limit_five_per_minute(accountant):
    codes = [accountant.post(reverse("check"), {"query": "bad"}).status_code for _ in range(6)]
    assert codes == [302] * 5 + [429]


# --- карточка -----------------------------------------------------------------------------------------

def test_card_has_four_tabs_and_chart_data(security, card_pk):
    html = security.get(reverse("contractor_card", args=[card_pk])).content.decode()
    for tab in ("Обзор", "ЕГРЮЛ", "Риски", "Документы"):
        assert f'type="button" role="tab">{tab}</button>' in html
    assert 'id="chart-data"' in html and 'id="risk-chart"' in html
    assert "vendor/chartjs/chart.umd.min.js" in html


def test_card_chart_points_follow_history(security, card_pk):
    contractor = Contractor.objects.get(pk=card_pk)
    older = CheckSession.objects.create(contractor=contractor, status="safe", score=10)
    CheckSession.objects.filter(pk=older.pk).update(started_at=timezone.now() - datetime.timedelta(days=60))
    chart = security.get(reverse("contractor_card", args=[card_pk])).context["chart"]
    assert [p["score"] for p in chart] == [10, 30]


def test_card_without_checks_does_not_crash(security):
    contractor = Contractor.objects.create(inn=CLEAN)
    html = security.get(reverse("contractor_card", args=[contractor.pk])).content.decode()
    assert "Проверок этого контрагента ещё не было" in html


def test_card_partial_check_notice(security, monkeypatch):
    session = run_check(CLEAN)
    SourceData.objects.filter(session=session, source_name="ФССП").update(status="unavailable")
    CheckSession.objects.filter(pk=session.pk).update(is_partial=True)
    html = security.get(reverse("contractor_card", args=[session.contractor.pk])).content.decode()
    assert "Неполные или недоступные сведения: ФССП" in html and "Частичная проверка" in html


def test_card_egrul_tab_and_unavailable_egrul(security):
    contractor = Contractor.objects.create(inn=CLEAN)
    assert "получить не удалось" in security.get(reverse("contractor_card", args=[contractor.pk])).content.decode()
    contractor = run_check(DIRECTOR_MASS).contractor
    html = security.get(reverse("contractor_card", args=[contractor.pk])).content.decode()
    assert "Макетов Сергей Борисович" in html


def test_card_404(security):
    assert security.get(reverse("contractor_card", args=[9999])).status_code == 404


def test_card_documents_tab_lists_verifications(security):
    call_command("seed_demo", force=True)
    clean = Contractor.objects.get(inn=CLEAN)
    html = security.get(reverse("contractor_card", args=[clean.pk])).content.decode()
    assert "УПД № 17" in html and "УПД № 18" in html and "Соответствует" in html and "Требует внимания" in html


# --- ОКВЭД: пометка «строительная отрасль» ------------------------------------------------------------------

@pytest.mark.parametrize("okved, expected", [
    ("41.20", True), ("42.11", True), ("43.99", True), ("47.11", False), ("", False)])
def test_is_construction(okved, expected):
    assert Contractor(inn=CLEAN, okved=okved).is_construction is expected


def test_okved_filled_from_mock_and_note_shown_but_not_scored(security):
    session = run_check(DIRECTOR_MASS)
    assert session.contractor.okved == "41.20"
    assert session.score == 30   # пометка не влияет на баллы
    html = security.get(reverse("contractor_card", args=[session.contractor.pk])).content.decode()
    assert "Строительная отрасль" in html


def test_no_construction_note_for_other_okved(security):
    contractor = Contractor.objects.create(inn=CLEAN, okved="47.11")
    assert "Строительная отрасль" not in security.get(reverse("contractor_card", args=[contractor.pk])).content.decode()


def test_okved_kept_when_egrul_fails_later(monkeypatch):
    from apps.scrapers.egrul import EgrulSource
    run_check(CLEAN)
    monkeypatch.setattr(EgrulSource, "fetch_mock", lambda self, q: (_ for _ in ()).throw(RuntimeError("down")))
    assert run_check(CLEAN).contractor.okved == "41.20"


def test_okved_from_dadata(settings, monkeypatch):
    import requests
    settings.SOURCE_MODES = {**settings.SOURCE_MODES, "EGRUL": "api"}
    settings.EGRUL_API_KEY = "k"
    data = {"inn": "0000000995", "okved": "43.21", "name": {}, "state": {"status": "ACTIVE"}}
    payload = {"suggestions": [{"data": data}]}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(requests, "request", lambda *a, **k: Resp())
    assert run_check("0000000995").contractor.okved == "43.21"


# --- seed_demo ----------------------------------------------------------------------------------------------

def test_seed_demo_creates_users_contractors_and_history(settings, django_user_model):
    settings.DEBUG = True
    call_command("seed_demo")
    call_command("seed_demo")   # повторный запуск не плодит дубли
    assert Contractor.objects.count() == 8
    users = {u.username: u for u in django_user_model.objects.all()}
    assert set(users) == {"buh_demo", "sb_demo", "admin_demo"}
    assert [g.name for g in users["buh_demo"].groups.all()] == [ACCOUNTING]
    assert [g.name for g in users["sb_demo"].groups.all()] == [SECURITY]
    assert [g.name for g in users["admin_demo"].groups.all()] == [ADMIN] and users["admin_demo"].is_staff
    assert users["sb_demo"].check_password("SbDemo-2026")
    for contractor in Contractor.objects.all():
        dates = list(contractor.checks.order_by("started_at").values_list("started_at", flat=True))
        assert len(dates) == 6 and (dates[-1] - dates[0]).days >= 120   # история за несколько месяцев
    expected = {"0000000018": "safe", "0000000025": "dangerous", "0000000032": "dangerous", "0000000040": "risky",
                "0000000057": "risky", "0000000064": "risky", "0000000071": "risky", "0000000089": "risky"}
    for inn, status in expected.items():
        assert Contractor.objects.get(inn=inn).checks.latest("started_at").status == status


def test_seed_demo_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo")
