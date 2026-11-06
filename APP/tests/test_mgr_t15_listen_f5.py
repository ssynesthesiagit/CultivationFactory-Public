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

BELL = [{'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}]

OPTIONS = ('Pull', 'Snare', 'Guide', 'Trip', 'Disarm')


def owner_labels(table, mid):
    menu = table.state(mid)['menu']
    return [o.get('label', '') for group in menu.get('actions', []) for o in group.get('options', [])]


def draw_candidate(table, mid, option):
    """The plain printed <option> mode of Draw the Line, mundane line, single target."""
    label = 'Draw the Line: ' + option
    labels = [(o.get('label') or group['label'], o['candidate_id'])
              for group in table.state(mid)['menu']['actions'] for o in group['options']]
    exact = [cid for text, cid in labels if text == label]
    return exact[0] if exact else candidate(table, mid, label, F)


def line_facts(engine, drawn):
    """Everything a reader needs to see which line state Listen's gate reads."""
    from combat.ext.thread_common import maintained_lines
    owner = engine.state.actors[P]

    def conds(actor):
        return [(c.condition_id, dict(c.data or {}), c.expires_on) for c in actor.conditions.values()]

    return {'drawn': drawn,
            'lines': [(iid, getattr(t, 'entity_id', None) or getattr(t, 'object_id', None), dict(line.data or {}),
                       line.expires_on) for iid, t, _h, line in maintained_lines(engine, owner)],
            'owner_conditions': conds(owner), 'foe_conditions': conds(engine.state.actors[F]),
            'owner_menu': None}


def test_listen_offered_to_owner_after_draw_on_creature_with_weaving(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED])
    mundane(table, mid)
    assert any('Listen Through Tension' in label for label in owner_labels(table, mid))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('handling',))
    assert private(table, mid)[0]['handling'] == 'unknown'
    assert len(grants(cold(tmp_path, mid))) == 1


@pytest.mark.parametrize('option', OPTIONS)
def test_listen_offered_to_owner_after_plain_draw_without_weaving(tmp_path, option):
    """bdiff script-2: no Hundred-Line Weaving. Draw the Line's printed effect is "On a hit, you create a Thread
    Line between yourself or an anchor you control and the target. The line lasts until the end of your next
    turn." Listen Through Tension's range is "One active Thread Line you maintain", so a hit must leave Listen
    on the owner's menu for every printed mode."""
    _, table, mid = fight(tmp_path)
    drawn = 'Draw the Line: ' + option
    if drawn not in owner_labels(table, mid):
        pytest.skip('fixture menu does not offer ' + drawn + ': ' + repr(owner_labels(table, mid)))
    choose(table, mid, draw_candidate(table, mid, option))
    facts = line_facts(cold(tmp_path, mid), drawn)
    facts['owner_menu'] = owner_labels(table, mid)
    assert any('Listen Through Tension' in label for label in facts['owner_menu']), facts
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert grants(cold(tmp_path, mid)), facts


def test_listen_offered_to_owner_after_draw_on_object_with_weaving(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED], objects=BELL)
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    assert any('Listen Through Tension' in label for label in owner_labels(table, mid))
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    assert private(table, mid)[0]['motion'] == 'still'
    assert len(grants(cold(tmp_path, mid))) == 1
