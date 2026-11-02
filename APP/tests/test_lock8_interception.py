"""Interception happens inside the accepted action before its payment."""
import pytest
from combat import ext, speech
from combat.technique_interception import activation, damage_amount, forced_distance
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, DiceSpec, EconomyKind
from combat.typed_executor import mark_condition_id
from tests import lock8_support as S
from tests.test_lock_choices import install


def action_for(e, *, typed=False):
    a = ActionDefinition(source_definition_id='test:activation', display_name='Test technique', owner_id=S.ME,
        economy=EconomyKind.ACTION, resolution_kind='TYPED' if typed else 'ATTACK', target_kind='HOSTILE_ENTITY',
        range_ft=60, radius_ft=20, attack_bonus=100, damage=DiceSpec(count=2, sides=8, modifier=0),
        damage_type='FORCE', costs=(('resource:core.qi', 3),),
        parameters={'typed': {'source': 'test:activation', 'numbers': {'save_dc': 50, 'pb': 4},
                             'range_ft': 60, 'area': {'shape': 'sphere', 'size_ft': 20}, 'effects': []}} if typed else {})
    e.action_catalog[a.source_definition_id] = a
    e.state.actors[S.ME].action_ids += (a.source_definition_id,)
    return a


def choose(e, source):
    return next(c for c in e.legal_candidates() if c.source_definition_id == source and c.target_ids == (S.FOE,))


def use(e, candidate):
    e.execute_intent(ActionIntent(intent_id='intercept-'+str(e.state.event_sequence), decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination))


@pytest.mark.parametrize('spend', [False, True])
def test_cancel_retains_or_explicitly_spends_payment_and_skips_completion(monkeypatch, spend):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    action = action_for(e)
    user = e.state.actors[S.ME]
    before = user.resources['resource:core.qi']
    install(monkeypatch, 'technique_declared', lambda *args: {'source_id': 'test:interceptor', 'label': 'Activation stopped',
                                                            'cancel': True, 'spend_activation': spend})
    completed = []
    install(monkeypatch, 'resolution_final', lambda *args: completed.append(True))
    use(e, choose(e, action.source_definition_id))
    assert user.resources['resource:core.qi'] == before - (3 if spend else 0)
    assert user.action_available is not spend
    assert not completed
    assert not any(r.reason.startswith('ATTACK:') for r in e.rolls)


def test_composed_changes_are_local_and_reduce_only_first_damage_roll(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    action = action_for(e, typed=True)
    original = action.model_dump(mode='json')
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'technique_declared', [
        lambda *args: {'source_id': 'test:a', 'label': 'Shorter range', 'range_delta_ft': -30, 'forced_cap_ft': 10},
        lambda *args: {'source_id': 'test:b', 'label': 'Smaller area', 'area_delta_ft': -10, 'damage_roll_reduction': 4}])
    c = choose(e, action.source_definition_id)
    with activation(e, e.state.actors[S.ME], action, c, None) as (changed, _, canceled):
        assert not canceled and changed.range_ft == 30 and changed.radius_ft == 10
        assert changed.parameters['typed']['area']['size_ft'] == 10
        assert forced_distance(e, S.ME, action.source_definition_id, 25) == 10
        assert damage_amount(e, S.ME, action.source_definition_id, 'roll:1', 12) == 8
        assert damage_amount(e, S.ME, action.source_definition_id, 'roll:1', 12) == 8
        assert damage_amount(e, S.ME, action.source_definition_id, 'roll:2', 12) == 12
        assert damage_amount(e, S.FOE, action.source_definition_id, 'roll:1', 12) == 12
    assert action.model_dump(mode='json') == original
    assert not getattr(e, '_interception_frame', None)


def test_retarged_native_attack_hits_its_source_without_catalog_mutation(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    action = action_for(e)
    original = action.model_dump(mode='json')
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': 10})
    install(monkeypatch, 'technique_declared', lambda *args: {'source_id': 'test:mirror', 'label': 'Reflected to its caster', 'retarget_id': S.ME})
    before = e.state.actors[S.ME].current_hp
    use(e, choose(e, action.source_definition_id))
    assert e.state.actors[S.ME].current_hp < before
    assert e.state.actors[S.FOE].current_hp == e.state.actors[S.FOE].maximum_hp
    assert e.action_catalog[action.source_definition_id].model_dump(mode='json') == original


def test_real_speech_knot_does_not_pay_or_refund_a_failed_activation(monkeypatch):
    e = S.fight(S.bundle('WARLEADER_BASE_FIERCE_SHOUT'))
    actor = e.state.actors[S.ME]
    e._apply_condition(actor, speech.SPEECH_KNOT, 'test:point', S.FOE, expires_on='START_OF_SOURCE_NEXT_TURN', data={'dc': 50})
    c = next(c for c in e.legal_candidates() if speech.needs_voice(e.action_catalog.get(c.source_definition_id)))
    before, start = dict(actor.resources), len(e.events)
    use(e, c)
    assert actor.resources == before and actor.action_available
    assert not any(ev.event_type in {'RESOURCE_SPENT', 'RESOURCE_GAINED'} and ev.actor_id == S.ME for ev in e.events[start:])
    assert not any(c.condition_id == speech.SPEECH_KNOT for c in actor.conditions.values())


def test_real_ice_script_shrinks_range_before_typed_attack(monkeypatch):
    ice = 'TAL_ICE_HEAVEN_SEALING_ICE_SCRIPT'
    e = S.fight(S.bundle('TAL_LIGHTNING_LIGHTNING_LASH'), foe=S.bundle(ice, actor_id=S.FOE, dc=50), foe_at=(12, 6))
    e._apply_condition(e.state.actors[S.ME], mark_condition_id('Fracture Mark', S.FOE), 'test:mark', S.FOE,
                       expires_on='UNTIL_REMOVED', data={'mark': 'Fracture Mark'})
    before = e.state.actors[S.FOE].resources['resource:core.qi']
    c = next(c for c in e.legal_candidates() if 'Lightning Lash' in c.display_name)
    use(e, c)
    assert e.state.actors[S.FOE].resources['resource:core.qi'] == before - 3
    assert not e.state.actors[S.FOE].reaction_available
    assert any(ev.payload.get('interceptions') for ev in e.events)
    assert not any(ev.event_type == 'ATTACK_ROLLED' for ev in e.events)


def test_direct_native_attack_calls_declaration_once(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    calls = []
    def stop(*args):
        calls.append(True)
        return {'source_id': 'test:stop', 'label': 'Stopped before rolling', 'cancel': True}
    install(monkeypatch, 'technique_declared', stop)
    assert e._resolve_attack_spec(e.state.actors[S.ME], e.state.actors[S.FOE],
        {'attack_bonus': 100, 'reach_ft': 60}, None, source_definition_id='test:direct') is False
    assert calls == [True]


def test_invalid_interception_rolls_back_earlier_callback_payment(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'))
    action = action_for(e)
    c = choose(e, action.source_definition_id)
    before = e.state.model_dump(mode='json')
    def invalid(engine, actor, *args):
        engine._spend_resource(actor, 'resource:core.qi', 1, 'test:reaction')
        return {'source_id': 'test:bad', 'label': 'Invalid', 'range_delta_ft': 0.5}
    install(monkeypatch, 'technique_declared', invalid)
    with pytest.raises(ValueError):
        use(e, c)
    assert e.state.model_dump(mode='json') == before
    assert not getattr(e, '_interception_frame', None)


def test_direct_attack_rechecks_shortened_range_before_rolling(monkeypatch):
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(12, 6))
    install(monkeypatch, 'technique_declared', lambda *args: {
        'source_id': 'test:ice', 'label': 'Range shortened', 'range_delta_ft': -30})
    assert e._resolve_attack_spec(e.state.actors[S.ME], e.state.actors[S.FOE],
        {'attack_bonus': 100, 'range_ft': 60}, None, source_definition_id='test:direct') is False
    assert not any(ev.event_type == 'ATTACK_ROLLED' for ev in e.events)


@pytest.mark.parametrize('weakening', ['range', 'damage'])
def test_ice_player_reaction_and_affected_player_choice_survive_reload(monkeypatch, tmp_path, weakening):
    import json
    import zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from tests.h1_support import ROOT, sheet
    from tests.test_hidden_targeting import turn
    from tests.test_lock2_persistence import act
    from tests.r10_fixup_support import commit
    ice = 'TAL_ICE_HEAVEN_SEALING_ICE_SCRIPT'
    caster, reactor = 'actor:factory.aaaaaaaa', 'actor:factory.ffffffff'
    for pid, owned in [('aaaaaaaa', 'TAL_LIGHTNING_LIGHTNING_LASH'), ('ffffffff', ice)]:
        doc = sheet([owned], cl=15, dc=50)
        doc['identity']['display_name'] = 'Adept' if pid == 'aaaaaaaa' else 'Frost Warden'
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {owned})
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': 10})
    def mark(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == caster:
            engine._apply_condition(engine.state.actors[caster], mark_condition_id('Fracture Mark', reactor),
                'test:prior-fracture', reactor, expires_on='UNTIL_REMOVED', data={'mark': 'Fracture Mark'})
    install(monkeypatch, 'event', mark)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Interception yard', 'width_squares': 20, 'height_squares': 14,
        'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[12, 6]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[reactor],
        control_modes={caster: 'MANUAL', reactor: 'MANUAL'}, arena_id='battlefield:map.interception-yard', match_seed='L8-INTERCEPT')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, caster)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    def sender(answers=()):
        state = table.state(mid)
        c = next(c for c in combat._load_session(mid).engine.legal_candidates() if 'Lightning Lash: Jolt' in c.display_name)
        return table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], list(answers))
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert sender()['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    prompts = []
    def select(prompt):
        ids = {o['id'] for o in prompt.get('choice', {}).get('options', [])}
        prompts.append(ids)
        if weakening in ids:
            return weakening, True
        if 'resource:core.qi' in ids:
            return 'resource:core.qi', True
        # The admitted Ice rider can separately offer Crack Aim. Decline that
        # defense instead of submitting an option that its prompt never offered.
        return None, False
    commit(sender, select)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    e = loaded.engine
    assert any('resource:core.qi' in ids for ids in prompts) and any(weakening in ids for ids in prompts)
    assert e.state.actors[reactor].resources['resource:core.qi'] == before['actors'][reactor]['resources']['resource:core.qi'] - 3
    assert not e.state.actors[reactor].reaction_available and not e.state.actors[caster].action_available
    if weakening == 'range':
        assert e.state.actors[reactor].current_hp == before['actors'][reactor]['current_hp']
        assert not any(ev.event_type == 'ATTACK_ROLLED' for ev in e.events)
    else:
        rolled = next(ev for ev in e.events if ev.event_type == 'DAMAGE_ROLLED' and ev.actor_id == caster)
        assert rolled.payload['combined_total'] == max(0, rolled.payload['total'] - 15)
    assert not getattr(e, '_interception_frame', None)
