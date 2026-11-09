"""Heaven's Luck's out-of-combat Cultivation Check rider keeps its printed once-between-sessions limit (LUCK3FIGHT1 F1R fix).

Owner ruling 2026-10-22 changed only the in-fight limit (three uses per fight). The GM rider for using the same reroll on a
Cultivation Check between fights is an out-of-combat effect and keeps the printed "once between Full Cultivation Sessions"
limit. Both the reviewed source and the generated authority must carry it.

## Stays private
The assertions quote the owner's printed rider wording, and the public export scrambles owner text and omits
reviewed_final.d/, so this file must run only on the private side (LUCK3FIGHT1 F1R: public run failed on both).
"""
import json
from pathlib import Path

AUTH = Path(__file__).resolve().parents[1] / 'authority'
KEY = 'insight.legacy-heavens-luck'
RIDER = 'GM: You may also use this same once-between-sessions reroll on a Cultivation Check. The table does not yet offer that use.'


def _reviewed_rider():
    data = json.loads((AUTH / 'typed_mechanics' / 'reviewed_final.d' / 'a2_insights_five.json').read_text())
    return data[KEY]['riders'] if KEY in data else _find_riders(data)


def _find_riders(node):
    if isinstance(node, dict):
        if KEY in node and isinstance(node[KEY], dict) and 'riders' in node[KEY]:
            return node[KEY]['riders']
        for value in node.values():
            found = _find_riders(value)
            if found is not None:
                return found
    return None


def test_reviewed_source_rider_keeps_once_between_sessions_limit():
    riders = _reviewed_rider()
    assert riders == [RIDER]
    assert 'between fights' not in riders[0]


def test_generated_authority_carries_the_same_rider():
    generated = json.dumps(json.loads((AUTH / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text()), ensure_ascii=False)
    assert RIDER in generated
    assert 'use this same reroll on a Cultivation Check between fights' not in generated
