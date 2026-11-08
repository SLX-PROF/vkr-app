import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.contractors.models import CheckSession, Contractor, SourceData
from apps.documents.models import DocumentVerification, PrimaryDocument

pytestmark = pytest.mark.django_db

INN = "7703317501"


def test_contractor_inn_unique():
    Contractor.objects.create(inn=INN, short_name="ООО «Тест»")
    with pytest.raises(IntegrityError):
        Contractor.objects.create(inn=INN)


def test_contractor_inn_validated_by_full_clean():
    with pytest.raises(ValidationError):
        Contractor(inn="7703317502").full_clean()


def test_check_session_chain():
    user = get_user_model().objects.create_user("buh", password="x")
    contractor = Contractor.objects.create(inn=INN)
    session = CheckSession.objects.create(contractor=contractor, initiator=user, status="safe", score=0)
    SourceData.objects.create(session=session, source_name="ЕГРЮЛ", status=SourceData.Status.SUCCESS, data={"a": 1})
    assert session.sources.get().data == {"a": 1}
    assert contractor.checks.count() == 1


def test_document_verification_one_to_one():
    doc = PrimaryDocument.objects.create(doc_type="upd", number="1", date=datetime.date(2026, 1, 1), inn=INN)
    DocumentVerification.objects.create(document=doc, issues=[{"code": "X"}])
    with pytest.raises(IntegrityError):
        DocumentVerification.objects.create(document=doc)
