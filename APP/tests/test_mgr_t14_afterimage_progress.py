"""Afterimage admission through native table transactions and cold replay."""
import pytest
import json
import zipfile

from combat import ext, motion
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import Position
from combat.granted_movement import resolve_path
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock8_passage import CLOUD
from tests.test_lock9_passage_review import table, hook, checked, OWNER, FOE
from tests.r10_fixup_support import cast_sender, commit

TALENT = "TAL_ATHLETICS_AFTERIMAGE"
SOURCE = "passive:" + TALENT


def armed_progress_table(tmp_path):
    """Real compiled weapon opponent, so leaving its reach has a legal OA."""
    from tests.h1_support import ROOT, sheet
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    for pid, talents in [('aaaaaaaa', [TALENT]), ('ffffffff', ['SAND_BASE_SCOURING_HAND'])]:
        kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu',
                                          'name': 'Fu (Short Axe)', 'quantity': 1}]}}
        doc = sheet(talents, cl=20, kit=kit)
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('ffffffff', {'mode': 'ask'}, set())
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Afterimage progress hall', 'width_squares': 12,
        'height_squares': 14, 'walls': [],
        'starts': {'team1': [[0, 6]], 'team2': [[5, 7]]}})
    mid = service.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, arena_id='battlefield:map.afterimage-progress-hall',
        match_seed='MGR-T14-PROGRESS-ARMED')['match_id']
    ui = TabletopService(service, tmp_path)
    turn(ui, mid, OWNER)
    return service, ui, mid


@pytest.mark.parametrize("off_turn,feet,existing,owned", [
    (True, 25, False, True), (False, 25, False, True),
    (False, 20, False, True), (True, 25, True, True),
    (True, 25, False, False),
])
def test_table_native_admission(monkeypatch, tmp_path, off_turn, feet, existing, owned):
    service, ui, mid = table(tmp_path, CLOUD, extra_features=[TALENT] if owned else [], start=(0, 6))
    engine = service._load_session(mid).engine
    rows = [r for r in engine.typed_passive_rows[OWNER]
            if r.get("kind") == "afterimage"]
    assert [r["feature_id"] for r in rows] == ([TALENT] if owned else [])
    if existing:
        def seed(e, event, kwargs):
            if event == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == OWNER:
                e._apply_condition(e.state.actors[OWNER], motion.AFTERIMAGE, SOURCE, OWNER,
                                   expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Afterimage"})
        hook(monkeypatch, "event", seed)
        assert act(ui, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    if off_turn:
        turn(ui, mid, FOE)
    trigger = FOE if off_turn else OWNER
    def grant(e, event, kwargs):
        if event == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == trigger:
            mover = e.state.actors[OWNER]
            cells = [0, 1, 2, 3, 2] if feet == 20 else range(feet // 5 + 1)
            path = tuple(Position(x=x, y=6) for x in cells)
            assert resolve_path(e, mover, path, "test:willing-grant", feet=feet,
                                intent=e._active_intent, provokes=False) == feet
    hook(monkeypatch, "event", grant)
    before = canonical_sha256(service._load_session(mid).engine.state.model_dump(mode="json"))
    ui.state(mid); ui.state(mid)
    assert canonical_sha256(service._load_session(mid).engine.state.model_dump(mode="json")) == before
    assert act(ui, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    engine = checked(tmp_path, mid)
    mover = engine.state.actors[OWNER]
    assert mover.position == Position(x=2 if feet == 20 else feet // 5, y=6)
    images = [c for c in mover.conditions.values() if c.condition_id == motion.AFTERIMAGE]
    assert bool(images) == (existing or (owned and not off_turn and feet > 20))
    if images:
        assert len(images) == 1 and images[0].source_definition_id == SOURCE
        assert images[0].expires_on == "START_OF_SOURCE_NEXT_TURN"


@pytest.mark.parametrize("owned,condition,source,actor", [
    (True, motion.AFTERIMAGE, "test:other-source", OWNER),
    (False, motion.AFTERIMAGE, SOURCE, OWNER),
    (True, motion.AFTERIMAGE, SOURCE, FOE),
    (True, "condition:typed.drunken_afterimage", SOURCE, OWNER),
])
def test_table_unrelated_condition_admission(monkeypatch, tmp_path, owned, condition, source, actor):
    service, ui, mid = table(tmp_path, CLOUD, extra_features=[TALENT] if owned else [], start=(0, 6))
    turn(ui, mid, FOE)
    def apply(e, event, kwargs):
        if event == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == FOE:
            e._apply_condition(e.state.actors[OWNER], condition, source, actor,
                               expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Afterimage"})
    hook(monkeypatch, "event", apply)
    assert act(ui, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    assert any(c.condition_id == condition and c.source_definition_id == source
               for c in checked(tmp_path, mid).state.actors[OWNER].conditions.values())


@pytest.mark.parametrize("destroy", [False, True])
def test_table_progress_at_committed_step_before_later_reaction(monkeypatch, tmp_path, destroy):
    service, ui, mid = armed_progress_table(tmp_path)
    from tests.test_lock9_passage_review import send
    engine = service._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=3, y=6))
    assert send(service, ui, mid, move)['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    assert not motion.has_afterimage(engine.state.actors[OWNER])
    # Preview and abandoning a displayed menu cannot cross the threshold.
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    ui.state(mid); ui.state(mid)
    assert canonical_sha256(service._load_session(mid).engine.state.model_dump(mode='json')) == before
    steps, attacks = [], []
    def observe_step(e, mover, previous, nxt, intent):
        if mover.entity_id == OWNER:
            steps.append((nxt.x, motion.has_afterimage(mover)))
            if destroy and nxt.x == 5:
                motion.strike_afterimage(e, mover, 'test:successful-image-target')
    def observe_reaction(e, event, kwargs):
        if (event == 'REACTION_WINDOW_OPENED' and kwargs.get('actor_id') == OWNER
                and FOE in kwargs.get('target_ids', ())):
            mover = e.state.actors[OWNER]
            attacks.append((mover.position.x, motion.has_afterimage(mover)))
    def grant(e, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            path = tuple(Position(x=x, y=6) for x in range(3, 8))
            resolve_path(e, e.state.actors[OWNER], path, 'test:progress-grant', feet=20,
                         intent=e._active_intent, provokes=True)
    hook(monkeypatch, 'movement_step', observe_step)
    hook(monkeypatch, 'event', observe_reaction)
    # The grant runs inside Hold's event callback. Its actual OA event is nested.
    monkeypatch.setitem(ext._NESTED_HOOKS, 'event', {*ext._NESTED_HOOKS.get('event', ()), observe_reaction})
    hook(monkeypatch, 'event', grant)
    send_action = cast_sender(service, ui, mid, 'Hold position')
    def send_with_rollback_check(answers):
        result = send_action(answers)
        if result['status'] == 'REACTION_REQUIRED':
            pending = service._load_session(mid).engine.state.actors[OWNER]
            assert pending.position == Position(x=3, y=6)
            assert not motion.has_afterimage(pending)
            assert pending.turn_flags['athletics_afterimage_distance_ft'] == 15
        return result
    answers, prompts = [], []
    for _ in range(4):
        result = send_with_rollback_check(answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        # Native OA consent is Use/Decline, with no selectable effect options.
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': []})
    assert result['status'] == 'COMMITTED' and prompts
    engine = checked(tmp_path, mid)
    assert engine.state.actors[OWNER].position == Position(x=7, y=6)
    assert (4, False) in steps and (5, True) in steps
    assert attacks and all(x == 6 and active == (not destroy) for x, active in attacks), attacks
    assert any(e.event_type == 'REACTION_RESOLVED' and e.actor_id == FOE for e in engine.events)
    assert not engine.state.actors[FOE].reaction_available
    if destroy:
        assert (6, False) in steps and (7, False) in steps
        assert not motion.has_afterimage(engine.state.actors[OWNER])
    assert engine.state.actors[OWNER].turn_flags['athletics_afterimage_distance_ft'] == 35
    assert engine.state.actors[OWNER].turn_flags['athletics_afterimage_created'] == 1


def test_table_forced_distance_excluded(monkeypatch, tmp_path):
    from combat.movement_paths import resolve
    service, ui, mid = table(tmp_path, CLOUD, extra_features=[TALENT], start=(6, 6))
    receipts = []
    def observe(e, mover, receipt):
        if mover.entity_id == OWNER:
            receipts.append(dict(receipt))
    def push(e, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            resolve(e, e.state.actors[OWNER], tuple(Position(x=x, y=6) for x in range(6, 12)),
                    'test:forced', kind='forced', feet=25, intent=e._active_intent, source_actor_id=FOE)
    hook(monkeypatch, 'movement_progress_committed', observe)
    hook(monkeypatch, 'event', push)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    mover = engine.state.actors[OWNER]
    assert mover.position == Position(x=11, y=6) and not motion.has_afterimage(mover)
    assert mover.turn_flags.get('athletics_afterimage_distance_ft', 0) == 0
    assert receipts and all(not r['voluntary'] and r['distance_ft'] == 5 for r in receipts)


def test_table_interrupted_route_counts_only_entered_steps(monkeypatch, tmp_path):
    service, ui, mid = table(tmp_path, CLOUD, extra_features=[TALENT], start=(0, 6))
    def stop(e, mover, previous, nxt, intent):
        if mover.entity_id == OWNER and nxt.x == 4:
            return {'stop': True, 'source_id': 'test:stop', 'label': 'The creature stops before entering the next space.'}
    def grant(e, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            resolve_path(e, e.state.actors[OWNER], tuple(Position(x=x, y=6) for x in range(7)),
                         'test:interrupted-grant', feet=30, intent=e._active_intent, provokes=False)
    hook(monkeypatch, 'movement_attempt', stop)
    hook(monkeypatch, 'event', grant)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    mover = engine.state.actors[OWNER]
    assert mover.position == Position(x=3, y=6) and not motion.has_afterimage(mover)
    assert mover.turn_flags['athletics_afterimage_distance_ft'] == 15
    event = next(e for e in reversed(engine.events) if e.source_definition_id == 'test:interrupted-grant'
                 and e.event_type == 'MOVEMENT_COMMITTED')
    assert event.payload['interrupted'] and event.payload['granted_cost_ft'] == 15
    assert len(event.payload['path']) == 4


def test_table_next_turn_expiry_and_new_crossing(monkeypatch, tmp_path):
    service, ui, mid = table(tmp_path, CLOUD, extra_features=[TALENT], start=(0, 6))
    receipts = []
    def observe(e, mover, receipt):
        if mover.entity_id == OWNER:
            receipts.append(dict(receipt))
    def grant(e, event, kwargs):
        if (event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER
                and e.state.actors[OWNER].position.x == 0):
            resolve_path(e, e.state.actors[OWNER], tuple(Position(x=x, y=6) for x in range(6)),
                         'test:lifetime-grant', feet=25, intent=e._active_intent, provokes=False)
    hook(monkeypatch, 'movement_progress_committed', observe)
    hook(monkeypatch, 'event', grant)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    mover = engine.state.actors[OWNER]
    first = next(c for c in mover.conditions.values() if c.condition_id == motion.AFTERIMAGE)
    assert mover.turn_flags['athletics_afterimage_distance_ft'] == 25
    assert all(r['voluntary'] and r['own_turn'] and r['distance_ft'] == 5
               and r['actor_id'] == OWNER and r['intent_id'] and r['source_id'] == 'test:lifetime-grant'
               for r in receipts)
    turn(ui, mid, FOE); turn(ui, mid, OWNER)
    mover = checked(tmp_path, mid).state.actors[OWNER]
    assert not motion.has_afterimage(mover)
    assert mover.turn_flags.get('athletics_afterimage_distance_ft', 0) == 0
    commit(cast_sender(service, ui, mid, 'Move', at=(10, 6)))
    mover = checked(tmp_path, mid).state.actors[OWNER]
    second = next(c for c in mover.conditions.values() if c.condition_id == motion.AFTERIMAGE)
    assert second.instance_id != first.instance_id and mover.position == Position(x=10, y=6)
    assert mover.turn_flags['athletics_afterimage_distance_ft'] == 25
