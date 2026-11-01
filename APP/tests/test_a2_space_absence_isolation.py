"""Absence boundaries through saved table intents, cold reload and replay."""
import pytest
from tests.test_hunt32_edge import OWNER, FOE, act, match, reload
from tests.test_a2_space_third_pass import EXILE, ALLY, _advance
from combat.ext.spatial_absence import absent

BOND = ['tianxia.talent.spirit_companions.battle_manifestation',
        'tianxia.talent.spirit_companions.covenant_spirit']


@pytest.mark.parametrize('exiled', [False, True], ids=['present-control', 'exiled'])
def test_crowded_map_restoration_uses_absent_occupants_square(tmp_path, exiled):
    from copy import deepcopy
    from combat.gate5_service import CombatService
    from combat.gate2_runtime_models import Position
    from combat import summons
    from tests.h1_support import ROOT

    arena = deepcopy(CombatService(ROOT, tmp_path).factory_arenas(
        include_retired=True)['battlefield:factory_pillar_arena'])
    # Two islands: after the summoner teleports, the destroyed spirit's old
    # landing and the distant caster are outside its 30-foot restoration range.
    open_cells = {(4, 6), (3, 7), (3, 6), (12, 6), (12, 7)}
    arena['terrain_regions'] = [{
        'region_id': 'blocked.crowded-regression', 'terrain_type': 'BLOCKED',
        'description': 'Crowded map with only the fixture landing spaces open.',
        'movement_cost': 0, 'height_ft': 0,
        'cells': [{'x': x, 'y': y} for y in range(arena['height_squares'])
                  for x in range(arena['width_squares']) if (x, y) not in open_cells]}]
    combat, table, fight = match(tmp_path, [EXILE], extra_foes=[(ALLY, 60)],
        foe_mids=BOND, battlefield=arena,
        positions={OWNER: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 7}, ALLY: {'x': 12, 'y': 6}},
        setup_actions=[{'name': 'Destroy spirit', 'target': 'ANY_CREATURE',
                        'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 500,
                                     'damage_types': ['force']}]}],
        foe_setup_actions=[{'name': 'Travel to crowded island',
                            'effects': [{'type': 'teleport', 'applies_to': 'self', 'distance_ft': 60}]}])
    spirit = _spirit(reload(combat, tmp_path, fight))
    assert spirit.active and spirit.position == Position(x=3, y=6)
    assert act(table, fight, 'Destroy spirit', spirit.entity_id)['status'] == 'COMMITTED'
    assert _spirit(reload(combat, tmp_path, fight)).summon['status'] == 'destroyed'
    if exiled:
        assert act(table, fight, 'Exile Beyond the Horizon', ALLY)['status'] == 'COMMITTED'
    while table.state(fight)['menu']['actor_id'] != FOE:
        _advance(table, fight)
    state = table.state(fight); menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == 'Travel to crowded island')
    option = group['options'][0]
    args = (option['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    result = table.act(fight, *args, [])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert any(o.get('cell') == {'x': 12, 'y': 7} for o in prompt['choice']['options']), prompt
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['cell:12,7']}
    assert table.act(fight, *args, [answer])['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, fight)
    owner = engine.state.actors[FOE]
    occupant = engine.state.actors[ALLY]
    assert owner.position == Position(x=12, y=7) and not absent(owner)
    assert occupant.active and absent(occupant) == exiled
    assert occupant.position == Position(x=12, y=6)
    assert engine.grid.distance_ft(owner.position, _spirit(engine).position) > 30
    start = engine.state.event_sequence
    assert act(table, fight, 'Call Back Bonded Spirit')['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, fight)
    spirit = _spirit(engine)
    assert spirit.active == exiled
    assert spirit.summon['status'] == ('present' if exiled else 'destroyed')
    events = [e for e in engine.events if e.sequence > start]
    assert any(e.event_type == 'SUMMON_APPEARED' for e in events) == exiled
    assert any(e.event_type == 'SUMMON_BLOCKED' and
               e.payload.get('reason') == 'no free space in range' for e in events) == (not exiled)
    if exiled:
        assert spirit.position == occupant.position and spirit.current_hp == spirit.maximum_hp
    # The one-cell initial-placement reader shares the same presence contract.
    # Exclude the restored creature itself when checking possible landings.
    actors = {key: actor for key, actor in engine.state.actors.items() if key != spirit.entity_id}
    spot = summons._free_square_near(engine, owner.position, actors, within_ft=30)
    assert spot == (occupant.position if exiled else None)


def _spirit(engine):
    return next(a for a in engine.state.actors.values()
                if a.summon and a.summon['owner'] == FOE and a.summon['group'] == 'bonded_spirit')


def _labels(table, fight):
    return [g['label'] for g in table.state(fight)['menu']['actions']]


@pytest.mark.parametrize('exiled', [False, True], ids=['present-control', 'exiled'])
@pytest.mark.parametrize('boundary', ['menu', 'execution'])
@pytest.mark.parametrize('operation', ['command', 'call-back'])
def test_exiled_summoner_cannot_command_or_restore_outside_spirit(tmp_path, operation, boundary, exiled):
    # The unmarked fixture calls the same effect as the compiled button, so the
    # service transaction checks the execution hook as well as menu eligibility.
    effect = {'type': 'command_summons', 'group': 'bonded_spirit'} if operation == 'command' else {'type': 'spirit_call_back'}
    if operation == 'command':
        # Nested command effects can be reached after a save even when no
        # direct command button is available; test the execution veto too.
        effect = {'type': 'save', 'ability': 'cha', 'applies_to': 'self',
                  'on_fail': [effect], 'on_success': [effect]}
    combat, table, fight = match(tmp_path, [EXILE], foe_mids=BOND,
        setup_actions=[{'name': 'Destroy spirit', 'target': 'ANY_CREATURE',
                        'effects': [{'type': 'damage', 'applies_to': 'target', 'flat': 500, 'damage_types': ['force']}]}],
        foe_setup_actions=[{'name': 'Boundary probe', 'effects': [effect]},
                           {'name': 'Self care', 'effects': [{'type': 'healing', 'applies_to': 'self', 'flat': 1}]}])
    spirit = _spirit(reload(combat, tmp_path, fight))
    if operation == 'call-back':
        assert act(table, fight, 'Destroy spirit', spirit.entity_id)['status'] == 'COMMITTED'
        spirit = _spirit(reload(combat, tmp_path, fight))
        assert not spirit.active and spirit.summon['status'] == 'destroyed'
    if exiled:
        assert act(table, fight, 'Exile Beyond the Horizon', FOE)['status'] == 'COMMITTED'
    _advance(table, fight)
    engine = reload(combat, tmp_path, fight)
    assert engine.state.current_actor_id == FOE
    assert absent(engine.state.actors[FOE]) == exiled
    action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE and
                  (a.parameters.get('summon_command') if operation == 'command' else a.parameters.get('spirit_call_back')))
    # Check both pure menu/AI candidates and the actual operation's public hook.
    if boundary == 'menu':
        assert (action.display_name in _labels(table, fight)) == (not exiled)
    assert act(table, fight, 'Self care')['status'] == 'COMMITTED'
    label = action.display_name if boundary == 'menu' and not exiled else 'Boundary probe'
    assert act(table, fight, label)['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, fight)
    spirit = _spirit(engine)
    if operation == 'command':
        assert spirit.summon['commanded'] == (not exiled)
        assert spirit.active and spirit.summon['status'] == 'present'
    else:
        assert spirit.active == (not exiled)
        assert spirit.summon['status'] == ('destroyed' if exiled else 'present')
        assert any(e.event_type == 'SUMMON_APPEARED' and e.actor_id == FOE for e in engine.events) == (not exiled)
    if not exiled:
        # The real compiled button is also usable (command was already spent by
        # the probe; its removal proves the ordinary once-commanded filter).
        assert action.display_name not in _labels(table, fight)


def _strike(table, fight):
    state = table.state(fight); menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == 'Normal melee hit')
    option = next(o for o in group['options'] if FOE in o.get('target_ids', []))
    args = (option['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    answers = []; prompts = []
    result = table.act(fight, *args, answers)
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']; prompts.append(prompt)
        assert prompt['context']['reaction_source_id'] == 'choice:needle.exploit', prompt
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': ['TAL_FENCING_ARM_STRIKE']})
        result = table.act(fight, *args, answers)
        assert len(prompts) <= 1
    assert result['status'] == 'COMMITTED'
    return prompts


def test_only_adjacent_ally_qualifies_exploit_before_absence_and_after_return(tmp_path):
    combat, table, fight = match(tmp_path, ['TAL_FENCING_ARM_STRIKE'], allies=True, ally_mids=[],
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, ALLY: {'x': 4, 'y': 7}},
        setup_actions=[{'name': 'Normal melee hit', 'target': 'ANY_CREATURE', 'economy': 'ACTION',
                        'effects': [{'type': 'attack', 'attack_kind': 'weapon', 'range_ft': 5}],
                        'typed': {'numbers': {'attack_bonus': 100}}},
                       {'name': 'Remove ally body', 'target': 'ANY_CREATURE',
                        'effects': [{'type': 'spatial_absence', 'applies_to': 'target',
                                     'expires_on': 'END_OF_SOURCE_TURN_AT:2'}]}])
    for phase, expected in [('before', True), ('during', False), ('after', True)]:
        engine = reload(combat, tmp_path, fight)
        assert engine.state.current_actor_id == OWNER
        assert absent(engine.state.actors[ALLY]) == (phase == 'during')
        start = engine.state.event_sequence
        prompts = _strike(table, fight)
        engine = reload(combat, tmp_path, fight)
        rolls = [e for e in engine.events if e.sequence > start and e.event_type == 'ATTACK_ROLLED']
        assert len(rolls) == 1 and rolls[0].payload['mode'] == 'NORMAL'
        assert rolls[0].payload['provisional_hit']
        assert bool(prompts) == expected
        applied = [e for e in engine.events if e.sequence > start and e.event_type == 'PASSIVE_TRIGGERED'
                   and 'applies Exploit: Arm Strike' in str(e.payload)]
        assert bool(applied) == expected
        if phase == 'before':
            assert act(table, fight, 'Remove ally body', ALLY)['status'] == 'COMMITTED'
            assert absent(reload(combat, tmp_path, fight).state.actors[ALLY])
        if phase != 'after':
            # Walk real initiative (including the absent ally's retained slot).
            _advance(table, fight)
            while table.state(fight)['menu']['actor_id'] != OWNER:
                _advance(table, fight)
            reload(combat, tmp_path, fight)
