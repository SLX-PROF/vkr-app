"""Общий миксин админки: экспорт выбранных записей в CSV."""
import csv

from django.contrib import admin
from django.http import HttpResponse


class CsvExportMixin:
    """Добавляет действие «Экспорт в CSV» (поля берутся из list_display)."""

    actions = ["export_csv"]

    @admin.action(description="Экспорт выбранных в CSV")
    def export_csv(self, request, queryset):
        fields = [f for f in self.list_display if f != "__str__"]
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{self.model._meta.model_name}.csv"'
        response.write("﻿")  # BOM, чтобы Excel открыл кириллицу
        writer = csv.writer(response, delimiter=";")
        writer.writerow(fields)
        for obj in queryset:
            writer.writerow([_cell(obj, f) for f in fields])
        return response


def _cell(obj, name):
    value = getattr(obj, name)
    value = value() if callable(value) else value
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
