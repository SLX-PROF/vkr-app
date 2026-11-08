import hashlib
import uuid
from datetime import timedelta

from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ratelimit import rate_limit
from apps.core.roles import ALL_ROLES, role_required

from .extraction import ExtractionError, extract_file
from .forms import ConfirmDocumentForm, DocumentForm, SignatureForm, UploadForm
from .models import DocumentUpload, PrimaryDocument
from .signatures import verify_cms, verify_pdf
from .uploads import cleanup_uploads
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
    return render(request, "documents/result.html", {"document": document, "verification": document.verification,
                                                     "signature_form": SignatureForm()})


@role_required(*ALL_ROLES)
@rate_limit(limit=5, window=60)
def document_upload(request):
    cleanup_uploads()
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        file = form.cleaned_data["file"]
        upload = DocumentUpload.objects.create(file=file, user=request.user,
                                                original_name=file.name.replace("\\", "/").split("/")[-1][:200])
        try:
            upload.extraction = extract_file(upload.file.path)
        except ExtractionError as exc:
            upload.file.delete(save=False)
            upload.delete()
            form.add_error("file", str(exc))
        else:
            upload.sha256 = upload.extraction["sha256"]
            upload.save(update_fields=["extraction", "sha256"])
            return redirect("documents:review", pk=upload.pk)
    return render(request, "documents/upload.html", {"form": form})


@role_required(*ALL_ROLES)
def document_review(request, pk):
    with transaction.atomic():
        upload = get_object_or_404(DocumentUpload.objects.select_for_update(), pk=pk, user=request.user,
                                   created_at__gte=timezone.now() - timedelta(hours=1))
        if upload.document_id:
            return redirect("documents:result", pk=upload.document_id)
        form = ConfirmDocumentForm(request.POST if request.method == "POST" else None,
                                   initial=upload.extraction.get("fields", {}))
        if request.method == "POST" and form.is_valid():
            document = form.save(commit=False)
            document.file.name = upload.file.name
            document.processing = {"method": upload.extraction["method"], "sha256": upload.sha256,
                                   "pages": upload.extraction["pages"], "original_name": upload.original_name,
                                   "extracted_fields": upload.extraction.get("fields", {}),
                                   "signature_fields": upload.extraction.get("signature_fields", 0),
                                   "confirmed_by": request.user.pk, "confirmed_at": timezone.now().isoformat(),
                                   "notes": upload.extraction.get("notes", [])}
            document.save()
            verify_document(document)
            upload.document = document
            upload.save(update_fields=["document"])
            return redirect("documents:result", pk=document.pk)
    return render(request, "documents/review.html", {"form": form, "upload": upload})


@role_required(*ALL_ROLES)
def document_file(request, pk):
    document = get_object_or_404(PrimaryDocument, pk=pk)
    if not document.file:
        from django.http import Http404
        raise Http404
    response = FileResponse(document.file.open("rb"), as_attachment=True,
                            filename=document.processing.get("original_name") or "document.pdf")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@role_required(*ALL_ROLES)
@require_POST
@rate_limit(limit=5, window=60)
def document_signature(request, pk):
    document = get_object_or_404(PrimaryDocument, pk=pk)
    if not document.file:
        return redirect("documents:result", pk=pk)
    form = SignatureForm(request.POST, request.FILES)
    embedded = request.POST.get("kind") == "embedded"
    if not embedded and not form.is_valid():
        return render(request, "documents/result.html", {"document": document,
                      "verification": document.verification, "signature_form": form})
    with document.file.open("rb") as source:
        content = source.read()
    saved = ""
    if embedded:
        checks = verify_pdf(content)
        if not checks:
            checks = [{"integrity": "not_found", "trust": "not_checked", "revocation": "not_checked",
                       "message": "Встроенные подписи в PDF не найдены"}]
    else:
        file = form.cleaned_data["signature"]
        signature = file.read()
        checks = [verify_cms(content, signature)]
        file.seek(0)
        saved = default_storage.save("document_signatures/" + uuid.uuid4().hex + ".sig", file)
        checks[0]["signature_sha256"] = hashlib.sha256(signature).hexdigest()
    try:
        with transaction.atomic():
            document = PrimaryDocument.objects.select_for_update().get(pk=pk)
            history = document.processing.get("signature_checks", [])
            history.append({"kind": "embedded" if embedded else "detached", "results": checks,
                            "checked_by": request.user.pk, "checked_at": timezone.now().isoformat(),
                            "signature_file": saved})
            document.processing = {**document.processing, "signature_checks": history}
            document.save(update_fields=["processing"])
            verify_document(document)
    except Exception:
        if saved:
            default_storage.delete(saved)
        raise
    return redirect("documents:result", pk=pk)
