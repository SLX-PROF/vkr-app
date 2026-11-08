from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.validators import validate_inn, validate_ogrn


class Contractor(models.Model):
    """Контрагент — юридическое лицо или ИП, сведения из ЕГРЮЛ."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Действующее"
        LIQUIDATING = "liquidating", "В стадии ликвидации"
        LIQUIDATED = "liquidated", "Ликвидировано"
        BANKRUPT = "bankrupt", "В стадии банкротства"

    inn = models.CharField("ИНН", max_length=12, unique=True, validators=[validate_inn])
    ogrn = models.CharField("ОГРН", max_length=15, blank=True, validators=[validate_ogrn])
    full_name = models.CharField("Полное наименование", max_length=500, blank=True)
    short_name = models.CharField("Сокращённое наименование", max_length=300, blank=True)
    director_name = models.CharField("ФИО руководителя", max_length=200, blank=True)
    director_position = models.CharField("Должность руководителя", max_length=200, blank=True)
    address = models.CharField("Адрес регистрации", max_length=500, blank=True)
    registration_date = models.DateField("Дата регистрации", null=True, blank=True)
    okved = models.CharField("Основной ОКВЭД", max_length=20, blank=True)
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    egrul_updated_at = models.DateTimeField("Данные ЕГРЮЛ обновлены", null=True, blank=True)

    class Meta:
        verbose_name = "контрагент"
        verbose_name_plural = "контрагенты"
        ordering = ["short_name", "inn"]

    @property
    def is_construction(self) -> bool:
        """Раздел F ОКВЭД 2 «Строительство» — коды 41, 42, 43. Информационная пометка, в баллы не входит."""
        return self.okved.split(".")[0] in ("41", "42", "43")

    def __str__(self):
        return f"{self.short_name or self.full_name or 'Без названия'} ({self.inn})"


class CheckSession(models.Model):
    """Сеанс проверки контрагента с итоговым баллом риска."""

    class Status(models.TextChoices):
        SAFE = "safe", "Безопасен"
        RISKY = "risky", "Рискованный"
        DANGEROUS = "dangerous", "Опасный"
        UNKNOWN = "unknown", "Недостаточно данных"

    contractor = models.ForeignKey(
        Contractor, on_delete=models.CASCADE, related_name="checks", verbose_name="Контрагент",
    )
    started_at = models.DateTimeField("Начало проверки", default=timezone.now, db_index=True)
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="checks", verbose_name="Инициатор",
    )
    status = models.CharField("Итоговый статус", max_length=10, choices=Status.choices)
    score = models.PositiveSmallIntegerField("Балл риска (0–100)")
    factors = models.JSONField("Сработавшие правила", default=list, blank=True)
    is_partial = models.BooleanField("Частичная проверка", default=False)
    scoring_config = models.JSONField("Параметры оценки", default=dict, blank=True)
    is_demo = models.BooleanField("Демонстрационные данные", default=False)

    class Meta:
        verbose_name = "сеанс проверки"
        verbose_name_plural = "сеансы проверок"
        ordering = ["-started_at"]
        constraints = [models.CheckConstraint(condition=models.Q(score__lte=100), name="check_score_lte_100")]

    def __str__(self):
        return f"{self.contractor.inn} · {self.started_at:%d.%m.%Y %H:%M} · {self.score}"


class SourceData(models.Model):
    """Ответ одного источника в рамках сеанса проверки (для анализа и аудита)."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Успех"
        ERROR = "error", "Ошибка"
        TIMEOUT = "timeout", "Таймаут"
        UNAVAILABLE = "unavailable", "Недоступен"

    session = models.ForeignKey(
        CheckSession, on_delete=models.CASCADE, related_name="sources", verbose_name="Сеанс",
    )
    source_name = models.CharField("Источник", max_length=50)
    data = models.JSONField("JSON-ответ", default=dict, blank=True)
    status = models.CharField("Статус запроса", max_length=20, choices=Status.choices)
    elapsed = models.FloatField("Время запроса, с", default=0)
    mode = models.CharField("Режим источника", max_length=10, default="unknown")
    error = models.TextField("Причина недоступности", blank=True)

    class Meta:
        verbose_name = "данные источника"
        verbose_name_plural = "данные источников"
        constraints = [models.UniqueConstraint(fields=["session", "source_name"], name="source_once_per_check")]

    def __str__(self):
        return f"{self.source_name}: {self.get_status_display()}"
