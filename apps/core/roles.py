"""Роли пользователей — группы Django (создаются миграцией apps/core/0001_roles).

Бухгалтерия — дашборд, проверка контрагента и документов, но не детальные факторы риска;
СБ и юристы — всё, включая факторы; Администратор — то же и админка (нужен флаг is_staff).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ACCOUNTING = "Бухгалтерия"
SECURITY = "СБ и юристы"
ADMIN = "Администратор"
ALL_ROLES = (ACCOUNTING, SECURITY, ADMIN)


def has_role(user, *roles) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name__in=roles).exists()


def can_see_details(user) -> bool:
    """Детальные факторы риска доступны СБ, юристам и администратору."""
    return has_role(user, SECURITY, ADMIN)


def role_required(*roles):
    """Не вошёл — на страницу входа; вошёл, но без нужной роли — 403."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied("Недостаточно прав для просмотра этой страницы.")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
