"""Named-ability contract proofs; rider lanes own the final ability adapters.

Devouring Return uses its actual compiled native reaction. Test-only subscribers
exercise the proposed adapter policy without applying the parked rider stash.
"""
from dataclasses import FrozenInstanceError
import pytest

from combat import ext, pending_damage
from combat.ext.needle import ask, checkpoint_id
from combat.gate2_runtime_models import ActionIntent, DiceSpec
from combat.gate5_service import CombatService
from tests.test_auto_lane1 import _sheet
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, duel, ME, FOE, script
from tests.r10_fixup_support import cast_sender, answer

PREFIX = 'foundation.heaven_devouring_shedding_womb_v0_2B.'
RETURN = PREFIX + 'devouring_return'
BLOW = PREFIX + 'origin_seizing_blow'
SPARK = 'resource:foundation.devoured_origin_spark'


def foundation_table(monkeypatch, tmp_path):
    def sheet(*args, **kwargs):
        return _sheet(RETURN, foundation={'foundation_id':PREFIX.split('.')[1], 'stage':'Awakened',
            'resource':{'name':'Devoured Origin Spark','resource_id':'foundation.resource.heaven_devouring',
                        'maximum':3,'initial_current':0,'current':0}})
    monkeypatch.setattr(H, 'sheet', sheet)
    return H.table_fight(tmp_path, [], ask=True)


def devouring(engine, reactor, row, packet, intent):
    if row.get('feature_id') != RETURN:
        return None
    owned_target = reactor.entity_id == packet.target_id
    forbidden = bool(packet.source_flags & {'self_cost','voluntary_overdraw','hidden_injury','breakthrough_backlash'})
    hostile = (packet.hostile and not forbidden) or 'gm_hostile' in packet.source_flags
    ready = packet.resource_before(reactor.entity_id, SPARK) >= 1
    bonus = row['numbers']['pb'] if packet.source_wounded or packet.source_flags & {'direct_drain','origin_theft'} else 0
    return {'allowed': owned_target and hostile and ready, 'reduction_bonus': bonus}


@pytest.mark.parametrize('wounded,flags,early,expected', [
    (False,(),True,6), (True,(),True,10), (False,('direct_drain',),True,10),
    (True,('direct_drain',),True,10), (False,('self_cost',),True,0),
    (False,('self_cost','gm_hostile'),True,6), (False,(),False,0)])
def test_compiled_devouring_return_reads_packet_before_consent_and_reloads(monkeypatch,tmp_path,wounded,flags,early,expected):
    combat, table, mid = foundation_table(monkeypatch,tmp_path)
    seen = []
    def inspect(engine,reactor,row,packet,intent):
        if row.get('feature_id') == RETURN and reactor.entity_id == packet.target_id:
            assert pending_damage.current(engine) is packet
            with pytest.raises(FrozenInstanceError):
                packet.amount = 100
            seen.append((packet.amount,packet.damage_type,packet.source_id,packet.target_id,packet.source_flags))
        return devouring(engine,reactor,row,packet,intent)
    install(monkeypatch,'damage_context_pending_reaction_rank',inspect)
    def gain_same_event(engine,event_type,kwargs):
        if (not early and event_type == 'REACTION_WINDOW_OPENED'
                and engine.events[-1].source_definition_id == 'test:hostile'):
            engine._gain_resource(engine.state.actors[H.LEFT],SPARK,1,'test:new_spark')
    install(monkeypatch,'event',gain_same_event)
    def damage(engine):
        target, source = engine.state.actors[H.LEFT], engine.state.actors[H.RIGHT]
        if early:
            engine._gain_resource(target,SPARK,1,'test:prior_spark')
        if wounded:
            engine._commit_damage(source,1,'FORCE','test:wound',H.LEFT,None,reaction_depth=3)
        engine._commit_damage(target,20,'NECROTIC','test:hostile',H.RIGHT,engine._active_intent,
                              reaction_depth=0,source_flags=flags)
        assert pending_damage.current(engine) is None
    H.on_hold(monkeypatch,damage)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    send = cast_sender(combat,table,mid,'Hold')
    result = send()
    if expected:
        assert result['status'] == 'REACTION_REQUIRED'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == 'reaction:typed.' + RETURN
        result = send([{**prompt['context'],'selection':'USE'}])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    a = loaded.engine.state.actors[H.LEFT]
    assert a.current_hp == before['actors'][H.LEFT]['current_hp'] - (20-expected)
    assert a.resources[SPARK] == (0 if expected else 1)
    assert a.reaction_available is (not bool(expected))
    assert seen and all(p[:4] == (20,'NECROTIC','test:hostile',H.LEFT) for p in seen)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('failure',[{'allowed':1},{'reduction_bonus':-1},{'unknown':True}])
def test_bad_packet_reply_unwinds_damage_and_clears_context(monkeypatch,failure):
    e = duel([])
    install(monkeypatch,'damage_context_pending_reaction_rank',lambda *args:failure)
    # The contract primes only generic rows; this real compiled owner supplies one.
    e.typed_reaction_rows.setdefault(ME,[]).append({'feature_id':'test:query','block':'generic','kind':'damaged'})
    before = e.state.model_dump(mode='json')
    with pytest.raises(ValueError):
        with e._transaction('test:damage','test:damage',FOE):
            c = next(iter(e.legal_candidates()))
            intent = ActionIntent(intent_id='test:damage',decision_id=c.decision_id,candidate_id=c.candidate_id,
                                  state_version=c.state_version,actor_id=c.actor_id)
            e._commit_damage(e.state.actors[ME],10,'FORCE','test:damage',FOE,intent,reaction_depth=0)
    assert e.state.model_dump(mode='json') == before and pending_damage.current(e) is None


def test_nested_packet_restores_outer_context_even_on_error():
    e = duel([])
    a = e.state.actors[ME]
    with pending_damage.scope(e,a,20,'FORCE','test:outer',FOE) as outer:
        with pytest.raises(RuntimeError):
            with pending_damage.scope(e,a,3,'POISON','test:inner',ME) as inner:
                assert pending_damage.current(e) is inner and inner.hostile is False
                raise RuntimeError('stop nested packet')
        assert pending_damage.current(e) is outer
    assert pending_damage.current(e) is None


@pytest.mark.parametrize('forbidden', [False, True])
def test_packet_eligibility_is_available_to_reaction_ranking(monkeypatch, forbidden):
    from combat import typed_reactions
    e = duel(RETURN, foundation={'foundation_id': PREFIX.split('.')[1], 'stage': 'Awakened',
        'resource': {'name': 'Devoured Origin Spark', 'resource_id': 'foundation.resource.heaven_devouring',
                     'maximum': 3, 'initial_current': 1, 'current': 1}})
    target, source = e.state.actors[ME], e.state.actors[FOE]
    row = next(r for r in e.typed_reaction_rows[ME] if r['feature_id'] == RETURN)
    row['priority'] = 0
    target.resources[SPARK] = 1
    install(monkeypatch, 'damage_context_pending_reaction_rank', devouring)
    with pending_damage.scope(e, target, 20, 'FORCE', 'test:rank', FOE,
                              source_flags=('self_cost',) if forbidden else ()):
        pending_damage.prepare(e, 13, None)
        assert pending_damage.current(e).amount == 13
        assert typed_reactions._outranked(e, target, source, {'priority': 1}, 2,
                                         {'pending': 13, 'ranged': False}) is (not forbidden)


@pytest.mark.parametrize('no_damage,hit', [(False, True), (True, True), (True, False)])
def test_native_typed_post_hit_is_once_and_never_runs_on_miss(monkeypatch, no_damage, hit):
    from combat.typed_executor import Context, block_attack
    from tests.test_lock_choices import intent
    e = duel([])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    target.armor_class = 0 if hit else 1000
    seen = []
    def observe(engine, attacker, defender, packet, request):
        seen.append(packet)
        with pytest.raises(FrozenInstanceError):
            packet.attack.source_id = 'changed'
    install(monkeypatch, 'post_hit_damage', observe)
    action = next(a for a in e.action_catalog.values() if a.owner_id == ME and
                  (a.parameters.get('typed') or {}).get('weapon'))
    script(e, [10, 1])
    ctx = Context(e, actor, action, intent(e), action.parameters['typed'], [target], target)
    block_attack(ctx, {'type': 'attack', 'attack_kind': 'weapon', 'no_damage': no_damage})
    assert len(seen) == int(hit)


@pytest.mark.parametrize('invalid_return', [True, False])
def test_failed_paid_checkpoint_unwinds_through_observational_and_generic_guards(monkeypatch, invalid_return):
    from combat import typed_executor, typed_reactions
    from tests.test_lock_choices import intent
    e = duel([])
    before = e.state.model_dump(mode='json')
    events, rolls = list(e.events), list(e.rolls)
    def broken(engine, actor, target, packet, request):
        engine._commit_damage(target, 3, 'FORCE', 'test:paid_extra', actor.entity_id, request, reaction_depth=3)
        if invalid_return:
            return True
        raise RuntimeError('consumer failed after its effect')
    install(monkeypatch, 'post_hit_damage', broken)
    def attack(*args):
        script(e, [10, 1])
        e._resolve_attack_spec(e.state.actors[ME], e.state.actors[FOE],
            {'attack_bonus': 100, 'damage': DiceSpec(count=1, sides=6), 'damage_type': 'FORCE', 'range_ft': 30},
            intent(e), source_definition_id='test:paid_attack')
    monkeypatch.setattr(typed_executor, 'run_effects', attack)
    install(monkeypatch, 'test:outer_observation', lambda: typed_reactions._run_generic_effects(
        e, e.state.actors[ME], e.state.actors[FOE], {'feature_id': 'test:outer'}, [], intent(e)))
    with pytest.raises(ext.CheckpointError):
        with e._transaction('test:paid_attack', 'test:paid_attack', ME):
            ext.run('test:outer_observation')
    assert e.state.model_dump(mode='json') == before
    assert e.events == events and e.rolls == rolls and pending_damage.current(e) is None


@pytest.mark.parametrize('early',[True,False])
def test_origin_seizing_paid_post_hit_choice_added_damage_and_threshold_reload(monkeypatch,tmp_path,early):
    combat, table, mid = foundation_table(monkeypatch,tmp_path)
    def seizing(engine,actor,target,hit,intent):
        if hit.attack.source_id != 'test:foundation_attack':
            return
        assert hit.attack.attacker_id == H.LEFT and hit.attack.target_id == H.RIGHT
        if not hit.resource_before(actor.entity_id,SPARK):
            return
        if not ask(engine,intent,checkpoint_id(engine,'ORIGIN_SEIZING',hit.attack.roll_id),actor,
                   'choice:needle.origin_seizing_proof',['spend'],labels={'spend':f'Spend 1 Devoured Origin Spark to deal 6 Force damage to {target.display_name}'},
                   allow_decline=True,name='Origin-Seizing Blow',feature_id=BLOW,target_id=target.entity_id,
                   prompt='After this hit, spend 1 Devoured Origin Spark without using an Action or Reaction. Gain 4 Temporary HP if the target is below half HP after the added damage.'):
            return
        engine._spend_resource(actor,SPARK,1,BLOW)
        engine._commit_damage(target,6,hit.damage_type,BLOW,actor.entity_id,intent,reaction_depth=3)
        if target.current_hp * 2 < target.maximum_hp:
            engine._grant_temp_hp(actor,4,BLOW,actor.entity_id)
    install(monkeypatch,'post_hit_damage',seizing)
    def new_spark(engine,event_type,kwargs):
        if not early and event_type == 'DAMAGE_COMMITTED' and engine.events[-1].source_definition_id == 'test:foundation_attack':
            engine._gain_resource(engine.state.actors[H.LEFT],SPARK,1,'test:new_spark')
    install(monkeypatch,'event',new_spark)
    def strike(engine):
        actor,target = engine.state.actors[H.LEFT],engine.state.actors[H.RIGHT]
        if early:
            engine._gain_resource(actor,SPARK,1,'test:prior_spark')
        engine._commit_damage(target,28,'FORCE','test:prior_wound',H.LEFT,None,reaction_depth=3)
        script(engine,[10,1])
        engine._resolve_attack_spec(actor,target,{'attack_bonus':100,'damage':DiceSpec(count=1,sides=6),
            'damage_type':'FORCE','range_ft':30},engine._active_intent,source_definition_id='test:foundation_attack')
    H.on_hold(monkeypatch,strike)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    send = cast_sender(combat,table,mid,'Hold')
    result = send()
    if early:
        assert result['status'] == 'REACTION_REQUIRED'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        result = send([answer(result['reaction'],'spend')])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    actor,target = loaded.engine.state.actors[H.LEFT],loaded.engine.state.actors[H.RIGHT]
    assert target.current_hp == (25 if early else 31)
    assert actor.temporary_hp == (4 if early else 0)
    assert actor.resources[SPARK] == (0 if early else 1) and actor.reaction_available
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
