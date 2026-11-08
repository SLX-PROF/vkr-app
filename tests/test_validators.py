import pytest
from django.core.exceptions import ValidationError

from apps.core.validators import is_valid_inn, is_valid_ogrn, validate_inn, validate_ogrn

# Реквизиты ООО «Валдэкс» из ТЗ и общеизвестные примеры
VALID_INN10 = "7703317501"
VALID_INN12 = "500100732259"
VALID_OGRN13 = "1027700348070"
VALID_OGRN15 = "304500116000157"


@pytest.mark.parametrize("value", [VALID_INN10, VALID_INN12])
def test_valid_inn(value):
    assert is_valid_inn(value)
    validate_inn(value)


@pytest.mark.parametrize("value", [
    "7703317502",      # неверная контрольная цифра (10)
    "500100732258",    # неверная 12-я цифра
    "500100732249",    # неверная 11-я цифра
    "770331750",       # 9 цифр
    "77033175011",     # 11 цифр
    "77033175ab",      # не цифры
    "",
])
def test_invalid_inn(value):
    assert not is_valid_inn(value)
    with pytest.raises(ValidationError):
        validate_inn(value)


@pytest.mark.parametrize("value", [VALID_OGRN13, VALID_OGRN15])
def test_valid_ogrn(value):
    assert is_valid_ogrn(value)
    validate_ogrn(value)


@pytest.mark.parametrize("value", [
    "1027700348071",     # неверная контрольная цифра (13)
    "304500116000158",   # неверная контрольная цифра (15)
    "102770034807",      # 12 цифр
    "10277003480701",    # 14 цифр
    "10277003480ab",
    "",
])
def test_invalid_ogrn(value):
    assert not is_valid_ogrn(value)
    with pytest.raises(ValidationError):
        validate_ogrn(value)
