"""Public synthetic fixture kept for legacy Soul Contract test imports."""
import pytest


@pytest.fixture
def source_checkpoint():
    """Compatibility value; unlike the old helper this reads no repository history."""
    return None
