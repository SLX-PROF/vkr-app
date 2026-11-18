import pytest

from apps.reports.scoring import SCORING_CONFIG, calculate_risk_score, config_from_env, status_for_score

CLEAN = {
    "EGRUL": {"status": "active"},
    "TRANSPARENT": {"director_companies_count": 1, "address_companies_count": 1, "avg_headcount": 25,
                    "revenue": 40_000_000, "has_tax_debt": False},
    "DISQUALIFIED": {"found": False},
    "FSSP": {"active_proceedings": 0, "total_debt": 0},
    "EFRSB": {"bankruptcy": False},
    "KAD": {"cases_last_year": 1, "lost_cases_amount": 0},
    "CBR": {"found_by_inn": False},
}


def sources(**changes):
    """Чистая компания с изменёнными блоками: sources(FSSP={...})."""
    return {**{k: dict(v) for k, v in CLEAN.items()}, **changes}


def codes(result):
    return [f.code for f in result.factors]


def test_clean_company_is_safe_with_no_factors():
    result = calculate_risk_score(sources())
    assert (result.score, result.status, result.factors, result.partial) == (0, "safe", [], False)


# --- по одному тесту на каждое правило ------------------------------------

@pytest.mark.parametrize("changes, code, points", [
    ({"EGRUL": {"status": "liquidated"}}, "liquidated", 100),
    ({"EGRUL": {"status": "liquidating"}}, "liquidating", 70),
    ({"EFRSB": {"bankruptcy": True, "procedure": "Наблюдение"}}, "bankruptcy", 80),
    ({"EGRUL": {"status": "bankrupt"}}, "bankruptcy", 80),
    ({"DISQUALIFIED": {"found": True}}, "disqualified", 50),
    ({"TRANSPARENT": {"director_companies_count": 6}}, "mass_director", 20),
    ({"TRANSPARENT": {"address_companies_count": 11}}, "mass_address", 10),
    ({"FSSP": {"total_debt": 50_000}}, "debt_small", 10),
    ({"FSSP": {"total_debt": 100_001}}, "debt_large", 30),
    ({"FSSP": {"active_proceedings": 6}}, "many_proceedings", 20),
    ({"KAD": {"cases_last_year": 11}}, "many_cases", 15),
    ({"KAD": {"lost_cases_amount": 1_000_001}}, "lost_large", 25),
    ({"TRANSPARENT": {"avg_headcount": 1, "revenue": 1}}, "tiny_headcount", 15),
    ({"TRANSPARENT": {"has_tax_debt": True, "tax_debt_amount": 480_000}}, "tax_debt", 15),
])
def test_each_rule_fires_alone(changes, code, points):
    result = calculate_risk_score(sources(**changes))
    assert codes(result) == [code]
    assert result.factors[0].points == points and result.score == points


def test_rule_values_in_config_match_spec():
    assert {k: SCORING_CONFIG[k] for k in ("liquidated", "liquidating", "bankruptcy", "disqualified")} == {
        "liquidated": 100, "liquidating": 70, "bankruptcy": 80, "disqualified": 50}


# --- границы порогов правил (строго больше / строго меньше) ----------------

@pytest.mark.parametrize("changes", [
    {"TRANSPARENT": {"director_companies_count": 5}},
    {"TRANSPARENT": {"address_companies_count": 10}},
    {"FSSP": {"active_proceedings": 5}},
    {"KAD": {"cases_last_year": 10}},
    {"KAD": {"lost_cases_amount": 1_000_000}},
    {"TRANSPARENT": {"avg_headcount": 2, "revenue": 1}},
    {"TRANSPARENT": {"avg_headcount": 1, "revenue": 0}},      # нет выручки
    {"FSSP": {"total_debt": 0}},
    {"TRANSPARENT": {"has_tax_debt": False, "tax_debt_amount": 0}},  # недоимки нет
])
def test_rule_thresholds_do_not_fire(changes):
    assert calculate_risk_score(sources(**changes)).factors == []


def test_debt_exactly_100k_is_small():
    assert codes(calculate_risk_score(sources(FSSP={"total_debt": 100_000}))) == ["debt_small"]


def test_headcount_none_does_not_fire():
    assert calculate_risk_score(sources(TRANSPARENT={"revenue": 5})).factors == []


def test_bankruptcy_counted_once_if_both_sources_say_so():
    result = calculate_risk_score(sources(EGRUL={"status": "bankrupt"}, EFRSB={"bankruptcy": True}))
    assert codes(result) == ["bankruptcy"]


# --- граница статусов 29/30 и 69/70 ----------------------------------------

@pytest.mark.parametrize("score, status", [
    (0, "safe"), (29, "safe"), (30, "risky"), (69, "risky"), (70, "dangerous"), (100, "dangerous")])
def test_status_boundaries(score, status):
    assert status_for_score(score) == status


@pytest.mark.parametrize("weight, status", [(29, "safe"), (30, "risky"), (69, "risky"), (70, "dangerous")])
def test_status_boundaries_end_to_end(weight, status):
    result = calculate_risk_score(sources(DISQUALIFIED={"found": True}), config={"disqualified": weight})
    assert (result.score, result.status) == (weight, status)


def test_real_weights_reach_30_and_70():
    mass = sources(TRANSPARENT={"director_companies_count": 8, "address_companies_count": 25})
    assert (calculate_risk_score(mass).score, calculate_risk_score(mass).status) == (30, "risky")
    both = sources(DISQUALIFIED={"found": True}, TRANSPARENT={"director_companies_count": 8})
    assert (calculate_risk_score(both).score, calculate_risk_score(both).status) == (70, "dangerous")


def test_score_capped_at_100():
    bad = sources(EGRUL={"status": "liquidated"}, DISQUALIFIED={"found": True}, EFRSB={"bankruptcy": True})
    result = calculate_risk_score(bad)
    assert result.score == 100 and result.status == "dangerous" and len(result.factors) == 3


# --- «однодневка»: ограничение суммарной оценки ------------------------------

def test_single_shell_sign_is_safe_but_visible():
    """Один признак «численность < 2» даёт 15 баллов и статус «безопасен», но фактор виден в отчёте."""
    result = calculate_risk_score(sources(TRANSPARENT={"avg_headcount": 1, "revenue": 52_000_000}))
    assert (result.score, result.status) == (15, "safe")
    assert codes(result) == ["tiny_headcount"]
    assert "технической" in result.factors[0].text and result.factors[0].source == "Прозрачный бизнес"


def test_shell_with_mass_director_is_risky():
    pb = {"avg_headcount": 1, "revenue": 52_000_000, "director_companies_count": 8}
    result = calculate_risk_score(sources(TRANSPARENT=pb))
    assert (result.score, result.status) == (35, "risky")


# --- частичная проверка и падение источника --------------------------------

def test_missing_source_skips_rule_and_marks_partial():
    data = sources(FSSP=None, DISQUALIFIED={"found": True})
    result = calculate_risk_score(data)
    assert codes(result) == ["disqualified"]
    assert result.partial and result.missing == ["ФССП"]
    assert "Данные по ФССП получены не были" in result.notes and "Частичная проверка" in result.notes


def test_absent_key_counts_as_missing():
    data = sources()
    del data["KAD"]
    assert calculate_risk_score(data).missing == ["КАД Арбитр"]


def test_all_sources_missing_is_unknown():
    result = calculate_risk_score({})
    assert result.score == 0 and len(result.missing) == 7 and result.partial
    assert result.status == "unknown"


def test_one_missing_source_prevents_safe_verdict():
    result = calculate_risk_score(sources(FSSP=None))
    assert result.status == "unknown" and result.score == 0


def test_missing_sources_do_not_erase_known_danger():
    result = calculate_risk_score({"EGRUL": {"status": "liquidated"}})
    assert result.status == "dangerous" and result.score == 100 and result.partial


def test_lost_amount_is_configurable():
    data = sources(KAD={"lost_cases_amount": 2_000_000})
    assert codes(calculate_risk_score(data)) == ["lost_large"]
    assert calculate_risk_score(data, config={"lost_amount_over": 5_000_000}).factors == []


def test_config_from_env():
    assert config_from_env({"RISK_LOST_AMOUNT_OVER": "3000000", "OTHER": "x"}) == {"lost_amount_over": 3_000_000}


# --- налоговая недоимка (правило 7) -------------------------------------------

def test_tax_debt_flag_without_amount_fires():
    result = calculate_risk_score(sources(TRANSPARENT={"has_tax_debt": True}))
    assert codes(result) == ["tax_debt"] and result.factors[0].text == "Есть недоимка по налогам"


def test_tax_debt_amount_without_flag_fires_and_is_shown():
    result = calculate_risk_score(sources(TRANSPARENT={"has_tax_debt": False, "tax_debt_amount": 1}))
    assert codes(result) == ["tax_debt"] and "1 руб." in result.factors[0].text


def test_tax_debt_alone_is_safe_but_visible():
    """Недоимка — единственное, что проверяет «Валдэкс» сейчас; сама по себе даёт 15 баллов («безопасен»)."""
    result = calculate_risk_score(sources(TRANSPARENT={"has_tax_debt": True}))
    assert (result.score, result.status) == (15, "safe")


def test_tax_debt_pushes_to_risky_exactly_at_boundary():
    # 15 (недоимка) + 15 (численность) = 30 — нижняя граница «рискованного»
    pb = {"has_tax_debt": True, "avg_headcount": 1, "revenue": 1}
    assert (calculate_risk_score(sources(TRANSPARENT=pb)).score,
            calculate_risk_score(sources(TRANSPARENT=pb)).status) == (30, "risky")
    # 15 + 10 (долг ФССП до порога) = 25 — ещё «безопасен»
    result = calculate_risk_score(sources(TRANSPARENT={"has_tax_debt": True}, FSSP={"total_debt": 10_000}))
    assert (result.score, result.status) == (25, "safe")


def test_tax_debt_weight_is_configurable():
    data = sources(TRANSPARENT={"has_tax_debt": True})
    assert calculate_risk_score(data, config={"tax_debt": 0}).factors == []
    assert calculate_risk_score(data, config={"tax_debt": 40}).score == 40
