"""Публичный поиск «Прозрачного бизнеса»: без ключа и без обхода CAPTCHA."""
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import requests

from .base import BaseSource, SourceUnavailable

URL = "https://pb.nalog.ru"


def number(value):
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).replace(" ", "").replace(",", "."))
        return float(result) if result.is_finite() else None
    except InvalidOperation:
        return None


def normalize_company(payload, inn):
    """Не заменяет отсутствующие показатели нулями и не складывает разные отчётные периоды."""
    data = payload.get("vyp") or {}
    if data.get("ИНН") != inn:
        raise SourceUnavailable("В ответе ФНС нет точного совпадения ИНН")
    years_match = data.get("sschr_yearcode") == data.get("form1_yearcode")
    headcount = number(data.get("sschr")) if years_match else None
    revenue = number(data.get("revenuesum")) if years_match else None
    # pr_zd — признак задолженности; totalarrearsum — общая задолженность, включая пени/штрафы.
    # Для правила налоговой недоимки используем именно arrearsum последнего периода.
    periods = [(number(r.get("yearcode")), number(r.get("periodcode"))) for r in payload.get("arrear", [])]
    periods = [p for p in periods if None not in p]
    latest = max(periods) if periods else None
    arrears = [number(r.get("arrearsum")) for r in payload.get("arrear", [])
               if (number(r.get("yearcode")), number(r.get("periodcode"))) == latest]
    debt = round(sum(arrears), 2) if arrears and all(x is not None for x in arrears) else None
    directors = [number(r.get("cnt")) for r in data.get("masruk", [])]
    directors = max(directors) if directors and all(x is not None for x in directors) else None
    addresses = payload.get("masaddress")
    address_counts = [number(r.get("cnt")) for r in addresses] if isinstance(addresses, list) else []
    address_count = max(address_counts) if address_counts and all(x is not None for x in address_counts) else None
    result = {"inn": inn, "avg_headcount": headcount, "revenue": revenue,
              "has_tax_debt": debt > 0 if debt is not None else None, "tax_debt_amount": debt,
              "director_companies_count": directors, "address_companies_count": address_count,
              "headcount_year": data.get("sschr_yearcode"), "revenue_year": data.get("form1_yearcode"),
              "tax_debt_period": list(latest) if latest else None,
              "source_dates": payload.get("oddate", {}), "unavailable_fields": [],
              "address": data.get("АдресРФ") or data.get("Адрес") or "",
              "okved_main": data.get("КодОКВЭД") or "",
              "registry_snapshot_date": data.get("ДатаВып")}
    result.update(normalize_unreliability(data))
    registered = data.get("ДатаРег")
    if registered:
        try:
            result["registration_date"] = (date.fromisoformat(registered) if '-' in registered
                                            else date(*map(int, reversed(registered.split('.'))))).isoformat()
        except (ValueError, AttributeError):
            result["registration_date"] = None
    result["unavailable_fields"] = [k for k in ("avg_headcount", "revenue", "tax_debt_amount",
                                                "director_companies_count", "address_companies_count",
                                                "unreliable_details", "unreliable_address", "unreliable_director")
                                      if result[k] is None]
    return result


def normalize_unreliability(data):
    """Признаки по полям официальной карточки ФНС; массовость не означает недостоверность."""
    value = number(data.get("invalid"))
    general = bool(value) if value in (0, 1) else None
    addresses = data.get("НедСвАдресЮЛ")
    address_notes = [str(row["ТекстНедАдресЮЛ"]).strip() for row in addresses or []
                     if isinstance(row, dict) and row.get("ТекстНедАдресЮЛ")]
    directors = data.get("masruk")
    director_notes = [str(row["invalid"]).strip() for row in directors or []
                      if isinstance(row, dict) and row.get("invalid")]
    # Если общий флаг положительный, отсутствие детализации не доказывает достоверность конкретного поля.
    address = True if address_notes else False if general is False or addresses == [] else None
    director = True if director_notes else False if general is False else None
    if address_notes or director_notes:
        general = True
    return {"unreliable_details": general, "unreliable_address": address,
            "unreliable_director": director, "unreliable_address_notes": address_notes,
            "unreliable_director_notes": director_notes}


class TransparentBusinessSource(BaseSource):
    cache_version = 2
    name = "Прозрачный бизнес"
    key = "TRANSPARENT"
    domain = "pb.nalog.ru"

    def _post(self, session, endpoint, data, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Исчерпан бюджет получения данных ФНС")
        response = self.http("POST", URL + endpoint, session=session, data=data, timeout=min(15, remaining))
        payload = response.json()
        if isinstance(payload, dict) and (payload.get("captchaRequired") or payload.get("ERRORS")):
            raise SourceUnavailable("ФНС требует CAPTCHA или ограничила запрос; автоматический обход не выполняется")
        return payload

    def _poll(self, session, endpoint, request, deadline):
        for _ in range(5):
            time.sleep(1)
            data = {"id": request["id"], "method": "get-response"}
            if request.get("token"):
                data["token"] = request["token"]
            payload = self._post(session, endpoint, data, deadline)
            if payload is not None:
                return payload
        raise requests.Timeout("ФНС не подготовила ответ за отведённое время")

    def fetch_web(self, query):
        deadline = time.monotonic() + 30
        with requests.Session() as session:
            search = self._post(session, "/search-proc.json",
                                {"mode": "search-ul", "queryUl": query, "page": 1, "pageSize": 10}, deadline)
            if not search or not search.get("id"):
                raise SourceUnavailable("ФНС не выдала идентификатор поиска")
            found = self._poll(session, "/search-proc.json", search, deadline)
            row = next((r for r in (found.get("ul") or {}).get("data", []) if r.get("inn") == query), None)
            if not row or not row.get("token"):
                raise SourceUnavailable("Юридическое лицо не найдено в «Прозрачном бизнесе»")
            request = self._post(session, "/company-proc.json",
                                 {"token": row["token"], "method": "get-request"}, deadline)
            if not request or not request.get("id"):
                raise SourceUnavailable("ФНС не подготовила запрос сведений организации")
            payload = self._poll(session, "/company-proc.json", request, deadline)
            return normalize_company(payload, query)
