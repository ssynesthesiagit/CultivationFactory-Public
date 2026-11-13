"""Due summons leave before all turn-start observers at the real Table boundary."""
import json
import zipfile
from pathlib import Path

import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_summons import _sheet

ROOT = Path(__file__).resolve().parents[1]
OWNER, FOE = 'actor:factory.h64-owner', 'actor:factory.h64-foe'
BONE = 'tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation'


def fight(tmp_path):
    for pid, talents in [('h64-owner', [BONE]), ('h64-foe', [])]:
        sheet = _sheet(talents)
        sheet['identity'].update(display_name=pid, path='Body Refining')
        sheet['ability_scores_and_statistics']['primary_resource'] = {'name': 'Stamina', 'maximum': 30}
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(sheet))
    service = CombatService(ROOT, tmp_path)
    mid = service.create_factory_match(project_ids=['h64-owner'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, match_seed='LOCK17-EXPIRY')['match_id']
    table = TabletopService(service, tmp_path)
    while table.state(mid)['menu']['actor_id'] != OWNER:
        act(table, mid)
    act(table, mid, BONE)
    return service, table, mid


def act(table, mid, source='end'):
    state = table.state(mid)
    menu = state['menu']
    assert menu['manual']
    candidate = menu['end_turn'] if source == 'end' else next(
        o['candidate_id'] for g in menu['actions'] if source in g['source_definition_id'] for o in g['options'])
    result = table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    return result


def test_exact_deadline_precedes_turn_start_hooks_reactions_zones(tmp_path, monkeypatch):
    service, table, mid = fight(tmp_path)
    session = service._load_session(mid)
    guard = next(a for a in session.engine.state.actors.values() if a.summon)
    deadline = tuple(map(int, guard.summon['expires_on'].split(':')[-2:]))
    assert deadline[0] == session.engine.state.round_number + 10
    observed = []
    # Read-only observers at the actual hook and typed-reaction/zone entry
    # points. They reject any due creature before a roll or choice can happen.
    def check(engine, label):
        clock = (engine.state.round_number, engine.state.current_slot_index)
        creature = engine.state.actors.get(guard.entity_id)
        if creature is None:  # temporary stock engine built by the disk loader
            return
        if clock >= deadline:
            assert not creature.active, label
            assert creature.summon['status'] == 'dismissed'
        observed.append((label, clock, creature.active))
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'turn_start', [*ext._HOOKS.get('turn_start', []),
        lambda engine, actor: check(engine, 'turn_start')])
    # The event is dispatched before typed reactions and zone resolution.
    def event(engine, kind, kwargs):
        if kind == 'TURN_STARTED':
            check(engine, 'TURN_STARTED')
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), event])
    from combat import typed_reactions
    original_reactions = typed_reactions.on_turn_start
    def reactions(engine, actor):
        check(engine, 'typed_reactions')
        return original_reactions(engine, actor)
    monkeypatch.setattr(typed_reactions, 'on_turn_start', reactions)
    boundary_counts = []
    def established_clock(engine, actor):
        boundary_counts.append(actor.turns_started)
        assert actor.turns_started > 0
    monkeypatch.setitem(ext._HOOKS, 'turn_boundary_start', [*ext._HOOKS.get('turn_boundary_start', []), established_clock])
    from combat.gate4_engine import Gate4ControllerEngine
    original_zones = Gate4ControllerEngine._resolve_zone_triggers
    def zones(engine, actor, *, checkpoint):
        if checkpoint == 'AT_TURN_START':
            check(engine, 'zones')
        return original_zones(engine, actor, checkpoint=checkpoint)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_zone_triggers', zones)
    rolls = session.engine.state.roll_counter
    for _ in range(40):
        session = service._load_session(mid)
        if not session.engine.state.actors[guard.entity_id].active:
            break
        act(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[guard.entity_id].active
    assert loaded.engine.state.roll_counter == rolls
    preceding = (deadline[0], deadline[1]-1) if deadline[1] else (deadline[0]-1, len(loaded.engine.state.initiative_order)-1)
    assert any(clock == preceding and active for _, clock, active in observed)
    assert {label for label, clock, _ in observed if clock == deadline} >= {'turn_start', 'TURN_STARTED', 'typed_reactions', 'zones'}
    dismissal = next(e for e in loaded.engine.events if e.event_type == 'SUMMON_DISMISSED' and e.payload.get('reason') == 'DURATION_ENDED')
    boundary = next(e for e in loaded.engine.events if e.event_type == 'TURN_STARTED'
                    and (e.payload['round'], e.payload['slot']) == deadline)
    assert dismissal.sequence < boundary.sequence
    assert loaded.verify()['status'] == 'PASS'
    assert any(row['summary'] == "Bone Guard's 1 minute is up; it disappears." for row in table.events(mid, 0)['events'])


def test_boundary_failure_rolls_back_counter_departure_and_events(tmp_path, monkeypatch):
    service, _, mid = fight(tmp_path)
    session = service._load_session(mid)
    engine = session.engine
    before = engine.state.model_dump(mode='json'), list(engine.events), engine.roller.counter
    def fail(engine, actor):
        raise ValueError('boundary failure')
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'turn_boundary_start', [*ext._HOOKS.get('turn_boundary_start', []), fail])
    with pytest.raises(Exception, match='boundary failure'):
        engine.end_turn()
    assert (engine.state.model_dump(mode='json'), engine.events, engine.roller.counter) == before
