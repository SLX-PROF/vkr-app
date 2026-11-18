from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.contractors.models import CheckSession
from apps.core.roles import ALL_ROLES, can_see_details, role_required

from .pdf import build_report


@role_required(*ALL_ROLES)
@require_GET
@never_cache
def contractor_report(request, pk):
    sessions = CheckSession.objects.select_related("contractor", "initiator").prefetch_related("sources")
    session = get_object_or_404(sessions, pk=pk)
    content = build_report(session, show_details=can_see_details(request.user))
    response = HttpResponse(content, content_type="application/pdf")
    filename = f"contractor-{session.contractor.inn}-check-{session.pk}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
