"""SOL132 uses built fights and the same perception as the table's fog."""
import pytest

from combat import targeting, target_knowledge
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_hidden_targeting import hidden_fight, LEFT, RIGHT, STRIKE
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.h1_support import ROOT


def subjects(combat, mid):
    e = combat._load_session(mid).engine
    actor, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    attack = next(a for a in e.action_catalog.values() if a.owner_id == LEFT and a.display_name == STRIKE)
    return e, actor, target, attack


def test_darkness_blocks_creature_effect_but_allows_known_square_attack(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, left_abilities=('DARK_BASE_DARKNESS',))
    e, actor, target, attack = subjects(combat, mid)
    spell = attack.model_copy(update={'attack_bonus': None, 'parameters': {'typed': {'effects': [{'type': 'save'}]}}})
    assert not target_knowledge.can_see(e, actor, target)
    assert targeting.reason(e, actor, target, spell) == "Can't target: no line of sight."
    assert targeting.reason(e, actor, target, attack) is None
    assert target_knowledge.knowledge(e, actor, target, attack).mode == 'LAST_OBSERVED'
    assert targeting.concealment_percent(e, actor, target) == 0
    assert targeting.reason(e, actor, actor, spell.model_copy(update={'target_kind': 'SELF'})) is None
    assert targeting.line_of_effect(e, actor, destination=target.position)
    darkness = next(a for a in e.action_catalog.values()
                    if a.owner_id == LEFT and a.display_name == 'Darkness')
    assert any(c.source_definition_id == darkness.source_definition_id and c.destination == target.position
               for c in e.legal_candidates()), 'An area origin needs effect, not sight of its occupants'
    target.conditions.clear()  # Darkness alone, without Hide, also blocks a creature spell.
    assert targeting.reason(e, actor, target, spell) == "Can't target: no line of sight."
    assert targeting.reason(e, actor, target, attack) is None
    e.state.observations[actor.team_id].pop(target.entity_id)
    assert 'known square' in targeting.reason(e, actor, target, attack)
    e.state.observations[actor.team_id][target.entity_id] = target.position.model_copy()
    for zone in e.state.zones.values():
        zone.active = False
    direct = next(c for c in e.legal_candidates() if c.source_definition_id == attack.source_definition_id)
    assert direct.destination is None
    e._active_candidate = direct
    e._apply_condition(target, 'condition:typed.invisible', 'test:invisible', target.entity_id,
                       expires_on='UNTIL_REMOVED')
    target.position = Position(x=target.position.x + 1, y=target.position.y)
    assert target_knowledge.location_missed(e, actor, target, attack.source_definition_id)
    assert e.events[-1].payload['destination'] == {'x': 15, 'y': 11}


def test_pillar_blocks_effect_but_sight_only_obstacle_does_not(tmp_path, monkeypatch):
    combat, _, mid = hidden_fight(tmp_path, monkeypatch)
    e, actor, target, attack = subjects(combat, mid)
    # Unit geometry only; execution rebuilds the grid from the map (corkboard #717).
    actor.position, target.position = Position(x=1, y=1), Position(x=3, y=1)
    e.state.observations[actor.team_id][target.entity_id] = target.position
    e.grid.blocked.add((2, 1))
    assert not targeting.line_of_effect(e, actor, target=target)
    assert 'no line of effect' in targeting.reason(e, actor, target, attack)
    assert not targeting.line_of_effect(e, actor, destination=target.position)
    e.grid.blocked.remove((2, 1))
    e.grid.opaque.add((2, 1))
    assert targeting.line_of_effect(e, actor, target=target)


def test_area_attack_uses_origin_and_does_not_follow_remembered_recipient(tmp_path, monkeypatch):
    combat, _, mid = hidden_fight(tmp_path, monkeypatch)
    e, actor, target, attack = subjects(combat, mid)
    actor.position, target.position = Position(x=1, y=1), Position(x=3, y=3)
    origin = Position(x=1, y=3)
    e.grid.blocked.add((2, 2))
    e.state.observations[actor.team_id][target.entity_id] = Position(x=4, y=3)
    area = attack.model_copy(update={'target_kind': 'CELL', 'parameters': {
        'typed': {'area': {'shape': 'sphere', 'size_ft': 10}, 'effects': [{'type': 'attack'}]}}})
    e.action_catalog[area.source_definition_id] = area
    from types import SimpleNamespace
    e._active_candidate = SimpleNamespace(actor_id=actor.entity_id,
        source_definition_id=area.source_definition_id, target_ids=(), destination=origin, metadata={})
    assert not targeting.line_of_effect(e, actor, target=target)
    assert targeting.line_of_effect(e, actor, destination=origin)
    assert targeting.line_of_effect(e, target, destination=origin)
    assert targeting.attack_line_of_effect(e, actor, target, area.source_definition_id)
    assert not target_knowledge.location_missed(e, actor, target, area.source_definition_id)
    from tests.h1_support import script
    script(e, [100])
    assert not targeting.attack_missed(e, actor, target, area.source_definition_id)
    assert not any('miss_chance_percent' in event.payload for event in e.events)
    e.grid.blocked.add((1, 2))
    assert not targeting.attack_line_of_effect(e, actor, target, area.source_definition_id)


@pytest.mark.parametrize('die, missed', [(1, True), (50, True), (51, False), (100, False)])
def test_total_concealment_roll_precedes_attack_and_reloads(tmp_path, monkeypatch, die, missed):
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    combat, table, mid = hidden_fight(tmp_path, monkeypatch)
    e, _, target, _ = subjects(combat, mid)
    hp, seq = target.current_hp, e.state.event_sequence
    monkeypatch.undo()  # Replace the setup's scripted Hide dice, rather than nesting scripts.
    from combat import ext, typed_reactions
    ext.effects()
    def miss_response(ctx, affected):
        ctx.engine._append_event('PASSIVE_TRIGGERED', 'test:concealment_miss', actor_id=ctx.actor.entity_id,
                                 payload={'log': 'The miss response ran.'})
    monkeypatch.setitem(ext._HOOKS, 'after_miss', [*ext._HOOKS.get('after_miss', []), miss_response])
    rolled_d20 = []
    original = typed_reactions.after_d20
    def observe_d20(engine, who, kind, **kwargs):
        if kind == 'attack':
            rolled_d20.append(kwargs.get('natural'))
        return original(engine, who, kind, **kwargs)
    monkeypatch.setattr(typed_reactions, 'after_d20', observe_d20)
    fixed_dice(monkeypatch, [die, 20, 20] + [6] * 80)
    commit(cast_sender(combat, table, mid, STRIKE, target=RIGHT))
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [v for v in session.engine.events if v.sequence > seq]
    receipts = [v for v in events if 'miss_chance_percent' in v.payload]
    assert len(receipts) == 1 and receipts[0].payload['missed'] is missed
    attacks = [v for v in events if v.event_type == 'ATTACK_ROLLED']
    assert bool(attacks) is not missed
    assert any(v.source_definition_id == 'test:concealment_miss' for v in events) is missed
    assert bool(rolled_d20) is not missed
    if attacks:
        assert receipts[0].sequence < attacks[0].sequence
    if missed:
        assert session.engine.state.actors[RIGHT].current_hp == hp
    assert session.verify()['status'] == 'PASS'


def test_menu_ai_and_seen_only_spell_attack_use_known_square(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, left_at=(7, 11),
        left_abilities=('INK_BASE_INK_LASH',))
    e, actor, target, _ = subjects(combat, mid)
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    options = [c for c in build_decision_context(e, policy, for_ai=True).legal_candidates
               if c.display_name == 'Ink Lash' and RIGHT in c.target_ids]
    assert options and all(c.destination == target.position for c in options)
    menu = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)['menu']
    shown = [o for g in menu['actions'] if g['label'] == 'Ink Lash' for o in g['options']]
    assert shown and all(o['destination'] == {'x': 15, 'y': 11} for o in shown)
    # The owner specifically overrides printed seen-only targeting for attacks.
    spell = next(a for a in e.action_catalog.values() if a.display_name == 'Ink Lash')
    e.action_catalog[spell.source_definition_id] = spell.model_copy(update={
        'parameters': {'typed': {'effects': [{'type': 'save'}]}}})
    context = build_decision_context(e, policy, for_ai=True)
    assert not any(c.source_definition_id == spell.source_definition_id for c in context.legal_candidates)
    choice = combat.controller.choose_primary_action(context)
    assert choice.intent.candidate_id in {c.candidate_id for c in context.legal_candidates}
    selected = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert selected.source_definition_id != spell.source_definition_id
    assert 'no line of sight' in e.action_availability(LEFT, spell.source_definition_id)['reason']


def test_light_concealment_twenty_percent(tmp_path, monkeypatch):
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    combat, _, mid = hidden_fight(tmp_path, monkeypatch)
    e, actor, target, _ = subjects(combat, mid)
    target.conditions.clear()
    for zone in e.state.zones.values():
        zone.trigger_profile['obscured'] = 'light'
        zone.trigger_profile['visual'] = {}
    assert target_knowledge.can_see(e, actor, target)
    assert targeting.concealment_percent(e, actor, target) == 20
    from tests.h1_support import script
    for die, missed in [(20, True), (21, False)]:
        script(e, [die])
        assert targeting.concealment_missed(e, actor, target, 'test:attack') is missed
    for zone in e.state.zones.values():
        zone.active = False
    assert targeting.concealment_percent(e, actor, target) == 0
    e._apply_condition(target, 'condition:typed.invisible', 'test:invisibility', target.entity_id,
                       expires_on='UNTIL_REMOVED')
    assert targeting.concealment_percent(e, actor, target) == 50
