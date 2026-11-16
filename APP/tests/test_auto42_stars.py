"""Stellar flight, chosen marks, exact aim scope and persisted impact ground."""
import pytest
from combat import flight
from combat.ext import placed, stars
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender

T = 'tianxia.talent.stars.'
BOLT = 'STARS_BASE_STARBOLT'
DOMAIN = T + 'stars_domain'
SOVEREIGN = T + 'star_sovereign_incarnation'
SHADOW = T + 'star_shadow'


def resolve(send, picks=None):
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        p = result['reaction']
        prompts.append(p)
        ids = [o['id'] for o in (p.get('choice') or {}).get('options', [])]
        chosen = (picks or {}).get(p['context']['reaction_source_id'], ids[:1])
        answers.append({**p['context'], 'selection': 'USE' if chosen or not p.get('choice') else 'DECLINE', 'option_ids': chosen})
    raise AssertionError('too many choices')


def turn(table, mid, actor_id):
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == actor_id:
            return
        resolve(lambda answers: act(table, mid, 'end', answers))
    raise AssertionError('turn did not advance')


def cell_send(table, mid, label, xy):
    def send(answers):
        state = table.state(mid)
        menu = state['menu']
        cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label for o in g['options']
            if o.get('destination') == {'x': xy[0], 'y': xy[1]})
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    return send


def ascend(combat, table, mid, actor_id):
    state = table.state(mid)
    actor = reload(combat, mid).state.actors[actor_id]
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
        if c.destination is not None and c.metadata.get('movement_mode') == 'fly'
        and (c.destination.x, c.destination.y, c.destination.z) == (actor.position.x, actor.position.y, 1))
    menu = state['menu']
    return table.act(mid, candidate.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], [])


@pytest.mark.parametrize('ai', [False, True])
def test_sovereign_has_native_hover_and_walking_is_unchanged(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [SOVEREIGN], cl=17,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 8, 'y': 6}})
    engine = reload(combat, mid)
    assert flight.profile(engine, engine.state.actors[LEFT]).speed_ft == 0
    resolve(action_sender(combat, table, mid, 'Star-Sovereign Incarnation', ai=ai))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert flight.profile(engine, actor).speed_ft == 80 and flight.profile(engine, actor).hover
    assert engine._effective_speed(actor) == 30 and actor.position.z == 0
    assert actor.resources['resource:core.qi'] == 85
    if not ai:
        assert ascend(combat, table, mid, LEFT)['status'] == 'COMMITTED'
        assert reload(combat, mid).state.actors[LEFT].position.z == 1


def test_star_shadow_flight_survives_actual_summon_turn_and_concentration_end(tmp_path):
    combat, table, mid = fight(tmp_path, [SHADOW],
        cause=[{'type': 'condition', 'condition': 'stunned', 'applies_to': 'target', 'duration': 'until_removed'}])
    resolve(lambda answers: act(table, mid, 'Star Shadow', answers))
    engine = reload(combat, mid)
    shadow = next(a for a in engine.state.actors.values() if (a.summon or {}).get('source') == SHADOW)
    assert flight.profile(engine, shadow).speed_ft == 30 and flight.profile(engine, shadow).hover
    assert shadow.maximum_hp == 75 and shadow.armor_class == 17
    assert engine.state.actors[LEFT].concentration is not None
    # Uncommanded summons automatically Dodge at their slot; command it first
    # so its actual, owner-controlled turn is exposed for the movement regression.
    resolve(lambda answers: act(table, mid, 'Command Star Shadow', answers))
    turn(table, mid, shadow.entity_id)
    assert ascend(combat, table, mid, shadow.entity_id)['status'] == 'COMMITTED'
    assert reload(combat, mid).state.actors[shadow.entity_id].position.z == 1
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert not engine.state.actors[shadow.entity_id].active


@pytest.mark.parametrize('ai,accept', [(False, False), (False, True), (True, True)])
def test_starbolt_optional_mark_and_turn_expiry(tmp_path, ai, accept):
    combat, table, mid = fight(tmp_path, [BOLT], left_attack_bonus=100)
    picks = {'choice:needle.starbolt_mark': ['MARK'] if accept else []}
    _, prompts = resolve(action_sender(combat, table, mid, 'Starbolt', ai=ai, target_id=RIGHT), picks)
    engine = reload(combat, mid)
    assert stars.bears_mark(engine.state.actors[RIGHT], LEFT) == accept
    assert engine.state.actors[RIGHT].current_hp < 1000
    if not ai:
        assert any('Starbolt hits Visitor' in str(p) for p in prompts)
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not stars.bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT)


@pytest.mark.parametrize('aligned,source,label', [(False, 'STARS_TAL_FALLING_STAR', 'Falling Star'),
    (True, 'STARS_TAL_FALLING_STAR', 'Falling Star'), (False, 'STARS_TAL_HEAVEN_FALLING_STAR', 'Heaven-Falling Star')])
def test_impact_difficult_ground_persists_without_concentration(tmp_path, aligned, source, label):
    combat, table, mid = fight(tmp_path, [source, *([DOMAIN] if aligned else [])], cl=17,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 8, 'y': 6}})
    if aligned:
        resolve(lambda answers: act(table, mid, 'Stars Domain', answers))
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)
    resolve(cell_send(table, mid, label, (8, 6)))
    engine = reload(combat, mid)
    zones = placed.of(engine, 'stellar_impact')
    assert len(zones) == int(aligned or source == 'STARS_TAL_HEAVEN_FALLING_STAR')
    if zones:
        zone, = zones
        assert zone.duration_rounds is None and not zone.concentration_link
        assert zone.trigger_profile['difficult'] == 'all'
        assert (zone.center.x, zone.center.y) == (8, 6)
        assert len(zone.affected_cells) == (1 if source == 'STARS_TAL_HEAVEN_FALLING_STAR' else len(placed.area(engine, zone.center, 'sphere', 20)))
        turn(table, mid, RIGHT)
        assert placed.of(reload(combat, mid), 'stellar_impact')


def test_aligned_meteor_variant_extends_actual_area(tmp_path):
    meteor = 'STARS_TAL_METEOR_SHOWER'
    combat, table, mid = fight(tmp_path, [meteor, DOMAIN], cl=17,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 8, 'y': 6}})
    assert not any(g['label'] == 'Meteor Shower (20-foot radius, only while you stand inside your own Stars Domain)' for g in table.state(mid)['menu']['actions'])
    resolve(lambda answers: act(table, mid, 'Stars Domain', answers))
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert any(g['label'] == 'Meteor Shower (20-foot radius, only while you stand inside your own Stars Domain)' for g in table.state(mid)['menu']['actions'])
    # Pick a native legal point 20 feet from Visitor, outside the ordinary area.
    engine = reload(combat, mid)
    group = next(g for g in table.state(mid)['menu']['actions'] if g['label'] == 'Meteor Shower (20-foot radius, only while you stand inside your own Stars Domain)')
    from combat.gate2_runtime_models import Position
    from combat.spatial_areas import actor_in_area
    action = next(a for a in engine.action_catalog.values() if a.display_name == group['label'])
    assert action.radius_ft == 20
    assert action.parameters['typed']['area']['size_ft'] == 20
    point = next(o['destination'] for o in group['options'] if o.get('destination')
        and engine.grid.distance_ft(engine.state.actors[RIGHT].position, Position(**o['destination'])) == 20
        and actor_in_area(engine, engine.state.actors[RIGHT], engine.state.actors[LEFT].position,
                          Position(**o['destination']), {'shape': 'sphere', 'size_ft': 20})
        and not actor_in_area(engine, engine.state.actors[RIGHT], engine.state.actors[LEFT].position,
                              Position(**o['destination']), {'shape': 'sphere', 'size_ft': 15}))
    before = engine.state.actors[RIGHT].current_hp
    resolve(cell_send(table, mid, 'Meteor Shower (20-foot radius, only while you stand inside your own Stars Domain)', (point['x'], point['y'])))
    assert reload(combat, mid).state.actors[RIGHT].current_hp < before


def test_needle_aim_is_not_consumed_by_other_ranged_cultivation(tmp_path):
    combat, table, mid = fight(tmp_path, [BOLT, 'STARS_TAL_COMET_SPEAR', T + 'star_needle_aim'], left_attack_bonus=100)
    assert act(table, mid, 'Star-Needle Aim')['status'] == 'COMMITTED'
    resolve(lambda answers: act(table, mid, 'Comet Spear', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert any(c.condition_id == stars.NEEDLE for c in engine.state.actors[LEFT].conditions.values())
    assert engine.state.actors[LEFT].turn_flags.get(stars.NEEDLE_PLUS) is None


@pytest.mark.parametrize('ai', [False, True])
def test_falling_spark_choice_matches_one_marked_target(tmp_path, ai):
    spark = 'STARS_TAL_FALLING_SPARK'
    combat, table, mid = fight(tmp_path, [spark],
        prepare=[{'type': 'mark', 'mark': stars.MARK, 'applies_to': subject, 'duration': {'kind': 'until_removed'}}
                 for subject in ('self', 'target')],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    if ai:
        from combat.gate4_adapters import ManualControllerAdapter
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                c = next(c for c in context.legal_candidates if c.source_definition_id.endswith(spark)
                         and c.destination is not None and (c.destination.x, c.destination.y) == (4, 6))
                return ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
        send = lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers)
    else:
        send = cell_send(table, mid, 'Falling Spark', (4, 6))
    _, prompts = resolve(send, {'choice:needle.falling_spark': [RIGHT]})
    if not ai:
        choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.falling_spark')
        assert {o['id'] for o in choice['choice']['options']} == {RIGHT}
    saves = [e for e in reload(combat, mid).events if e.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1 and saves[0].actor_id == RIGHT and saves[0].payload['mode'] == 'DISADVANTAGE'
    assert reload(combat, mid).state.actors[LEFT].current_hp == 1000
    if not ai:
        assert next(e for e in saves if e.actor_id == RIGHT).payload['mode'] == 'DISADVANTAGE'


def test_starbolt_mark_can_be_used_only_once_during_one_turn(tmp_path):
    attack = {'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1, 'on_hit': [
        {'type': 'damage', 'flat': 1, 'damage_types': ['force']}, {'type': 'stars_starbolt_mark'}]}
    combat, table, mid = fight(tmp_path, [BOLT], prepare=[attack], prepare_source=BOLT, left_attack_bonus=100)
    resolve(lambda answers: act(table, mid, 'Starbolt', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    first_mark = next(c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id.endswith('stellar_mark.' + LEFT))
    _, prompts = resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT))
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.starbolt_mark' for p in prompts)
    engine = reload(combat, mid)
    second_mark = next(c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id == first_mark.condition_id)
    assert second_mark.applied_sequence == first_mark.applied_sequence
