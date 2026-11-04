"""Wall Stunt's real native routes, choices, reactions and cold persistence."""
import pytest
from combat.tabletop import normalize_map, to_battlefield
from combat.gate2_runtime_models import CandidateKind
from combat.ext import effect
from tests.worker2_support import fixture, OWNER, FOE, ALLY, settle, reload, turn, candidate
from tests.auto8f1_table_support import candidate_id
from tests.auto8f1_table_support import AXE_KIT
from combat.dynamic_size import shape

WALL = 'TAL_ATHLETICS_WALL_STUNT'
SPIDER = 'TAL_ATHLETICS_SPIDER_S_TOUCH'


@effect('mgr_t16_test_drop_grip')
def drop_grip(ctx, eff):
    from combat.falling import drop
    drop(ctx.engine, ctx.actor, ctx.intent)


def game(tmp_path, *, handholds=False, creature=False, talents=(WALL,)):
    document = normalize_map({'display_name': 'Wall running yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [] if creature else [{'id': 'running-wall', 'shape': 'line', 'points': [[4, 1], [4, 6]],
            'height_ft': 15, 'handholds': handholds}], 'roofs': {'enabled': False}})
    arena = to_battlefield(document)
    def prepare(bundles):
        from tests.athletics_table_support import add_action
        b = next(b for b in bundles if b['actor_id'] == OWNER)
        add_action(b, 'Let go of the wall', [{'type': 'mgr_t16_test_drop_grip'}])
        if creature:
            b = next(b for b in bundles if b['actor_id'] == FOE)
            b['actor_template']['size_category'] = 'Huge'
    combat, table, mid = fixture(tmp_path, list(talents), named=True, battlefield=arena,
        foe_kit=AXE_KIT,
        positions={OWNER: {'x': 3, 'y': 3}, FOE: {'x': 4 if creature else 9, 'y': 3}, ALLY: {'x': 10, 'y': 6}},
        bundle_transform=prepare, seed='MGR-T16-WALL-'+tmp_path.name)
    turn(table, mid, OWNER)
    return combat, table, mid


def action(table, mid, label, picks=None):
    return settle(table, mid, candidate_id(table.state(mid)['menu'], label), picks=picks)


def move(table, mid, xyz, *, use_oa=False):
    c = next(c for c in table.combat._load_session(mid).engine.legal_candidates()
             if c.kind == CandidateKind.MOVE and c.destination and
             (c.destination.x, c.destination.y, c.destination.z) == xyz and c.metadata.get('movement_mode') == 'climb')
    settle(table, mid, c.candidate_id,
           picks={'reaction:typed.opportunity_attack': 'first'} if use_oa else None)
    return c


@pytest.mark.parametrize('talents', [(WALL,), (WALL, SPIDER)])
def test_wall_up_along_and_difficult_cost_are_native(tmp_path, talents):
    combat, table, mid = game(tmp_path, talents=talents)
    engine = combat._load_session(mid).engine
    assert all('zone_spec' not in a.parameters.get('typed', {}) for a in engine.action_catalog.values()
               if any(e.get('type') == 'wall_stunt' for e in a.parameters.get('typed', {}).get('effects', ())))
    action(table, mid, 'run up or along a wall')
    assert move(table, mid, (3, 3, 1)).movement_cost_ft == 10
    assert move(table, mid, (3, 4, 1)).movement_cost_ft == 10
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.z == 1
    assert engine.state.actors[OWNER].movement_remaining_ft == 10


@pytest.mark.parametrize('handholds,hold,height', [(False, False, 0), (True, True, 1), (True, False, 0)])
def test_wall_turn_end_holds_or_falls_through_ask_and_reload(tmp_path, handholds, hold, height):
    combat, table, mid = game(tmp_path, handholds=handholds)
    action(table, mid, 'run up or along a wall')
    move(table, mid, (3, 3, 1))
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     picks={'choice:needle.wall_handhold': 'hold' if hold else None})
    if handholds:
        assert any('Wall Stunt' in str(p) and 'handhold' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.z == height
    assert not any(c.condition_id == 'condition:typed.wall_running' for c in engine.state.actors[OWNER].conditions.values())


def test_creature_wall_requires_recorded_approval_and_pays_reaction(tmp_path):
    combat, table, mid = game(tmp_path, creature=True)
    action(table, mid, 'run up or along a wall')
    assert not any(c.kind == CandidateKind.MOVE and c.metadata.get('movement_mode') == 'climb'
                   for c in combat._load_session(mid).engine.legal_candidates())
    prompts = action(table, mid, 'record GM approval for a creature wall')
    assert any('GM' in str(p) and 'Wall Stunt' in str(p) for p in prompts)
    move(table, mid, (3, 3, 1), use_oa=True)
    engine = reload(tmp_path, mid)
    # The foe's default deterministic plan accepts its real opportunity attack.
    assert not engine.state.actors[FOE].reaction_available
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE for e in engine.events)


def test_wall_gm_approval_is_asked_of_the_table_not_decided_by_an_automatic_owner(tmp_path):
    """The printed "with GM approval" clause is a table ruling, never the owner's own choice.

    An automatic owner may ask for the approval, but the service must stop and
    put the question to the table (the GM adjudication transport) instead of
    granting it from the owner's controller; the recorded approval follows only
    the table's answer."""
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = game(tmp_path, creature=True)
    engine = combat._load_session(mid).engine
    row = next(a for a in engine.action_catalog.values()
               if a.display_name == 'Wall Stunt: record GM approval for a creature wall')
    assert row.parameters['typed']['gm_adjudication'] is True
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, row.display_name).candidate_id
    original = combat.controller
    combat.controller = ManualControllerAdapter(lambda _: (cid, ()),
        reaction_chooser=lambda context: original.choose_reaction(context).decision)
    asked = table.auto_step(mid, 0, [])
    assert asked['status'] == 'REACTION_REQUIRED', asked
    assert asked['reaction']['context']['reaction_source_id'] == 'choice:needle.wall_approval'
    assert 'GM' in str(asked['reaction'])
    assert not any(c.condition_id == 'condition:typed.wall_surface_approval'
                   for actor in combat._load_session(mid).engine.state.actors.values()
                   for c in actor.conditions.values())
    answer = {**asked['reaction']['context'], 'selection': 'USE', 'option_ids': ['approved']}
    committed = table.auto_step(mid, 0, [answer])
    assert committed['status'] == 'COMMITTED', committed
    assert any(c.condition_id == 'condition:typed.wall_surface_approval'
               for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_ai_holds_an_explicit_handhold_without_prompting_player(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = game(tmp_path, handholds=True)
    action(table, mid, 'run up or along a wall')
    move(table, mid, (3, 3, 1))
    cid = table.state(mid)['menu']['end_turn']
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    original = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: original.choose_reaction(context).decision)
    assert not settle(table, mid, cid, auto=True)
    assert reload(tmp_path, mid).state.actors[OWNER].position.z == 1


def test_wall_stunt_is_published_as_applied_not_as_needing_the_table():
    # The sheet's own status data must say the record runs on this table. It said
    # "table" (needs climbing and elevation) after the plug-in automated the whole
    # record, so the sheet told players a working ability was unsupported.
    from combat.factory_compiler import feature_status
    from tests.h1_support import bundle
    entry = feature_status()[WALL]
    assert entry['status'] == 'applied'
    assert 'not model yet' not in entry['why'] and 'no elevation' not in entry['why']
    skipped = bundle([WALL])['diagnostics']['skipped']
    assert 'Wall Stunt' not in skipped['table']


def test_deliberate_drop_removes_the_persisted_wall_handhold(tmp_path):
    combat, table, mid = game(tmp_path, handholds=True)
    action(table, mid, 'run up or along a wall')
    move(table, mid, (3, 3, 1))
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    action(table, mid, 'Let go of the wall')
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.position.z == 0
    assert not any(c.condition_id == 'condition:typed.wall_running_grip' for c in actor.conditions.values())
