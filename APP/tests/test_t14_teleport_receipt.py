"""T14: actual chosen landing publishes distance, never previews or attempts."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_models import Position
from tests.test_mmx86_paid_teleport_variant import (
    ROOT, OWNER, FOE, EMPTY_STEP, _table, _owners_turn, _group, _send, _events, _act)

AFTERIMAGE = "TAL_ATHLETICS_AFTERIMAGE"


def receipts(combat, mid):
    return [e for e in _events(combat, mid) if e['event_type'] == 'PASSIVE_TRIGGERED'
            and e['payload'].get('receipt_kind') == 'motion_distance_receipt']


def test_anchored_return_receipt_uses_return_ability_after_reload(tmp_path):
    from tests.test_a2_space_third_pass import (
        match, reload, _answered_action, ANCHOR, DISPLACE, FOE as recipient, OWNER as caster)

    combat, table, mid = match(tmp_path, [DISPLACE], foe_mids=[ANCHOR, AFTERIMAGE])
    start = reload(combat, tmp_path, mid).state.actors[recipient].position
    prompts = _answered_action(table, mid, 'Spatial Displacement', recipient)
    assert any('anchored_soul' in str(p['context']) for p in prompts)
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[recipient].position == start
    rows = receipts(CombatService(ROOT, tmp_path), mid)
    assert len(rows) == 1
    row = rows[0]
    receipt = row['payload']
    assert receipt['source_definition_id'] == receipt['source_feature_id'] == ANCHOR
    assert row['source_definition_id'] == ANCHOR
    assert receipt['source_actor_id'] == receipt['actor_id'] == recipient != caster
    assert receipt['willing'] == receipt['self_teleport'] == 1
    assert receipt['own_turn'] == 0
    movement = next(e for e in engine.events if e.sequence == receipt['movement_sequence'])
    assert receipt['distance_ft'] == engine.grid.distance_ft(
        Position(**movement.payload['path'][0]), start) > 0
    assert (receipt['destination_x'], receipt['destination_y'], receipt['destination_z']) == (start.x, start.y, start.z)


def test_receipt_history_explains_distance_after_table_reload(tmp_path):
    from combat.history_feed import format_history_feed

    combat, table, mid = _table(tmp_path, owner_talents=(EMPTY_STEP, AFTERIMAGE))
    candidate = _group(_owners_turn(table, mid), 'Empty Step')['options'][0]['candidate_id']
    _act(table, mid, candidate, lambda prompt: [prompt['choice']['options'][-1]['id']])
    cold = CombatService(ROOT, tmp_path)
    row, = receipts(cold, mid)
    actor = cold._load_session(mid).engine.state.actors[OWNER]
    feed = format_history_feed([row], [], pre_state={}, post_state={},
                               actor_names={OWNER: actor.display_name}, definition_names={})
    assert len(feed) == 1
    summary = feed[0]['summary']
    assert actor.display_name in summary
    assert f"{row['payload']['distance_ft']} feet" in summary
    assert 'teleport' in summary.lower() and 'willingly' in summary.lower()
    assert 'Detailed breakdown' not in summary and 'afterimage' not in summary.lower()


@pytest.mark.parametrize('paid', [False, True])
def test_native_chosen_teleport_pause_commit_reload(tmp_path, paid):
    combat, table, mid = _table(tmp_path, owner_talents=(EMPTY_STEP, AFTERIMAGE),
                              unbind_paid=paid)
    group = _group(_owners_turn(table, mid), 'Empty Step (1 Stamina)' if paid else 'Empty Step')
    candidate = group['options'][0]['candidate_id']
    before = combat._load_session(mid).engine.state.actors[OWNER].model_copy(deep=True)
    assert not receipts(combat, mid)
    for _ in range(2):
        table.state(mid)
    paused = _send(table, mid, candidate)
    assert paused['status'] == 'REACTION_REQUIRED'
    assert not receipts(combat, mid)
    prompt = paused['reaction']
    cell = prompt['choice']['options'][-1]
    wanted = Position(**cell['cell'])
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    result = _send(fresh, mid, candidate, [{**prompt['context'], 'selection': 'USE', 'option_ids': [cell['id']]}])
    assert result['status'] == 'COMMITTED'
    cold = CombatService(ROOT, tmp_path)
    engine = cold._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert actor.position == wanted
    pool = 'resource:core.stamina' if paid else 'resource:core.qi'
    assert actor.resources == {k: v - int(k == pool) for k, v in before.resources.items()}
    assert actor.action_available and not actor.bonus_action_available
    rows = receipts(cold, mid)
    assert len(rows) == 1  # paid fixture includes duplicate child spelling
    receipt = rows[0]['payload']
    assert receipt['actor_id'] == receipt['source_actor_id'] == receipt['turn_actor_id'] == OWNER
    assert receipt['willing'] == receipt['self_teleport'] == receipt['own_turn'] == 1
    assert receipt['source_feature_id'] == EMPTY_STEP
    assert receipt['source_definition_id'] == rows[0]['source_definition_id']
    assert receipt['intent_id'] and receipt['receipt_id']
    assert receipt['distance_ft'] == engine.grid.distance_ft(before.position, wanted)
    assert receipt['distance_ft'] > 0
    assert (receipt['previous_x'], receipt['previous_y'], receipt['previous_z']) == (before.position.x, before.position.y, before.position.z)
    assert (receipt['destination_x'], receipt['destination_y'], receipt['destination_z']) == (wanted.x, wanted.y, wanted.z)
    assert receipt['round_number'] == engine.state.round_number
    # Persistence attaches its existing control snapshot to the last event.
    # The receipt itself stays primitive; preserve that framework-owned field.
    assert all(type(value) in (int, str) for key, value in receipt.items()
               if key != 'gate3_runtime_control_after')
    movement = [e for e in _events(cold, mid) if e['event_type'] == 'MOVEMENT_COMMITTED' and e['actor_id'] == OWNER]
    assert len(movement) == 1
    assert receipt['movement_sequence'] == movement[0]['sequence']
    assert not any('afterimage' in c.condition_id.lower() for c in actor.conditions.values())
    assert receipts(CombatService(ROOT, tmp_path), mid) == rows


def test_native_decline_is_not_progress(tmp_path):
    combat, table, mid = _table(tmp_path, owner_talents=(EMPTY_STEP, AFTERIMAGE))
    group = _group(_owners_turn(table, mid), 'Empty Step')
    candidate = group['options'][0]['candidate_id']
    before = combat._load_session(mid).engine.state.actors[OWNER].position
    prompt = _send(table, mid, candidate)['reaction']
    assert _send(table, mid, candidate, [{**prompt['context'], 'selection': 'DECLINE', 'option_ids': []}])['status'] == 'COMMITTED'
    cold = CombatService(ROOT, tmp_path)
    assert cold._load_session(mid).engine.state.actors[OWNER].position == before
    assert not receipts(cold, mid)


def test_native_failed_gate_commits_cost_without_distance(tmp_path):
    # The gate is provided by a dynamically loaded compiled row, not the
    # talent's prose. Declare its input for public test export as well.
    import json
    data = json.loads((ROOT / 'combat/rules/feature_blocks.d/riders_lane9.json').read_text())
    assert data['features']['TAL_EARTH_THE_GRAVE_REFUSES_THE_STEP']['kind'] == 'grave'
    combat, table, mid = _table(tmp_path, owner_talents=(EMPTY_STEP, AFTERIMAGE),
                              unbind_paid=True, grave=True, cha_save=-100)
    from combat.ext.earth_responses import rows
    engine = combat._load_session(mid).engine
    assert rows(engine, engine.state.actors[FOE], 'grave')
    if table.state(mid)['menu']['actor_id'] != FOE:
        _send(table, mid, table.state(mid)['menu']['end_turn'])
    mountain = _group(table.state(mid), 'Incarnation of the Patient Mountain')
    _act(table, mid, mountain['options'][0]['candidate_id'], lambda prompt: None)
    group = _group(_owners_turn(table, mid), 'Empty Step (1 Stamina)')
    before = combat._load_session(mid).engine.state.actors[OWNER].model_copy(deep=True)
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source == 'choice:needle.teleport_destination': return ['cell:4,6']
        if source == 'choice:needle.grave_refuses': return ['use']
        return None
    prompts = _act(table, mid, group['options'][0]['candidate_id'], answer)
    assert len(prompts) == 2  # duplicate child does not retry the failed gate
    cold = CombatService(ROOT, tmp_path)
    actor = cold._load_session(mid).engine.state.actors[OWNER]
    assert actor.position == before.position
    assert actor.resources['resource:core.stamina'] == before.resources['resource:core.stamina'] - 1
    assert not actor.bonus_action_available
    assert not receipts(cold, mid)


@pytest.mark.parametrize('control', ['same', 'illegal', 'sealed', 'unwilling', 'forced', 'subject', 'nonowner', 'offturn', 'duplicate'])
def test_general_settlement_controls(control):
    from combat.typed_executor import Context, teleport_subject
    from combat.ext.motion_status import teleport_distance
    from tests.test_mmx86_teleport_destination import _engine, _unbound_teleport, _intent, ME
    engine = _engine(talents=(EMPTY_STEP,) if control == 'nonowner' else (EMPTY_STEP, AFTERIMAGE))
    actor = engine.state.actors[ME]
    action = _unbound_teleport(engine)
    ctx = Context(engine, actor, action, _intent(engine), action.parameters['typed'], [])
    subject = actor
    destination = Position(x=4, y=6)
    kwargs = {}
    if control == 'same': destination = actor.position
    if control == 'illegal': destination = engine.state.actors[next(a for a in engine.state.actors if a != ME)].position
    if control == 'sealed':
        engine._apply_condition(actor, 'condition:typed.restrained', ctx.source, ME,
                                expires_on='START_OF_SOURCE_NEXT_TURN', data={'rule': {'no_teleport': True}})
    if control == 'unwilling': kwargs['unwilling'] = True
    if control == 'forced': kwargs.update(movement_context='FORCED', forced=True)
    if control == 'subject':
        subject = engine.state.actors[next(a for a in engine.state.actors if a != ME)]
        kwargs.update(movement_context='FORCED', unwilling=True, forced=True)
    if control == 'offturn': engine.state.current_actor_id = next(a for a in engine.state.actors if a != ME)
    previous = subject.position
    teleport_subject(ctx, subject, destination, **kwargs)
    rows = [e for e in engine.events if e.payload.get('receipt_kind') == 'motion_distance_receipt']
    if control in ('duplicate', 'offturn'):
        assert len(rows) == 1
        assert rows[0].payload['own_turn'] == int(control != 'offturn')
        teleport_distance(engine, dict(rows[0].payload))
        teleport_subject(ctx, subject, destination, **kwargs)
        assert len([e for e in engine.events if e.payload.get('receipt_kind') == 'motion_distance_receipt']) == 1
    else:
        assert not rows
    assert subject.position == (previous if control in ('same', 'illegal', 'sealed') else destination)
