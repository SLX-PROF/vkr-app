"""Подключение к документированному API «Офдата» с ограничением бесплатных запросов."""
import hashlib
import re
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .base import BaseSource, SourceUnavailable

API_URL = "https://api.ofdata.ru/v2/"
MAX_PAGES = 3


def amount(value):
    """Отсутствующая, отрицательная или некорректная сумма остаётся неизвестной."""
    if value is None or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
        return float(n) if n.is_finite() and n >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def normalized(value):
    return re.sub(r"[\W_]+", "", str(value or "").casefold().replace("ё", "е"))


class OfdataSource(BaseSource):
    """Запросы отправляются POST, чтобы ключ не попадал в адреса и текст HTTP-ошибок."""
    cache_version = 2

    @property
    def mode(self):
        selected = super().mode
        return "api" if selected == "web" and settings.OFDATA_API_KEY else selected

    def request_data(self, method, inn, deadline, **params):
        key = settings.OFDATA_API_KEY
        if not key:
            raise SourceUnavailable("Для бесплатного API нужен ключ «Офдаты»; добавьте OFDATA_API_KEY")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout()
        quota_key = ("ofdata-quota:" + hashlib.sha256(key.encode()).hexdigest()[:16]
                     + ":" + timezone.localdate().isoformat())
        cache.add(quota_key, 0, 48 * 3600)
        count = cache.incr(quota_key)
        if count > settings.OFDATA_DAILY_LIMIT:
            raise SourceUnavailable("Достигнут установленный суточный лимит бесплатного API")
        response = self.http("POST", API_URL + method, domain="api.ofdata.ru",
                             data={"key": key, "inn": inn, **params}, timeout=min(15, remaining))
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
            raise SourceUnavailable("Поставщик вернул неожиданный формат данных")
        meta = payload["meta"]
        remote_count = meta.get("today_request_count")
        if isinstance(remote_count, int) and remote_count > count:
            # Учитываем обращения из других приложений с этим же ключом.
            cache.incr(quota_key, remote_count - count)
        if meta.get("status") != "ok":
            raise SourceUnavailable("API не предоставил данные: проверьте ключ, доступ к методу и суточный лимит")
        company = payload.get("company") or payload.get("entrepreneur") or payload.get("data")
        if not isinstance(company, dict) or company.get("ИНН") != inn:
            raise SourceUnavailable("API не подтвердил точное совпадение ИНН")
        return payload

    def pages(self, method, inn, **params):
        deadline = time.monotonic() + 40
        records, company, total = [], {}, None
        complete = True
        for page in range(1, MAX_PAGES + 1):
            payload = self.request_data(method, inn, deadline, page=page, limit=100, **params)
            company = payload.get("company") or payload.get("entrepreneur")
            if not isinstance(company, dict):
                raise SourceUnavailable("API не выдал реквизиты участника поиска")
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("Записи"), list):
                raise SourceUnavailable("API не выдал список записей источника")
            pages = data.get("СтрВсего")
            current = data.get("СтрТекущ")
            if (type(pages) is not int or pages < 0 or type(current) is not int
                    or current != page or (pages == 0 and data["Записи"])):
                raise SourceUnavailable("API не подтвердил полноту страниц результатов")
            if total is not None and total != data.get("ЗапВсего"):
                complete = False
            total = data.get("ЗапВсего")
            if not all(isinstance(row, dict) for row in data["Записи"]):
                raise SourceUnavailable("API вернул некорректные записи источника")
            records.extend(data["Записи"])
            if pages <= page:
                break
        else:
            complete = False
        return company, records, complete, total


class FsspSource(OfdataSource):
    name = "ФССП"
    key = "FSSP"
    domain = "fssp.gov.ru"

    def fetch_web(self, query):
        raise SourceUnavailable("Бесплатный автоматический доступ к ФССП подключается через API «Офдата» по ключу")

    def fetch_api(self, query):
        company, rows, complete, _ = self.pages("enforcements", query)
        names = {normalized(company.get(k)) for k in ("НаимПолн", "НаимСокр")} - {""}
        address = normalized(company.get("ЮрАдрес"))
        confirmed, candidates, seen = [], [], set()
        for row in rows:
            number = row.get("ИспПрНомер")
            if not number or number in seen:
                complete = False
                continue
            seen.add(number)
            # Поставщик предупреждает о нечётком поиске. Суммы не начисляются по одним похожим именам.
            exact = normalized(row.get("ДолжНаим")) in names and address and normalized(row.get("ДолжАдрес")) == address
            (confirmed if exact else candidates).append(row)
        debts = [amount(r.get("ОстЗадолж")) for r in confirmed]
        known = [x for x in debts if x is not None]
        unavailable = ["active_proceedings"]  # API не возвращает состояние окончания производства.
        if not complete or candidates or len(known) != len(debts):
            unavailable.append("total_debt")
        return {"inn": query, "provider": "Офдата", "primary_url": "https://fssp.gov.ru/iss/ip/",
                "total_debt": round(sum(known), 2) if "total_debt" not in unavailable else None,
                "confirmed_debt_lower_bound": round(sum(known), 2), "active_proceedings": None,
                "records": confirmed, "candidate_records": candidates, "unavailable_fields": unavailable,
                "limitation": "Принадлежность проверяется по точному наименованию и адресу; "
                              "активность производств API не сообщает."}


class EfrsbSource(OfdataSource):
    name = "ЕФРСБ"
    key = "EFRSB"
    domain = "bankrot.fedresurs.ru"

    def fetch_web(self, query):
        raise SourceUnavailable("Федресурс требует CAPTCHA; сообщения подключаются через API по ключу")

    def fetch_api(self, query):
        payload = self.request_data("company", query, time.monotonic() + 20)
        messages = payload["data"].get("ЕФРСБ")
        if not isinstance(messages, list) or not all(isinstance(row, dict) for row in messages):
            raise SourceUnavailable("API не предоставил сведения ЕФРСБ для этой компании")
        return {"inn": query, "provider": "Офдата", "primary_url": "https://bankrot.fedresurs.ru/",
                "messages": messages, "has_bankruptcy_messages": bool(messages), "bankruptcy": None,
                "unavailable_fields": ["bankruptcy"],
                "limitation": "Сообщения ЕФРСБ не устанавливают текущую стадию банкротства; "
                              "её нужно подтвердить судебным актом."}


class KadSource(OfdataSource):
    name = "КАД Арбитр"
    key = "KAD"
    domain = "kad.arbitr.ru"

    def fetch_web(self, query):
        raise SourceUnavailable("Автоматический поиск КАД подключается через бесплатный API по ключу")

    def fetch_api(self, query):
        end = timezone.localdate()
        try:
            start = end.replace(year=end.year - 1)
        except ValueError:
            start = end - timedelta(days=365)
        _, rows, complete, total = self.pages("legal-cases", query,
                                             date_from=start.isoformat(), date_to=end.isoformat())
        confirmed, candidates, seen = [], [], set()
        for row in rows:
            identity = row.get("UUID") or row.get("Номер")
            if not identity or identity in seen:
                complete = False
                continue
            seen.add(identity)
            participants = (row.get("Ист") or []) + (row.get("Ответ") or [])
            exact = any(isinstance(p, dict) and p.get("ИНН") == query for p in participants)
            try:
                in_period = start <= date.fromisoformat(str(row.get("Дата", ""))[:10]) <= end
            except ValueError:
                in_period = False
            (confirmed if exact and in_period else candidates).append(row)
        if total is not None and (type(total) is not int or total != len(rows)):
            complete = False
        unavailable = ["lost_cases_amount"]
        if not complete or candidates:
            unavailable.append("cases_last_year")
        return {"inn": query, "provider": "Офдата", "primary_url": "https://kad.arbitr.ru/",
                "period_start": start.isoformat(), "period_end": end.isoformat(),
                "cases_last_year": len(confirmed) if "cases_last_year" not in unavailable else None,
                "confirmed_cases_lower_bound": len(confirmed), "lost_cases_amount": None,
                "records": confirmed, "candidate_records": candidates, "unavailable_fields": unavailable,
                "limitation": "Сведения поставщика могут поступать с задержкой 1–2 недели. "
                              "Сумма иска не считается суммой проигранного дела."}
