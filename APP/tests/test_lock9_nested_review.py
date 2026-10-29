"""Reaction payment interruption, footprint-aware links and projected explanations."""
import pytest
from combat import ext
from combat.gate2_runtime_models import Position
from combat.ext.chain_links import LINK
from combat.ext.daemonic_riders import BLACK_SUN_STATE
from tests.test_lock8_nested_table import fight, install, reload_checked, select, hold_sender, OWNER, FOE, PARTNER, CP
from tests.r10_fixup_support import cast_sender, commit
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act

DEFENSE = 'TAL_FORCE_COUNTERPRESSURE'


def test_payment_condition_interrupts_living_reactor_without_refunding(monkeypatch, tmp_path):
    service, ui, mid = fight(monkeypatch, tmp_path, foe_features=[DEFENSE])
    def payment_condition(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            engine._commit_damage(engine.state.actors[PARTNER], 5, 'BLUDGEONING', 'test:incoming', OWNER,
                                  engine._active_intent, reaction_depth=0)
        elif kind == 'RESOURCE_SPENT' and kwargs.get('actor_id') == FOE and (kwargs.get('payload') or {}).get('resource_id') == CP:
            engine._apply_condition(engine.state.actors[FOE], 'condition:typed.review_cannot_react', DEFENSE, OWNER,
                expires_on='UNTIL_REMOVED', data={'rule': {'no_reactions': True}})
    install(monkeypatch, 'event', payment_condition)
    monkeypatch.setitem(ext._NESTED_HOOKS, 'event', {*ext._NESTED_HOOKS.get('event', ()), payment_condition})
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    send = hold_sender(service, ui, mid); paused = send()
    assert paused['status'] == 'REACTION_REQUIRED'
    assert send([{**paused['reaction']['context'], 'selection': 'USE', 'option_ids': []}])['status'] == 'COMMITTED'
    e = reload_checked(tmp_path, mid); payer = e.state.actors[FOE]
    assert payer.active and payer.current_hp == before['actors'][FOE]['current_hp'] and not payer.reaction_available
    assert payer.resources[CP] == before['actors'][FOE]['resources'][CP] - 1
    assert e.state.actors[PARTNER].current_hp == before['actors'][PARTNER]['current_hp'] - 5
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == DEFENSE for ev in e.events)



@pytest.mark.parametrize('hp', [1, 200])
def test_black_sun_paid_ally_defense_stops_if_payer_falls_and_reloads(monkeypatch, tmp_path, hp):
    service, ui, mid = fight(monkeypatch, tmp_path, foe_hp=hp, foe_features=[DEFENSE])
    commit(cast_sender(service, ui, mid, 'Black Sun Over the Dantian', target=FOE), select)
    payment_reactions = []
    def payment_window(engine, target, *args):
        if target.entity_id == FOE:
            payment_reactions.append(target.reaction_available)
    install(monkeypatch, 'final_damage', payment_window)
    def hit_ally(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            engine._commit_damage(engine.state.actors[PARTNER], 5, 'BLUDGEONING', 'test:incoming', OWNER,
                                  engine._active_intent, reaction_depth=0)
    install(monkeypatch, 'event', hit_ally)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    send = hold_sender(service, ui, mid)
    paused = send()
    assert paused['status'] == 'REACTION_REQUIRED' and 'Counterpressure' in paused['reaction']['reaction']
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    answers = [{**paused['reaction']['context'], 'selection': 'USE', 'option_ids': []}]
    result = send(answers)
    for _ in range(3):
        if result['status'] == 'COMMITTED':
            break
        assert result['reaction']['reaction'] == 'Devour Essence'
        assert service._load_session(mid).engine.state.model_dump(mode='json') == before
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
        result = send(answers)
    assert result['status'] == 'COMMITTED'
    assert payment_reactions and not any(payment_reactions)
    e = reload_checked(tmp_path, mid); payer, ally = e.state.actors[FOE], e.state.actors[PARTNER]
    assert e.state.terminal_result is None and ally.active
    assert payer.resources[CP] == before['actors'][FOE]['resources'][CP] - 1
    assert not payer.reaction_available
    assert (payer.current_hp == 0) == (hp == 1)
    assert ally.current_hp == before['actors'][PARTNER]['current_hp'] - (5 if hp == 1 else 0)
    resolved = [ev for ev in e.events if ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == DEFENSE]
    assert bool(resolved) == (hp != 1)
    assert any('cannot finish this reaction' in ev.payload.get('log', '') for ev in e.events) == (hp == 1)


def test_large_linked_creature_measures_nearest_occupied_square_through_reload(monkeypatch, tmp_path):
    from combat.footprint_registry import ACTOR_FOOTPRINTS
    from combat.footprints import ActorFootprintDefinition
    # A wide creature spans columns 6–7. Its partner can stand at column 9:
    # origins are 15 feet apart, but their nearest occupied squares are 10 apart.
    monkeypatch.setitem(ACTOR_FOOTPRINTS, FOE, ActorFootprintDefinition(footprint_id='test:wide', width_cells=2,
        height_cells=1, occupied_relative_cells=(Position(x=0,y=0), Position(x=1,y=0)), source_definition_id='test:wide'))
    service, ui, mid = fight(monkeypatch, tmp_path, partner_at=(8,4))
    def link(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED' or kwargs.get('actor_id') != OWNER:
            return
        from combat.typed_executor import Context, run_effects
        action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and 'Lightning Chains' in a.display_name)
        target = engine.state.actors[PARTNER]
        ctx = Context(engine, engine.state.actors[OWNER], action, engine._active_intent, action.parameters['typed'], [target], target)
        from combat.ext.arcs import arc_state
        arc_state(ctx)['primary'] = FOE
        run_effects(ctx, [{'type': 'lightning_link'}])
    install(monkeypatch, 'event', link)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    turn(ui, mid, PARTNER)
    e = service._load_session(mid).engine
    before = e.state.actors[PARTNER].current_hp
    for x, expect_link in [(9, True), (10, False)]:
        e = service._load_session(mid).engine
        c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=x,y=4))
        state = ui.state(mid)
        commit(lambda answers=(): ui.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], list(answers)), select)
        e = reload_checked(tmp_path, mid)
        assert any(c.condition_id == LINK for c in e.state.actors[PARTNER].conditions.values()) == expect_link
        assert e.state.actors[PARTNER].current_hp == before - (0 if expect_link else 4)
        if expect_link:
            rendered = str(ui.state(mid))
            assert 'Lightning link with Target' in rendered and '10 feet' in rendered
            assert '4 lightning damage' in rendered and 'willingly move' in rendered


def test_projected_black_sun_explains_trigger_damage_and_actual_expiry(monkeypatch, tmp_path):
    service, ui, mid = fight(monkeypatch, tmp_path)
    commit(cast_sender(service, ui, mid, 'Black Sun Over the Dantian', target=FOE), select)
    e = reload_checked(tmp_path, mid)
    state = next(c for c in e.state.actors[FOE].conditions.values() if c.condition_id == BLACK_SUN_STATE)
    assert 'end' in state.data['reading'] and '4d8' in state.data['reading']
    rendered = str(ui.state(mid))
    assert state.data['label'] in rendered and state.data['reading'] in rendered
    assert 'Qi, Stamina or Resonance' in rendered and 'Caster' in rendered and 'necrotic damage' in rendered
