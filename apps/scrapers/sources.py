"""Доступные провайдеры проверки контрагентов."""
from .cbr import CbrWarningSource
from .disqualified import DisqualifiedSource
from .egrul import EgrulSource
from .ofdata import EfrsbSource, FsspSource, KadSource
from .transparent import TransparentBusinessSource

ALL_SOURCES = [EgrulSource, TransparentBusinessSource, DisqualifiedSource, FsspSource, EfrsbSource, KadSource,
               CbrWarningSource]
