"""Verdant movement riders through real decisions, commits and reloads."""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from combat.ext import verdant_chassis as verdant
from tests.worker2_support import OWNER, FOE, fixture, candidate, act, settle, reload, prompt_turn as turn
SOW = 'TAL_VERDANT_GROWTH_SOW_LIVING_CLAIM'
SEED = 'TAL_VERDANT_GROWTH_SEED_THORN_STRIKE'
SNARE = 'TAL_VERDANT_GROWTH_ROOT_SNARE_STEP'
DEEP = 'TAL_VERDANT_GROWTH_DEEP_ROOT_HOLDS_THE_GATE'


def prepare_marks(bundles):
    """Fixed setup places marks using a committed typed table action."""
    for b in bundles:
        if b['actor_id'] == OWNER:
            a = deepcopy(next(a for a in b['action_catalog'] if a['display_name'] == 'Seed-Thorn Strike'))
            a.update(source_definition_id='test:auto36.mark', display_name='Prepare Growth Mark', economy='NONE')
            a['parameters']['typed'].update(source='test:auto36.mark', effects=[{'type': 'mark', 'mark': 'Growth Mark', 'applies_to': 'target'}])
            b['action_catalog'].append(a)
            b['actor_template']['action_ids'].append(a['source_definition_id'])
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)


def movement(combat, mid, x):
    e = combat._load_session(mid).engine
    return next(c for c in e.legal_candidates() if c.kind.value == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y, c.destination.z) == (x, 5, 0))


@pytest.mark.parametrize('case', ['fail', 'success', 'decline', 'old_bundle'])
def test_root_snare_stops_after_ten_physical_feet(tmp_path, case):
    def prepare(bundles):
        prepare_marks(bundles)
        if case == 'old_bundle':
            for b in bundles:
                for r in b.get('typed_passives', []):
                    r.pop('step_snare', None)
                b.pop('bundle_sha256', None)
                b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [SOW, SEED, SNARE], owner_dc=1 if case == 'success' else 100,
                                bundle_transform=prepare, foe_position={"x": 6, "y": 5})
    settle(table, mid, candidate(combat, mid, 'Prepare Growth Mark', target=FOE).candidate_id)
    turn(table, mid, FOE)
    c = movement(combat, mid, 10)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert act(table, mid, c.candidate_id)['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    prompts = settle(table, mid, c.candidate_id, {'choice:needle.root_snare_step': None if case == 'decline' else 'snare'})
    assert any(p['context']['reactor_id'] == OWNER for p in prompts)
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    assert foe.position.x == (8 if case == 'fail' else 10)
    assert verdant.marks(foe, e.state.actors[OWNER]) == int(case == 'decline')
    ev = next(ev for ev in reversed(e.events) if ev.event_type == 'MOVEMENT_COMMITTED')
    assert ev.payload['cost_ft'] == (10 if case == 'fail' else 20)
    if case == 'fail':
        assert ev.payload['interrupted']
        assert foe.movement_remaining_ft == 20
    if case == 'success':
        assert any(m.target_field == 'speed_ft' and m.value == -10 for m in foe.modifiers.values())
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert not any(m.target_field == 'speed_ft' and m.value == -10 for m in reload(tmp_path, mid).state.actors[FOE].modifiers.values())


@pytest.mark.parametrize('case', ['fail', 'success', 'decline'])
def test_deep_root_catches_before_departure_and_has_bounded_conditions(tmp_path, case):
    combat, table, mid = fixture(tmp_path, [SOW, SEED, DEEP], owner_dc=1 if case == 'success' else 100,
                                bundle_transform=prepare_marks, foe_position={"x": 6, "y": 5})
    settle(table, mid, candidate(combat, mid, 'Sow Living Claim', at=(5, 5)).candidate_id)
    for _ in range(2):
        settle(table, mid, candidate(combat, mid, 'Prepare Growth Mark', target=FOE).candidate_id)
    turn(table, mid, FOE)
    c = movement(combat, mid, 8)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert act(table, mid, c.candidate_id)['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    prompts = settle(table, mid, c.candidate_id, {'choice:needle.deep_root': None if case == 'decline' else 'hold'})
    assert any(p['context']['reactor_id'] == OWNER for p in prompts)
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    assert foe.position.x == (8 if case == 'decline' else 6)
    assert verdant.marks(foe, e.state.actors[OWNER]) == (2 if case == 'decline' else 0)
    conds = [c for c in foe.conditions.values() if c.source_definition_id == DEEP]
    assert len(conds) == int(case != 'decline')
    if case == 'fail':
        assert 'restrained' in conds[0].condition_id
        assert conds[0].data['repeat_save']['dc'] == 100
        assert conds[0].expires_on == 'END_OF_SOURCE_TURN_AT:2'
    elif case == 'success':
        assert 'grappled' in conds[0].condition_id
        assert conds[0].expires_on == 'END_OF_CURRENT_TURN'
        assert 'reach_ft' not in conds[0].data
        assert not e._dragged_by(e.state.actors[OWNER])
    if case != 'decline':
        turn(table, mid, OWNER)
        e = reload(tmp_path, mid)
        assert bool([c for c in e.state.actors[FOE].conditions.values() if c.source_definition_id == DEEP]) == (case == 'fail')
        if case == 'fail':
            saves = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED' and ev.source_definition_id == DEEP]
            assert len(saves) >= 2
            settle(table, mid, table.state(mid)['menu']['end_turn'])
            assert not any(c.source_definition_id == DEEP for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_shelter_grove_existing_two_options_and_single_save_cover(tmp_path):
    from tests.test_c16_shelter_grove import test_shelter_grove_requires_two_options_and_cover_protects_one_dex_save
    test_shelter_grove_requires_two_options_and_cover_protects_one_dex_save(tmp_path)
