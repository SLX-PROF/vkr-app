import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache(settings):
    """Кэш источников и счётчики rate limit не должны переходить из теста в тест."""
    cache.clear()
    settings.OFDATA_API_KEY = ""  # тесты не расходуют реальную бесплатную квоту
