"""Ограничение частоты запросов с одного IP (для эндпоинта проверки: 5 в минуту)."""
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse


def client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "")


def is_limited(key: str, limit: int = 5, window: int = 60) -> bool:
    """Считает обращения по ключу в окне `window` секунд; True, если лимит превышен."""
    cache.add(key, 0, window)
    return cache.incr(key) > limit


def rate_limit(limit: int = 5, window: int = 60):
    """Декоратор для view: при превышении лимита отвечает 429."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if is_limited(f"rl:{view.__name__}:{client_ip(request)}", limit, window):
                return HttpResponse("Слишком много запросов, повторите позже.", status=429)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
