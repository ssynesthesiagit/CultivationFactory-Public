"""Cancelled projectiles neither repeat an old d20 nor poison the next attack."""
import pytest
from combat import typed_reactions
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_lock9_sight_review import table, checked, hook, OWNER, FOE
from tests.h1_support import ROOT
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import commit, cast_sender

ROLL_RESPONSE = 'TAL_DRUNKEN_STYLE_BORROWED_MISFORTUNE'


@pytest.mark.parametrize('natural', [1, 20])
@pytest.mark.parametrize('held', [False, True])
def test_cancelled_route_preserves_held_benefits_and_does_not_retrigger_prior_roll(monkeypatch, tmp_path, natural, held):
    def prior(engine, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            a, target = engine.state.actors[OWNER], engine.state.actors[FOE]
            # A prior native roll against this defender populates the history
            # queried by the old aftermath code. It is not the cancelled shot.
            # SOL132 requires a physical path for the synthetic prior roll too.
            # Keep the later ricochet setup unchanged after this fixture probe.
            old = target.position
            try:
                target.position = Position(x=3, y=8)
                engine._resolve_attack_spec(a, target, {'attack_bonus': 0, 'damage': None, 'range_ft': 120},
                    engine._active_intent, source_definition_id='test:prior_roll')
            finally:
                target.position = old
            if held:
                engine._add_modifier(a, 'test:held_benefit', 'attack_mode', 'SET', 'ADVANTAGE', 'NEXT_ATTACK', expires_on='CONSUMED')
    hook(monkeypatch, 'event', prior)
    service, mid, candidate, send = table(monkeypatch, tmp_path, foe_features=[ROLL_RESPONSE], natural=natural)
    aftermath = []
    original = typed_reactions.after_d20
    def observe(*args, **kwargs):
        aftermath.append(kwargs.get('natural'))
        return original(*args, **kwargs)
    monkeypatch.setattr(typed_reactions, 'after_d20', observe)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    def mode(ctx, target):
        if ctx.source == candidate.source_definition_id:
            return 'DISADVANTAGE'
    hook(monkeypatch, 'attack_mode', mode)
    def step(engine, actor, target, intent, context):
        if context.get('source_id') == candidate.source_definition_id:
            old = target.position
            target.position = Position(x=3, y=8)
            engine._append_event('MOVEMENT_COMMITTED', 'test:step', actor_id=target.entity_id,
                payload={'destination': target.position.model_dump(mode='json'),
                         'path': [old.model_dump(mode='json'), target.position.model_dump(mode='json')], 'cost_ft': 0})
    hook(monkeypatch, 'before_attack', step)
    prompts = commit(send)
    e = checked(tmp_path, mid)
    assert not aftermath
    assert not any(ROLL_RESPONSE in str(p) for p in prompts)
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == ROLL_RESPONSE for ev in e.events)
    assert e.state.actors[FOE].resources == before['actors'][FOE]['resources']
    assert e.state.actors[FOE].reaction_available
    rolls = [ev for ev in e.events if ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == OWNER]
    assert len(rolls) == 1 and rolls[0].payload['natural_result'] == natural
    mods = list(e.state.actors[OWNER].modifiers.values())
    assert not any(m.target_field == 'attack_mode' and m.source_definition_id == candidate.source_definition_id for m in mods)
    assert any(m.source_definition_id == 'test:held_benefit' for m in mods) is held
    # The actually owned, affordable natural-roll reaction is eligible; the
    # cancelled shot must not invoke it using the historical natural result.
    row = next(r for r in e.typed_reaction_rows[FOE] if r['feature_id'] == ROLL_RESPONSE)
    assert row['kind'] == 'natural_1'
    assert typed_reactions._can_trigger(e, e.state.actors[FOE], row)
    ui = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert act(ui, mid, 'end')['status'] == 'COMMITTED'; turn(ui, mid, OWNER)
    service = ui.combat
    e = service._load_session(mid).engine
    weapon = next(a for a in e.action_catalog.values() if a.owner_id == OWNER and
                  '.weapon.gong_jian' in a.source_definition_id and '#' not in a.source_definition_id)
    # Use an ordinary attack in current short-range circumstances. Decline any
    # genuine Borrowed Misfortune prompted by its new natural 1.
    sequence = e.state.event_sequence
    commit(cast_sender(service, ui, mid, weapon.display_name, target=FOE), lambda p: (None, False))
    e = checked(tmp_path, mid)
    later = [ev for ev in e.events if ev.sequence > sequence and ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == OWNER]
    assert later and later[0].payload['mode'] == ('ADVANTAGE' if held else 'NORMAL')
    assert not any(m.source_definition_id == 'test:held_benefit' for m in e.state.actors[OWNER].modifiers.values())
