"""Public regression: native advancement exposes its learning choices without repository history."""

from tests.test_learning_training_native import native, offered


def test_native_advancement_has_learning_choices_from_its_producer(tmp_path):
    """A native sheet must not fail with KeyError when the producer is wired in."""
    _combat, table = native(tmp_path)

    choices = offered(table, "alchemy")

    assert choices
    assert all(row.get("id") and isinstance(row.get("options"), list) for row in choices)
