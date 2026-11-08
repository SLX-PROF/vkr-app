from django.contrib import admin

from apps.core.admin_mixins import CsvExportMixin

from .models import DocumentVerification, PrimaryDocument


@admin.register(PrimaryDocument)
class PrimaryDocumentAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ("doc_type", "number", "date", "inn", "signer_name", "amount")
    list_filter = ("doc_type", "date")
    search_fields = ("number", "inn", "signer_name")


@admin.register(DocumentVerification)
class DocumentVerificationAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ("document", "contractor", "name_match", "signer_is_director", "verified_at")
    list_filter = ("name_match", "signer_is_director")
    search_fields = ("document__number", "document__inn", "contractor__inn")
