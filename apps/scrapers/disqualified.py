"""Публичный реестр ФНС: точный поиск руководителя, без обхода CAPTCHA."""
import re
from datetime import date, datetime

from .base import BaseSource, SourceUnavailable
from .egrul import EgrulSource


def normalized_name(value):
    return re.sub(r"[^а-яa-z]", "", (value or "").lower().replace("ё", "е"))


def parse_date(value):
    if not value:
        return None
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value)[:10], pattern).date()
        except ValueError:
            pass
    return None


def normalize_registry(payload, inn, director_name, today=None):
    today = today or date.today()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or "rowCount" not in payload:
        raise SourceUnavailable("Формат ответа реестра не позволяет подтвердить результат поиска")
    rows = payload["data"]
    result = {"found": False, "possible_matches": 0, "unavailable_fields": [], "checked_at": today.isoformat()}
    if payload["rowCount"] > len(rows):
        result["unavailable_fields"].append("full_search_results")
    for row in rows:
        if normalized_name(row.get("ФИО")) != normalized_name(director_name):
            continue
        start, end = parse_date(row.get("ДатаНачДискв")), parse_date(row.get("ДатаКонДискв"))
        if end is not None and end < today or start is not None and start > today:
            continue
        if start is None or end is None or str(row.get("ИННОрг")) != inn:
            result["possible_matches"] += 1
        else:
            result["found"] = True
    if result["possible_matches"]:
        result["unavailable_fields"].append("person_identity_or_period")
        result["warnings"] = ["Есть совпадения ФИО без достаточного подтверждения организации или срока; "
                              "необходима ручная проверка реестра"]
    return result


class DisqualifiedSource(BaseSource):
    name = "Дисквалифицированные лица"
    key = "DISQUALIFIED"
    domain = "service.nalog.ru"

    def fetch_web(self, query):
        mode = self.source_modes["EGRUL"]
        if mode == "mock":
            raise SourceUnavailable("Для реестра нужны реальные сведения о руководителе из ЕГРЮЛ")
        registry = EgrulSource(mode=mode, source_modes=self.source_modes).fetch(query)
        director = registry.data.get("director_name") if registry.ok else None
        if not director:
            raise SourceUnavailable("Не удалось получить ФИО руководителя для проверки реестра")
        response = self.http("POST", "https://service.nalog.ru/disqualified-proc.json",
                             data={"query": director, "page": 1, "pageSize": 50})
        payload = response.json()
        if payload.get("captchaRequired") or payload.get("ERRORS"):
            raise SourceUnavailable("Реестр требует CAPTCHA или ограничил доступ")
        return normalize_registry(payload, query, director)
