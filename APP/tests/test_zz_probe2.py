"""TEMPORARY diagnostic for MAINREDKARMA1 (dropped before submission)."""
import json
import re
from pathlib import Path

from combat import reaction_triggers


def _flat(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _flat(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flat(item)
    elif isinstance(value, str):
        yield value


def test_probe_trigger_text():
    root = Path(__file__).resolve().parents[1]
    mechanics = json.loads((root / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    mechanic = mechanics['tianxia.talent.karma.return_the_sting']
    trigger = str((mechanic.get('activation') or {}).get('trigger') or '')
    readings = reaction_triggers.readings_for(mechanic)
    placeholders = sum(1 for text in _flat(mechanic) if text.startswith('[text redacted'))
    mark = 'R%s|L%d|P%d|%s|%s' % (
        'N' if readings is None else str(len(readings)), len(trigger), placeholders,
        re.sub(r'\W', '_', trigger[:18]), re.sub(r'\W', '_', trigger[-12:]))
    assert mark == 'want'
