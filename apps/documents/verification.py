"""Сверка первичного документа с данными ЕГРЮЛ.

Серьёзность несоответствий:
  error   — документ нельзя принять без исправления (нет обязательного реквизита, неверный ИНН, дата раньше
            регистрации контрагента);
  warning — нужна проверка человеком (подписант не директор — проверить доверенность или приказ;
            данные ЕГРЮЛ получить не удалось);
  info    — замечание без последствий (неточное совпадение ФИО).
"""
import re
from difflib import SequenceMatcher

from apps.contractors.models import Contractor
from apps.contractors.services import update_contractor
from apps.core.validators import is_valid_inn
from apps.scrapers.egrul import EgrulSource

from .models import DocumentVerification, PrimaryDocument

SIMILARITY = 0.85  # порог нечёткого сравнения (difflib.SequenceMatcher)
ERROR, WARNING, INFO = "error", "warning", "info"
# Для счёта-фактуры и УПД номер обязателен по НК РФ (ст. 169); для остальных документов ФЗ-402 его прямо не называет.
NUMBER_REQUIRED_TYPES = (PrimaryDocument.DocType.VAT_INVOICE, PrimaryDocument.DocType.UPD)


def issue(code: str, text: str, severity: str) -> dict:
    return {"code": code, "text": text, "severity": severity}


# --- сравнение ФИО -----------------------------------------------------------------------------

def _tokens(name: str) -> list:
    """Слова ФИО в нижнем регистре, «ё» → «е»; точки и пробелы разделяют инициалы («П.С.» → п, с)."""
    return re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)*", name.lower().replace("ё", "е"))


def _split(name: str):
    """Фамилия — первое слово длиннее одной буквы (допускается запись «П.С. Образцов»); остальное — имя, отчество."""
    tokens = _tokens(name)
    for i, token in enumerate(tokens):
        if len(token) > 1:
            return token, tokens[:i] + tokens[i + 1:]
    return None


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def compare_names(signer: str, director: str):
    """'exact' | 'typo' | 'different' | None (нет данных для сравнения).

    Фамилия сравнивается нечётко (порог SIMILARITY); имя и отчество — нечётко, если записаны полностью,
    и по первой букве, если хотя бы с одной стороны инициал. Только фамилия без имени — не совпадение.
    """
    s, d = _split(signer or ""), _split(director or "")
    if not s or not d:
        return None
    (s_surname, s_rest), (d_surname, d_rest) = s, d
    if _similar(s_surname, d_surname) < SIMILARITY:
        return "different"
    exact = s_surname == d_surname
    pairs = list(zip(s_rest, d_rest))
    if not pairs:
        return "different"
    for a, b in pairs:
        if len(a) == 1 or len(b) == 1:
            if a[0] != b[0]:
                return "different"
        elif a != b:
            if _similar(a, b) < SIMILARITY:
                return "different"
            exact = False
    return "exact" if exact else "typo"


# --- обязательные реквизиты (ФЗ-402, ст. 9, ч. 2) -------------------------------------------------

def check_requisites(doc: PrimaryDocument) -> list:
    issues = []
    if not (doc.number or "").strip():
        severity = ERROR if doc.doc_type in NUMBER_REQUIRED_TYPES else WARNING
        issues.append(issue("NUMBER_MISSING", "Не указан номер документа", severity))
    if not doc.date:
        issues.append(issue("DATE_MISSING", "Не указана дата составления документа", ERROR))
    if not (doc.inn or "").strip():
        issues.append(issue("INN_MISSING", "Не указан ИНН контрагента", ERROR))
    elif not is_valid_inn(doc.inn):
        issues.append(issue("INN_INVALID", f"ИНН {doc.inn} некорректен: неверная длина или контрольная сумма", ERROR))
    if not doc.amount:
        issues.append(issue("AMOUNT_MISSING", "Не указана сумма документа (или она равна нулю)", ERROR))
    elif doc.amount < 0:
        issues.append(issue("AMOUNT_INVALID", "Для этого вида сверки сумма должна быть положительной", ERROR))
    if not (doc.signer_name or "").strip():
        issues.append(issue("SIGNER_MISSING", "Нет подписи: не указаны фамилия и инициалы подписанта", ERROR))
    if not (doc.signer_position or "").strip():
        issues.append(issue("POSITION_MISSING", "Не указана должность подписанта", ERROR))
    return issues


# --- сверка ------------------------------------------------------------------------------------

def find_contractor(inn: str, issues: list):
    """Контрагент из БД; если его нет или данных ЕГРЮЛ ещё не было — быстрая проверка ЕГРЮЛ."""
    contractor = Contractor.objects.filter(inn=inn).first()
    if contractor is None or contractor.egrul_updated_at is None:
        result = EgrulSource().fetch(inn)
        if result.ok:
            contractor = update_contractor(inn, result.data, bankrupt=False)
        else:
            issues.append(issue(
                "EGRUL_UNAVAILABLE",
                f"Данные ЕГРЮЛ получить не удалось ({result.error}): сверка подписанта и даты невозможна", WARNING))
    return contractor


def verify_document(doc: PrimaryDocument) -> DocumentVerification:
    issues = check_requisites(doc)
    contractor, name_match, signer_is_director = None, DocumentVerification.NameMatch.NO_DATA, None

    if is_valid_inn(doc.inn):
        contractor = find_contractor(doc.inn, issues)
    has_egrul = contractor is not None and contractor.egrul_updated_at is not None

    if has_egrul and doc.signer_name.strip():
        if not contractor.director_name:
            issues.append(issue(
                "NO_DIRECTOR_DATA", "В ЕГРЮЛ нет сведений о руководителе: подписанта сверить нельзя", WARNING))
        else:
            verdict = compare_names(doc.signer_name, contractor.director_name)
            signer_is_director = verdict in ("exact", "typo")
            if verdict is None:
                signer_is_director = None
                issues.append(issue("SIGNER_UNREADABLE", "ФИО подписанта не удалось разобрать для сравнения", WARNING))
            elif verdict == "different":
                name_match = DocumentVerification.NameMatch.MISMATCH
                issues.append(issue(
                    "SIGNER_NOT_DIRECTOR",
                    f"Подписант «{doc.signer_name}» не является действующим руководителем согласно данным ЕГРЮЛ "
                    f"(«{contractor.director_name}»). Проверьте доверенность или приказ о полномочиях: "
                    "данных о них в системе нет", WARNING))
            else:
                name_match = DocumentVerification.NameMatch.MATCH
                if verdict == "typo":
                    issues.append(issue(
                        "SIGNER_NAME_TYPO",
                        f"ФИО подписанта «{doc.signer_name}» совпало с руководителем «{contractor.director_name}» "
                        "неточно — возможна опечатка", INFO))

    if has_egrul and doc.date and contractor.registration_date and doc.date < contractor.registration_date:
        issues.append(issue(
            "DATE_BEFORE_REGISTRATION",
            f"Дата документа {doc.date:%d.%m.%Y} раньше даты регистрации контрагента "
            f"{contractor.registration_date:%d.%m.%Y}", ERROR))
    elif has_egrul and doc.date and not contractor.registration_date:
        issues.append(issue("REGISTRATION_DATE_UNKNOWN", "Дата создания организации не установлена: "
                            "хронологическую проверку выполнить нельзя", WARNING))

    verification, _ = DocumentVerification.objects.update_or_create(
        document=doc,
        defaults={"contractor": contractor, "name_match": name_match,
                  "signer_is_director": signer_is_director, "issues": issues},
    )
    return verification
