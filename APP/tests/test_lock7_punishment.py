"""C4 Punishment through real ward actions, native/typed hits and saved tables."""
import json
import zipfile

import pytest

from combat import ext
from combat.gate2_runtime_models import DiceSpec
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.ext.protection import PUNISHMENT, aegises
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit

OWNER_PID, ALLY_PID, FOE_PID = 'aaaaaaaa', 'bbbbbbbb', 'ffffffff'
OWNER, ALLY, FOE = ('actor:factory.' + name for name in (OWNER_PID, ALLY_PID, FOE_PID))
ATTACK = 'test:confirmed-attack'


def jian_attack(engine, actor):
    # A carried/held-item copy is not necessarily the Jian the actor can wield.
    from combat.ext.hand_occupancy import weapon_allowed
    actions = (engine.action_catalog[source] for source in actor.action_ids)
    return min((action for action in actions if action.display_name.startswith('Jian')
                and weapon_allowed(engine, actor, action) is not False),
               key=lambda action: len(action.display_name))


def fight(tmp_path, *, owns=True, cl=1, primary='Qi', ally=False, foe_hp=None, teammate=False):
    ids = [OWNER_PID, *([ALLY_PID] if ally else []), FOE_PID]
    for name in ids:
        document = sheet([PUNISHMENT] if owns and name == OWNER_PID else [], cl=cl, primary=primary,
            kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian'}]}})
        document['identity']['display_name'] = {OWNER_PID: 'Owner', ALLY_PID: 'Ally', FOE_PID: 'Foe'}[name]
        if name == FOE_PID and foe_hp is not None:
            document['ability_scores_and_statistics']['hit_points']['maximum'] = foe_hp
        folder = tmp_path / 'portable_characters' / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(OWNER_PID, {'mode': 'ask'}, {PUNISHMENT})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Punishment yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4], [3, 5]], 'team2': [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=[OWNER_PID] if teammate else ids[:-1],
        opponent_actor_ids=[FOE, ALLY] if teammate else [FOE],
        control_modes={'actor:factory.' + n: 'MANUAL' for n in ids},
        arena_id='battlefield:map.punishment-yard', match_seed='LOCK7-PUNISHMENT')['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def cast_ward(combat, table, mid, target=OWNER, persistent=True):
    turn(table, mid, OWNER)
    commit(cast_sender(combat, table, mid,
        'Aegis: Punishment' + (' (Persistent)' if persistent else ''), target=target))
    e = combat._load_session(mid).engine
    assert len(aegises(e.state.actors[target], OWNER, persistent=persistent)) == 1


def fixture_attack(monkeypatch, *, case='damage', path='native', target_id=OWNER, count=1):
    install(monkeypatch, 'd20_result', lambda e, roll, *args: {'source_id': 'test:fixed-roll',
        'operation': 'replace', 'natural_result': 1 if 'concentration' in roll.reason.lower() else 10})
    if case == 'zero_damage':
        install(monkeypatch, 'final_damage', lambda e, t, amount, dtype, source, *args:
            {'amount': 0} if source == ATTACK else None)
    if case == 'defended_miss':
        if path == 'portable':
            install(monkeypatch, 'before_attack', lambda *args:
                {'force_miss': True, 'source_id': 'test:defense', 'label': 'The defense makes this attack miss.'})
        else:
            install(monkeypatch, 'hit_response', lambda e, a, t, spec, total, natural, ac: (total + 100, False))
    if case == 'redirected':
        install(monkeypatch, 'retarget_attack', lambda e, a, t, *args:
            {'source_id': 'test:redirect', 'target_id': ALLY} if t.entity_id == OWNER else None)
    def strike(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs['actor_id'] != FOE:
            return
        attacker, target = engine.state.actors[FOE], engine.state.actors[target_id]
        for _ in range(count):
            damage = None if case == 'no_damage' else DiceSpec(count=1, sides=4)
            amount = 1000 if case == 'lethal' else 3
            bonus = -100 if case == 'rolled_miss' else 50
            if path == 'portable':
                # Exercise the portable resolver inside the same saved table transaction.
                from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
                CharacterCombatRuntimeEngine._resolve_character_attack(engine, attacker, target, source_id=ATTACK,
                    attack_bonus=bonus, damage=damage, damage_type='BLUDGEONING',
                    intent=engine._active_intent, fixed_damage=0 if damage is None else amount, ranged=False)
            else:
                engine._resolve_attack_spec(attacker, target,
                    {'reach_ft': 5, 'attack_bonus': bonus, 'damage': damage, 'damage_type': 'BLUDGEONING',
                     'fixed_damage': amount}, engine._active_intent, source_definition_id=ATTACK)
    install(monkeypatch, 'event', strike)


def retaliations(engine):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and '.aegis.punishment' in e.source_definition_id]


def hold_sender(combat, table, mid):
    state = table.state(mid)
    c = next(c for c in combat._load_session(mid).engine.legal_candidates()
             if c.source_definition_id == 'system:combat.hold_position')
    return lambda answers=(): table.act(mid, c.candidate_id, c.decision_id, c.state_version,
                                      state['last_sequence'], list(answers))


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('path', ['native', 'portable'])
@pytest.mark.parametrize('case', ['damage', 'no_damage', 'zero_damage', 'rolled_miss', 'defended_miss', 'unowned', 'lethal'])
def test_confirmed_hit_once_per_attack_at_table_and_reload(monkeypatch, tmp_path, path, case):
    combat, table, mid = fight(tmp_path, owns=case != 'unowned')
    if case != 'unowned':
        cast_ward(combat, table, mid)
    fixture_attack(monkeypatch, case=case, path=path)
    turn(table, mid, FOE)
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    expected = case not in ('rolled_miss', 'defended_miss', 'unowned')
    assert len(retaliations(e)) == int(expected)
    assert e.state.actors[FOE].current_hp == before - (4 if expected else 0)
    if case == 'no_damage':
        assert not any(ev.event_type == 'DAMAGE_ROLLED' and ev.source_definition_id == ATTACK for ev in e.events)
    if case == 'defended_miss':
        assert any(ev.event_type == 'ATTACK_ROLLED' and ev.payload['provisional_hit'] for ev in e.events)


def test_two_hits_and_expired_concentration_keep_only_hit_time_receipt(monkeypatch, tmp_path):
    combat, table, mid = fight(tmp_path)
    cast_ward(combat, table, mid, persistent=False)
    fixture_attack(monkeypatch, count=2)
    turn(table, mid, FOE)
    commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    assert len(retaliations(e)) == 1
    assert not aegises(e.state.actors[OWNER]) and e.state.actors[OWNER].concentration is None


def test_each_hit_retaliates_and_redirect_uses_actual_bearer(monkeypatch, tmp_path):
    combat, table, mid = fight(tmp_path, ally=True)
    cast_ward(combat, table, mid, target=ALLY)
    fixture_attack(monkeypatch, case='redirected', count=2)
    turn(table, mid, FOE)
    commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    assert len(retaliations(e)) == 2


@pytest.mark.parametrize('use', [False, True, 'AI'])
def test_succor_sacrifice_stacks_exactly_once_and_survives_pause(monkeypatch, tmp_path, use):
    combat, table, mid = fight(tmp_path, ally=True, primary='Stamina')
    stamina = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.stamina']
    cast_ward(combat, table, mid, target=ALLY)
    assert combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.stamina'] == stamina - 2
    fixture_attack(monkeypatch, target_id=ALLY)
    turn(table, mid, FOE)
    if use == 'AI':
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    send = hold_sender(combat, table, mid)
    if use != 'AI':
        paused = send()
        assert paused['status'] == 'REACTION_REQUIRED' and 'Punishment' in paused['reaction']['reaction']
        assert all(word in paused['reaction']['moment'] for word in ('Foe', 'Ally', 'Persistent Aegis', 'ward'))
        label = paused['reaction']['choice']['options'][0]['label']
        assert all(word in label for word in ('Reaction', 'end', 'Ally', '4 Psychic', 'no cultivation-resource cost'))
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    prompts = commit(send, lambda prompt: (None, bool(use)) if 'Punishment' in prompt['reaction'] else (None, False))
    e = reload_checked(tmp_path, mid)
    assert len(retaliations(e)) == 1
    succor = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED'
              and ev.source_definition_id == PUNISHMENT]
    assert len(succor) == int(bool(use))
    assert bool(aegises(e.state.actors[ALLY])) is not bool(use)
    if use == 'AI':
        assert not prompts


@pytest.mark.parametrize('owns', [False, True])
def test_real_typed_weapon_hit_and_no_ward_negative_control(monkeypatch, tmp_path, owns):
    combat, table, mid = fight(tmp_path, owns=owns)
    if owns:
        cast_ward(combat, table, mid)
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:natural20', 'operation': 'replace', 'natural_result': 20})
    turn(table, mid, FOE)
    commit(cast_sender(combat, table, mid, 'Jian', target=OWNER))
    assert len(retaliations(reload_checked(tmp_path, mid))) == int(owns)


def test_snapshot_contract_rejects_invalid_and_duplicate_receipts(monkeypatch):
    from combat.attack_notifications import capture
    for reply in ([], {1: []}, {'bad': object()}):
        install(monkeypatch, 'hit_snapshot', lambda *args: reply)
        with pytest.raises((ValueError, TypeError)):
            capture(None, None, None, None, None)
    monkeypatch.setitem(ext._HOOKS, 'hit_snapshot', [lambda *a: {'same': []}, lambda *a: {'same': []}])
    with pytest.raises(ValueError, match='duplicate'):
        capture(None, None, None, None, None)


@pytest.mark.parametrize('cl,count', [(4, 0), (5, 1), (11, 2), (17, 3), (20, 3)])
def test_printed_damage_bands_at_table(monkeypatch, tmp_path, cl, count):
    combat, table, mid = fight(tmp_path, cl=cl)
    cast_ward(combat, table, mid)
    fixture_attack(monkeypatch, case='no_damage')
    turn(table, mid, FOE)
    commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    damage = retaliations(e)
    assert len(damage) == 1 and 4 + count <= damage[0].payload['hp_damage'] <= 4 + count * 6
    rolls = [ev for ev in e.events if ev.event_type == 'DAMAGE_ROLLED' and '.aegis.punishment' in ev.source_definition_id]
    assert len(rolls) == int(count > 0)
    if count:
        assert len(rolls[0].payload['dice']) == count


def test_nonattack_damage_does_not_trigger_aegis_or_succor(monkeypatch, tmp_path):
    combat, table, mid = fight(tmp_path, ally=True)
    cast_ward(combat, table, mid, target=ALLY)
    def damage(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == FOE:
            engine._commit_damage(engine.state.actors[ALLY], 3, 'FIRE', 'test:nonattack', FOE,
                                  engine._active_intent, reaction_depth=0)
    install(monkeypatch, 'event', damage)
    turn(table, mid, FOE)
    assert not commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    assert not retaliations(e) and aegises(e.state.actors[ALLY])
    assert e.state.actors[OWNER].reaction_available
    assert not any(ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == PUNISHMENT for ev in e.events)


class AttackProvider:
    def __init__(self):
        self.calls = 0

    def status(self):
        return {'ready': True}

    def complete_json(self, *, prompt_text, **kwargs):
        from combat.gate5_service import AI_RESPONSE_SCHEMA
        self.calls += 1
        frame = json.loads(prompt_text.split('\n\n', 1)[1])
        candidate = next(c for c in frame['legal_candidates'] if c['display_name'].startswith('Jian')
                         and c['target_ids'] == [ALLY])
        payload = {key: candidate[key] for key in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
        payload.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
        return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': payload, 'rationale': 'Strike the warded ally.'},
                'provider_id': 'test:offline', 'model': 'fake', 'request_sha256': 'test:punishment'}


@pytest.mark.parametrize('path', ['native', 'typed'])
def test_retaliation_stops_actual_multiattack_when_attacker_falls(monkeypatch, tmp_path, path):
    from combat.typed_executor import Context, run_effects
    combat, table, mid = fight(tmp_path, ally=True, teammate=True, foe_hp=4)
    cast_ward(combat, table, mid)
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    def strike(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs['actor_id'] != FOE:
            return
        attacker, target = engine.state.actors[FOE], engine.state.actors[OWNER]
        action = jian_attack(engine, attacker)
        if path == 'native':
            action = action.model_copy(update={'resolution_kind': 'MULTI_ATTACK', 'attack_count': 3,
                'attack_bonus': 50, 'damage': DiceSpec(count=1, sides=4), 'damage_type': 'SLASHING',
                'reach_ft': 5})
            candidate = engine._active_candidate.model_copy(update={'target_ids': (OWNER,)})
            engine._resolve_action(attacker, action, candidate, engine._active_intent)
        else:
            typed = dict(action.parameters['typed'])
            run_effects(Context(engine, attacker, action, engine._active_intent, typed, [target], target),
                        [{'type': 'attack', 'attack_kind': 'weapon', 'count': 3}])
    install(monkeypatch, 'event', strike)
    turn(table, mid, FOE)
    commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    assert e.state.terminal_result is None and e.state.actors[ALLY].active
    assert e.state.actors[FOE].current_hp == 0
    attacks = [ev for ev in e.events if ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == FOE]
    assert len(attacks) == len(retaliations(e)) == 1


@pytest.mark.parametrize('owns', [False, True])
def test_nonattack_after_typed_hit_has_no_attack_provenance(monkeypatch, tmp_path, owns):
    from combat.typed_executor import Context, run_effects
    combat, table, mid = fight(tmp_path, owns=owns)
    if owns:
        cast_ward(combat, table, mid)
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    seen = []
    def damage_context(engine, target, amount, dtype, source, *args):
        if source == 'test:later-damage':
            seen.append(engine.damage_context())
    install(monkeypatch, 'final_damage', damage_context)
    def strike(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs['actor_id'] != FOE:
            return
        attacker, target = engine.state.actors[FOE], engine.state.actors[OWNER]
        action = jian_attack(engine, attacker)
        ctx = Context(engine, attacker, action, engine._active_intent, dict(action.parameters['typed']), [target], target)
        run_effects(ctx, [{'type': 'attack', 'attack_kind': 'weapon'}])
        assert ctx.attack_damage_context is None and ctx.hit_snapshots == {}
        ctx.action = action.model_copy(update={'source_definition_id': 'test:later-damage'})
        run_effects(ctx, [{'type': 'damage', 'flat': 1, 'damage_types': ['fire']}])
    install(monkeypatch, 'event', strike)
    turn(table, mid, FOE)
    commit(hold_sender(combat, table, mid))
    e = reload_checked(tmp_path, mid)
    assert seen and all(value is None for value in seen)
    assert len(retaliations(e)) == int(owns)


def test_hit_final_restores_metadata_even_when_callback_raises(monkeypatch):
    from types import SimpleNamespace
    from combat.attack_notifications import finish
    old = object()
    def fail(*args):
        raise RuntimeError('callback failure')
    ctx = SimpleNamespace(hit_snapshots={'old': []}, attack_damage_context=old,
                          engine=SimpleNamespace(_run_final_riders=fail))
    with pytest.raises(RuntimeError, match='callback failure'):
        finish(ctx, None, 'weapon', {'hit_snapshots': {'new': []}, 'resolved_attack_context': object()})
    assert ctx.hit_snapshots == {'old': []} and ctx.attack_damage_context is old


def test_manual_succor_on_api_turn_resumes_after_reload_without_new_provider_call(monkeypatch, tmp_path):
    from tests.r10_fixup_support import answer
    combat, table, mid = fight(tmp_path, ally=True)
    cast_ward(combat, table, mid, target=ALLY)
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:natural20', 'operation': 'replace', 'natural_result': 20})
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='API_AUTO')
    provider = AttackProvider()
    combat = CombatService(ROOT, tmp_path, ai_provider=provider)
    table = TabletopService(combat, tmp_path)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'REACTION_REQUIRED' and 'Punishment' in result['reaction']['reaction']
    assert 'Jian' in result['reaction']['moment']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    resumed = table.auto_step(mid, table.state(mid)['last_sequence'], [answer(result['reaction'])])
    assert resumed['status'] == 'COMMITTED' and provider.calls == 1
    e = reload_checked(tmp_path, mid)
    assert len(retaliations(e)) == 1 and not aegises(e.state.actors[ALLY])
    assert len([ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == PUNISHMENT]) == 1
