from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.roles import ALL_ROLES, role_required

from .forms import DocumentForm
from .models import PrimaryDocument
from .verification import verify_document


@role_required(*ALL_ROLES)
def document_verify(request):
    form = DocumentForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            document = form.save()
            verify_document(document)
        return redirect("documents:result", pk=document.pk)
    return render(request, "documents/verify.html", {"form": form})


@role_required(*ALL_ROLES)
def document_result(request, pk):
    document = get_object_or_404(PrimaryDocument.objects.select_related("verification__contractor"), pk=pk)
    return render(request, "documents/result.html", {"document": document, "verification": document.verification})
