"""Расчёт индекса риска (Risk Score, 0–100) по данным источников.

Чистая функция без обращения к БД. Все веса и пороги — в одном словаре SCORING_CONFIG
(из него строится таблица весов в ВКР). Любое значение можно переопределить: параметром
`config` или переменной окружения RISK_<КЛЮЧ> (например, RISK_LOST_AMOUNT_OVER=2000000).
"""
import os
from dataclasses import asdict, dataclass, field

SCORING_CONFIG = {
    # --- веса правил (баллы) ---
    "liquidated": 100,        # ЕГРЮЛ: ликвидировано / исключено — критический стоп-фактор
    "liquidating": 70,        # ЕГРЮЛ: в стадии ликвидации (решение автора, не из ТЗ)
    "bankruptcy": 80,         # ЕФРСБ (или статус ЕГРЮЛ): процедура банкротства
    "disqualified": 50,       # руководитель в реестре дисквалифицированных
    "mass_director": 20,      # массовый руководитель
    "mass_address": 10,       # массовый адрес
    "debt_small": 10,         # ФССП: долг до порога debt_large_over
    "debt_large": 30,         # ФССП: долг свыше порога
    "many_proceedings": 20,   # ФССП: много активных производств
    "many_cases": 15,         # КАД: много исков за год
    "lost_large": 25,         # КАД: проиграны дела на крупную сумму
    "tiny_headcount": 15,     # ПБ: численность < 2 при наличии выручки (признак «технической» компании)
    "tax_debt": 15,           # ПБ: есть недоимка по налогам (правило 7 ТЗ v1.2)
    "unreliable_address": 30,  # дополнительные экспертные правила; требуют проверки на выборке
    "unreliable_director": 40,
    "unreliable_details": 30,  # общий флаг, только если конкретные признаки не установлены
    "cbr_warning": 70,         # точное совпадение ИНН в открытом перечне ЦБ
    # --- пороги правил ---
    "mass_director_over": 5,       # фирм у одного руководителя: строго больше
    "mass_address_over": 10,       # фирм по одному адресу: строго больше
    "debt_large_over": 100_000,    # руб.
    "proceedings_over": 5,         # активных производств: строго больше
    "cases_over": 10,              # исков за последний год: строго больше
    "lost_amount_over": 1_000_000,  # руб.; «крупная сумма» — экспертный параметр, подбирается по типовым договорам
    "headcount_below": 2,          # человек: строго меньше
    # --- итоговые границы статусов ---
    "score_max": 100,
    "risky_from": 30,       # 0–29 безопасен
    "dangerous_from": 70,   # 30–69 рискованный, 70–100 опасный
}

SOURCE_NAMES = {
    "EGRUL": "ЕГРЮЛ", "TRANSPARENT": "Прозрачный бизнес", "DISQUALIFIED": "Дисквалифицированные лица",
    "FSSP": "ФССП", "EFRSB": "ЕФРСБ", "KAD": "КАД Арбитр",
    "CBR": "ЦБ: нелегальная деятельность",
}


@dataclass
class Factor:
    code: str
    points: int
    text: str
    source: str = ""


@dataclass
class ScoreResult:
    score: int
    status: str  # safe | risky | dangerous | unknown
    factors: list = field(default_factory=list)
    missing: list = field(default_factory=list)  # названия источников, данные которых не получены
    incomplete: list = field(default_factory=list)  # ответ есть, но часть показателей неизвестна

    @property
    def partial(self) -> bool:
        return bool(self.missing or self.incomplete)

    @property
    def notes(self) -> list:
        notes = [f"Данные по {name} получены не были" for name in self.missing]
        notes += [f"Данные по {name} получены не полностью" for name in self.incomplete]
        return notes + (["Частичная проверка"] if self.partial else [])

    def factors_as_dicts(self) -> list:
        return [asdict(f) for f in self.factors]


def config_from_env(environ=os.environ) -> dict:
    """Переопределения весов и порогов из переменных RISK_<КЛЮЧ>."""
    return {k: int(environ[f"RISK_{k.upper()}"]) for k in SCORING_CONFIG if f"RISK_{k.upper()}" in environ}


def status_for_score(score: int, config: dict = SCORING_CONFIG) -> str:
    if score >= config["dangerous_from"]:
        return "dangerous"
    if score >= config["risky_from"]:
        return "risky"
    return "safe"


def calculate_risk_score(sources: dict, config: dict | None = None) -> ScoreResult:
    """sources: {ключ источника: нормализованный словарь | None, если данных нет}."""
    cfg = {**SCORING_CONFIG, **(config or {})}
    factors = []

    def hit(code, text, source):
        if cfg[code]:
            factors.append(Factor(code, cfg[code], text, SOURCE_NAMES[source]))

    egrul, pb, disq = sources.get("EGRUL"), sources.get("TRANSPARENT"), sources.get("DISQUALIFIED")
    fssp, efrsb, kad = sources.get("FSSP"), sources.get("EFRSB"), sources.get("KAD")

    if egrul and egrul.get("status") == "liquidated":
        hit("liquidated", "Организация ликвидирована или исключена из ЕГРЮЛ", "EGRUL")
    elif egrul and egrul.get("status") == "liquidating":
        hit("liquidating", "Организация находится в стадии ликвидации", "EGRUL")

    if (efrsb and efrsb.get("bankruptcy")) or (egrul and egrul.get("status") == "bankrupt"):
        procedure = (efrsb or {}).get("procedure") or "процедура банкротства"
        hit("bankruptcy", f"Организация в стадии банкротства: {procedure}", "EFRSB" if efrsb else "EGRUL")

    if disq and disq.get("found"):
        hit("disqualified", "Руководитель найден в реестре дисквалифицированных лиц", "DISQUALIFIED")

    if pb:
        if pb.get("unreliable_address") is True:
            hit("unreliable_address", "ФНС: недостоверность сведений об адресе", "TRANSPARENT")
        if pb.get("unreliable_director") is True:
            hit("unreliable_director", "ФНС: недостоверность сведений о руководителе", "TRANSPARENT")
        if (pb.get("unreliable_details") is True and not pb.get("unreliable_address")
                and not pb.get("unreliable_director")):
            hit("unreliable_details", "ФНС: запись о недостоверности сведений без установленной детализации",
                "TRANSPARENT")
        if (pb.get("director_companies_count") or 0) > cfg["mass_director_over"]:
            hit("mass_director", f"Массовый руководитель: {pb['director_companies_count']} организаций", "TRANSPARENT")
        if (pb.get("address_companies_count") or 0) > cfg["mass_address_over"]:
            hit("mass_address", f"Массовый адрес: {pb['address_companies_count']} организаций", "TRANSPARENT")
        headcount = pb.get("avg_headcount")
        if headcount is not None and headcount < cfg["headcount_below"] and (pb.get("revenue") or 0) > 0:
            hit("tiny_headcount", f"Численность {headcount} чел. при наличии выручки — признак «технической» компании",
                "TRANSPARENT")
        tax_debt = pb.get("tax_debt_amount") or 0
        if pb.get("has_tax_debt") or tax_debt > 0:
            amount = f" на сумму {tax_debt:,} руб.".replace(",", " ") if tax_debt else ""
            hit("tax_debt", f"Есть недоимка по налогам{amount}", "TRANSPARENT")

    if fssp:
        debt = fssp.get("total_debt") or fssp.get("confirmed_debt_lower_bound") or 0
        debt_label = ("Подтверждённая задолженность по исполнительным производствам не менее"
                      if fssp.get("total_debt") is None else "Задолженность по исполнительным производствам")
        if debt > cfg["debt_large_over"]:
            hit("debt_large", f"{debt_label} {debt:,} руб.".replace(",", " "), "FSSP")
        elif debt > 0:
            hit("debt_small", f"{debt_label} {debt:,} руб.".replace(",", " "), "FSSP")
        if (fssp.get("active_proceedings") or 0) > cfg["proceedings_over"]:
            hit("many_proceedings", f"Активных исполнительных производств: {fssp['active_proceedings']}", "FSSP")

    if kad:
        case_count = kad.get("cases_last_year")
        lower_bound = case_count is None
        case_count = case_count if case_count is not None else kad.get("confirmed_cases_lower_bound", 0)
        if case_count > cfg["cases_over"]:
            prefix = "не менее " if lower_bound else ""
            hit("many_cases", f"Арбитражных дел за последний год: {prefix}{case_count}", "KAD")
        if (kad.get("lost_cases_amount") or 0) > cfg["lost_amount_over"]:
            hit("lost_large", f"Проиграны дела на сумму {kad['lost_cases_amount']:,} руб.".replace(",", " "), "KAD")

    if (sources.get("CBR") or {}).get("found_by_inn") is True:
        hit("cbr_warning", "ИНН найден в перечне ЦБ с признаками нелегальной финансовой деятельности", "CBR")

    score = min(sum(f.points for f in factors), cfg["score_max"])
    missing = [name for key, name in SOURCE_NAMES.items() if not sources.get(key)]
    incomplete = [name for key, name in SOURCE_NAMES.items()
                  if sources.get(key) and sources[key].get("unavailable_fields")]
    status = status_for_score(score, cfg)
    if (missing or incomplete) and status == "safe":
        status = "unknown"
    return ScoreResult(score, status, factors, missing, incomplete)
