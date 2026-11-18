"""Object activation choices through service/table intents, cold reload and replay."""
import pytest
from combat.gate2_rolls import DeterministicRollAuthority
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload
from tests.hunt12_support import send
from tests.test_auto2_talismans import family
from tests.test_a2_talismans_second_pass import EMBER, TALENT, PREPARED, objects

COUNTER = 'TAL_QIWEAVING_COUNTERWEAVE'
REACTION = 'reaction:typed.' + COUNTER

@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('use', [False, True])
def test_object_activation_counterweave_use_decline_and_reload(tmp_path, monkeypatch, auto, use):
    objects(monkeypatch)
    combat, table, mid = fixture(tmp_path, [EMBER], owner_dc=1,
        foe_sheet=sheet([COUNTER], cl=15))
    if auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    chosen = candidate(combat, mid, 'Ember Talisman', target='object:map.1')
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    # Only test dice and selection of this legal AI candidate are controlled.
    # The opposing manual player's response remains a real table decision.
    original = DeterministicRollAuthority._die
    start = combat._load_session(mid).engine.roller.counter
    def die(roller, sides):
        if roller.counter < start:
            return original(roller, sides)
        index = roller.counter
        roller.counter += 1
        return (18 if sides == 20 else 4), index
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    result = send(combat, table, mid, chosen, auto=auto)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == REACTION
    assert prompt['context']['reactor_id'] == FOE
    assert prompt['reaction'] == 'Counterweave'
    assert 'Ember Talisman' in prompt['moment']
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
    result = send(combat, table, mid, chosen,
        [{**prompt['context'], 'selection': 'USE' if use else 'DECLINE'}], auto=auto)
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert not owner.action_available
    assert owner.resources[PREPARED] == before['actors'][OWNER]['resources'][PREPARED] - 1
    assert foe.reaction_available == (not use)
    assert any(r.reason == 'REACTION_COUNTER' for r in engine.rolls) == use
    if use:
        assert foe.resources['resource:core.qi'] < before['actors'][FOE]['resources']['resource:core.qi']
        assert engine.state.objects['object:map.1'].current_hp == before['objects']['object:map.1']['current_hp']
        assert not any(e.event_type == 'ATTACK_ROLLED' and e.target_ids == ('object:map.1',) for e in engine.events)
        assert not any(r.reason.startswith('DAMAGE:') for r in engine.rolls)
    else:
        assert foe.resources == before['actors'][FOE]['resources']
        assert engine.state.objects['object:map.1'].current_hp < before['objects']['object:map.1']['current_hp']
        assert any(e.event_type == 'ATTACK_ROLLED' and e.target_ids == ('object:map.1',) for e in engine.events)


def test_object_affinity_prompt_names_object_and_reloads(tmp_path, monkeypatch):
    objects(monkeypatch)
    combat, table, mid = fixture(tmp_path, [EMBER, TALENT + 'talisman_affinity'])
    family(combat, table, mid, 'Attack')
    chosen = candidate(combat, mid, 'Ember Talisman', target='object:map.1')
    before = reload(tmp_path, mid)
    object_name = before.state.objects['object:map.1'].component['name']
    owner_name = before.state.actors[OWNER].display_name
    expected = before.action_catalog[chosen.source_definition_id].parameters['typed']['numbers']['attack_bonus'] + 1
    result = send(combat, table, mid, chosen)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.talisman_affinity_benefit'
    assert 'affecting ' + object_name in prompt['moment']
    assert 'affecting ' + owner_name not in prompt['moment']
    assert 'object:map' not in prompt['moment']
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before.state.model_dump(mode='json')
    result = send(combat, table, mid, chosen,
        [{**prompt['context'], 'selection': 'USE', 'option_ids': ['attack']}])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    attack = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.target_ids == ('object:map.1',))
    assert attack.payload['modifier'] == expected


@pytest.mark.parametrize('counter', ['absent', 'decline', 'use'])
def test_object_modulation_acceptance_shared_gate_and_next_turn(tmp_path, monkeypatch, counter):
    from combat.canonical import canonical_sha256
    from combat.ext.qiweaving_second_pass import GATE
    from tests.worker2_support import settle, turn

    distant = 'TAL_QIWEAVING_DISTANT_MODULATION'
    stable = 'TAL_QIWEAVING_STABLE_MODULATION'
    objects(monkeypatch)

    def available_second_action(bundles):
        # Test economy only: preserve compiled targeting, modifiers, costs and
        # hooks, while leaving a same-turn candidate to expose the shared gate.
        for action in bundles[0]['action_catalog']:
            if action['display_name'].startswith('Ember Talisman') or 'Modulation' in action['display_name']:
                action['economy'] = 'NONE'
        bundles[0].pop('bundle_sha256')
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])

    combat, table, mid = fixture(tmp_path, [EMBER, distant, stable, 'TAL_FORCE_FORCE_MANTLE'],
        owner_dc=1, bundle_transform=available_second_action,
        foe_sheet=sheet([COUNTER] if counter != 'absent' else [], cl=15))
    chosen = candidate(combat, mid, 'Ember Talisman + Distant Modulation', target='object:map.1')
    before = reload(tmp_path, mid)
    assert before.action_catalog[chosen.source_definition_id].parameters['typed']['qiweaving_modulation_gate']
    assert candidate(combat, mid, 'Force Mantle + Stable Modulation')
    saved = before.state.model_dump(mode='json')

    original = DeterministicRollAuthority._die
    start = combat._load_session(mid).engine.roller.counter
    def die(roller, sides):
        if roller.counter < start:
            return original(roller, sides)
        index = roller.counter
        roller.counter += 1
        return (18 if sides == 20 else 1), index
    monkeypatch.setattr(DeterministicRollAuthority, '_die', die)
    result = send(combat, table, mid, chosen)
    if counter != 'absent':
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == REACTION
        assert reload(tmp_path, mid).state.model_dump(mode='json') == saved
        result = send(combat, table, mid, chosen,
            [{**prompt['context'], 'selection': 'USE' if counter == 'use' else 'DECLINE'}])
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.turn_flags.get(GATE), 'Accepted object Modulation must spend the shared allowance'
    assert owner.action_available  # no unrelated economy gate hides the bug
    assert owner.resources[PREPARED] == saved['actors'][OWNER]['resources'][PREPARED] - 1
    assert bool([r for r in engine.rolls if r.reason == 'REACTION_COUNTER']) == (counter == 'use')
    assert bool([e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
                 and e.target_ids == ('object:map.1',)]) == (counter != 'use')
    assert (engine.state.objects['object:map.1'].current_hp == saved['objects']['object:map.1']['current_hp']) == (counter == 'use')
    legal = engine.legal_candidates()
    assert not any(engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('qiweaving_modulation_gate')
                   for c in legal if c.source_definition_id in engine.action_catalog)
    assert candidate(combat, mid, 'Ember Talisman', target='object:map.1')
    assert candidate(combat, mid, 'Force Mantle')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    assert not reload(tmp_path, mid).state.actors[OWNER].turn_flags.get(GATE)
    assert candidate(combat, mid, 'Ember Talisman + Distant Modulation', target='object:map.1')
    assert candidate(combat, mid, 'Force Mantle + Stable Modulation')
