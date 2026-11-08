from django.db import models

from apps.contractors.models import Contractor
from apps.core.validators import validate_inn


class PrimaryDocument(models.Model):
    """Первичный учётный документ, поступивший от контрагента."""

    class DocType(models.TextChoices):
        INVOICE = "invoice", "Счёт"
        KS2 = "ks2", "Акт КС-2"
        KS3 = "ks3", "Справка КС-3"
        TORG12 = "torg12", "Накладная ТОРГ-12"
        UPD = "upd", "УПД"
        VAT_INVOICE = "vat_invoice", "Счёт-фактура"

    doc_type = models.CharField("Тип документа", max_length=20, choices=DocType.choices)
    number = models.CharField("Номер", max_length=50)
    date = models.DateField("Дата документа")
    inn = models.CharField("ИНН контрагента в документе", max_length=12, validators=[validate_inn])
    signer_name = models.CharField("ФИО подписанта", max_length=200, blank=True)
    signer_position = models.CharField("Должность подписанта", max_length=200, blank=True)
    amount = models.DecimalField("Сумма, руб.", max_digits=15, decimal_places=2, null=True, blank=True)
    file = models.FileField("Скан/PDF", upload_to="documents/", blank=True)
    created_at = models.DateTimeField("Внесён", auto_now_add=True)

    class Meta:
        verbose_name = "первичный документ"
        verbose_name_plural = "первичные документы"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_doc_type_display()} № {self.number} от {self.date:%d.%m.%Y}"


class DocumentVerification(models.Model):
    """Результат сверки документа с данными ЕГРЮЛ."""

    class NameMatch(models.TextChoices):
        MATCH = "match", "Совпадает"
        MISMATCH = "mismatch", "Не совпадает"
        NO_DATA = "no_data", "Нет данных"

    document = models.OneToOneField(
        PrimaryDocument, on_delete=models.CASCADE, related_name="verification", verbose_name="Документ",
    )
    contractor = models.ForeignKey(
        Contractor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="verifications", verbose_name="Найденный контрагент",
    )
    name_match = models.CharField("Сверка ФИО", max_length=10, choices=NameMatch.choices, default=NameMatch.NO_DATA)
    signer_is_director = models.BooleanField("Подписант — директор", null=True, blank=True)
    issues = models.JSONField("Несоответствия", default=list, blank=True)
    verified_at = models.DateTimeField("Сверено", auto_now_add=True)

    class Meta:
        verbose_name = "результат сверки"
        verbose_name_plural = "результаты сверки"

    @property
    def verdict(self) -> str:
        """error — есть ошибки; warning — только предупреждения; ok — «Соответствует» (замечания info допускаются)."""
        severities = {i["severity"] for i in self.issues}
        return "error" if "error" in severities else "warning" if "warning" in severities else "ok"

    def __str__(self):
        return f"Сверка: {self.document}"
