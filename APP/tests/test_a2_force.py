"""Force second pass: real compiled abilities through session/table commit and cold reload."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from combat.gate4_adapters import ManualControllerAdapter
from combat.ext import force_second_pass as P
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, turn, settle, cell_send, reload

IMPACT = 'TAL_FORCE_IMPACT'
SUNDER = 'TAL_FORCE_SUNDERING_PRESSURE'
WALL = 'TAL_FORCE_FORCE_WALL'
BRACE = 'TAL_FORCE_WORLD_BRACING_INCARNATION'
SHOCK = 'TAL_FORCE_SHOCKWAVE'


def cold(combat, mid):
    engine = reload(combat, mid)
    session = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    return engine


def send_candidate(combat, table, mid, name, *, target=None, at=None, remote=False, ai=False):
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id) is not None and engine.action_catalog[c.source_definition_id].display_name == name
                  and (target is None or target in c.target_ids)
                  and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
                  and bool(c.metadata.get('effect_origin')) == remote]
    assert candidates, (name, target, at, remote)
    selected = candidates[0]
    if not ai:
        def send(answers):
            state = table.state(mid)
            return table.act(mid, selected.candidate_id, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], answers)
        return send
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    return lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers)


def open_arena(arena):
    arena['terrain_regions'] = []


def anchor(combat, table, mid, at=(8, 6)):
    settle(cell_send(table, mid, 'Set Anchor', at))
    settle(lambda a: act(table, mid, 'end', a))
    turn(table, mid, LEFT)
    cold(combat, mid)


@pytest.mark.parametrize('ai', [False, True])
def test_anchor_impact_range_cover_and_physical_state(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [IMPACT], left_attack_bonus=100,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 12, 'y': 6}},
        arena_edit=lambda a: a.update(terrain_regions=[{'region_id': 'cover', 'terrain_type': 'SIMPLE_COVER', 'movement_cost': 0, 'cells': [{'x': 5, 'y': 6}]}]))
    anchor(combat, table, mid)
    before = cold(combat, mid).state.actors[LEFT].model_copy(deep=True)
    settle(send_candidate(combat, table, mid, 'Impact', target=RIGHT, remote=True, ai=ai))
    engine = cold(combat, mid)
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert target.current_hp < 1000
    assert actor.position == before.position
    assert actor.movement_remaining_ft == before.movement_remaining_ft
    roll = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED')
    assert roll.payload['cover_bonus'] == 0
    assert any(e.payload.get('effect_origin') for e in engine.events)
    assert not getattr(engine, '_effect_origin', None)


@pytest.mark.parametrize('feature,label', [('TAL_FORCE_GROUND_ANSWERING_PALM', 'Ground-Answering Palm'),
                                          ('TAL_FORCE_MERIDIAN_OF_IMPACT', 'Meridian of Impact')])
def test_ground_lines_from_saved_anchor(tmp_path, feature, label):
    combat, table, mid = fight(tmp_path, [IMPACT, feature],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 12, 'y': 6}}, arena_edit=open_arena)
    anchor(combat, table, mid)
    settle(send_candidate(combat, table, mid, label, at=(12, 6), remote=True))
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert any(c.condition_id.endswith('prone') for c in engine.state.actors[RIGHT].conditions.values())
    assert engine.state.actors[LEFT].position.x == 3


@pytest.mark.parametrize('sunder', [False, True])
def test_impact_and_paid_sundering_damage_map_object(tmp_path, sunder):
    def arena(a):
        a['map_objects'] = [{'id': 1, 'x': 6, 'y': 6, 'kind': 'custom', 'name': 'Practice block',
                             'size': 'medium', 'material': 'stone', 'hp': 1000, 'ac': 1}]
    combat, table, mid = fight(tmp_path, [IMPACT, *([SUNDER] if sunder else [])], cl=5, left_attack_bonus=100, arena_edit=arena)
    label = 'Impact + Sundering Pressure' if sunder else 'Impact'
    before = cold(combat, mid)
    hp = before.state.objects['object:map.1'].current_hp
    pool = before.state.actors[LEFT].resources['resource:core.qi']
    settle(send_candidate(combat, table, mid, label, target='object:map.1'))
    engine = cold(combat, mid)
    assert engine.state.objects['object:map.1'].current_hp < hp
    dice = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and IMPACT in r.reason)
    assert len(dice.dice) == (3 if sunder else 2)
    assert pool - engine.state.actors[LEFT].resources['resource:core.qi'] == int(sunder)


@pytest.mark.parametrize('construct', [False, True])
def test_sundering_adds_die_only_against_printed_construct(tmp_path, construct):
    def sheet_edit(sheet, aid):
        if aid == RIGHT:
            sheet['identity']['creature_type'] = 'Construct' if construct else 'Humanoid'
    combat, table, mid = fight(tmp_path, [IMPACT, SUNDER], cl=5, left_attack_bonus=100, sheet_edit=sheet_edit)
    settle(send_candidate(combat, table, mid, 'Impact + Sundering Pressure', target=RIGHT))
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    damage = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and IMPACT in r.reason)
    assert len(damage.dice) == (3 if construct else 2)


@pytest.mark.parametrize('braced', [False, True])
def test_incarnation_freezes_new_barrier_hp_and_wall_origin(tmp_path, braced):
    combat, table, mid = fight(tmp_path, [IMPACT, WALL, *([BRACE] if braced else [])], cl=15,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 14, 'y': 6}}, arena_edit=open_arena)
    anchor(combat, table, mid)
    if braced:
        settle(lambda a: act(table, mid, 'World-Bracing Incarnation', a))
    settle(send_candidate(combat, table, mid, 'Force Wall', at=(9, 6), remote=True))
    engine = cold(combat, mid)
    from combat.ext.docket_walls import stats
    wall = next(z for z in engine.state.zones.values() if WALL in z.source_definition_id)
    assert stats(wall)['hp'] == 45 + (20 if braced else 0)
    assert wall.center.x == 9
    hp = stats(wall)['hp']
    turn(table, mid, RIGHT)
    engine = cold(combat, mid)
    assert stats(engine.state.zones[wall.zone_id])['hp'] == hp
    assert not engine.state.actors[LEFT].temporary_hp


def test_sundering_impact_against_destructible_wall(tmp_path):
    combat, table, mid = fight(tmp_path, [IMPACT, SUNDER], right_talents=[WALL], cl=5, left_attack_bonus=100,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 7, 'y': 6}})
    turn(table, mid, RIGHT)
    settle(send_candidate(combat, table, mid, 'Force Wall', at=(6, 6)))
    turn(table, mid, LEFT)
    settle(send_candidate(combat, table, mid, 'Impact + Sundering Pressure (wall section)', at=(6, 6)))
    engine = cold(combat, mid)
    wall = next(z for z in engine.state.zones.values() if WALL in z.source_definition_id)
    assert wall.trigger_profile.get('sections') or not any(c.x == 6 and c.y == 6 for c in wall.affected_cells)
    damage = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and IMPACT in r.reason)
    assert len(damage.dice) == 3


@pytest.mark.parametrize('ai', [False, True])
def test_shockwave_enemy_recipients_and_explicit_object_weights(tmp_path, ai):
    def arena(a):
        a['map_objects'] = [
            {'id': 1, 'x': 3, 'y': 8, 'kind': 'custom', 'name': 'Light crate', 'size': 'small', 'material': 'wood', 'weight_lb': 100},
            {'id': 2, 'x': 2, 'y': 6, 'kind': 'custom', 'name': 'Heavy crate', 'size': 'small', 'material': 'wood', 'weight_lb': 101},
            {'id': 3, 'x': 2, 'y': 7, 'kind': 'custom', 'name': 'Unweighed crate', 'size': 'small', 'material': 'wood'},
        ]
    combat, table, mid = fight(tmp_path, [IMPACT, SHOCK], ally=[], cl=5, arena_edit=arena,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}, ALLY: {'x': 3, 'y': 5}})
    before = cold(combat, mid)
    settle(send_candidate(combat, table, mid, 'Shockwave', at=(3, 6), ai=ai),
           choose=lambda p: [RIGHT] if RIGHT in [o['id'] for o in p.get('choice', {}).get('options', [])] else
                 [o['id'] for o in p.get('choice', {}).get('options', [])][:max(1, p.get('choice', {}).get('minimum', 1))])
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    for aid in (LEFT, ALLY):
        assert engine.state.actors[aid].current_hp == 1000
        assert engine.state.actors[aid].position == before.state.actors[aid].position
    assert engine.state.objects['object:map.1'].position.y == 10
    for oid in ('object:map.2', 'object:map.3'):
        assert engine.state.objects[oid].position == before.state.objects[oid].position


def test_sundering_construct_die_doubles_on_native_critical(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    def sheet_edit(sheet, aid):
        if aid == RIGHT:
            sheet['identity']['creature_type'] = 'Construct'
    combat, table, mid = fight(tmp_path, [IMPACT, SUNDER], cl=5, left_attack_bonus=100, sheet_edit=sheet_edit)
    install(monkeypatch, 'attack_critical_qualification', lambda *a: True)
    settle(send_candidate(combat, table, mid, 'Impact + Sundering Pressure', target=RIGHT))
    engine = cold(combat, mid)
    damage = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and IMPACT in r.reason)
    assert len(damage.dice) == 6


@pytest.mark.parametrize('defense', ['threshold', 'immune'])
def test_sundering_preserves_object_defenses(tmp_path, defense):
    def arena(a):
        a['map_objects'] = [{'id': 1, 'x': 6, 'y': 6, 'kind': 'custom', 'name': 'Protected block',
            'size': 'medium', 'material': 'stone', 'hp': 1000, 'ac': 1,
            **({'threshold': 10000} if defense == 'threshold' else {'immune': ['FORCE', 'BLUDGEONING']})}]
    combat, table, mid = fight(tmp_path, [IMPACT, SUNDER], cl=5, left_attack_bonus=100, arena_edit=arena)
    before = cold(combat, mid).state.objects['object:map.1'].current_hp
    settle(send_candidate(combat, table, mid, 'Impact + Sundering Pressure', target='object:map.1'))
    engine = cold(combat, mid)
    assert engine.state.objects['object:map.1'].current_hp == before
    damage = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and IMPACT in r.reason)
    assert len(damage.dice) == 3


def test_shockwave_cannot_push_object_through_blocked_route(tmp_path):
    def arena(a):
        a['map_objects'] = [{'id': 1, 'x': 3, 'y': 8, 'kind': 'custom', 'name': 'Crate',
                            'size': 'small', 'material': 'wood', 'weight_lb': 100}]
        a['terrain_regions'] = [{'region_id': 'wall', 'terrain_type': 'BLOCKED', 'movement_cost': 0,
                                'cells': [{'x': 3, 'y': 9}]}]
    combat, table, mid = fight(tmp_path, [IMPACT, SHOCK], cl=5, arena_edit=arena,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}})
    before = cold(combat, mid).state.objects['object:map.1'].position
    settle(send_candidate(combat, table, mid, 'Shockwave', at=(3, 6)))
    assert cold(combat, mid).state.objects['object:map.1'].position == before


@pytest.mark.parametrize('feature,label', [('TAL_FORCE_GROUND_ANSWERING_PALM', 'Ground-Answering Palm'),
                                          ('TAL_FORCE_MERIDIAN_OF_IMPACT', 'Meridian of Impact')])
def test_ai_ground_line_harms_only_enemies_on_shared_surface(tmp_path, feature, label):
    combat, table, mid = fight(tmp_path, [IMPACT, feature], ally=[], cl=10, arena_edit=open_arena,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}, ALLY: {'x': 5, 'y': 6}})
    settle(send_candidate(combat, table, mid, label, at=(6, 6), ai=True))
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert engine.state.actors[ALLY].current_hp == 1000
    assert not any(c.condition_id.endswith('prone') for c in engine.state.actors[ALLY].conditions.values())


def test_shockwave_from_saved_anchor_keeps_origin_and_caster_separate(tmp_path):
    def arena(a):
        a['terrain_regions'] = []
        a['map_objects'] = [{'id': 1, 'x': 8, 'y': 8, 'kind': 'custom', 'name': 'Crate',
                            'size': 'small', 'material': 'wood', 'weight_lb': 100}]
    combat, table, mid = fight(tmp_path, [IMPACT, SHOCK], cl=5, arena_edit=arena,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 10, 'y': 6}})
    anchor(combat, table, mid)
    before = cold(combat, mid).state.actors[LEFT].position
    settle(send_candidate(combat, table, mid, 'Shockwave', at=(8, 6), remote=True))
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert engine.state.actors[LEFT].position == before
    assert engine.state.objects['object:map.1'].position.y == 10


def test_shockwave_object_route_respects_other_object_cells(tmp_path):
    def arena(a):
        a['terrain_regions'] = []
        a['map_objects'] = [
            {'id': 1, 'x': 3, 'y': 8, 'kind': 'custom', 'name': 'Light crate', 'size': 'small', 'material': 'wood', 'weight_lb': 100},
            {'id': 2, 'x': 3, 'y': 9, 'kind': 'custom', 'name': 'Heavy crate', 'size': 'small', 'material': 'wood', 'weight_lb': 101}]
    combat, table, mid = fight(tmp_path, [IMPACT, SHOCK], cl=5, arena_edit=arena,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}})
    before = cold(combat, mid).state.objects['object:map.1'].position
    settle(send_candidate(combat, table, mid, 'Shockwave', at=(3, 6)))
    assert cold(combat, mid).state.objects['object:map.1'].position == before


@pytest.mark.parametrize('braced', [False, True])
def test_impact_player_can_decline_push_including_incarnation_bonus(tmp_path, braced):
    combat, table, mid = fight(tmp_path, [IMPACT, *([BRACE] if braced else [])], cl=15,
        left_attack_bonus=100, arena_edit=open_arena)
    if braced:
        settle(lambda a: act(table, mid, 'World-Bracing Incarnation', a))
    before = cold(combat, mid).state.actors[RIGHT].position
    def choose(prompt):
        ids = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        return ['stay'] if 'stay' in ids else ids[:max(1, prompt.get('choice', {}).get('minimum', 1))]
    settle(send_candidate(combat, table, mid, 'Impact', target=RIGHT), choose=choose)
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert engine.state.actors[RIGHT].position == before


# ------------------------------------------------------------------ regressions: the shared modifier folds and swept footprints
MANTLE = 'TAL_FORCE_FORCE_MANTLE'
WHEEL_BONUS = 2          # Turning Wheel's attack face at the levels used below (CL >= 11 and < 17)


def add_hook(monkeypatch, point, fn):
    """Add one subscriber to a live hook point, keeping every real subscriber in place."""
    from combat import ext
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), fn])


def wheel_face(ctx_engine, actor, kind='attack'):
    """Write the condition ``fate_riders.turning_wheel`` itself writes for a chosen face."""
    from combat.ext import fate_riders as FR
    for old in FR._held(actor, FR.WHEEL):
        ctx_engine._remove_condition(actor, FR.WHEEL, FR.WHEEL_ID)
    words = {'attack': 'attack rolls and damage rolls', 'save': 'saving throws', 'check': 'ability checks'}[kind]
    ctx_engine._apply_condition(actor, FR.WHEEL, FR.WHEEL_ID, actor.entity_id, expires_on='UNTIL_REMOVED',
                                data={'kind': kind, 'bonus': WHEEL_BONUS, 'face': 1,
                                      'label': f'Turning Wheel (1): +{WHEEL_BONUS} to {words}'})


def wheel_attack_hook(monkeypatch):
    """The real Fate rider's own attack-roll fold, reached only if the route dispatches it."""
    def hook(ctx, actor):
        from combat.ext import fate_riders as FR
        wheel_face(ctx.engine, actor)
        return FR.fate_attack_bonus(ctx, actor)
    add_hook(monkeypatch, 'attack_bonus', hook)


def wheel_damage_hook(monkeypatch):
    """The real Fate rider's own damage-roll fold, reached only if the route dispatches it."""
    def hook(ctx, effect_row=None, kinds=None):
        from combat.ext import fate_riders as FR
        wheel_face(ctx.engine, ctx.actor)
        return FR.wheel_damage(ctx, effect_row, kinds)
    add_hook(monkeypatch, 'damage_roll_bonus', hook)


def jinx_once_hook(monkeypatch):
    """Jinxed Name's consumable penalty, as its own rider applies the one-round condition."""
    def hook(ctx, actor):
        from combat.ext import fate_riders as FR
        if not FR._held(actor, FR.JINX_ONCE):
            ctx.engine._apply_condition(actor, FR.JINX_ONCE, FR.JINX_ID, actor.entity_id,
                                        expires_on='START_OF_SOURCE_NEXT_TURN',
                                        data={'label': 'Jinxed Name: -1d4 on its next attack roll or ability check'})
        return FR.fate_attack_bonus(ctx, actor)
    add_hook(monkeypatch, 'attack_bonus', hook)


def wall_fight(tmp_path, **kwargs):
    """A Force Wall stands at (6, 6) and the caster faces it from (3, 6)."""
    return fight(tmp_path, right_talents=[WALL], cl=15, left_attack_bonus=8,
                 positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 7, 'y': 6}}, **kwargs)


def test_wall_impact_attack_roll_reads_shared_attack_bonus(tmp_path, monkeypatch):
    """A wall-section Impact must fold the same attack modifiers as the object and creature routes."""
    wheel_attack_hook(monkeypatch)
    combat, table, mid = wall_fight(tmp_path, talents=[IMPACT])
    turn(table, mid, RIGHT)
    settle(send_candidate(combat, table, mid, 'Force Wall', at=(6, 6)))
    turn(table, mid, LEFT)
    settle(send_candidate(combat, table, mid, 'Impact (wall section)', at=(6, 6)))
    engine = cold(combat, mid)
    attack = next(r for r in reversed(engine.rolls) if r.reason.startswith('ATTACK:') and r.reason.endswith(':wall'))
    assert attack.modifier == 8 + WHEEL_BONUS


def test_wall_impact_attack_roll_spends_a_consumable_penalty(tmp_path, monkeypatch):
    """Jinxed Name's once-a-round cut is spent by the roll that reads it, not left for later."""
    jinx_once_hook(monkeypatch)
    combat, table, mid = wall_fight(tmp_path, talents=[IMPACT])
    turn(table, mid, RIGHT)
    settle(send_candidate(combat, table, mid, 'Force Wall', at=(6, 6)))
    turn(table, mid, LEFT)
    settle(send_candidate(combat, table, mid, 'Impact (wall section)', at=(6, 6)))
    engine = cold(combat, mid)
    cut = next(r for r in reversed(engine.rolls) if r.reason.endswith('JINXED_NAME')).total
    attack = next(r for r in reversed(engine.rolls) if r.reason.startswith('ATTACK:') and r.reason.endswith(':wall'))
    assert attack.modifier == 8 - cut
    from combat.ext import fate_riders as FR
    assert not FR._held(engine.state.actors[LEFT], FR.JINX_ONCE)   # spent by this roll


def impact_damage_roll(root, route, talents):
    """Play one Impact against a block or a wall section; return the damage roll it recorded."""
    if route == 'object':
        def arena(a):
            a['map_objects'] = [{'id': 1, 'x': 6, 'y': 6, 'kind': 'custom', 'name': 'Practice block',
                                 'size': 'medium', 'material': 'stone', 'hp': 1000, 'ac': 1}]
        combat, table, mid = fight(root, talents, cl=15, left_attack_bonus=100, arena_edit=arena,
                                   positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 7, 'y': 6}})
        label, extra = 'Impact', {'target': 'object:map.1'}
    else:
        combat, table, mid = fight(root, talents, cl=15, left_attack_bonus=100, right_talents=[WALL],
                                   positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 7, 'y': 6}})
        turn(table, mid, RIGHT)
        settle(send_candidate(combat, table, mid, 'Force Wall', at=(6, 6)))
        turn(table, mid, LEFT)
        label, extra = 'Impact (wall section)', {'at': (6, 6)}
    settle(send_candidate(combat, table, mid, label, **extra))
    engine = cold(combat, mid)
    return next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and IMPACT in r.reason), engine


@pytest.mark.parametrize('mantled', [False, True])
@pytest.mark.parametrize('route', ['object', 'wall'])
def test_impact_object_and_wall_damage_read_shared_damage_roll_bonus(tmp_path, monkeypatch, route, mantled):
    """Turning Wheel's attack face adds to an object and a wall Impact exactly once.

    Measured against the same fight without the rider, so the printed dice and Force's own
    shaping are identical and the wheel face is the only difference.
    """
    from combat.ext import fate_riders as FR
    talents = [IMPACT, *([MANTLE] if mantled else [])]
    (tmp_path / 'plain').mkdir()
    plain, _ = impact_damage_roll(tmp_path / 'plain', route, talents)
    wheel_damage_hook(monkeypatch)
    (tmp_path / 'wheel').mkdir()
    boosted, engine = impact_damage_roll(tmp_path / 'wheel', route, talents)
    assert FR._held(engine.state.actors[LEFT], FR.WHEEL)          # the rider really answered
    assert boosted.modifier == plain.modifier + WHEEL_BONUS       # paid exactly once, on top of Mantle
    assert boosted.total == sum(boosted.dice) + boosted.modifier


@pytest.mark.parametrize('blocked', [False, True])
def test_shockwave_stops_a_wide_object_at_a_swept_edge(tmp_path, blocked):
    """A blocker inside an intermediate footprint stops a diagonal push of a multi-cell object.

    The 2-by-2 bench is anchored at (3, 7) and the burst originates at (2, 6), so it moves
    southeast. The blocker at (3, 9) is in neither the destination footprint -- (4, 8), (5, 8),
    (4, 9), (5, 9) -- nor the two cells beside the anchor, which for a wide object are both its
    own cells. It is reachable only by checking the full translated side footprints. Without the
    blocker the same bench moves, so a stopped bench can only mean the sweep was checked.
    """
    def arena(a):
        a['map_objects'] = [{'id': 1, 'x': 3, 'y': 7, 'kind': 'custom', 'name': 'Long bench',
                             'size': 'large', 'material': 'wood', 'weight_lb': 100,
                             'width_cells': 2, 'length_cells': 2, 'rotation': 0}]
        a['terrain_regions'] = ([{'region_id': 'wall', 'terrain_type': 'BLOCKED', 'movement_cost': 0,
                                   'cells': [{'x': 3, 'y': 9}]}] if blocked else [])
    combat, table, mid = fight(tmp_path, [IMPACT, SHOCK], cl=5, arena_edit=arena,
        positions={LEFT: {'x': 2, 'y': 6}, RIGHT: {'x': 4, 'y': 6}})
    from combat.object_geometry import target_cells
    reloaded = cold(combat, mid)
    obj = reloaded.state.objects['object:map.1']
    assert {(c.x, c.y) for c in target_cells(reloaded, obj)} == {(3, 7), (4, 7), (3, 8), (4, 8)}
    before = obj.position
    settle(send_candidate(combat, table, mid, 'Shockwave', at=(2, 6)))
    after = cold(combat, mid).state.objects['object:map.1'].position
    if blocked:
        assert after == before
    else:
        assert after.x > before.x and after.y > before.y, (before, after)   # control: this bench is free to move


def held(actor, condition_id):
    """The conditions this actor actually holds, by printed condition id."""
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def test_world_bracing_barrier_bonus_lapses_on_the_shared_clock(tmp_path):
    """The incarnation's barrier bonus expires like every other counted condition, not forever."""
    combat, table, mid = fight(tmp_path, [IMPACT, WALL, BRACE], cl=15, left_attack_bonus=100,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 14, 'y': 6}}, arena_edit=open_arena)
    settle(lambda a: act(table, mid, 'World-Bracing Incarnation', a))
    engine = cold(combat, mid)
    braced = held(engine.state.actors[LEFT], P.BRACED)
    assert len(braced) == 1
    assert braced[0].expires_on and braced[0].expires_on != 'UNTIL_REMOVED', braced[0].expires_on
    for _ in range(6):                      # one printed minute elapses
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)
    assert held(cold(combat, mid).state.actors[LEFT], P.BRACED) == []


def test_impact_asks_the_player_to_choose_during_an_ai_turn(tmp_path):
    """An AI casting Impact still asks the player, in plain words, whether to push."""
    combat, table, mid = fight(tmp_path, [IMPACT], cl=15, left_attack_bonus=100, arena_edit=open_arena)
    before = cold(combat, mid).state.actors[RIGHT].position
    def choose(prompt):
        ids = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        return ['stay'] if 'stay' in ids else ids[:max(1, prompt.get('choice', {}).get('minimum', 1))]
    result, prompts = settle(send_candidate(combat, table, mid, 'Impact', target=RIGHT, ai=True), choose=choose)
    asked = [p for p in prompts if any(o['id'] == 'stay' for o in (p.get('choice') or {}).get('options', []))]
    assert asked, [p.get('choice') for p in prompts]
    labels = [o.get('label') for o in asked[0]['choice']['options']]
    assert labels == ['Push away from the origin', 'Deal damage without pushing'], labels
    engine = cold(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert engine.state.actors[RIGHT].position == before
