"""Валидаторы ИНН и ОГРН (длина и контрольные цифры)."""
from django.core.exceptions import ValidationError

# Весовые коэффициенты для контрольных цифр ИНН
_INN10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_FIRST = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_SECOND = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def is_valid_inn(value: str) -> bool:
    """ИНН юрлица — 10 цифр, ИП/физлица — 12; проверяется контрольная сумма."""
    if not value or not value.isascii() or not value.isdigit():
        return False
    if len(value) == 10:
        return _check_digit(value, _INN10) == int(value[9])
    if len(value) == 12:
        return (
            _check_digit(value, _INN12_FIRST) == int(value[10])
            and _check_digit(value, _INN12_SECOND) == int(value[11])
        )
    return False


def is_valid_ogrn(value: str) -> bool:
    """ОГРН — 13 цифр (юрлицо, делитель 11) или 15 цифр (ОГРНИП, делитель 13)."""
    if not value or not value.isascii() or not value.isdigit():
        return False
    if len(value) == 13:
        return int(value[:12]) % 11 % 10 == int(value[12])
    if len(value) == 15:
        return int(value[:14]) % 13 % 10 == int(value[14])
    return False


def validate_inn(value: str) -> None:
    if not is_valid_inn(value):
        raise ValidationError("Некорректный ИНН: нужно 10 или 12 цифр с верной контрольной суммой.")


def validate_ogrn(value: str) -> None:
    if not is_valid_ogrn(value):
        raise ValidationError("Некорректный ОГРН: нужно 13 или 15 цифр с верной контрольной цифрой.")
