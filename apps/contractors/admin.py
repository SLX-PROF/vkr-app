from django.contrib import admin

from apps.core.admin_mixins import CsvExportMixin

from .models import CheckSession, Contractor, SourceData


@admin.register(Contractor)
class ContractorAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ("inn", "ogrn", "short_name", "director_name", "okved", "status", "egrul_updated_at")
    list_filter = ("status",)
    search_fields = ("inn", "ogrn", "full_name", "short_name", "director_name")


class SourceDataInline(admin.TabularInline):
    model = SourceData
    extra = 0
    readonly_fields = ("source_name", "status", "elapsed", "data")


@admin.register(CheckSession)
class CheckSessionAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ("contractor", "started_at", "initiator", "status", "score", "is_partial")
    list_filter = ("status", "is_partial", "started_at")
    search_fields = ("contractor__inn", "contractor__short_name")
    inlines = [SourceDataInline]


@admin.register(SourceData)
class SourceDataAdmin(CsvExportMixin, admin.ModelAdmin):
    list_display = ("source_name", "session", "status", "elapsed")
    list_filter = ("source_name", "status")
    search_fields = ("session__contractor__inn", "source_name")
