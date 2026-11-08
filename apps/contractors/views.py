from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ratelimit import rate_limit
from apps.core.roles import ALL_ROLES, can_see_details, role_required
from apps.core.validators import is_valid_inn, is_valid_ogrn
from apps.documents.models import DocumentVerification
from apps.reports.observations import source_evidence, source_observations
from apps.scrapers.egrul import EgrulSource
from apps.scrapers.sources import ALL_SOURCES

from .models import CheckSession, Contractor
from .services import run_check

SOURCE_URLS = {cls.name: f"https://{cls.domain}" for cls in ALL_SOURCES}


@role_required(*ALL_ROLES)
def dashboard(request):
    recent = CheckSession.objects.select_related("contractor")[:10]
    since = timezone.now() - timedelta(days=30)
    latest_per_contractor = (CheckSession.objects.filter(started_at__gte=since)
                             .order_by("contractor_id", "-started_at").distinct("contractor_id"))
    counts = Counter(session.status for session in latest_per_contractor)
    stats = [(key, label, counts.get(key, 0)) for key, label in CheckSession.Status.choices]
    return render(request, "contractors/dashboard.html", {"recent": recent, "stats": stats})


@role_required(*ALL_ROLES)
@require_POST
@rate_limit(limit=5, window=60)
def check_contractor(request):
    """Быстрая проверка по ИНН или ОГРН с точным поиском идентификатора в ЕГРЮЛ."""
    query = request.POST.get("query", "").strip()
    profile = request.POST.get("profile", "configured")
    if profile not in ("configured", "live", "demo"):
        messages.error(request, "Неизвестный режим проверки")
        return redirect("dashboard")
    modes = {c.key: "mock" if profile == "demo" else "web" for c in ALL_SOURCES} if profile != "configured" else None
    inn = query
    if is_valid_ogrn(query):
        known = Contractor.objects.filter(ogrn=query).first()
        if known is None:
            source = EgrulSource(mode=modes["EGRUL"], source_modes=modes) if modes else EgrulSource()
            registry = source.fetch(query)
            inn = registry.data.get("inn", "") if registry.ok else ""
            if not is_valid_inn(inn):
                messages.error(request, "Контрагент с таким ОГРН не найден в доступном источнике — введите его ИНН.")
                return redirect("dashboard")
        else:
            inn = known.inn
    elif not is_valid_inn(query):
        messages.error(request, "Введите корректный ИНН (10 или 12 цифр) или ОГРН (13 или 15 цифр).")
        return redirect("dashboard")
    try:
        if modes:
            run_check(inn, request.user, source_modes=modes)
        else:
            run_check(inn, request.user)
    except ValidationError as exc:  # на случай рассинхрона валидаторов
        messages.error(request, exc.messages[0])
        return redirect("dashboard")
    return redirect("contractor_card", pk=Contractor.objects.get(inn=inn).pk)


@role_required(*ALL_ROLES)
def contractor_card(request, pk):
    contractor = get_object_or_404(Contractor, pk=pk)
    checks = list(contractor.checks.order_by("started_at"))
    latest = checks[-1] if checks else None
    details = can_see_details(request.user)
    factors = [{**f, "url": SOURCE_URLS.get(f["source"], "")} for f in latest.factors] if latest and details else []
    context = {
        "contractor": contractor,
        "latest": latest,
        "check_history": list(reversed(checks)),
        "chart": [{"date": timezone.localtime(c.started_at).strftime("%d.%m.%Y"), "score": c.score} for c in checks],
        "missing_sources": [s.source_name for s in latest.sources.all()
                            if s.status != "success" or s.data.get("unavailable_fields")] if latest else [],
        "factors": factors,
        "observations": source_observations(list(latest.sources.all())) if latest and details else [],
        "evidence": source_evidence(list(latest.sources.all())) if latest and details else [],
        "source_statuses": [{"name": s.source_name, "status": s.get_status_display(),
                             "mode": s.mode, "partial": bool(s.data.get("unavailable_fields")),
                             "error": s.error, "url": SOURCE_URLS.get(s.source_name, "")}
                            for s in latest.sources.all()] if latest else [],
        "verifications": DocumentVerification.objects.filter(contractor=contractor)
        .select_related("document").order_by("-verified_at"),
    }
    return render(request, "contractors/card.html", context)
