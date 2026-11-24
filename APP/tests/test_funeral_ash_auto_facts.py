"""Funeral Ash classifies real table packets without asking a player to vote."""
import pytest

from tests.table_act_support import act
from tests.test_a2_foundations3 import add_action, pool
from tests.test_mgr_t14_ash_parent import native_fixture
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, sealed_native_attack, settle, turn

CAUTERY = 'foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery'
REACTION = 'reaction:typed.' + CAUTERY
ASH = pool('ash')
POSITIONS = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}}


def damage(kind):
    return {'type': 'damage', 'flat': 12, 'damage_types': [kind], 'applies_to': 'target'}


def typed_hit(bundle, name, kind, *, sphere=None):
    add_action(bundle, name, [damage(kind)], economy='NONE')
    if sphere:
        bundle['action_catalog'][-1]['parameters']['typed']['sphere'] = 'tianxia.sphere.' + sphere


def observed(result, engine):
    pending = result.get('reaction') or {}
    context = pending.get('context') or {}
    return (f"status={result['status']}; pending={pending.get('choice') or context or None}; "
            f"checkpoint={context.get('checkpoint_id')}; asked={context.get('reactor_id')}; "
            f"Ash={engine.state.actors[OWNER].resources[ASH]}")


def receipt(engine, source, target, after):
    return next((e for e in engine.events if e.sequence > after and e.event_type == 'DAMAGE_COMMITTED'
                 and e.source_definition_id == source and target in e.target_ids), None)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'MANUAL'])
def test_wounded_ash_owner_survives_ordinary_slash_without_a_witness_question(tmp_path, mode):
    def prepare(bundles):
        typed_hit(bundles[2], 'Setup wound', 'force')
        sealed_native_attack(bundles[2], 'Synthetic Slash', damage_type='SLASHING', attack_bonus=100)

    combat, table, mid = native_fixture(tmp_path, bundle_transform=prepare, positions=POSITIONS)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Setup wound', target=OWNER).candidate_id, choices={})
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    row = candidate(combat, mid, 'Synthetic Slash', target=OWNER)
    before = reload(tmp_path, mid)
    result = act(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    why = observed(result, engine)
    assert result['status'] == 'COMMITTED' and not result.get('reaction'), why
    hit = receipt(engine, row.source_definition_id, OWNER, before.state.event_sequence)
    assert hit and 0 < hit.payload['hp_before'] < before.state.actors[OWNER].maximum_hp, why
    assert engine.state.actors[OWNER].resources[ASH] == 0, why


@pytest.mark.parametrize('initial', [0, 1], ids=['generate', 'cautery'])
@pytest.mark.parametrize('category', ['fire', 'blood', 'lasting', 'other'])
def test_incoming_generation_and_paid_cautery_use_the_same_damage_facts(tmp_path, initial, category):
    def prepare(bundles):
        typed_hit(bundles[2], 'Setup wound', 'force')
        if category == 'lasting':
            add_action(bundles[2], 'Held injury', [damage('slashing'), {
                'type': 'ongoing', 'condition': 'fixture_injury', 'applies_to': 'target',
                'expires_on': 'UNTIL_REMOVED', 'turn_start_effects': [damage('slashing')],
            }], economy='NONE')
        else:
            typed_hit(bundles[2], 'Test damage', 'fire' if category == 'fire' else 'slashing',
                      sphere='blood' if category == 'blood' else None)

    combat, table, mid = native_fixture(tmp_path, incoming=False, initial=initial,
        owner_talents=[CAUTERY], bundle_transform=prepare, positions=POSITIONS)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Setup wound', target=OWNER).candidate_id, choices={})
    if category == 'lasting':
        row = candidate(combat, mid, 'Held injury', target=OWNER)
        placed = act(table, mid, row.candidate_id)
        engine = reload(tmp_path, mid)
        why = observed(placed, engine)
        assert placed['status'] == 'COMMITTED' and not placed.get('reaction'), why
        assert engine.state.actors[OWNER].resources[ASH] == initial, why
        delivery = receipt(engine, row.source_definition_id, OWNER, 0)
        assert delivery is not None and 'delivery_hazard' not in delivery.payload, why
        # Advance to the End Turn that will start the holder's turn. Submit it
        # ourselves rather than letting the fixture swallow a pending choice.
        order = engine.state.initiative_order
        turn(table, mid, order[order.index(OWNER) - 1])
        cid = table.state(mid)['menu']['end_turn']
    else:
        row = candidate(combat, mid, 'Test damage', target=OWNER)
        cid = row.candidate_id

    before = reload(tmp_path, mid)
    result = act(table, mid, cid)
    engine = reload(tmp_path, mid)
    why = observed(result, engine)
    if initial and category != 'other':
        assert result['status'] == 'REACTION_REQUIRED', why
        context = result['reaction']['context']
        assert context['reaction_source_id'] == REACTION and context['reactor_id'] == OWNER, why
        result = act(table, mid, cid, [{**context, 'selection': 'DECLINE'}])
        engine = reload(tmp_path, mid)
    assert result['status'] == 'COMMITTED' and not result.get('reaction'), why
    hit = receipt(engine, row.source_definition_id, OWNER, before.state.event_sequence)
    assert hit and hit.payload['hp_damage'] > 0, why
    assert 0 < hit.payload['hp_before'] < before.state.actors[OWNER].maximum_hp, why
    assert hit.payload.get('delivery_hazard') == ('lasting' if category == 'lasting' else None), why
    assert engine.state.actors[OWNER].resources[ASH] == int(initial or category != 'other'), why


@pytest.mark.parametrize('sphere,expected', [('fire', 1), ('air', 0)])
def test_outgoing_wounded_enemy_with_public_residue_needs_a_typed_method(tmp_path, sphere, expected):
    def prepare(bundles):
        from combat.gate5_service import CombatService

        bundles[0] = CombatService._with_prefight(object.__new__(CombatService), bundles[0], {
            OWNER: ['setup-choice:ash_public_residue:1']})
        typed_hit(bundles[0], 'Setup wound', 'force')
        typed_hit(bundles[0], 'Test method', 'slashing', sphere=sphere)

    combat, table, mid = native_fixture(tmp_path, bundle_transform=prepare, positions=POSITIONS)
    settle(table, mid, candidate(combat, mid, 'Setup wound', target=FOE).candidate_id, choices={})
    row = candidate(combat, mid, 'Test method', target=FOE)
    before = reload(tmp_path, mid)
    result = act(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    why = observed(result, engine)
    assert result['status'] == 'COMMITTED' and not result.get('reaction'), why
    hit = receipt(engine, row.source_definition_id, FOE, before.state.event_sequence)
    assert hit and 0 < hit.payload['hp_before'] < before.state.actors[FOE].maximum_hp, why
    assert engine.state.actors[OWNER].resources[ASH] == expected, why
