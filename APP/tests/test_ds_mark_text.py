"""The generic mark catalog reading explains its purpose without a source pointer."""
from combat.condition_text import READING


def test_generic_mark_reading_explains_its_purpose():
    assert READING["mark"] == ("A technique has marked it. The Mark has no effect by itself; "
                                "the technique's other abilities can use it. "
                                "Its effects and duration depend on the technique that applied it.")
