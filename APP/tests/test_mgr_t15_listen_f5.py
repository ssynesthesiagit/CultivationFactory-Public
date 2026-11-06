"""F5/F22: Listen Through Tension stays offered to the owner after Draw the Line.

Covers the bdiff script-3 gap (owner menu lost Listen after Draw on a creature
while Hundred-Line Weaving was held), the script-2 case (no Hundred-Line
Weaving: every printed Draw mode that hits still creates the Thread Line that
Listen's printed range needs) and the object-line case the lead asked for.
Each test asserts the owner's real menu, then uses Listen.

Runtime inputs: authority/typed_mechanics/rules_text.json,
authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/Tianxia_Forged_Technique_Authority_R1.json,
authority/Tianxia_Immortal_Art_Authority_R1.json,
catalog_authority/cat3/generated/catalog_authority.v1.json,
authority/typed_mechanics/reviewed_final.d/review_sw-thread.json,
authority/Tianxia_Sphere_Path_Access_R1.json,
catalog_authority/cat1/data/prerequisite_projection.v1.json.
"""
import pytest
from tests.mgr_t15_listen_fixture import (P, F, HUNDRED, fight, cold, mundane, choose, candidate, private, grants)
from combat.gate5_service import CombatService
from tests.h1_support import ROOT

BELL = [{'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}]

MODES = ('Pull', 'Snare', 'Guide', 'Trip', 'Disarm')


def menu_rows(table, mid):
    """(label, candidate id, target ids) for every option the real table offers now.

    The table keeps an option's own label when it has one and otherwise falls back to its group label, so reading
    only option['label'] misses the whole Draw the Line group and makes a present option look absent.
    """
    return [((o.get('label') or group['label']), o['candidate_id'], o.get('target_ids') or [])
            for group in table.state(mid)['menu']['actions'] for o in group['options']]


def owner_labels(table, mid):
    return [label for label, _, _ in menu_rows(table, mid)]


def draw_mode(table, mid, mode):
    """The plain printed <mode> of Draw the Line on FOE, else its lowest-ranked printed variant."""
    rows = [r for r in menu_rows(table, mid) if r[0].startswith('Draw the Line: ') and mode in r[0] and F in r[2]]
    exact = [cid for label, cid, _ in rows if label == 'Draw the Line: ' + mode]
    return exact[0] if exact else rows[0][1] if rows else None


def line_facts(table, mid, drawn):
    """The line state Listen's gate reads, in the reviewer's words: which mark the target bears, which line it is."""
    from combat.ext.thread_common import maintained_lines, mark_condition_id
    engine = CombatService(ROOT, table.combat.userdata_root)._load_session(mid).engine
    foe = engine.state.actors[F]
    return {'drawn': drawn,
            'target_thread_line_mark': [c.condition_id for c in foe.conditions.values()
                                        if c.condition_id == mark_condition_id(engine.state.actors[P].entity_id, 'Thread Line')],
            'maintained_lines': [(iid, getattr(t, 'entity_id', None) or getattr(t, 'object_id', None), dict(line.data or {}))
                                 for iid, t, _h, line in maintained_lines(engine, engine.state.actors[P])],
            'menu': owner_labels(table, mid)}


@pytest.mark.parametrize('mode', MODES)
def test_listen_offered_to_owner_after_plain_draw_without_weaving(tmp_path, mode):
    """bdiff script-2: the owner has Draw the Line and Listen Through Tension, no Hundred-Line Weaving.

    Draw the Line: "On a hit, you create a Thread Line between yourself or an anchor you control and the target.
    The line lasts until the end of your next turn." Listen Through Tension's range is one active Thread Line the
    owner maintains, so a hit of any printed mode must leave Listen on the owner's menu."""
    _, table, mid = fight(tmp_path)
    cid = draw_mode(table, mid, mode)
    if cid is None:
        pytest.skip('the printed ' + mode + ' mode is not legal here: ' + repr(owner_labels(table, mid)))
    choose(table, mid, cid)
    facts = line_facts(table, mid, mode)
    assert facts['maintained_lines'] or not facts['target_thread_line_mark'], facts
    assert any('Listen Through Tension' in label for label in facts['menu']), facts
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert grants(cold(tmp_path, mid)), facts


def test_listen_offered_to_owner_after_draw_on_creature_with_weaving(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED])
    mundane(table, mid)
    assert any('Listen Through Tension' in label for label in owner_labels(table, mid))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    assert private(table, mid)[0]['handling'] == 'unknown'
    assert len(grants(cold(tmp_path, mid))) == 1


def test_listen_offered_to_owner_after_draw_on_object_with_weaving(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED], objects=BELL)
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    assert any('Listen Through Tension' in label for label in owner_labels(table, mid))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    assert len(grants(cold(tmp_path, mid))) == 1
