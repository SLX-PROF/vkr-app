from io import BytesIO
from pathlib import Path

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from apps.documents import extraction
from apps.documents.models import DocumentUpload, PrimaryDocument

TEXT = "УПД № 17 от 20.05.2026\nИНН: 0000000018\nИтого к оплате: 120 000,00\nГенеральный директор Образцов П.С."
GOOD = {"doc_type": "upd", "number": "17", "date": "2026-05-20", "inn": "0000000018", "amount": "120000",
        "signer_name": "Образцов П.С.", "signer_position": "Генеральный директор", "confirmed": "on"}


def make_pdf(pages=1):
    stream = BytesIO()
    pdfmetrics.registerFont(TTFont("ExtractTest", str(Path("static/fonts/NotoSans-Regular.ttf"))))
    pdf = canvas.Canvas(stream)
    for _ in range(pages):
        pdf.setFont("ExtractTest", 12)
        for i, line in enumerate(TEXT.splitlines()):
            pdf.drawString(40, 780 - i * 30, line)
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


def test_extract_fields_and_keep_valid_inn_only():
    fields, inns, notes = extraction.extract_fields(TEXT + "\nТелефон 1234567890")
    assert fields["inn"] == "0000000018" and inns == ["0000000018"]
    assert fields["number"] == "17" and fields["date"] == "2026-05-20"
    assert fields["amount"] == "120000.00" and fields["signer_name"] == "Образцов П.С."
    assert fields["doc_type"] == "upd" and notes


def test_multiple_parties_require_user_choice():
    fields, inns, notes = extraction.extract_fields(TEXT + "\nПокупатель ИНН/КПП 0000000025/000000000")
    assert len(inns) == 2 and "inn" not in fields
    assert "несколько ИНН" in notes[0]


def test_ocr_label_mixed_alphabet_requires_valid_checksum():
    fields, _, _ = extraction.extract_fields("UHH: 0000000018", ocr=True)
    assert fields["inn"] == "0000000018"
    assert "inn" not in extraction.extract_fields("UHH: 0000000018")[0]
    assert "inn" not in extraction.extract_fields("UHH: 0000000019", ocr=True)[0]


def test_ambiguous_amounts_and_dates_not_selected():
    fields, _, _ = extraction.extract_fields(TEXT + "\nАкт от 01.01.2025\nИтого: 10,00")
    assert "date" not in fields and "amount" not in fields


def test_text_pdf_and_isolated_worker(tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(make_pdf())
    result = extraction.extract_file(path)
    assert result["method"] == "pdf_text" and result["fields"]["inn"] == "0000000018"
    assert result["pages"] == 1 and len(result["sha256"]) == 64


def test_page_limit(tmp_path):
    path = tmp_path / "long.pdf"
    path.write_bytes(make_pdf(21))
    with pytest.raises(extraction.ExtractionError, match="20 страниц"):
        extraction.process_file(path)


def test_image_ocr_path(tmp_path, monkeypatch):
    path = tmp_path / "scan.png"
    Image.new("RGB", (200, 200), "white").save(path)
    monkeypatch.setattr(extraction, "_ocr", lambda p: TEXT)
    result = extraction.process_file(path)
    assert result["method"] == "ocr" and result["fields"]["amount"] == "120000.00"


def test_damaged_file_has_controlled_error(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"not a document")
    with pytest.raises(extraction.ExtractionError):
        extraction.extract_file(path)


@pytest.fixture
def signed_in(client, django_user_model, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    user = django_user_model.objects.create_user("document_uploader")
    user.groups.add(Group.objects.get(name="Бухгалтерия"))
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_upload_confirmation_download_and_original_snapshot(signed_in):
    client, user = signed_in
    content = make_pdf()
    response = client.post(reverse("documents:upload"), {"file": SimpleUploadedFile("example.pdf", content)})
    assert response.status_code == 302 and not PrimaryDocument.objects.exists()
    upload = DocumentUpload.objects.get()
    preview = client.get(response.url)
    assert preview.context["form"].initial["inn"] == "0000000018"
    rejected = client.post(response.url, {k: v for k, v in GOOD.items() if k != "confirmed"})
    assert rejected.status_code == 200 and not PrimaryDocument.objects.exists()
    accepted = client.post(response.url, GOOD)
    doc = PrimaryDocument.objects.get()
    assert accepted.status_code == 302 and doc.processing["confirmed_by"] == user.pk
    assert doc.processing["sha256"] == upload.sha256
    assert doc.processing["extracted_fields"]["amount"] == "120000.00"
    client.post(response.url, GOOD)
    assert PrimaryDocument.objects.count() == 1
    download = client.get(reverse("documents:file", args=[doc.pk]))
    assert b"".join(download.streaming_content) == content and "no-store" in download["Cache-Control"]


@pytest.mark.django_db
def test_upload_private_and_expires(signed_in, django_user_model):
    client, _ = signed_in
    client.post(reverse("documents:upload"), {"file": SimpleUploadedFile("example.pdf", make_pdf())})
    upload = DocumentUpload.objects.get()
    url = reverse("documents:review", args=[upload.pk])
    DocumentUpload.objects.filter(pk=upload.pk).update(created_at=timezone.now() - timezone.timedelta(hours=2))
    assert client.get(url).status_code == 404
    DocumentUpload.objects.filter(pk=upload.pk).update(created_at=timezone.now())
    other = django_user_model.objects.create_user("other_uploader")
    other.groups.add(Group.objects.get(name="Бухгалтерия"))
    client.force_login(other)
    assert client.get(url).status_code == 404
    client.logout()
    assert client.get(url).status_code == 302


@pytest.mark.django_db
def test_upload_failure_cleans_file(signed_in):
    client, _ = signed_in
    response = client.post(reverse("documents:upload"), {"file": SimpleUploadedFile("damaged.pdf", b"bad data")})
    assert response.status_code == 200 and not DocumentUpload.objects.exists()
    assert not PrimaryDocument.objects.exists()


@pytest.mark.django_db
def test_cleanup_keeps_confirmed_documents(signed_in):
    from apps.documents.uploads import cleanup_uploads

    client, _ = signed_in
    first = client.post(reverse("documents:upload"), {"file": SimpleUploadedFile("first.pdf", make_pdf())})
    client.post(first.url, GOOD)
    client.post(reverse("documents:upload"), {"file": SimpleUploadedFile("unused.pdf", make_pdf())})
    used = DocumentUpload.objects.get(document__isnull=False)
    unused = DocumentUpload.objects.get(document__isnull=True)
    used_path, unused_path = Path(used.file.path), Path(unused.file.path)
    DocumentUpload.objects.update(created_at=timezone.now() - timezone.timedelta(hours=2))
    cleanup_uploads()
    assert used_path.exists() and not unused_path.exists()
    assert DocumentUpload.objects.count() == 1 and PrimaryDocument.objects.count() == 1


@pytest.mark.django_db
def test_unsupported_and_oversized_upload(signed_in):
    client, _ = signed_in
    for name, content in [("file.exe", b"bad"), ("large.pdf", b"x" * (extraction.MAX_BYTES + 1))]:
        response = client.post(reverse("documents:upload"), {"file": SimpleUploadedFile(name, content)})
        assert response.status_code == 200 and not DocumentUpload.objects.exists()
