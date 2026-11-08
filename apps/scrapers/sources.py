"""Остальные источники. Реализован режим mock; api/web — через интерфейс BaseSource (пока «недоступен»)."""
from .base import BaseSource
from .disqualified import DisqualifiedSource
from .egrul import EgrulSource
from .transparent import TransparentBusinessSource


class FsspSource(BaseSource):
    name = "ФССП"
    key = "FSSP"
    domain = "fssp.gov.ru"


class EfrsbSource(BaseSource):
    name = "ЕФРСБ"
    key = "EFRSB"
    domain = "bankrot.fedresurs.ru"


class KadSource(BaseSource):
    name = "КАД Арбитр"
    key = "KAD"
    domain = "kad.arbitr.ru"


ALL_SOURCES = [EgrulSource, TransparentBusinessSource, DisqualifiedSource, FsspSource, EfrsbSource, KadSource]
