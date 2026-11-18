"""Источник ЕГРЮЛ: mock (фикстуры), api (DaData по ключу), web (egrul.nalog.ru без обхода CAPTCHA)."""
import json
from datetime import date, datetime, timezone

from django.conf import settings

from .base import BaseSource, SourceUnavailable

DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
EGRUL_URL = "https://egrul.nalog.ru"

DADATA_STATUS = {
    "ACTIVE": "active", "REORGANIZING": "active",
    "LIQUIDATING": "liquidating", "LIQUIDATED": "liquidated", "BANKRUPT": "bankrupt",
}


class EgrulSource(BaseSource):
    name = "ЕГРЮЛ"
    key = "EGRUL"
    domain = "egrul.nalog.ru"

    def fetch_mock(self, query: str) -> dict:
        if len(query) in (13, 15):
            for path in (settings.FIXTURES_DIR / "egrul").glob("*.json"):
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("ogrn") == query:
                    return data
            raise SourceUnavailable("Нет демонстрационных данных для этого ОГРН")
        return super().fetch_mock(query)

    def fetch_api(self, query: str) -> dict:
        """Официального бесплатного API по ИНН у ФНС нет, поэтому используется DaData (ключ в .env)."""
        if not settings.EGRUL_API_KEY:
            raise SourceUnavailable("Не задан EGRUL_API_KEY: режим api для ЕГРЮЛ недоступен")
        response = self.http("POST", DADATA_URL, domain="suggestions.dadata.ru", json={"query": query},
                             headers={"Authorization": f"Token {settings.EGRUL_API_KEY}"})
        suggestions = response.json().get("suggestions")
        if not suggestions:
            raise SourceUnavailable(f"Организация с ИНН {query} не найдена")
        d = next((s["data"] for s in suggestions
                  if query in (s["data"].get("inn"), s["data"].get("ogrn"))), None)
        if d is None:
            raise SourceUnavailable("В ответе источника нет точного совпадения ИНН/ОГРН")
        state, management = d.get("state") or {}, d.get("management") or {}
        registered = state.get("registration_date")  # миллисекунды Unix-времени
        return {
            "inn": d.get("inn", query),
            "ogrn": d.get("ogrn") or "",
            "full_name": (d.get("name") or {}).get("full_with_opf", ""),
            "short_name": (d.get("name") or {}).get("short_with_opf", ""),
            "director_name": management.get("name", ""),
            "director_position": management.get("post", ""),
            "address": (d.get("address") or {}).get("value", ""),
            "registration_date": (
                datetime.fromtimestamp(registered / 1000, timezone.utc).date().isoformat() if registered else None
            ),
            "status": DADATA_STATUS.get(state.get("status"), "active"),
            "okved_main": d.get("okved", ""),
        }

    def fetch_web(self, query: str) -> dict:
        """Разбор публичного поиска egrul.nalog.ru. Если сайт требует CAPTCHA — источник «недоступен»."""
        token = self.http("POST", f"{EGRUL_URL}/", data={"query": query}).json()
        if token.get("captchaRequired") or "t" not in token:
            raise SourceUnavailable("ЕГРЮЛ требует ввода CAPTCHA; автоматически она не обходится")
        rows = self.http("GET", f"{EGRUL_URL}/search-result/{token['t']}").json().get("rows") or []
        row = next((r for r in rows if query in (r.get("i"), r.get("o"))), None)
        if row is None:
            raise SourceUnavailable(f"Организация с ИНН {query} не найдена")
        position, _, name = (row.get("g") or "").partition(":")
        assigned = _iso(row.get("r"))
        # Для компаний, существовавших до ЕГРЮЛ, «r» — дата присвоения ОГРН, а не создания организации.
        legacy = str(row.get("o", ""))[1:3] == "02"
        return {
            "inn": row["i"],
            "ogrn": row.get("o", ""),
            "full_name": row.get("n", ""),
            "short_name": row.get("c", ""),
            "director_name": name.strip(),
            "director_position": position.strip().capitalize() if name else "",
            "address": "",  # в списке результатов адреса нет (он есть только в PDF-выписке)
            "registration_date": None if legacy else assigned,
            "ogrn_assigned_date": assigned,
            "status": "liquidated" if row.get("e") else "active",  # «e» — дата прекращения деятельности
            "okved_main": "",
        }


def _iso(value):
    """'23.10.2002' -> '2002-10-23'."""
    if not value:
        return None
    return date(*map(int, reversed(value.split(".")))).isoformat()
