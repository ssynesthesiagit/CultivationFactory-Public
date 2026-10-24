"""Shadowed Mien activation, observer checks and owned HP through cold service."""
import pytest
from combat import senses
from combat.canonical import canonical_sha256
from combat.ext.shadowed_mien import MIEN, POOL, grant
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle, turn


def setup(sense='none'):
    def transform(bundles):
        bundles[0]['concentration_rules'] = {'capacity': 'cultivation_level', 'limits_by_cl': [[1, 1]]}
        if sense in ('darkvision', 'truesight'):
            bundles[2].setdefault('senses', {})['rows'] = [{'feature_id': 'test:observer', 'sense': sense, 'range_ft': 60, 'when': 'always'}]
        for bundle in bundles:
            source = 'action:test.mien.damage.' + bundle['actor_id']
            bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Test damage',
                'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
                'range_ft': 120, 'parameters': {'free_primary': True, 'typed': {'numbers': {'cl': 15},
                    'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 20, 'damage_types': ['force']}]}}})
            bundle['actor_template']['action_ids'].append(source)
            for name, ability, skill in [('Test Deception', 'cha', 'deception'), ('Test Insight', 'wis', 'insight')]:
                source = 'action:test.mien.' + skill + '.' + bundle['actor_id']
                bundle['action_catalog'].append({'source_definition_id': source, 'display_name': name,
                    'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
                    'target_kind': 'HOSTILE_ENTITY', 'range_ft': 120, 'parameters': {'free_primary': True,
                    'typed': {'numbers': {'cl': 15, 'pb': 5}, 'effects': [{'type': 'contest_against',
                        'actor_check': {'kind': 'check', 'ability': ability, 'skill': skill},
                        'target_check': {'kind': 'check', 'ability': 'wis' if skill == 'deception' else 'cha',
                                         'skill': 'insight' if skill == 'deception' else 'deception'}}]}}})
                bundle['actor_template']['action_ids'].append(source)
            for amount in (5, 50):
                source = 'action:test.mien.hp.' + str(amount) + bundle['actor_id']
                bundle['action_catalog'].append({'source_definition_id': source, 'display_name': f'Test HP {amount}',
                    'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
                    'parameters': {'free_primary': True, 'typed': {'numbers': {'cl': 15},
                        'effects': [{'type': 'temp_hp', 'applies_to': 'self', 'flat': amount}]}}})
                bundle['actor_template']['action_ids'].append(source)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    return transform


@pytest.mark.parametrize('sense', ['none', 'darkvision', 'truesight', 'clearsight'])
def test_mien_social_checks_depend_on_actual_observer(tmp_path, sense):
    combat, table, mid = fixture(tmp_path, [MIEN], bundle_transform=setup(sense),
        foe_sheet=sheet(['TAL_DARK_CLEARSIGHT'] if sense == 'clearsight' else [], cl=15))
    settle(table, mid, candidate(combat, mid, 'Meld: Shadowed Mien', target=OWNER).candidate_id)
    if sense == 'clearsight':
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Meld: Clearsight', target=FOE).candidate_id)
        turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Test Deception', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.actor_id == OWNER and 'CHECK' in r.reason]
    assert len(rolls[-1].dice) == (1 if sense in ('truesight', 'clearsight') else 2)
    assert engine.state.actors[OWNER].temporary_hp == 0
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test Insight', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.actor_id == FOE and 'CHECK' in r.reason]
    assert len(rolls[-1].dice) == (1 if sense in ('truesight', 'clearsight') else 2)
    assert grant(engine, engine.state.actors[OWNER]) is not None


@pytest.mark.parametrize('replacement,remaining', [(None, 0), (5, 0), (50, 50)])
def test_optional_mien_hp_expires_without_erasing_another_grant(tmp_path, replacement, remaining):
    combat, table, mid = fixture(tmp_path, [MIEN], bundle_transform=setup())
    settle(table, mid, candidate(combat, mid, 'Meld: Shadowed Mien (1 CP: Temporary HP)', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 15
    assert any(c.condition_id == POOL for c in engine.state.actors[OWNER].conditions.values())
    if replacement:
        settle(table, mid, candidate(combat, mid, f'Test HP {replacement}').candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == remaining
    assert grant(engine, engine.state.actors[OWNER]) is None
    assert not any(c.condition_id == POOL for c in engine.state.actors[OWNER].conditions.values())


def test_unwilling_recipient_resists_hp_and_mien_together(tmp_path):
    combat, table, mid = fixture(tmp_path, [MIEN], owner_dc=-50, foe_position={'x': 3, 'y': 7}, bundle_transform=setup())
    settle(table, mid, candidate(combat, mid, 'Meld: Shadowed Mien (1 CP: Temporary HP)', target=FOE).candidate_id,
           picks={'choice:needle.dark_meld_consent': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].temporary_hp == 0
    assert grant(engine, engine.state.actors[FOE]) is None


def test_ai_can_choose_paid_mien_option_without_a_live_model(tmp_path):
    combat, table, mid = fixture(tmp_path, [MIEN], bundle_transform=setup(), ask=False)
    chosen = candidate(combat, mid, 'Meld: Shadowed Mien (1 CP: Temporary HP)', target=OWNER)
    policy, _ = combat.policies.for_actor(OWNER)
    combat._dao_policies[OWNER] = policy.model_copy(update={
        'action_priorities': {chosen.source_definition_id: 100}}).model_dump(mode='json')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    settle(table, mid, chosen.candidate_id, auto=True)
    engine = reload(tmp_path, mid)
    assert any(a.temporary_hp == 15 and grant(engine, a) is not None for a in engine.state.actors.values())


def test_losing_mien_hp_to_damage_does_not_end_the_cloak(tmp_path):
    combat, table, mid = fixture(tmp_path, [MIEN, 'TAL_DARK_PERSISTENT_MELD'], bundle_transform=setup())
    settle(table, mid, candidate(combat, mid, 'Meld: Shadowed Mien (Persistent) (1 CP: Temporary HP)', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 15
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 97
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test damage', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 0
    assert grant(engine, engine.state.actors[OWNER]) is not None
