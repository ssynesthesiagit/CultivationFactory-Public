"""Owner-text guard and behaviour pin for Swift Movement (TAL_ATHLETICS_SWIFT_MOVEMENT).

The owner's printed clause is not quoted in the public tree (F20 finding 1). This file pins only the behaviour the
clause grants: while Martial Focus is held, walking Speed is 10 feet higher, and spending Focus removes it. The guard
below fails if any test under tests/ quotes the printed clause or pins its source hash again.
"""
from pathlib import Path

from tests.test_auto_athletics import FOCUS, SWIFT, _engine, _me

TESTS = Path(__file__).resolve().parent
# Built from pieces so that this guard file does not itself contain the quoted clause.
CLAUSE = 'increase all movement Speeds by ' + '10 feet'
SOURCE_HASH_PREFIX = 'b86068e8' + 'd978c534'


def test_swift_movement_adds_ten_feet_only_while_focus_is_held():
    engine = _engine([SWIFT], speed_focus=1)
    held = engine._effective_speed(_me(engine))
    _me(engine).resources[FOCUS] = 0
    spent = engine._effective_speed(_me(engine))
    assert held - spent == 10


def test_no_test_file_quotes_the_owner_clause_or_pins_its_source_hash():
    offenders = []
    for path in sorted(TESTS.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if CLAUSE in text or SOURCE_HASH_PREFIX in text:
            offenders.append(path.name)
    assert offenders == []
