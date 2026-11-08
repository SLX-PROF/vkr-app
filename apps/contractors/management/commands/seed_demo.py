"""Демо-данные: три пользователя по ролям, 8 синтетических контрагентов с историей проверок и документами.

Пароли ниже — только для разработки и демонстрации (см. README). Команда повторно запускается без дублей.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from django.utils import timezone

from apps.contractors.models import CheckSession, Contractor
from apps.contractors.services import run_check
from apps.core.roles import ACCOUNTING, ADMIN, SECURITY
from apps.documents.models import PrimaryDocument
from apps.documents.verification import verify_document
from apps.reports.scoring import SCORING_CONFIG, status_for_score

DEMO_USERS = [  # (логин, пароль, группа, is_staff, is_superuser)
    ("buh_demo", "BuhDemo-2026", ACCOUNTING, False, False),
    ("sb_demo", "SbDemo-2026", SECURITY, False, False),
    ("admin_demo", "AdminDemo-2026", ADMIN, True, True),
]
HISTORY_POINTS = 6   # проверок на контрагента: последняя — сейчас, остальные раз в 28 дней назад
HISTORY_STEP_DAYS = 28


class Command(BaseCommand):
    help = "Создаёт демо-пользователей, 8 демо-контрагентов с историей проверок и тестовые документы"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="разрешить запуск при DEBUG=False")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("seed_demo создаёт учётные записи со слабыми паролями и допустим только при DEBUG=True.")
        users = self.create_users()
        demo = json.loads((settings.FIXTURES_DIR / "demo_contractors.json").read_text(encoding="utf-8"))
        inns = [item["inn"] for item in demo]
        Contractor.objects.filter(inn__in=inns).delete()
        PrimaryDocument.objects.filter(inn__in=inns).delete()
        # Источники всегда mock: демо не должно ходить в сеть, что бы ни стояло в .env
        with override_settings(SOURCE_MODES={key: "mock" for key in settings.SOURCE_MODES}):
            for item in demo:
                self.create_history(item["inn"], users["sb_demo"])
            self.create_documents(inns)
        self.stdout.write(self.style.SUCCESS(f"Готово: {len(demo)} контрагентов, {len(users)} пользователя."))

    def create_users(self):
        users = {}
        for username, password, group, is_staff, is_superuser in DEMO_USERS:
            user, _ = get_user_model().objects.get_or_create(username=username)
            user.is_staff, user.is_superuser = is_staff, is_superuser
            user.set_password(password)
            user.save()
            user.groups.set([Group.objects.get(name=group)])
            users[username] = user
        return users

    def create_history(self, inn, initiator):
        """Последняя проверка — настоящий run_check. Прежние — накопление факторов: чем ближе к сегодняшнему дню,
        тем больше сработавших правил (риск контрагента нарастал), баллы и статусы согласованы с факторами."""
        latest = run_check(inn, initiator)
        factors = latest.factors
        now = timezone.now()
        for i in range(HISTORY_POINTS - 1):  # i = 0 — самая давняя проверка
            known = factors[: len(factors) * i // (HISTORY_POINTS - 1)]
            score = min(sum(f["points"] for f in known), SCORING_CONFIG["score_max"])
            session = CheckSession.objects.create(
                contractor=latest.contractor, initiator=initiator, score=score,
                status=status_for_score(score), factors=known, is_demo=True, scoring_config=latest.scoring_config)
            started = now - timedelta(days=HISTORY_STEP_DAYS * (HISTORY_POINTS - 1 - i), hours=i)
            CheckSession.objects.filter(pk=session.pk).update(started_at=started)

    def create_documents(self, inns):
        """Пара документов для вкладки «Документы»: корректный, чужой подписант, дата до регистрации."""
        clean, mass = inns[0], inns[4]
        base = dict(doc_type="upd", amount=Decimal("1200000"), signer_position="Генеральный директор")
        for inn, number, day, signer in [
            (clean, "17", date(2026, 5, 20), "Образцов П.С."),
            (clean, "18", date(2026, 6, 2), "Иванов Иван Иванович"),
            (mass, "5", date(2010, 1, 15), "Макетов Сергей Борисович"),
        ]:
            document = PrimaryDocument.objects.create(inn=inn, number=number, date=day, signer_name=signer, **base)
            verify_document(document)
