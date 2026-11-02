"""SOL180 separates knowledge previews from actual legal area resolution."""
import json

import pytest

from combat import area_knowledge, area_safety, senses, target_knowledge
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender, commit
from tests.test_hidden_targeting import hidden_fight, LEFT, RIGHT
from tests.test_sol142_area_knowledge import area_context

FIRE = 'FIRE_TAL_FIREBALL_ART'


def action_of(engine, source=FIRE):
    return next(a for a in engine.action_catalog.values()
                if a.owner_id == LEFT and (a.parameters.get('typed') or {}).get('source') == source)


def test_unknown_occupancy_changes_neither_preview_nor_ai_metadata(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, left_abilities=(FIRE,), left_primary='Stamina', greater_darkness=False)
    engine = combat._load_session(mid).engine
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    engine.state.observations[actor.team_id].pop(RIGHT)
    assert target_knowledge.knowledge(engine, actor, target) is None
    action = action_of(engine)
    destination = Position(x=11, y=11)
    assert senses.perceives_cell(engine, actor, destination)
    before = area_context(engine, FIRE)
    preview = area_safety.preview(engine, actor, action, destination)
    assert preview[0] == 0
    # Counterfactual observations are intentionally not committed. Exercise the
    # actual player menu adapter on that view; a cold service read would restore
    # the saved observation and correctly count the remembered creature instead.
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    context = build_decision_context(engine, PolicyLibrary(ROOT).fallback())
    menu = TabletopService._menu({'context': context.model_dump(mode='json'), 'control_mode': 'MANUAL'},
        {a.entity_id: a.display_name for a in engine.state.actors.values()},
        {a.source_definition_id: a.display_name for a in engine.action_catalog.values()}, engine)
    group = next(g for g in menu['actions'] if g['label'] == 'Fireball Art')
    option = next(o for o in group['options'] if o['destination'] == {'x': 11, 'y': 11})
    assert option['expected_damage'] == 0
    target.position = Position(x=17, y=12)
    assert target_knowledge.knowledge(engine, actor, target) is None
    assert area_safety.preview(engine, actor, action, destination) == preview
    assert area_context(engine, FIRE) == before


def test_player_origin_and_preview_use_square_sight_and_remembered_location(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_abilities=(FIRE,), left_primary='Stamina', greater_darkness=False)
    # A cold table read includes the remembered creature at (15,11), not its
    # hidden live (16,11). Center (11,11) catches only the remembered footprint.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if g['label'] == 'Fireball Art')
    assert group['options']
    remembered_option = next(o for o in group['options'] if o['destination'] == {'x': 11, 'y': 11})
    assert remembered_option['expected_damage'] == 21
    for option in group['options']:
        assert senses.perceives_cell(engine, actor, Position(**option['destination']))
    option = next(c for c in area_context(engine, FIRE) if c.destination == Position(x=11, y=11))
    assert option.metadata['hostiles_in_area'] == 1
    assert option.metadata['expected_damage'] == 21
    assert not area_knowledge.origin_allowed(engine, actor, action_of(engine), Position(x=15, y=11))


def test_legal_blast_hits_hidden_recipient_through_table_commit_and_reload(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, left_abilities=(FIRE,), left_primary='Stamina', greater_darkness=False)
    engine = combat._load_session(mid).engine
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert not target_knowledge.located(engine, actor, target)
    before_hp = target.current_hp
    assert senses.perceives_cell(engine, actor, Position(x=11, y=11))
    commit(cast_sender(combat, table, mid, 'Fireball Art', at=(11, 11)))
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.actors[RIGHT].current_hp < before_hp
    assert any(e.event_type == 'DAMAGE_COMMITTED' and RIGHT in e.target_ids
               for e in fresh.engine.events)
    assert area_knowledge.enabled(fresh.engine)
    assert fresh.verify()['status'] == 'PASS'


def test_explicit_unseen_permission_remains_and_old_policy_is_inert(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, left_abilities=(FIRE, 'DARK_BASE_DARKNESS'), left_primary='Stamina', greater_darkness=False)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    at = Position(x=15, y=11)
    assert not senses.perceives_cell(engine, actor, at)
    assert area_knowledge.origin_allowed(engine, actor, action_of(engine, 'DARK_BASE_DARKNESS'), at)
    assert not area_knowledge.origin_allowed(engine, actor, action_of(engine), at)
    for event in engine.events:
        event.payload.pop(area_knowledge.STAMP, None)
    assert not area_knowledge.enabled(engine)
    assert area_knowledge.origin_allowed(engine, actor, action_of(engine), at)
    assert area_safety.preview(engine, actor, action_of(engine), at)[0] == 1


def test_stamp_validation():
    events = [{'event_type': 'MATCH_CREATED', 'payload': {'area_knowledge_policy': 1}}]
    assert area_knowledge.saved_policy(events) == 1
    events[-1]['payload']['area_knowledge_policy'] = True
    with pytest.raises(ValueError):
        area_knowledge.saved_policy(events)


def test_area_policy_survives_commit_and_cold_reload(tmp_path, monkeypatch):
    from combat.gate4_persistence import Gate4Persistence
    from tests.persistence_support import end_turn
    old = Gate4Persistence(ROOT, tmp_path).create_match(match_seed='area-policy-persistence')
    end_turn(old)
    assert area_knowledge.enabled(old.engine)
    permissions = area_knowledge.saved_origin_permissions(old.engine.events)
    monkeypatch.setattr(area_knowledge, 'printed_rules', lambda root: {})
    fresh = Gate4Persistence(ROOT, tmp_path).load_match(old.match_id)
    assert area_knowledge.enabled(fresh.engine)
    assert area_knowledge.saved_origin_permissions(fresh.engine.events) == permissions
    assert fresh.verify()['status'] == 'PASS'


def test_source_change_cannot_change_saved_origins_through_table_commit_reload(tmp_path, monkeypatch):
    # Only the mutable prose file is copied. Everything else stays symlinked to
    # the checkout; no private fixture or complete app copy is required.
    source = tmp_path / 'source'
    rules_relative = 'authority/typed_mechanics/rules_text.json'
    rules_path = source / rules_relative
    rules_path.parent.mkdir(parents=True)
    for parent in ('', 'authority', 'authority/typed_mechanics'):
        excluded = {'': 'authority', 'authority': 'typed_mechanics',
                    'authority/typed_mechanics': 'rules_text.json'}[parent]
        for path in (ROOT / parent).iterdir():
            if path.name != excluded:
                (source / parent / path.name).symlink_to(path, target_is_directory=path.is_dir())
    prose = json.loads((ROOT / rules_relative).read_text())
    rules_path.write_text(json.dumps(prose))
    from tests import test_hidden_targeting
    monkeypatch.setattr(test_hidden_targeting, 'ROOT', source)
    data = tmp_path / 'data'
    combat, table, mid = hidden_fight(data, monkeypatch,
        left_abilities=(FIRE, 'DARK_BASE_DARKNESS'), left_primary='Stamina', greater_darkness=False)
    engine = combat._load_session(mid).engine
    permissions = area_knowledge.saved_origin_permissions(engine.events)
    at = Position(x=15, y=11)
    assert not senses.perceives_cell(engine, engine.state.actors[LEFT], at)
    assert permissions['DARK_BASE_DARKNESS'] == 0
    assert area_knowledge.origin_allowed(engine, engine.state.actors[LEFT], action_of(engine, 'DARK_BASE_DARKNESS'), at)
    assert not area_knowledge.origin_allowed(engine, engine.state.actors[LEFT], action_of(engine), at)
    # Simulate a new process reading changed authority: reverse both permissions.
    prose['DARK_BASE_DARKNESS'] = 'Create Darkness at a point you can see within range.'
    prose[FIRE] = 'Create fire centered anywhere within range.'
    rules_path.write_text(json.dumps(prose))
    assert area_knowledge.bind_origin_permissions(source).get('DARK_BASE_DARKNESS', 1) == 1
    assert area_knowledge.bind_origin_permissions(source)[FIRE] == 0
    combat = CombatService(source, data)
    table = TabletopService(combat, data)
    fresh = combat._load_session(mid)
    assert area_knowledge.saved_origin_permissions(fresh.engine.events) == permissions
    groups = {g['label']: g for g in table.state(mid)['menu']['actions']}
    assert any(o['destination'] == at.model_dump() for o in groups['Darkness']['options'])
    assert not any(o['destination'] == at.model_dump() for o in groups['Fireball Art']['options'])
    commit(cast_sender(combat, table, mid, 'Darkness', at=(15, 11)))
    reloaded = CombatService(source, data)._load_session(mid)
    assert area_knowledge.saved_origin_permissions(reloaded.engine.events) == permissions
    assert reloaded.verify()['status'] == 'PASS'


def test_missing_or_invalid_saved_origin_binding_is_not_reinferred():
    with pytest.raises(ValueError, match='no saved area origin permissions'):
        area_knowledge.saved_origin_permissions([])
    with pytest.raises(ValueError, match='invalid'):
        area_knowledge.saved_origin_permissions([{'event_type': 'MATCH_CREATED',
            'payload': {area_knowledge.ORIGIN_AUTHORITY: {'source': False}}}])
