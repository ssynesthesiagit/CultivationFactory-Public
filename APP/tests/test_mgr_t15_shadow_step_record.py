"""Shadow Step's reviewed typed record must carry the next-Stealth-check Advantage and the draw/stow clause.

Review F2R finding 3: tabik.json lacked clauses the plug-in (combat/ext/tabik_ninpo.py) implements. This fails
against the pre-fix record (riders == []) and passes once the reviewed record and the rebuilt authority carry them.
"""
import json

from pathlib import Path

APP = Path(__file__).resolve().parents[1]
RECORD = 'tianxia.subpath.qi.ninpo_adept.feature.shadow_step'
REVIEWED = APP / 'authority/typed_mechanics/reviewed_final.d/tabik.json'
AUTHORITY = APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json'


def _riders(row):
    return ' '.join(row.get('riders') or [])


def test_reviewed_record_states_next_stealth_advantage_and_draw_or_stow():
    rows = [r for r in json.loads(REVIEWED.read_text(encoding='utf-8'))['mechanics'] if r.get('mechanic_id') == RECORD]
    assert len(rows) == 1, 'Shadow Step missing from reviewed tabik.json'
    text = _riders(rows[0])
    assert 'next Stealth check' in text and 'Advantage' in text
    assert 'draw or stow' in text and 'weapon, tool, talisman, or implement' in text


def test_shadow_step_authority_row_carries_the_reviewed_clauses():
    data = json.loads(AUTHORITY.read_text(encoding='utf-8'))
    rows = [r for r in _walk(data) if isinstance(r, dict) and r.get('mechanic_id') == RECORD]
    assert rows, 'Shadow Step missing from the typed authority'
    text = ' '.join(_riders(r) for r in rows)
    assert 'next Stealth check' in text
    assert 'draw or stow' in text


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
