import datetime
from decimal import Decimal

import pytest

from apps.contractors.models import Contractor
from apps.documents.models import DocumentVerification, PrimaryDocument
from apps.documents.verification import compare_names, verify_document
from apps.scrapers.egrul import EgrulSource

pytestmark = pytest.mark.django_db

INN = "0000000018"          # демо-контрагент №1: директор «Образцов Пётр Сергеевич», регистрация 2011-03-15
INN_NO_FIXTURE = "0000000995"  # корректный ИНН без фикстур — источник «недоступен»


def make_doc(**changes):
    values = dict(doc_type="upd", number="17", date=datetime.date(2026, 5, 20), inn=INN,
                  signer_name="Образцов Пётр Сергеевич", signer_position="Генеральный директор",
                  amount=Decimal("1200000.00"))
    values.update(changes)
    return PrimaryDocument.objects.create(**values)


def codes(verification):
    return [i["code"] for i in verification.issues]


def severity(verification, code):
    return next(i["severity"] for i in verification.issues if i["code"] == code)


# --- пять основных кейсов ------------------------------------------------------------------

def test_case_match():
    v = verify_document(make_doc())
    assert v.issues == [] and v.verdict == "ok"
    assert v.name_match == "match" and v.signer_is_director is True and v.contractor.inn == INN


def test_case_typo_in_name_is_match_with_info():
    v = verify_document(make_doc(signer_name="Абразцов Пётр Сергеевич"))
    assert v.name_match == "match" and v.signer_is_director is True
    assert codes(v) == ["SIGNER_NAME_TYPO"] and severity(v, "SIGNER_NAME_TYPO") == "info"
    assert v.verdict == "ok"  # замечание не мешает «Соответствует»


def test_case_foreign_signer():
    v = verify_document(make_doc(signer_name="Тестов Иван Иванович"))
    assert v.name_match == "mismatch" and v.signer_is_director is False
    assert codes(v) == ["SIGNER_NOT_DIRECTOR"]
    assert "Подписант" in v.issues[0]["text"] and "не является действующим руководителем" in v.issues[0]["text"]


def test_case_date_before_registration():
    v = verify_document(make_doc(date=datetime.date(2011, 3, 14)))
    assert codes(v) == ["DATE_BEFORE_REGISTRATION"] and severity(v, "DATE_BEFORE_REGISTRATION") == "error"
    assert v.verdict == "error"


def test_date_equal_to_registration_is_allowed():
    assert verify_document(make_doc(date=datetime.date(2011, 3, 15))).issues == []


def test_case_invalid_inn(monkeypatch):
    monkeypatch.setattr(EgrulSource, "fetch", lambda *a: pytest.fail("ЕГРЮЛ не должен запрашиваться при неверном ИНН"))
    v = verify_document(make_doc(inn="1234567890"))
    assert codes(v) == ["INN_INVALID"] and severity(v, "INN_INVALID") == "error"
    assert v.contractor is None and v.name_match == "no_data" and v.signer_is_director is None


# --- подписант не директор, доверенности нет: предупреждение, а не ошибка ---------------------

def test_signer_not_director_is_warning_not_error():
    v = verify_document(make_doc(signer_name="Тестов Иван Иванович", signer_position="Заместитель директора"))
    assert severity(v, "SIGNER_NOT_DIRECTOR") == "warning"
    assert not [i for i in v.issues if i["severity"] == "error"]
    assert v.verdict == "warning"
    assert "доверенност" in v.issues[0]["text"] and "приказ" in v.issues[0]["text"]


# --- обязательные реквизиты ФЗ-402 и серьёзность ------------------------------------------------

@pytest.mark.parametrize("changes, code, expected", [
    ({"signer_name": ""}, "SIGNER_MISSING", "error"),
    ({"signer_position": " "}, "POSITION_MISSING", "error"),
    ({"amount": None}, "AMOUNT_MISSING", "error"),
    ({"amount": Decimal("0")}, "AMOUNT_MISSING", "error"),
    ({"inn": ""}, "INN_MISSING", "error"),
    ({"number": "", "doc_type": "upd"}, "NUMBER_MISSING", "error"),
    ({"number": "", "doc_type": "vat_invoice"}, "NUMBER_MISSING", "error"),
    ({"number": "", "doc_type": "ks2"}, "NUMBER_MISSING", "warning"),
    ({"number": "", "doc_type": "invoice"}, "NUMBER_MISSING", "warning"),
])
def test_missing_requisite_severity(changes, code, expected):
    v = verify_document(make_doc(**changes))
    assert severity(v, code) == expected


def test_missing_signer_does_not_trigger_signer_comparison():
    v = verify_document(make_doc(signer_name=""))
    assert codes(v) == ["SIGNER_MISSING"] and v.name_match == "no_data" and v.signer_is_director is None


def test_all_requisites_missing_reports_each():
    v = verify_document(make_doc(number="", inn="", amount=None, signer_name="", signer_position="", doc_type="ks3"))
    assert set(codes(v)) == {"NUMBER_MISSING", "INN_MISSING", "AMOUNT_MISSING", "SIGNER_MISSING", "POSITION_MISSING"}


# --- поиск контрагента -------------------------------------------------------------------------

def test_unknown_contractor_triggers_quick_egrul_check_and_is_saved():
    assert not Contractor.objects.filter(inn=INN).exists()
    v = verify_document(make_doc())
    assert Contractor.objects.get(inn=INN).director_name == "Образцов Пётр Сергеевич"
    assert v.contractor.egrul_updated_at is not None


def test_known_contractor_does_not_trigger_egrul(monkeypatch):
    verify_document(make_doc())
    monkeypatch.setattr(EgrulSource, "fetch", lambda *a: pytest.fail("повторный запрос ЕГРЮЛ не нужен"))
    assert verify_document(make_doc(number="18")).issues == []


def test_egrul_unavailable_is_warning_and_no_comparison():
    v = verify_document(make_doc(inn=INN_NO_FIXTURE))
    assert codes(v) == ["EGRUL_UNAVAILABLE"] and severity(v, "EGRUL_UNAVAILABLE") == "warning"
    assert v.contractor is None and v.name_match == "no_data"
    assert not Contractor.objects.filter(inn=INN_NO_FIXTURE).exists()


def test_contractor_without_egrul_data_is_refreshed():
    Contractor.objects.create(inn=INN)  # заготовка без данных ЕГРЮЛ (например, после неудачной проверки)
    v = verify_document(make_doc())
    assert v.issues == [] and v.contractor.director_name


def test_contractor_without_director_in_egrul():
    Contractor.objects.create(inn=INN, egrul_updated_at="2026-01-01T00:00:00Z")
    v = verify_document(make_doc())
    assert set(codes(v)) == {"NO_DIRECTOR_DATA", "REGISTRATION_DATE_UNKNOWN"} and v.name_match == "no_data"


def test_reverify_updates_same_record():
    doc = make_doc(signer_name="Тестов Иван Иванович")
    verify_document(doc)
    doc.signer_name = "Образцов П.С."
    v = verify_document(doc)
    assert DocumentVerification.objects.count() == 1 and v.issues == []


# --- сравнение ФИО ----------------------------------------------------------------------------

@pytest.mark.parametrize("signer, expected", [
    ("Образцов Пётр Сергеевич", "exact"),
    ("  ОБРАЗЦОВ   ПЕТР  СЕРГЕЕВИЧ ", "exact"),     # регистр, пробелы, «ё»/«е»
    ("Образцов П.С.", "exact"),
    ("Образцов П. С.", "exact"),
    ("П.С. Образцов", "exact"),
    ("Образцов П.", "exact"),                       # один инициал
    ("Образцов Пётр", "exact"),                     # без отчества
    ("Абразцов Пётр Сергеевич", "typo"),            # опечатка в фамилии (сходство 0,875)
    ("Образцов Пётр Сергеевч", "typo"),             # опечатка в отчестве
    ("Образцов Игорь Сергеевич", "different"),      # другое имя при той же фамилии
    ("Образцов И.С.", "different"),                 # другой инициал
    ("Тестов Иван Иванович", "different"),
    ("Образцов", "different"),                      # одна фамилия — слишком слабо
    ("", None),
    ("   ", None),
])
def test_compare_names(signer, expected):
    assert compare_names(signer, "Образцов Пётр Сергеевич") == expected


def test_compare_names_no_director():
    assert compare_names("Образцов П.С.", "") is None


def test_compare_names_double_surname():
    assert compare_names("Иванова-Петрова А.Б.", "Иванова-Петрова Анна Борисовна") == "exact"


def test_date_missing_is_error_for_unsaved_document():
    from apps.documents.verification import check_requisites
    doc = PrimaryDocument(
        doc_type="upd", number="1", date=None, inn=INN, signer_name="А", signer_position="Б", amount=1)
    assert [i["code"] for i in check_requisites(doc)] == ["DATE_MISSING"]


def test_str_of_models():
    doc = make_doc()
    assert str(doc) == "УПД № 17 от 20.05.2026" and str(verify_document(doc)).startswith("Сверка:")
