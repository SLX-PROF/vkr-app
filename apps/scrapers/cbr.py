"""Открытый перечень ЦБ: признаки нелегальной деятельности на финансовом рынке."""
from .base import BaseSource, SourceUnavailable

URL = "https://www.cbr.ru/warninglistapi"
LIMITATION = "Поиск по ИНН в открытом перечне нелегальной финансовой деятельности. Часть записей не содержит ИНН."


class CbrWarningSource(BaseSource):
    name = "ЦБ: нелегальная деятельность"
    key = "CBR"
    domain = "www.cbr.ru"

    def fetch_web(self, query):
        payload = self.http("GET", URL + "/Search", params={"sphrase": query, "page": 0}).json()
        rows = payload.get("Data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) > 10:
            raise SourceUnavailable("ЦБ вернул неожиданный или слишком широкий результат поиска")
        matches, uncertain = [], False
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                raise SourceUnavailable("ЦБ не выдал идентификатор записи перечня")
            detail = self.http("GET", URL + "/DetailInfo", params={"id": row["id"]}).json()
            info = detail.get("Info") if isinstance(detail, dict) else None
            if not isinstance(info, list) or not info:
                raise SourceUnavailable("ЦБ не выдал сведения для подтверждения ИНН")
            for company in info:
                inn = str(company.get("inn") or "").strip()
                if not inn:
                    uncertain = True
                elif inn == query:
                    matches.append({"id": row["id"], "inn": inn, "name": company.get("nameOrg"),
                                    "included_at": company.get("dt"), "updated_at": company.get("dateUpdate"),
                                    "signs": [s.get("signRus", "") for s in detail.get("Signs", [])]})
        return {"inn": query, "found_by_inn": True if matches else None if uncertain else False,
                "records": matches, "limitation": LIMITATION,
                "unavailable_fields": ["found_by_inn"] if uncertain and not matches else []}

    fetch_api = fetch_web
