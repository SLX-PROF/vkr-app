"""Генератор синтетических фикстур источников (tests/fixtures/<источник>/<ИНН>.json).

Все ИНН/ОГРН начинаются с кода региона «00» — такого региона не существует, поэтому
совпадение с реальной организацией исключено, при этом контрольные суммы корректны.
Запуск: python scripts/make_fixtures.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)


def make_inn(serial: int) -> str:
    body = f"0000{serial:05d}"
    return body + str(sum(int(d) * w for d, w in zip(body, W10)) % 11 % 10)


def make_ogrn(serial: int) -> str:
    body = f"1000000{serial:05d}"  # 1 | 00 (год) | 00 (регион) | 00 | серийный номер
    return body + str(int(body) % 11 % 10)


CLEAN = dict(director_companies_count=1, address_companies_count=1, avg_headcount=25, revenue=40_000_000,
             taxes_paid=3_000_000, tax_regime="ОСНО", has_tax_debt=False, tax_debt_amount=0)

# (название, руководитель, сценарий, ожидаемый статус, переопределения по источникам)
SCENARIOS = [
    ("ООО «Тестстрой-1»", "Образцов Пётр Сергеевич", "Чистая компания", "safe", {}),
    ("ООО «Тестстрой-2»", "Тестов Иван Иванович", "Ликвидированная компания", "dangerous",
     {"EGRUL": {"status": "liquidated"}}),
    ("ООО «Тестстрой-3»", "Примеров Олег Андреевич", "Банкрот", "dangerous",
     {"EFRSB": {"bankruptcy": True, "procedure": "Конкурсное производство", "messages_count": 4}}),
    ("ООО «Тестстрой-4»", "Шаблонов Денис Павлович", "Дисквалифицированный директор", "risky",
     {"DISQUALIFIED": {"found": True, "person": "Шаблонов Денис Павлович", "until": "2028-05-01"}}),
    ("ООО «Тестстрой-5»", "Макетов Сергей Борисович", "Массовый адрес и руководитель", "risky",
     {"TRANSPARENT": {"director_companies_count": 8, "address_companies_count": 25}}),
    ("ООО «Тестстрой-6»", "Пробин Алексей Львович", "Много долгов ФССП", "risky",
     {"FSSP": {"active_proceedings": 9, "total_debt": 1_850_000}}),
    ("ООО «Тестстрой-7»", "Демонстров Игорь Николаевич", "Много арбитражных дел", "risky",
     {"KAD": {"cases_last_year": 17, "as_defendant": 14, "as_plaintiff": 3, "lost_cases_amount": 7_400_000}}),
    ("ООО «Тестстрой-8»", "Эталонов Максим Юрьевич", "Фирма-«однодневка»", "risky",
     {"TRANSPARENT": {"avg_headcount": 1, "revenue": 52_000_000, "taxes_paid": 90_000,
                      "director_companies_count": 8, "tax_regime": "УСН",
                      "has_tax_debt": True, "tax_debt_amount": 480_000}}),
]


def build(i, name, director, overrides):
    inn, ogrn = make_inn(i), make_ogrn(i)
    base = {
        "EGRUL": {"inn": inn, "ogrn": ogrn, "full_name": f"ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ {name[4:]}",
                  "short_name": name, "director_name": director, "director_position": "Генеральный директор",
                  "address": f"г. Тестоград, ул. Образцовая, д. {i}", "registration_date": f"20{10 + i:02d}-03-15",
                  "status": "active", "okved_main": "41.20"},
        "TRANSPARENT": dict(CLEAN),
        "DISQUALIFIED": {"found": False, "person": "", "until": None},
        "FSSP": {"active_proceedings": 0, "total_debt": 0},
        "EFRSB": {"bankruptcy": False, "procedure": None, "messages_count": 0},
        "KAD": {"cases_last_year": 1, "as_defendant": 1, "as_plaintiff": 0, "lost_cases_amount": 0},
    }
    for source, changes in overrides.items():
        base[source].update(changes)
    return inn, base


def main():
    index = []
    for i, (name, director, scenario, expected, overrides) in enumerate(SCENARIOS, start=1):
        inn, sources = build(i, name, director, overrides)
        for source, data in sources.items():
            path = ROOT / source.lower() / f"{inn}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index.append({"inn": inn, "name": name, "scenario": scenario, "expected_status": expected})
    text = json.dumps(index, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "demo_contractors.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
