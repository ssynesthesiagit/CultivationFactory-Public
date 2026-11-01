"""Space second pass: printed action economy, damage and caster-turn expiry.

All behavior is exercised through CombatService's saved table transactions and
cold reload with mechanical replay, rather than a bare engine invocation.
"""
import pytest



from tests.test_hunt32_edge import OWNER, FOE, act, match, reload
from tests.test_auto23_space import ALLY, SWAP, SEVERANCE, PHASE

REFLEXES = 'insight.folded-reflexes'
FOLD = 'TAL_SPACE_FOLD_STEP'
EXTENDED = 'tianxia.talent.space.extended_fold'


def _swap(table, mid, label):
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == label)
    option = next(o for o in group['options'] if ALLY in o.get('target_ids', []))
    args = (option['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    answers = []
    result = table.act(mid, *args, answers)
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        assert len(answers) < 4, result
        answers.append({**prompt['context'], 'selection': 'USE',
                        'option_ids': [prompt['choice']['options'][0]['id']]})
        result = table.act(mid, *args, answers)
    assert result['status'] == 'COMMITTED'
    return result


@pytest.mark.parametrize('cl', [10, 20])
@pytest.mark.parametrize('ally_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_short_swap_bonus_action_cost_and_cold_reload(tmp_path, cl, ally_mode):
    combat, table, mid = match(tmp_path, [SWAP], cl=cl, allies=True, ally_mode=ally_mode)
    before = reload(combat, tmp_path, mid)
    positions = {a: before.state.actors[a].position for a in [OWNER, ALLY]}
    resources = dict(before.state.actors[OWNER].resources)
    _swap(table, mid, 'Short Swap (Bonus Action, 2 CP)')
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[OWNER].position == positions[ALLY]
    assert engine.state.actors[ALLY].position == positions[OWNER]
    assert sum(resources.values()) - sum(engine.state.actors[OWNER].resources.values()) == 2
    assert not engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[OWNER].action_available
    assert not any(e.event_type == 'GM_RIDER' and 'short_swap' in str(e.source_definition_id)
                   for e in engine.events)


def test_short_swap_bonus_action_not_offered_below_cl10(tmp_path):
    combat, table, mid = match(tmp_path, [SWAP], cl=9, allies=True)
    engine = reload(combat, tmp_path, mid)
    assert not any('Bonus Action, 2 CP' in c.display_name for c in engine.legal_candidates())
    _swap(table, mid, 'Short Swap')
    engine = reload(combat, tmp_path, mid)
    assert not engine.state.actors[OWNER].action_available
    assert engine.state.actors[OWNER].bonus_action_available


def test_phase_step_crosses_creatures_for_double_cost_and_expires(tmp_path):
    combat, table, mid = match(tmp_path, [PHASE], allies=True)
    assert act(table, mid, 'Phase Step')['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    hp = engine.state.actors[OWNER].current_hp
    condition = next(c for c in engine.state.actors[OWNER].conditions.values()
                     if c.condition_id == 'condition:typed.space_phase')
    assert condition.data['creature_passage'] == 1
    state = table.state(mid)
    menu = state['menu']
    assert not any(m['destination'] in [{'x': 4, 'y': 6}, {'x': 5, 'y': 6}] for m in menu['moves'])
    assert any(m['destination'] == {'x': 6, 'y': 6} for m in menu['moves'])
    path = [{'x': x, 'y': 6} for x in range(3, 7)]
    from combat.movement_routes import explicit_candidate, parse_waypoints

    route = explicit_candidate(engine, OWNER, parse_waypoints(path))
    result = table.act(mid, route.candidate_id, menu['decision_id'], menu['state_version'],
                       state['last_sequence'], movement_path=path, actor_id=OWNER)
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[OWNER].position.x == 6
    assert engine.state.actors[OWNER].movement_remaining_ft == 5  # 10 + 10 + 5
    assert engine.state.actors[OWNER].current_hp == hp
    assert act(table, mid)['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.space_phase'
                   for c in engine.state.actors[OWNER].conditions.values())


def test_legacy_phase_packet_does_not_gain_new_passage(tmp_path):
    from combat.ext.space_phase import phased_creature_passage

    combat, table, mid = match(tmp_path, [], setup_actions=[{
        'name': 'Legacy Phase Step', 'effects': [{'type': 'space_phase', 'applies_to': 'self'}]}])
    assert act(table, mid, 'Legacy Phase Step')['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.space_phase' for c in owner.conditions.values())
    assert phased_creature_passage(engine, owner, foe) is None


def test_short_swap_bonus_action_can_spend_safe_return_mark(tmp_path):
    from combat.ext import placed

    combat, table, mid = match(tmp_path, [SWAP, 'tianxia.talent.space.safe_return_mark'], cl=10)
    home = reload(combat, tmp_path, mid).state.actors[OWNER].position
    assert act(table, mid, 'Safe Return Mark (1 CP)')['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    move = menu['moves'][0]
    args = (move['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    answers = []
    result = table.act(mid, *args, answers)
    while result['status'] == 'REACTION_REQUIRED':
        assert len(answers) < 4, result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        result = table.act(mid, *args, answers)
    assert result['status'] == 'COMMITTED'
    assert reload(combat, tmp_path, mid).state.actors[OWNER].position != home
    assert act(table, mid)['status'] == 'COMMITTED'
    assert act(table, mid)['status'] == 'COMMITTED'
    before = dict(reload(combat, tmp_path, mid).state.actors[OWNER].resources)
    assert act(table, mid, 'Short Swap to the Safe Return Mark (Bonus Action, 2 CP)')['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.position == home
    assert not owner.bonus_action_available and owner.action_available
    assert sum(before.values()) - sum(owner.resources.values()) == 2
    assert not placed.of(engine, 'return', owner_id=OWNER)


@pytest.mark.parametrize('cl,count', [(16, 6), (17, 8), (20, 8)])
def test_spatial_severance_scales_and_blocks_until_casters_next_end(tmp_path, cl, count):
    combat, table, mid = match(tmp_path, [SEVERANCE], cl=cl)
    assert act(table, mid, 'Spatial Severance', FOE)['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'
              and 'spatial_severance' in str(e.source_definition_id)]
    assert damage and damage[-1].payload['expression'] == f'{count}d8+0'
    held = lambda e: [c for c in e.state.actors[FOE].conditions.values()
                      if c.condition_id == 'condition:typed.cannot_teleport']
    assert held(engine)
    # Target's first turn ending is earlier than the caster's NEXT turn ending.
    assert act(table, mid)['status'] == 'COMMITTED'
    assert act(table, mid)['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    assert held(engine), 'block ended with target, before the printed caster deadline'
    assert act(table, mid)['status'] == 'COMMITTED'
    assert not held(reload(combat, tmp_path, mid))


def test_spatial_severance_success_blocks_until_casters_next_start(tmp_path):
    combat, table, mid = match(tmp_path, [SEVERANCE], setup_actions=[{
        'name': 'Test Dexterity save bonus', 'target': 'ANY_CREATURE',
        'effects': [{'type': 'save_bonus', 'amount': 100, 'abilities': ['DEX'],
                     'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}]}])
    assert act(table, mid, 'Test Dexterity save bonus', FOE)['status'] == 'COMMITTED'
    assert act(table, mid, 'Spatial Severance', FOE)['status'] == 'COMMITTED'
    held = lambda e: any(c.condition_id == 'condition:typed.cannot_teleport'
                         for c in e.state.actors[FOE].conditions.values())
    assert held(reload(combat, tmp_path, mid))
    assert act(table, mid)['status'] == 'COMMITTED'
    assert held(reload(combat, tmp_path, mid)), 'success block ended at target start'
    assert act(table, mid)['status'] == 'COMMITTED'
    assert not held(reload(combat, tmp_path, mid))


@pytest.mark.parametrize('extended,reach', [(False, 20), (True, 35)])
@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_folded_reflexes_asks_destination_and_negates_out_of_reach_attack(tmp_path, extended, reach, mode):
    combat, table, mid = match(tmp_path, [FOLD, REFLEXES, *([EXTENDED] if extended else [])], mode=mode)
    start = reload(combat, tmp_path, mid).state.actors[OWNER].position
    if mode == 'MANUAL':
        assert act(table, mid)['status'] == 'COMMITTED'
    else:
        # Advance this synthetic AI's turn without letting a different ability
        # move it away before the trigger. Still a real committed session intent.
        from combat.gate2_runtime_models import ActionIntent, CandidateKind

        session = combat._load_session(mid)
        candidate = next(c for c in session.engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
        session.submit_intent(ActionIntent(intent_id='reflexes-ai-end-turn', actor_id=OWNER,
            candidate_id=candidate.candidate_id, decision_id=candidate.decision_id,
            state_version=candidate.state_version), primary_decision_record=None, reaction_provider=None)
        reload(combat, tmp_path, mid)
    state = table.state(mid)
    menu = state['menu']
    group = next(g for g in menu['actions'] if g['label'] == 'Unarmed Strike')
    option = next(o for o in group['options'] if OWNER in o.get('target_ids', []))
    args = (option['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    answers, prompts = [], []
    result = table.act(mid, *args, answers)
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        assert len(answers) < 4, result
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            options = prompt['choice']['options']
            # The shared teleport lists the farthest landing first.
            answer['option_ids'] = [options[0]['id']]
        answers.append(answer)
        result = table.act(mid, *args, answers)
    assert result['status'] == 'COMMITTED'
    if mode == 'MANUAL':
        assert prompts, 'Folded Reflexes never answered the attack at the table'
    else:
        assert not prompts, 'AI owner must decide automatically'
    engine = reload(combat, tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert engine.grid.distance_ft(start, owner.position) == reach
    assert owner.current_hp == owner.maximum_hp
    assert not owner.reaction_available
    assert any(e.event_type == 'RESOURCE_SPENT' and 'folded-reflexes' in str(e.source_definition_id)
               for e in engine.events)
    # The generic scene-use counter is spent and survives cold reload.
    uses = {key: value for key, value in owner.resources.items()
            if key.startswith('resource:uses.') and 'folded-reflexes' in key}
    assert uses and set(uses.values()) == {0}
