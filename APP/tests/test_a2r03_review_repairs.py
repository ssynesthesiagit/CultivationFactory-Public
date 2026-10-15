"""A2R03R2 regressions: actual table transitions and exact rendered decisions."""
import copy
from types import SimpleNamespace

import pytest

from combat.ext import beast_echo_marrow as marrow, foundation_sacred_body as body
from tests.test_a2r03_fix_round import _add_companion, _prepare_pressure, COMPANION
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, SERVICE_ALLY, SACRED_BARE, MARROW_BARE, PULSE, ECHO,
    _sacred, _marrow, _service_fight, _until, _candidate, _play, _engine,
    _duel, M_STATE, ME, FOE, ALLY, give, use,
    _act, _answer_for,
)


def _action(bundles, name, effects, *, costs=None, source=None):
    foe = next(b for b in bundles if b['actor_id'] == SERVICE_FOE)
    row = copy.deepcopy(next(a for a in foe['action_catalog'] if a['display_name'] == 'Unarmed Strike'))
    row.update(source_definition_id=source or 'action:test.' + name, display_name=name,
               resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', economy='ACTION')
    row['parameters'] = {'typed': {'source': source or 'test:' + name,
        'numbers': {'cl': 10, 'pb': 4}, 'effects': effects, 'riders': [],
        'duration': {'kind': 'rounds', 'amount': 1}}}
    if costs is not None:
        row['costs'] = costs
    foe['action_catalog'].append(row)
    foe['actor_template']['action_ids'].append(row['source_definition_id'])
    return row


@pytest.mark.parametrize('damage_type', ['poison', 'necrotic'])
def test_ordinary_corruptive_damage_reduction_and_mark_at_table(tmp_path, monkeypatch, damage_type):
    def prepare(bundles):
        _prepare_pressure('CON', 30, 'poisoned', held=1)(bundles)
        _action(bundles, 'Corruptive hit', [{'type': 'damage', 'applies_to': 'target',
            'flat': 30, 'damage_types': [damage_type]}])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE, prepare=prepare)
    _play(table, mid, _candidate(table, mid, 'Corruptive hit', FIGHTER), answer='USE')
    cold = _engine(combat, mid)
    damage = next(e for e in reversed(cold.events) if e.event_type == 'DAMAGE_COMMITTED')
    assert damage.payload['hp_damage'] == 16  # Guard 2PB + CON 2 + corruptive PB
    assert any(c.condition_id == body.GUARD_ADVANTAGE
               for c in cold.state.actors[FIGHTER].conditions.values())


def test_voluntary_movement_is_not_corruptive():
    engine = _duel([], _sacred())
    action = next(iter(engine.action_catalog.values()))
    action.parameters['typed'] = {'effects': [{'type': 'movement', 'applies_to': 'self', 'distance_ft': 5}]}
    assert not body._corruptive(engine, engine.state.actors[FOE], action.source_definition_id)
    action.parameters['typed']['effects'][0]['forced'] = True
    assert body._corruptive(engine, engine.state.actors[FOE], action.source_definition_id)


def test_wake_ends_when_native_zero_hp_applies_unconscious():
    engine = _duel([], _sacred())
    actor = engine.state.actors[ME]
    engine.state.rules['zero_hp'] = 'dying_2024'
    engine._apply_condition(actor, body.WAKE_CONDITION, 'test:wake', ME,
                            expires_on='UNTIL_REMOVED')
    actor.current_hp = 1
    engine._commit_damage(actor, 1, 'UNTYPED', 'test:fall', FOE, None, reaction_depth=1)
    assert actor.life_state == 'DYING'
    assert not any(c.condition_id == body.WAKE_CONDITION for c in actor.conditions.values())


@pytest.mark.parametrize('condition', ['paralyzed', 'petrified', 'stunned', 'unconscious', 'incapacitated'])
def test_wake_ends_on_incapacity_and_stays_ended_after_table_recovery(tmp_path, monkeypatch, condition):
    def prepare(bundles):
        _action(bundles, 'Disable', [{'type': 'condition', 'condition': condition, 'applies_to': 'target'}])
        _action(bundles, 'Recover', [{'type': 'remove_condition', 'condition': condition, 'applies_to': 'target'}])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE, prepare=prepare)
    _until(table, mid, FIGHTER)
    _play(table, mid, _candidate(table, mid, 'Sacred Body Wake'))
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, SERVICE_FOE)
    _play(table, mid, _candidate(table, mid, 'Disable', FIGHTER))
    assert not any(c.condition_id == body.WAKE_CONDITION for c in _engine(combat, mid).state.actors[FIGHTER].conditions.values())
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, SERVICE_FOE)
    _play(table, mid, _candidate(table, mid, 'Recover', FIGHTER))
    cold = _engine(combat, mid)
    assert not any(c.condition_id == body.WAKE_CONDITION for c in cold.state.actors[FIGHTER].conditions.values())
    assert not body._incapacitated(cold.state.actors[FIGHTER])


def test_off_turn_marrow_link_stops_at_latest_owner_start():
    engine = _duel([marrow.GUARD], _marrow(), ally_mids=[])
    owner, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.creature_types = ('Humanoid',)
    engine._active_action_source_id = None
    engine._append_event('DAMAGE_COMMITTED', 'test:old', actor_id=ME, target_ids=(FOE,), payload={})
    engine._append_event('TURN_STARTED', 'test:start', actor_id=ME, payload={})
    engine.state.current_actor_id = FOE
    assert not marrow._damaged_since_last_turn(engine, owner, foe, [ME])
    assert marrow.marrow_pack_guard_trigger(engine, owner, foe, owner, {'feature_id': marrow.GUARD}) is False
    assert not marrow._pressed_by_owner(engine, owner, foe)
    engine._append_event('DAMAGE_COMMITTED', 'test:new', actor_id=ME, target_ids=(FOE,), payload={})
    assert marrow._damaged_since_last_turn(engine, owner, foe, [ME])


@pytest.mark.parametrize('summoned', [False, True])
def test_state_zero_hp_credits_damage_source_not_active_intent(summoned):
    engine = _duel([M_STATE], _marrow(), ally_mids=[])
    give(engine, ME, pack_echo=1)
    use(engine, 'Beast-Echo Marrow State')
    foe = engine.state.actors[FOE]
    foe.creature_types = ('Beast',)
    foe.current_hp = 1
    if summoned:
        foe.summon = {'owner': FOE, 'group': 'test:beast', 'source': 'test:beast', 'status': 'present'}
    engine._active_intent = SimpleNamespace(actor_id=FOE)
    before = len(engine.events)
    engine._commit_damage(foe, 1, 'SLASHING', 'reaction:opportunity_attack', ME, None, reaction_depth=1)
    actor = engine.state.actors[ME]
    assert actor.temporary_hp == 10
    rewards = [e for e in engine.events[before:] if e.event_type == 'TEMP_HP_GRANTED'
               and e.source_definition_id == 'passive:' + marrow.STATE]
    assert len(rewards) == 1
    engine._commit_damage(foe, 1, 'SLASHING', 'test:again', ME, None, reaction_depth=1)
    assert len([e for e in engine.events[before:] if e.event_type == 'TEMP_HP_GRANTED'
                and e.source_definition_id == 'passive:' + marrow.STATE]) == 1


def test_state_rewards_an_actual_opportunity_kill_during_enemy_table_movement(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        foe = next(b for b in bundles if b['actor_id'] == SERVICE_FOE)
        foe['actor_template']['maximum_hp'] = 1
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, foe_creature_types=('Beast',), prepare=prepare)
    _until(table, mid, FIGHTER, answer='DECLINE')
    _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=SERVICE_ALLY)
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, SERVICE_FOE)
    cold = _engine(combat, mid)
    move = next(c for c in cold.legal_candidates() if c.kind == 'MOVE'
                and c.destination.x == 5 and c.destination.y == 6 and c.destination.z == 0)
    start = len(cold.events)
    _play(table, mid, move.candidate_id, answer='USE')
    cold = _engine(combat, mid)
    killed = [e for e in cold.events[start:] if e.event_type == 'DAMAGE_COMMITTED'
              and SERVICE_FOE in e.target_ids and e.payload.get('hp_damage')]
    assert killed and killed[-1].actor_id in {FIGHTER, SERVICE_ALLY}
    killer = cold.state.actors[killed[-1].actor_id]
    assert killer.temporary_hp == 10
    rewards = [e for e in cold.events[start:] if e.event_type == 'TEMP_HP_GRANTED'
               and e.source_definition_id == 'passive:' + marrow.STATE]
    assert len(rewards) == 1 and rewards[0].actor_id == killer.entity_id


def test_companion_witness_rendered_bonus_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        _add_companion(bundles)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
        ally=True, prepare=prepare, positions={FIGHTER: {'x': 4, 'y': 7}})
    _, prompts = _play(table, mid, _candidate(table, mid, 'Body pressure', COMPANION), answer='USE')
    choice = next(p for p in prompts if 'Companion Bond' in str(p))
    assert 'bonded companion' in choice['moment']
    logs = [e.payload.get('log', '') for e in _engine(combat, mid).events]
    assert any('adds 8' in line and 'bonded companion' in line for line in logs)
    cold = _engine(combat, mid)
    holder = SimpleNamespace(actor=cold.state.actors[FIGHTER], numbers={'pb': 4})
    rc = SimpleNamespace(roller=cold.state.actors[COMPANION], kind='save', roll=SimpleNamespace(roll_id='quoted'))
    text = marrow._witness_say(cold, holder, rc, rc.roll)
    assert 'Companion Echo' in text and 'add 8' in text and 'bonded companion' in text


def test_rescue_release_names_actual_ability_at_table(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    observed = []
    def prepare(bundles):
        _action(bundles, 'Body pressure', [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}])
    def release(ctx):
        subject = ctx.engine.state.actors[FIGHTER]
        source = ctx.engine.state.actors[SERVICE_FOE]
        riders = [c for c in subject.conditions.values() if c.condition_id == 'condition:typed.prone']
        observed.append((ctx.action.display_name, [c.condition_id for c in subject.conditions.values()]))
        body._release(ctx.engine, subject, ctx.intent, source, body.RESCUE, riders)
    install(monkeypatch, 'technique_used', release)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _sacred(), SACRED_BARE, prepare=prepare)
    _, prompts = _play(table, mid, _candidate(table, mid, 'Body pressure', FIGHTER), answer='USE')
    choices = [p for p in prompts if any(o['id'].startswith('release:')
               for o in p.get('choice', {}).get('options', []))]
    assert choices, (observed, prompts)
    release = choices[0]
    assert release['reaction'] == 'Refuse Heaven-Lock'
    assert 'the fighter' in release['moment'] and 'Prone' in release['moment']


def test_guard_companion_step_repositions_off_turn_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('WIS', 22, 'frightened', held=1)(bundles)
        _add_companion(bundles)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
        ally=True, foe_creature_types=('Beast',), prepare=prepare,
        positions={FIGHTER: {'x': 4, 'y': 7}})
    before = _engine(combat, mid).state.actors[COMPANION].position
    _, prompts = _play(table, mid, _candidate(table, mid, 'Unarmed Strike', COMPANION), answer='move')
    cold = _engine(combat, mid)
    assert cold.state.actors[COMPANION].position != before
    assert cold.state.current_actor_id == SERVICE_FOE
    assert any(p['reaction'] == 'Marrow Pack Guard' and 'choose where' in p['moment'] for p in prompts)
    assert not cold.state.actors[COMPANION].turn_flags.get('oa_free_ft')


def test_state_moves_off_turn_pair_member_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        row = _action(bundles, 'Pack technique', [], costs=[['resource:core.qi', 1]],
                      source='action:tianxia.talent.blood.test_pack')
        foe = next(b for b in bundles if b['actor_id'] == SERVICE_FOE)
        foe['action_catalog'].remove(row)
        foe['actor_template']['action_ids'].remove(row['source_definition_id'])
        owner = next(b for b in bundles if b['actor_id'] == FIGHTER)
        row['owner_id'] = FIGHTER
        owner['action_catalog'].append(row)
        owner['actor_template']['action_ids'].append(row['source_definition_id'])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, prepare=prepare)
    _until(table, mid, FIGHTER, answer='DECLINE')
    _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=SERVICE_ALLY)
    before = _engine(combat, mid).state.actors[SERVICE_ALLY].position
    _play(table, mid, _candidate(table, mid, 'Pack technique', SERVICE_FOE), answer=SERVICE_ALLY)
    cold = _engine(combat, mid)
    assert cold.state.current_actor_id == FIGHTER
    assert cold.state.actors[SERVICE_ALLY].position != before
    assert not cold.state.actors[SERVICE_ALLY].turn_flags.get('oa_free_ft')


def test_strike_prompt_quotes_effective_bonus_and_hit_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=2)(bundles)
        owner = next(b for b in bundles if b['actor_id'] == FIGHTER)
        owner['actor_template']['initiative_bonus'] = 4  # foe, owner, ally: no intervening Guard spend
        row = _action(bundles, 'Press prey', [{'type': 'damage', 'applies_to': 'target',
                                             'flat': 100, 'damage_types': ['bludgeoning']}])
        foe = next(b for b in bundles if b['actor_id'] == SERVICE_FOE)
        foe['action_catalog'].remove(row)
        foe['actor_template']['action_ids'].remove(row['source_definition_id'])
        row['owner_id'] = FIGHTER
        owner['action_catalog'].append(row)
        owner['actor_template']['action_ids'].append(row['source_definition_id'])
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
        ally=True, prepare=prepare)
    _until(table, mid, FIGHTER, answer='DECLINE')
    _play(table, mid, _candidate(table, mid, 'Press prey', SERVICE_FOE))
    _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=SERVICE_ALLY)
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, SERVICE_ALLY, answer='DECLINE')
    _, prompts = _play(table, mid, _candidate(table, mid, 'Unarmed Strike', SERVICE_FOE), answer='strike')
    choices = [p['moment'] for p in prompts if 'Pack-Marrow Strike' in p['moment']]
    assert choices, prompts
    rendered = choices[0]
    assert '12 damage' in str(rendered)  # PB + linked Marrow PB + State PB
    assert 'the ally' in str(rendered) and 'the foe' in str(rendered)
    assert 'Unarmed Strike' in str(rendered)


def test_predator_step_exempts_only_hit_target_and_other_enemy_can_attack_at_table(tmp_path, monkeypatch):
    enemy = 'actor:factory.a2r03-other-enemy'
    def prepare(bundles):
        foe = next(b for b in bundles if b['actor_id'] == SERVICE_FOE)
        template = copy.deepcopy(foe['actor_template'])
        template.update(entity_id=enemy, owner_id=SERVICE_FOE, display_name='another enemy',
                        primary_combatant=False)
        catalog = copy.deepcopy(foe['action_catalog'])
        renamed = {a['source_definition_id']: a['source_definition_id'] + '.test_other_enemy' for a in catalog}
        for action in catalog:
            action['source_definition_id'] = renamed[action['source_definition_id']]
            action['owner_id'] = enemy
        for key in ('action_ids', 'reaction_ids'):
            template[key] = [renamed.get(a, a) for a in template.get(key, [])]
        reactions = copy.deepcopy([r for r in foe['typed_reactions'] if r.get('block') == 'opportunity'])
        for row in reactions:
            row['action_id'] = renamed[row['action_id']]
        foe['summons'].append({'actor_id': enemy, 'actor_template': template,
            'action_catalog': catalog, 'typed_passives': [], 'typed_reactions': reactions,
            'summon': {'owner': SERVICE_FOE, 'group': 'test:enemy', 'source': 'test:enemy',
                       'arrives': 'start', 'command': 'free', 'command_range_ft': 60,
                       'range_ft': 60, 'concentration': False, 'expected_damage': 0}})
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
                                       ally=True, foe_creature_types=('Beast',), prepare=prepare,
                                       positions={SERVICE_ALLY: {'x': 3, 'y': 5}})
    _until(table, mid, FIGHTER)
    cold = _engine(combat, mid)
    assert cold._distance_actor_to_actor(cold.state.actors[FIGHTER], cold.state.actors[enemy]) == 5
    start = len(cold.events)
    candidate = _candidate(table, mid, 'Unarmed Strike', SERVICE_FOE)
    answers = []
    for _ in range(24):
        result = _act(table, mid, candidate, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        options = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        pick = 'step:2,6' if 'step:2,6' in options else 'move' if 'move' in options else 'DECLINE'
        answers.append(_answer_for(prompt, pick))
    else:
        pytest.fail('movement did not settle')
    cold = _engine(combat, mid)
    assert (cold.state.actors[FIGHTER].position.x, cold.state.actors[FIGHTER].position.y) == (2, 6)
    attacks = [e for e in cold.events[start:] if e.event_type == 'ATTACK_ROLLED' and e.actor_id == enemy]
    assert attacks
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == SERVICE_FOE for e in cold.events[start:])
    assert not cold.state.actors[FIGHTER].turn_flags.get('oa_free_ft')
