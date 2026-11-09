"""Journal comparisons for the AI-turn timing probe use exact played bytes."""
import hashlib

from tools.ai_turn_journal import journal_summary


def test_journal_summary_compares_bytes_and_allows_reference_suffix(tmp_path):
    journal = tmp_path / "played.ndjson"
    reference = tmp_path / "reference.ndjson"
    first = b'{"record_sequence":1,"actor":"a"}\n'
    second = b'{"record_sequence":2,"actor":"b"}\n'
    journal.write_bytes(first)
    reference.write_bytes(first + second)
    assert journal_summary(journal, reference) == {
        "journal_md5": hashlib.md5(first).hexdigest(),
        "last_sequence": 1, "first_different_sequence": None,
    }
    journal.write_bytes(first + b'{"record_sequence":2, "actor":"b"}\n')
    assert journal_summary(journal, reference)["first_different_sequence"] == 2
    reference.write_bytes(first)
    assert journal_summary(journal, reference)["first_different_sequence"] == 2
