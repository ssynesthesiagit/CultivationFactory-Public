"""One native critical packet, source-qualified range and pre-damage consent."""
import pytest

from combat import ext, typed_executor as te
from combat.ext import needle, critical_hits
from combat.ext.mind_hidden_eye import mark_analyzed
from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script
from tests.test_auto_lane4 import _duel, _use, _axe, ME, SUBJ, t
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, ALLY, HOLD
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import answer

GAP = 'TAL_THE_HIDDEN_EYE_FIND_GAP'
HELMET = 'tianxia.talent.equipment.helmet_discipline'


def hold_sender(table, mid):
    state = table.state(mid)
    menu = state['menu']
    candidate = next(g['options'][0]['candidate_id'] for g in menu['actions'] if g['source_definition_id'] == HOLD)
    return lambda answers=(): table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))


def native(e, natural=19, *, attacker=ME, target=SUBJ):
    script(e, [natural, 10, 10, 10])
    spec = {'attack_bonus': 0, 'reach_ft': 100, 'damage': DiceSpec(count=1, sides=10, modifier=0), 'damage_type': 'SLASHING'}
    start = len(e.events)
    hit = e._resolve_attack_spec(e.state.actors[attacker], e.state.actors[target], spec, e._active_intent,
                                 source_definition_id='test:native-crit')
    return hit, spec, e.events[start:]


@pytest.mark.parametrize('natural,analyzed,critical', [(18, True, False), (19, False, False), (19, True, True), (20, False, True)])
def test_find_gap_native_automatic_hit_and_final_context(natural, analyzed, critical):
    e = _duel([], attacker_talents=[GAP], attacker_kit=t.AXE_KIT)
    a, target = e.state.actors[ME], e.state.actors[SUBJ]
    target.armor_class = 100
    if analyzed:
        mark_analyzed(e, a, target, 'test:analyze')
    hit, spec, events = native(e, natural)
    assert hit is critical
    if critical:
        assert spec['resolved_attack_context'].critical
        rolls = [x for x in events if x.event_type == 'DAMAGE_ROLLED']
        assert len(rolls) == 1 and rolls[0].payload['dice'] == [10, 10]
        assert len([x for x in events if x.event_type == 'DAMAGE_COMMITTED']) == 1


@pytest.mark.parametrize('resist,expected', [(False, 17), (True, 8)])
def test_one_packet_defense_and_concentration(monkeypatch, resist, expected):
    e = _duel([], attacker_talents=[GAP], attacker_kit=t.AXE_KIT)
    a, target = e.state.actors[ME], e.state.actors[SUBJ]
    mark_analyzed(e, a, target, 'test:analyze')
    calls = []
    install(monkeypatch, 'incoming_damage', lambda *args: calls.append(args[2]) or 3)
    if resist:
        e._add_modifier(target, 'test:resistance', 'damage_resistance', 'SET', 'SLASHING', 'SELF', expires_on='UNTIL_REMOVED')
    e._start_concentration(target, 'test:concentration')
    hit, spec, events = native(e)
    commits = [x.payload['hp_damage'] for x in events if x.event_type == 'DAMAGE_COMMITTED']
    assert hit and commits == [expected] and calls == [20]
    assert len([x for x in events if x.event_type == 'SAVE_ROLLED' and x.source_definition_id == 'system:combat.concentration']) == 1


def test_legacy_typed_query_is_before_damage_and_adapter_does_not_repeat_it(monkeypatch):
    e = _duel([], attacker_kit=t.AXE_KIT)
    seen = []
    def ranged(ctx, target):
        seen.append((ctx.attack_spec['damage'], ctx.attack_effect['attack_kind']))
        return 19
    install(monkeypatch, 'critical_range', ranged)
    script(e, [19, 5, 4])
    events = _use(e, _axe(e))
    assert seen and len([x for x in events if x.event_type == 'DAMAGE_COMMITTED']) == 1
    event = next(x for x in events if x.event_type == 'ATTACK_ROLLED')
    action = next(a for a in e.action_catalog.values() if a.owner_id == ME and a.parameters.get('typed', {}).get('weapon'))
    ctx = te.Context(e, e.state.actors[ME], action, None, action.parameters['typed'], [e.state.actors[SUBJ]])
    count = len(e.events)
    assert critical_hits.expanded(ctx, e.state.actors[SUBJ], event)
    assert len(e.events) == count and getattr(e, '_typed_critical_scope', None) is None


def test_cancellation_stops_later_providers_and_critical_riders(monkeypatch):
    e = _duel([], attacker_kit=t.AXE_KIT)
    calls, after = [], []
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'critical_cancel', [lambda *a: True, lambda *a: calls.append('bad')])
    monkeypatch.setitem(ext._HOOKS, 'after_hit', [lambda ctx, *a: after.append(ctx.critical_hit)])
    script(e, [20, 5, 4])
    events = _use(e, _axe(e))
    assert not calls and after == [False]
    assert [x.payload['critical'] for x in events if x.event_type == 'DAMAGE_ROLLED'] == [False]


@pytest.mark.parametrize('cancel,disadvantage', [(False, False), (True, False), (False, True)])
def test_fatal_opening_respects_cancelled_critical_and_cancelled_advantage(monkeypatch, cancel, disadvantage):
    from tests import test_needle as n
    e = n._team(['TAL_FENCING_FATAL_OPENING', 'TAL_FENCING_EXPERT_FEINT'], foes=1)
    n._answers(e, {'exploit': None})
    n.L4._use(e, 'Feint (Bonus Action)')
    if cancel:
        install(monkeypatch, 'critical_cancel', lambda *a: True)
    if disadvantage:
        e._apply_condition(e.state.actors[n.FENCER], 'condition:typed.blinded', 'test:blind', n.FENCER, expires_on='UNTIL_REMOVED')
    script(e, [19, 19, 3, 3, 3, 3])
    events = n.L4._use(e, 'Bi Shou (Dagger) attack')
    rolls = [x for x in events if x.event_type == 'DAMAGE_ROLLED']
    assert len(rolls) == 1 and rolls[0].payload['critical'] is (not cancel and not disadvantage)
    assert len([x for x in events if x.event_type == 'DAMAGE_COMMITTED']) == 1


@pytest.mark.parametrize('use', [False, True])
def test_helmet_choice_before_damage_pause_reload_and_replay(monkeypatch, tmp_path, use):
    combat, table, mid = table_fight(tmp_path, [HELMET], ally_talents=[])
    on_hold(monkeypatch, lambda e: native(e, 20, attacker=RIGHT, target=LEFT))
    send = hold_sender(table, mid)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    first = send()
    assert first['status'] == 'REACTION_REQUIRED'
    assert 'Native-Crit' in str(first['reaction'])
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    # Reconstruct both service objects and answer the same saved intent.
    fresh = CombatService(ROOT, tmp_path)
    send = hold_sender(TabletopService(fresh, tmp_path), mid)
    result = send([answer(first['reaction'], use=use)])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [x for x in loaded.engine.events if x.event_type == 'DAMAGE_ROLLED' and x.source_definition_id == 'test:native-crit']
    assert len(rolls) == 1 and rolls[0].payload['critical'] is (not use)
    assert len(rolls[0].payload['dice']) == (1 if use else 2)
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_unknown_helmet_not_assumed_without_player():
    e = _duel([HELMET], attacker_kit=t.AXE_KIT)
    hit, spec, events = native(e, 20)
    assert hit and spec['resolved_attack_context'].critical
    assert not any(x.event_type == 'PASSIVE_TRIGGERED' and x.payload.get('critical_turned_normal') for x in events)


def test_find_gap_table_reloads_with_one_critical_packet(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [GAP], ally_talents=[])
    seen = []
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'after_hit', [lambda ctx, *a: seen.append(ctx.critical_hit)])
    def attack(e):
        mark_analyzed(e, e.state.actors[LEFT], e.state.actors[RIGHT], 'test:analyze')
        native(e, 19, attacker=LEFT, target=RIGHT)
    on_hold(monkeypatch, attack)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    damage = [x for x in loaded.engine.events if x.event_type == 'DAMAGE_COMMITTED' and x.source_definition_id == 'test:native-crit']
    assert len(damage) == 1 and damage[0].payload['hp_damage'] == 20
    assert seen and all(seen)
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('defender_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_api_turn_asks_player_but_ai_does_not_invent_headgear(monkeypatch, tmp_path, defender_mode):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[HELMET])
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='API_AUTO')
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode=defender_mode)
    on_hold(monkeypatch, lambda e: native(e, 20, attacker=RIGHT, target=ALLY))
    context = combat.decision(mid)['context']
    candidate = next(c for c in context['legal_candidates'] if c['source_definition_id'] == HOLD)
    payload = {key: candidate[key] for key in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
    payload.update(decision_id=context['decision_id'], state_version=context['state_version'])
    token = combat.ai_validate(mid, payload)['validation_token']
    result = combat.ai_execute(mid, payload, token)
    if defender_mode == 'MANUAL':
        assert result['status'] == 'AWAITING_REACTION'
        prompt = result['reaction_context']
        assert 'Native-Crit' in str(prompt)
        response = {key: prompt[key] for key in ('checkpoint', 'reactor_id', 'reaction_source_id')}
        response.update(selection='USE', option_ids=['protected'])
        combat = CombatService(ROOT, tmp_path)
        result = combat.ai_execute(mid, payload, token, reactions=[response])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    roll = next(x for x in reversed(loaded.engine.events) if x.event_type == 'DAMAGE_ROLLED' and x.source_definition_id == 'test:native-crit')
    assert roll.payload['critical'] is (defender_mode == 'LOCAL_AUTO')
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('point,value', [('attack_critical_range', True), ('attack_critical_range', 1), ('critical_cancel', 'yes')])
def test_invalid_critical_policy_rolls_back(monkeypatch, tmp_path, point, value):
    combat, table, mid = table_fight(tmp_path, [])
    install(monkeypatch, point, lambda *a: value)
    on_hold(monkeypatch, lambda e: native(e, 20, attacker=RIGHT, target=LEFT))
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(CombatServiceError):
        act(table, mid, HOLD)
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode='json') == before


@pytest.mark.parametrize('natural,cancel,failures', [(19, False, 2), (19, True, 1), (20, True, 1)])
def test_damage_at_zero_uses_final_critical_status(monkeypatch, natural, cancel, failures):
    from combat.ext import life_state
    e = _duel(['TAL_BERSERKER_DEATHLESS'], attacker_talents=[GAP], attacker_kit=t.AXE_KIT)
    actor, target = e.state.actors[ME], e.state.actors[SUBJ]
    e._commit_damage(target, target.current_hp, 'FORCE', 'test:down', ME, None, reaction_depth=0)
    assert target.life_state == 'DYING'
    mark_analyzed(e, actor, target, 'test:analyze')
    if cancel:
        install(monkeypatch, 'critical_cancel', lambda *a: True)
    hit, spec, events = native(e, natural)
    assert hit and target.turn_flags[life_state.RECORD]['bad'] == failures
    assert spec['resolved_attack_context'].critical is (not cancel)
    assert spec['resolved_attack_context'].critical_cancelled is cancel
