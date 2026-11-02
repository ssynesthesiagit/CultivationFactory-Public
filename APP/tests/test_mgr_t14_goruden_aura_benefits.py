"""Golden Aura benefit-time choices for committed allies on another team."""
import pytest

from tests.cw2_service_support import add_action
from tests.test_mgr_t14_goruden import use
from tests.test_mgr_t14_goruden_clauses import acquired_game
from tests.worker2_support import ALLY, FOE, OWNER, reload, turn


@pytest.mark.parametrize('benefit', ['necrotic', 'frightened'])
@pytest.mark.parametrize('selection', ['include', 'exclude'])
def test_cross_team_ally_gets_owner_choice_at_off_turn_benefit(
        catalog_environment, monkeypatch, tmp_path, benefit, selection):
    """Actual damage/save consumers honor a new decision after prior exclusion."""
    name = f'Aura {benefit} benefit trial'

    def setup(bundles):
        effect = ({'type': 'damage', 'flat': 20, 'damage_types': ['necrotic'],
                   'applies_to': 'target'} if benefit == 'necrotic' else
                  {'type': 'save', 'ability': 'wis',
                   'on_fail': [{'type': 'condition', 'condition': 'frightened',
                                'applies_to': 'target',
                                'expires_on': 'END_OF_TARGET_NEXT_TURN'},
                               {'type': 'damage', 'flat': 1, 'damage_types': ['force'],
                                'applies_to': 'target'}]})
        add_action(bundles[1], name, [effect])

    combat, table, mid = acquired_game(catalog_environment, monkeypatch, tmp_path, setup)
    engine = reload(tmp_path, mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
        'other': FOE, 'relation': 'ALLY'}, expected_state_version=engine.state.state_version)
    use(combat, table, mid, 'Golden Aura',
        picks={'choice:needle.goruden.aura_ally': ['exclude']})
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid)
    assert before.state.current_actor_id == ALLY
    assert before.state.actors[OWNER].team_id != before.state.actors[FOE].team_id
    assert not any(c.data.get('rule', {}).get('save_against')
                   for c in before.state.actors[FOE].conditions.values())

    prompts = use(combat, table, mid, name, FOE,
                  {'choice:needle.goruden.aura_ally': [selection]})
    choices = [p for p in prompts
               if p['context']['reaction_source_id'] == 'choice:needle.goruden.aura_ally']
    assert len(choices) == 1, 'Golden Aura must ask its owner at the actual benefit.'
    assert choices[0]['context']['reactor_id'] == OWNER
    prompt = choices[0]
    affected = before.state.actors[FOE].display_name
    acting = before.state.actors[ALLY].display_name
    assert prompt['action'] == name
    assert prompt['affected'] == affected
    assert prompt['by'] == affected
    assert prompt['trigger_actor'] == acting
    assert 'Golden Aura' in prompt['moment']
    assert name in prompt['moment'] and affected in prompt['moment']
    assert acting in prompt['moment']
    after = reload(tmp_path, mid)  # Cold load also verifies mechanical replay.
    if benefit == 'necrotic':
        packet = next(e for e in after.events if e.sequence > before.state.event_sequence
                      and e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids)
        assert packet.payload['hp_damage'] == (10 if selection == 'include' else 20)
        assert before.state.actors[FOE].current_hp - after.state.actors[FOE].current_hp == packet.payload['hp_damage']
    else:
        saves = [r for r in after.rolls if r.actor_id == FOE and r.reason.startswith('SAVE:')]
        assert saves[-1].mode == ('ADVANTAGE' if selection == 'include' else 'NORMAL')


def test_radiant_fist_source_binding_cannot_grant_an_unowned_rider(tmp_path):
    from tests.worker2_support import fixture

    def setup(bundles):
        add_action(bundles[1], 'Unowned light denial', [{
            'type': 'no_invisible_benefit', 'source_owned': 1,
            'source_feature': 'tianxia.subpath.body.goruden.feature.radiant_fist',
            'applies_to': 'target', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}])

    combat, table, mid = fixture(tmp_path, [], bundle_transform=setup)
    turn(table, mid, ALLY)
    use(combat, table, mid, 'Unowned light denial', FOE)
    assert not any(c.condition_id == 'condition:typed.no_invisible_benefit'
                   for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
