"""Оркестратор проверки: опрос всех источников параллельно, скоринг, сохранение результата."""
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core.validators import validate_inn
from apps.reports.scoring import SCORING_CONFIG, calculate_risk_score, config_from_env
from apps.scrapers.base import SourceResult
from apps.scrapers.sources import ALL_SOURCES

from .models import CheckSession, Contractor, SourceData

TOTAL_BUDGET = 60  # секунд на все источники — проектное ограничение, фактическое время см. docs/testing_report.md

EGRUL_STATUS = {
    "active": Contractor.Status.ACTIVE,
    "liquidating": Contractor.Status.LIQUIDATING,
    "liquidated": Contractor.Status.LIQUIDATED,
    "bankrupt": Contractor.Status.BANKRUPT,
}


def fetch_all(inn: str, source_modes=None) -> dict:
    """Запускает все источники параллельно; не успевшие за TOTAL_BUDGET получают статус «таймаут»."""
    sources = [cls(mode=source_modes[cls.key], source_modes=source_modes) if source_modes else cls()
               for cls in ALL_SOURCES]
    pool = ThreadPoolExecutor(max_workers=len(sources))
    futures = {pool.submit(source.fetch, inn): source for source in sources}
    done, _ = wait(futures, timeout=TOTAL_BUDGET)
    pool.shutdown(wait=False, cancel_futures=True)
    results = {}
    for future, source in futures.items():
        if future not in done:
            result = SourceResult(ok=False, error=f"Превышен общий лимит времени {TOTAL_BUDGET} с",
                                  elapsed=TOTAL_BUDGET, status="timeout")
        else:
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 — защита оркестратора от ошибки реализации провайдера
                result = SourceResult(ok=False, error=f"Ошибка провайдера: {type(exc).__name__}", status="error")
        results[source] = result
    return results


def update_contractor(inn: str, egrul: dict | None, bankrupt: bool) -> Contractor:
    """Создаёт или обновляет карточку; если ЕГРЮЛ не ответил, прежние данные не затираются."""
    contractor, _ = Contractor.objects.get_or_create(inn=inn)
    if egrul:
        for name in ("ogrn", "full_name", "short_name", "director_name", "director_position", "address"):
            if egrul.get(name):
                setattr(contractor, name, egrul[name])
        contractor.okved = egrul.get("okved_main") or contractor.okved
        if egrul.get("registration_date"):
            contractor.registration_date = date.fromisoformat(egrul["registration_date"])
        contractor.status = EGRUL_STATUS.get(egrul.get("status"), Contractor.Status.ACTIVE)
        contractor.egrul_updated_at = timezone.now()
    if bankrupt:
        contractor.status = Contractor.Status.BANKRUPT
    contractor.save()
    return contractor


def run_check(inn: str, user=None, source_modes=None) -> CheckSession:
    """Полная проверка контрагента по ИНН. Неверный ИНН — ValidationError."""
    validate_inn(inn)
    started_at = timezone.now()
    results = fetch_all(inn, source_modes) if source_modes else fetch_all(inn)
    data = {source.key: (result.data if result.ok else None) for source, result in results.items()}
    config = {**SCORING_CONFIG, **config_from_env()}
    score = calculate_risk_score(data, config)
    bankrupt = bool((data["EFRSB"] or {}).get("bankruptcy"))
    with transaction.atomic():
        contractor = update_contractor(inn, data["EGRUL"], bankrupt)
        transparent = data["TRANSPARENT"] or {}
        registered = transparent.get("registration_date")
        if registered:
            contractor.registration_date = date.fromisoformat(registered)
            contractor.save(update_fields=["registration_date"])
        for target, field in (("address", "address"), ("okved", "okved_main")):
            if transparent.get(field):
                setattr(contractor, target, transparent[field])
                contractor.save(update_fields=[target])
        session = CheckSession.objects.create(
            contractor=contractor, initiator=user, status=score.status, score=score.score,
            factors=score.factors_as_dicts(), is_partial=score.partial,
            started_at=started_at,
            scoring_config=config, is_demo=any(s.mode == "mock" for s in results),
        )
        SourceData.objects.bulk_create(
            SourceData(session=session, source_name=source.name, data=result.data,
                       status=result.status, elapsed=result.elapsed,
                       mode=source.mode, error=result.error)
            for source, result in results.items()
        )
    return session
