"""Iron Oath Skin's Refined expressions: Iron Interposition (+PB to Iron Oath Guard) and Scar-Ledger Defense (+PB to Stand-Fast Witness).

Selected once per fight, like the other Foundation expressions; unselected, the base value stands.
"""
from combat.ext import foundation_combat as f
from tests.test_a2_r11_foundations import _committed, _fight, _strike
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle, turn

OATH = 'iron_oath_skin_v0_2B'
PB = 4


def _guarded_hit(tmp_path, expression, victim=ALLY):
    combat, table, mid = _fight(tmp_path, OATH, 'Guarding Iron', stage='Refined', held=1,
                                foe_actions=[_strike('Foe strike', FOE, damage=30)], owner_hp=200)
    settle(table, mid, candidate(combat, mid, 'Declare Protected Subject').candidate_id,
           choices={f.CHOICE + 'foundation_subject': [ALLY]})
    if expression:
        settle(table, mid, candidate(combat, mid, 'Foundation expression: ' + expression).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe strike', target=victim).candidate_id,
           choices={'choice:needle.foundation_combat': 'use'})
    engine = reload(tmp_path, mid)
    return [e.payload for e in _committed(engine, victim)][-1]['hp_damage']


def test_iron_interposition_adds_one_pb_to_the_guard_reduction(tmp_path):
    plain = _guarded_hit(tmp_path / 'plain', None)
    chosen = _guarded_hit(tmp_path / 'chosen', 'Iron Interposition')
    assert plain - chosen == PB


def test_iron_interposition_does_not_add_pb_when_the_oath_bearer_guards_their_own_damage(tmp_path):
    # Iron Interposition's trigger is 'for an adjacent ally': the bearer's own damage gets only the base Guard.
    plain = _guarded_hit(tmp_path / 'plain', None, victim=OWNER)
    chosen = _guarded_hit(tmp_path / 'chosen', 'Iron Interposition', victim=OWNER)
    assert plain < 30  # the base Guard did reduce the bearer's own damage
    assert plain == chosen


def test_the_other_expression_does_not_change_the_guard(tmp_path):
    plain = _guarded_hit(tmp_path / 'plain', None)
    other = _guarded_hit(tmp_path / 'other', 'Scar-Ledger Defense')
    assert plain == other


def _fear_save(tmp_path, dc, held, expression):
    from tests.test_a2_r11_foundations import _typed_action
    fear = _typed_action('Fear save', FOE, [{'type': 'save', 'ability': 'WIS', 'dc': dc, 'applies_to': 'target',
        'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target'}], 'on_success': []}], economy='ACTION',
        numbers={'save_dc': dc})
    combat, table, mid = _fight(tmp_path, OATH, 'Guarding Iron', stage='Refined', held=held, foe_actions=[fear], owner_hp=200)
    if expression:
        settle(table, mid, candidate(combat, mid, 'Foundation expression: ' + expression).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Fear save', target=OWNER).candidate_id,
           choices={'choice:needle.foundation_combat': 'use'})
    engine = reload(tmp_path, mid)
    roll = next(e.payload for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER)
    frightened = any(c.condition_id.endswith('.frightened') for c in engine.state.actors[OWNER].conditions.values())
    return roll['total'], frightened


def test_scar_ledger_defense_adds_one_more_pb_to_the_stand_fast_witness_roll(tmp_path):
    total, _ = _fear_save(tmp_path / 'probe', 100, 0, None)  # no Guarding Iron: the bare roll
    dc = total + PB + 1  # the base Witness (+PB) falls one short; with the expression (+2 PB) it reaches
    assert _fear_save(tmp_path / 'plain', dc, 1, None)[1] is True
    assert _fear_save(tmp_path / 'chosen', dc, 1, 'Scar-Ledger Defense')[1] is False
