"""Native sequences, compound riders and portable completion boundaries."""
import pytest

from combat import typed_executor as te
from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
from combat.gate2_runtime_content import AN, BAI
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, ME, FOE, ALLY, bundle, duel, script, use
from tests.test_lock9_attack_completion import install


def native_fight(attacker):
    engine = Gate4ControllerEngine(ROOT, match_seed='LOCK11-COMPLETION', typed_bundles=(bundle([]),),
        roster_setup={'primary_actor_ids': [AN, BAI, ME],
            'team_by_actor': {AN: 'a', BAI: 'b', ME: 'a' if attacker == AN else 'b'},
            'starting_positions': {AN: {'x': 3, 'y': 6}, BAI: {'x': 4, 'y': 6}, ME: {'x': 3, 'y': 8}}})
    while engine.state.current_actor_id != attacker:
        engine.end_turn()
    return engine


@pytest.mark.parametrize('defeats', [False, True])
def test_native_paired_assault_stops_when_response_disables_attacker(monkeypatch, defeats):
    engine = native_fight(AN)
    actor = engine.state.actors[AN]
    def response(e, notice, intent):
        assert notice.attacker_id == AN
        if defeats:
            e._commit_damage(actor, 10000, 'FORCE', 'test:response', BAI, intent, reaction_depth=1)
        else:
            e._apply_condition(actor, 'condition:typed.incapacitated', 'test:response', BAI, expires_on='UNTIL_REMOVED')
    install(monkeypatch, response)
    script(engine, [19, 1] * 10)
    events = use(engine, 'Paired Bi Shou Assault', BAI, actor_id=AN)
    assert len([ev for ev in events if ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == AN]) == 1
    assert engine.state.actors[ME].active and engine.state.terminal_result is None


@pytest.mark.parametrize('defeats', [False, True])
def test_separate_typed_attack_blocks_stop_but_nonattack_riders_finish(monkeypatch, defeats):
    engine = duel([], ally_mids=[])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    def response(e, notice, intent):
        if defeats:
            e._commit_damage(actor, 10000, 'FORCE', 'test:response', FOE, intent, reaction_depth=1)
        else:
            e._apply_condition(actor, 'condition:typed.incapacitated', 'test:response', FOE, expires_on='UNTIL_REMOVED')
    install(monkeypatch, response)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {'numbers': {'attack_bonus': 100}}, [target], target)
    strike = {'type': 'attack', 'attack_kind': 'cultivation', 'no_damage': True}
    script(engine, [10] * 10)
    start = len(engine.events)
    te.run_effects(ctx, [strike, {'type': 'temp_hp', 'flat': 7, 'applies_to': 'self'}, strike])
    assert len([ev for ev in engine.events[start:] if ev.event_type == 'ATTACK_ROLLED']) == 1
    if not defeats:
        assert actor.temporary_hp == 7
    assert engine.state.actors[ALLY].active and engine.state.terminal_result is None


@pytest.mark.parametrize('lethal', [False, True])
def test_numbing_venom_finishes_save_dose_and_denial_before_response(monkeypatch, lethal):
    engine = native_fight(BAI)
    target = engine.state.actors[AN]
    seen = []
    def response(e, notice, intent):
        assert notice.source_id == 'action:bai_meizhen.numbing_venom_palm'
        assert any(c.condition_id == 'condition:core.reaction_denied' for c in target.conditions.values())
        assert any(ev.event_type == 'SAVE_ROLLED' and ev.source_definition_id == notice.source_id for ev in e.events)
        assert any('dose' in c.condition_id for c in target.conditions.values())
        seen.append(notice)
        if lethal:
            # End the fight at the response boundary. Already-triggered riders
            # must have settled even though this prevents any later delivery.
            e._commit_damage(target, 10000, 'FORCE', 'test:response', BAI, intent, reaction_depth=1)
    install(monkeypatch, response)
    script(engine, [19, 1, 1] + [1] * 20)
    events = use(engine, 'Numbing Venom Palm', AN, actor_id=BAI)
    assert len(seen) == 1
    assert not getattr(engine, '_attack_completion_queue', None)
    if lethal:
        assert engine.state.terminal_result is not None
        save = next(i for i, ev in enumerate(events) if ev.event_type == 'SAVE_ROLLED')
        response_damage = next(i for i, ev in enumerate(events) if ev.event_type == 'DAMAGE_COMMITTED' and ev.source_definition_id == 'test:response')
        assert save < response_damage


@pytest.mark.parametrize('hit', [False, True])
@pytest.mark.parametrize('ranged', [False, True])
def test_portable_hit_and_miss_notify_once_after_local_riders(monkeypatch, hit, ranged):
    engine = duel([])
    actor, target = engine.state.actors[FOE], engine.state.actors[ME]
    seen = []
    def response(e, notice, intent):
        assert notice.hit is hit and notice.melee is (not ranged)
        assert notice.attacker_id == FOE and notice.target_id == ME
        assert target.current_hp == target.maximum_hp - (2 if hit else 0)
        seen.append(notice)
    install(monkeypatch, response)
    script(engine, [19 if hit else 1])
    intent = ActionIntent(intent_id='portable', decision_id='test', candidate_id='test', state_version=engine.state.state_version, actor_id=FOE, target_ids=(ME,))
    assert CharacterCombatRuntimeEngine._resolve_character_attack(engine, actor, target,
        source_id='test:portable', attack_bonus=100, damage=None, fixed_damage=2,
        damage_type='FIRE' if ranged else 'BLUDGEONING', intent=intent, ranged=ranged) is hit
    assert len(seen) == 1


def test_water_lash_compound_rider_settles_before_response(monkeypatch):
    engine = native_fight(BAI)
    seen = []
    def response(e, notice, intent):
        assert any(c.condition_id == 'condition:bai_meizhen.soaked' for c in e.state.actors[AN].conditions.values())
        seen.append(notice)
    install(monkeypatch, response)
    script(engine, [19, 1] * 10)
    use(engine, 'Water Lash', AN, actor_id=BAI)
    assert len(seen) == 1


@pytest.mark.parametrize('hit', [False, True])
def test_runtime_opportunity_attack_delivers_completion_from_its_adapter(monkeypatch, hit):
    engine = duel([])
    engine.runtime_actor_ids = {*engine.runtime_actor_ids, FOE}
    seen = []
    install(monkeypatch, lambda e, notice, intent: seen.append(notice))
    def consent(request):
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE'), None
    engine.set_reaction_provider(consent)
    actor = engine.state.actors[ME]
    actor.armor_class = 0
    script(engine, [19 if hit else 1])
    intent = ActionIntent(intent_id='move', decision_id='test', candidate_id='test', state_version=engine.state.state_version, actor_id=ME)
    engine._resolve_leave_reach(actor, actor.position, Position(x=2, y=6), intent)
    assert len(seen) == 1 and seen[0].hit is hit
    assert (seen[0].attacker_id, seen[0].target_id) == (FOE, ME)
    assert seen[0].source_id == 'system:combat.opportunity_attack'
