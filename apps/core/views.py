from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001 — внешнему проверяющему не раскрываются параметры БД
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
