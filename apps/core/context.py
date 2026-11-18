from django.conf import settings

from .roles import ALL_ROLES, can_see_details, has_role


def roles(request):
    """Переменные для шаблонов: has_role_any (есть любая роль), can_see_details (видит факторы риска)."""
    user = request.user
    return {"has_role_any": has_role(user, *ALL_ROLES), "can_see_details": can_see_details(user),
            "demo_mode": "mock" in settings.SOURCE_MODES.values()}
