"""Цветные бейджи: цвет всегда сопровождается текстом."""
from django import template
from django.utils.html import format_html

register = template.Library()

CHECK = {"safe": ("Безопасен", "bg-success"), "risky": ("Рискованный", "bg-warning text-dark"),
         "dangerous": ("Опасный", "bg-danger"), "unknown": ("Недостаточно данных", "bg-secondary")}
VERDICT = {"ok": ("Соответствует", "bg-success"), "warning": ("Требует внимания", "bg-warning text-dark"),
           "error": ("Есть расхождения", "bg-danger")}
SEVERITY = {"error": ("Ошибка", "bg-danger"), "warning": ("Предупреждение", "bg-warning text-dark"),
            "info": ("Замечание", "bg-info text-dark")}
CONTRACTOR = {"active": ("Действующее", "bg-success"), "liquidating": ("В стадии ликвидации", "bg-danger"),
              "liquidated": ("Ликвидировано", "bg-danger"), "bankrupt": ("В стадии банкротства", "bg-danger")}


def _badge(table, key):
    text, css = table.get(key, (key, "bg-secondary"))
    return format_html('<span class="badge {}">{}</span>', css, text)


@register.filter
def status_badge(status):
    return _badge(CHECK, status)


@register.filter
def verdict_badge(verdict):
    return _badge(VERDICT, verdict)


@register.filter
def severity_badge(severity):
    return _badge(SEVERITY, severity)


@register.filter
def contractor_badge(status):
    return _badge(CONTRACTOR, status)
