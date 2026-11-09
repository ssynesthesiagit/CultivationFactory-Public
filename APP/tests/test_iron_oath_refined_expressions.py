"""Iron Oath Skin's Refined expressions: Iron Interposition (+PB to Iron Oath Guard) and Scar-Ledger Defense (+PB to Stand-Fast Witness).

Selected once per fight, like the other Foundation expressions; unselected, the base value stands.
"""
from combat.ext import foundation_combat as f
from tests.test_a2_r11_foundations import _committed, _fight, _strike
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle, turn

OATH = 'iron_oath_skin_v0_2B'
PB = 4


def _guarded_hit(tmp_path, expression, victim=ALLY, movement=None, *, vertical=False, audit_oa=False, oa_use=False):
    places = ({OWNER: {'x': 3, 'y': 6, 'z': 0}, ALLY: {'x': 3, 'y': 6, 'z': 1},
               FOE: {'x': 4, 'y': 6, 'z': 0}} if vertical else None)
    combat, table, mid = _fight(tmp_path, OATH, 'Guarding Iron', stage='Refined', held=1,
                                foe_actions=[_strike('Foe strike', FOE, damage=30)], owner_hp=200,
                                places=places, owner_flying=vertical)
    settle(table, mid, candidate(combat, mid, 'Declare Protected Subject').candidate_id,
           choices={f.CHOICE + 'foundation_subject': [ALLY]})
    if expression:
        settle(table, mid, candidate(combat, mid, 'Foundation expression: ' + expression).candidate_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Foe strike', target=victim).candidate_id,
           choices={'choice:needle.foundation_combat': 'use',
                    'choice:needle.iron_interposition': movement,
                    'reaction:typed.opportunity_attack': 'use' if oa_use else None})
    engine = reload(tmp_path, mid)
    damage = [e.payload for e in _committed(engine, victim)][-1]['hp_damage']
    result = (damage, engine.state.actors[OWNER].position)
    if audit_oa:
        oa = next(row for row in engine.typed_reaction_rows[FOE] if row['block'] == 'opportunity')
        assert any(p['context']['reaction_source_id'] == 'reaction:typed.opportunity_attack' for p in prompts)
        attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
                   and e.actor_id == FOE and e.target_ids == (OWNER,)
                   and e.source_definition_id == oa['action_id']]
        return (*result, attacks)
    return result


def test_iron_interposition_adds_one_pb_to_the_guard_reduction(tmp_path):
    plain, _ = _guarded_hit(tmp_path / 'plain', None)
    chosen, _ = _guarded_hit(tmp_path / 'chosen', 'Iron Interposition')
    assert plain - chosen == PB


def test_iron_interposition_accept_moves_toward_ally_and_decline_keeps_reduction(tmp_path):
    declined_damage, declined_position = _guarded_hit(
        tmp_path / 'declined', 'Iron Interposition', movement=None)
    moved_damage, moved_position = _guarded_hit(
        tmp_path / 'moved', 'Iron Interposition', movement='cell:2,5')
    baseline_damage, _ = _guarded_hit(tmp_path / 'baseline', None)
    assert moved_position != declined_position
    assert moved_position.x == 2 and moved_position.y == 5
    assert moved_damage == declined_damage == baseline_damage - PB

    # Directly-above ally: a flying bearer can take a legal diagonal ascending
    # step toward it; altitude must participate in the direction test.
    _, vertical_position = _guarded_hit(
        tmp_path / 'vertical', 'Iron Interposition', movement='cell:2,6,1', vertical=True)
    assert (vertical_position.x, vertical_position.y, vertical_position.z) == (2, 6, 1)

    # The feature does not waive Opportunity Attacks. A hostile in reach reacts
    # when the chosen route leaves its reach, while declining leaves it unused.
    _, _, accepted_oa = _guarded_hit(
        tmp_path / 'oa-accepted', 'Iron Interposition', movement='cell:2,5', audit_oa=True, oa_use=True)
    _, _, declined_oa = _guarded_hit(
        tmp_path / 'oa-declined', 'Iron Interposition', movement='cell:2,5', audit_oa=True)
    assert accepted_oa
    assert not declined_oa


def test_iron_interposition_does_not_add_pb_when_the_oath_bearer_guards_their_own_damage(tmp_path):
    # Iron Interposition's trigger is 'for an adjacent ally': the bearer's own damage gets only the base Guard.
    plain, _ = _guarded_hit(tmp_path / 'plain', None, victim=OWNER)
    chosen, _ = _guarded_hit(tmp_path / 'chosen', 'Iron Interposition', victim=OWNER)
    assert plain < 30  # the base Guard did reduce the bearer's own damage
    assert plain == chosen


def test_the_other_expression_does_not_change_the_guard(tmp_path):
    plain, _ = _guarded_hit(tmp_path / 'plain', None)
    other, _ = _guarded_hit(tmp_path / 'other', 'Scar-Ledger Defense')
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
    return roll['total'], frightened, engine, table, mid


def test_scar_ledger_defense_adds_one_more_pb_to_the_stand_fast_witness_roll(tmp_path, monkeypatch):
    total, _, _, _, _ = _fear_save(tmp_path / 'probe', 100, 0, None)  # no Guarding Iron: the bare roll
    dc = total + PB + 1  # the base Witness (+PB) falls one short; with the expression (+2 PB) it reaches
    assert _fear_save(tmp_path / 'plain', dc, 1, None)[1] is True
    _, frightened, engine, _, _ = _fear_save(tmp_path / 'chosen', dc, 1, 'Scar-Ledger Defense')
    assert frightened is False
    # The successful table spend persisted the witness through reload. Even if the
    # base MOVEPASS1 rule would permit the source through its defender, the veto wins.
    from combat import creature_passage, movement_passage
    monkeypatch.setattr(movement_passage, 'passable', lambda *_: True)
    source = engine.state.actors[FOE]
    defender = engine.state.actors[OWNER]
    assert creature_passage.permission(engine, source, defender) is None


def test_scar_ledger_all_defenders_and_expires_at_source_turn_end(tmp_path, monkeypatch):
    import copy
    total, _, _, _, _ = _fear_save(tmp_path / 'probe', 100, 0, None)
    dc = total + PB + 1
    _, _, engine, table, mid = _fear_save(tmp_path / 'boundary', dc, 1, 'Scar-Ledger Defense')
    from combat import creature_passage, movement_passage
    monkeypatch.setattr(movement_passage, 'passable', lambda *_: True)
    source = engine.state.actors[FOE]
    witness = next(c for c in source.conditions.values()
                   if c.condition_id.endswith('.scar_ledger_witness'))
    second = copy.deepcopy(witness)
    second.data['defender_id'] = ALLY
    source.conditions['second-scar-ledger-witness'] = second
    assert creature_passage.permission(engine, source, engine.state.actors[OWNER]) is None
    assert creature_passage.permission(engine, source, engine.state.actors[ALLY]) is None
    turn(table, mid, OWNER)  # end the source's current turn
    engine = reload(tmp_path / 'boundary', mid)
    source = engine.state.actors[FOE]
    assert not any(c.condition_id.endswith('.scar_ledger_witness') for c in source.conditions.values())
    assert creature_passage.permission(engine, source, engine.state.actors[OWNER]) is not None
