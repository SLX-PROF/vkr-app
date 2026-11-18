"""Удаление просроченных загрузок, которые не были подтверждены."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import DocumentUpload


def cleanup_uploads():
    with transaction.atomic():
        expired = list(DocumentUpload.objects.select_for_update(skip_locked=True).filter(
            document__isnull=True, created_at__lt=timezone.now() - timedelta(hours=1))[:20])
        for upload in expired:
            upload.file.delete(save=False)
            upload.delete()
