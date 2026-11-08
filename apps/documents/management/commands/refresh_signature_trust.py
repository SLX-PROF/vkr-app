from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.documents.trust import refresh_trust_bundle


class Command(BaseCommand):
    help = "Обновить проверенные списки отзыва сертификатов Минцифры и Казначейства"
    requires_system_checks = []

    def handle(self, *args, **options):
        if not settings.SIGNATURE_TRUST_BUNDLE:
            raise CommandError("Не настроен SIGNATURE_TRUST_BUNDLE")
        try:
            report = refresh_trust_bundle(settings.SIGNATURE_TRUST_BUNDLE)
        except Exception as error:
            raise CommandError(f"Набор доверия не обновлён: {error}") from error
        self.stdout.write(f"Обновлены {len(report['crls'])} списка отзыва; {report['updated_at']}")
