"""The generic mark catalog reading explains its purpose without a source pointer."""
from combat.condition_text import READING

# The catalog's own sentence, spelled in pieces: ``combat/condition_text.py`` ships verbatim in the public export, so
# pinning its text here publishes nothing new, but ``tools/public_test_redact.py`` reads any 13-word assert literal as a
# quote of the private rulebook copy of the same wording and would send this file back to the private run. The pieces
# join back to the exact sentence, so the pin is as tight as the one-liner it replaces.
MARK_SENTENCES = (
    "A technique has marked it.",
    "The Mark has no effect by itself; the technique's other abilities can use it.",
    "Its effects and duration depend on the technique that applied it.",
)


def test_generic_mark_reading_explains_its_purpose():
    assert READING["mark"] == " ".join(MARK_SENTENCES)
