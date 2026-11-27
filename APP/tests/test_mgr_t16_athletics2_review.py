"""Four spatial review findings through real table commits and cold reloads."""
from combat.ext import effect
from combat.gate2_runtime_models import CandidateKind, Position, ZoneState
from combat import creature_attachment
from combat.tabletop import normalize_map, to_battlefield
from tests.worker2_support import fixture, OWNER, ALLY, FOE, settle, turn, reload, candidate, sealed_native_attack
from tests.auto8f1_table_support import candidate_id, AXE_KIT
from tests.athletics_table_support import add_action
from tests.test_mgr_t16_athletics2_wall import WALL, action
from tests.test_mgr_t16_athletics2_scale import SCALE, QUARTERS, climb


@effect('mgr_t16_review_setup')
def setup(ctx, eff):
    engine = ctx.engine
    from combat.dynamic_size import apply_growth, sync
    apply_growth(engine, engine.state.actors[FOE], 'Huge', ctx.source,
                 source_actor_id=ctx.actor.entity_id, expires_on='UNTIL_REMOVED')
    sync(engine, ctx.source)
    if eff['case'] == 'area':
        zone = ZoneState(zone_id='zone:test.carried', source_definition_id=ctx.source, owner_id=ALLY,
            center=Position(x=5, y=6), radius_cells=0, affected_cells=(Position(x=5, y=6),),
            concentration_link=False, created_round=engine.state.round_number,
            trigger_profile={'kind': 'TYPED', 'numbers': {'save_dc': 99},
                'inside': [{'id': 'carried-inside', 'name': 'Inside burning square',
                            'reading': 'Affected only while inside the square.', 'rule': {}}],
                'triggers': [{'id': 'carried-entry', 'name': 'Burning square', 'on': ['enter'], 'who': 'any',
                    'effects': [{'type': 'save', 'ability': 'DEX', 'dc': 99, 'applies_to': 'target',
                        'on_fail': [{'type': 'damage', 'flat': 3, 'damage_types': ['force'], 'applies_to': 'target'}]}]},
                    {'id': 'carried-leave', 'name': 'Leaving burning square', 'on': ['leave'], 'who': 'any',
                     'effects': [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'target'}]}],
                'move_through': {'who': 'any', 'min_ft': 0, 'effects': [
                    {'type': 'damage', 'flat': 9, 'damage_types': ['force'], 'applies_to': 'target'}]}})
        engine.state.zones[zone.zone_id] = zone
        engine._append_event('ZONE_CREATED', ctx.source, actor_id=ALLY, payload={'zone': zone.model_dump(mode='json')})
    elif eff['case'] == 'inside':
        attacker, host = engine.state.actors[ALLY], engine.state.actors[FOE]
        creature_attachment.bind(engine, attacker, host, SCALE)
        before = attacker.position
        attacker.position = Position(x=host.position.x + 1, y=host.position.y, z=host.position.z)
        engine._append_event('MOVEMENT_COMMITTED', ctx.source, actor_id=ALLY,
            payload={'destination': attacker.position.model_dump(mode='json'), 'cost_ft': 0, 'forced': True,
                     'path': [before.model_dump(mode='json'), attacker.position.model_dump(mode='json')]})


def scale_game(tmp_path, case):
    def prepare(bundles):
        for b in bundles:
            b['skills'] = {'Athletics': 100, 'Acrobatics': 100} if b['actor_id'] == OWNER else {'Acrobatics': -100}
            if b['actor_id'] == FOE:
                b['actor_template']['armor_class'] = 1
            if b['actor_id'] == OWNER:
                b['actor_template']['armor_class'] = 20
                add_action(b, 'Review setup', [{'type': 'mgr_t16_review_setup', 'case': case}])
            if b['actor_id'] == ALLY:
                sealed_native_attack(b, 'Inside attack', attack_bonus=10)
    arena = to_battlefield(normalize_map({'display_name': 'Attachment review', 'width_squares': 12,
        'height_squares': 10, 'roofs': {'enabled': False}}))
    combat, table, mid = fixture(tmp_path, [SCALE, QUARTERS], named=True, battlefield=arena,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, ALLY: {'x': 9, 'y': 6}},
        team_overrides={ALLY: 'team:opponents'}, bundle_transform=prepare,
        seed='MGR-T16-REVIEW-'+tmp_path.name)
    settle(table, mid, candidate_id(table.state(mid)['menu'], 'Review setup'))
    climb(table, mid)
    return combat, table, mid


def test_carried_clinger_receives_area_entry_save_damage_and_leave(tmp_path):
    combat, table, mid = scale_game(tmp_path, 'area')
    turn(table, mid, FOE)
    start = reload(tmp_path, mid).state.actors[OWNER].current_hp
    for x in (5, 6):
        engine = combat._load_session(mid).engine
        c = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE
                 and c.destination == Position(x=x, y=6))
        settle(table, mid, c.candidate_id)
        fresh = reload(tmp_path, mid)
        assert fresh.state.actors[OWNER].position == fresh.state.actors[FOE].position
        assert fresh.state.actors[OWNER].current_hp == start - 3
        assert creature_attachment.carrier(fresh, fresh.state.actors[OWNER]) is fresh.state.actors[FOE]
        assert any(c.data.get('zone_id') == 'zone:test.carried'
                   for c in fresh.state.actors[OWNER].conditions.values()) == (x == 5)
    moments = [e.payload.get('moment') for e in fresh.events if e.event_type == 'PASSIVE_TRIGGERED'
               and OWNER in e.target_ids and e.payload.get('zone_id') == 'zone:test.carried']
    assert moments.count('enter') == moments.count('leave') == 1
    assert 'move_through' not in moments
    assert fresh.state.actors[OWNER].temporary_hp == 1
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER for e in fresh.events)


def test_inside_clinger_attack_gets_no_cover_or_redirection(tmp_path):
    combat, table, mid = scale_game(tmp_path, 'inside')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Inside attack', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert creature_attachment.carrier(engine, engine.state.actors[ALLY]) is engine.state.actors[FOE]
    row = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY)
    assert row.target_ids == (OWNER,)
    assert row.payload['cover_bonus'] == 0
    assert 'redirected_from' not in row.payload
    # The single Close Quarters provider excludes attacks from a fellow clinger.
    from combat.ext.athletics import close_cover
    assert close_cover(engine, engine.state.actors[ALLY], engine.state.actors[OWNER], {}) is None


def wall_game(tmp_path, *, elevated=False):
    def prepare(bundles):
        for b in bundles:
            if b['actor_id'] == FOE:
                b['actor_template'].update(fly_speed_ft=30, hover=True)
            elif b['actor_id'] == OWNER:
                b['actor_template'].update(fly_speed_ft=30, hover=True)
                add_action(b, 'Review geometry', [{'type': 'mgr_t16_review_setup', 'case': 'wall'}])
    arena = to_battlefield(normalize_map({'display_name': 'Creature wall review', 'width_squares': 12,
        'height_squares': 10, 'roofs': {'enabled': False}}))
    combat, table, mid = fixture(tmp_path, [WALL], named=True, battlefield=arena, foe_kit=AXE_KIT,
        positions={OWNER: {'x': 3, 'y': 3, 'z': 6 if elevated else 0},
                   FOE: {'x': 4, 'y': 3, 'z': 6 if elevated else 0}, ALLY: {'x': 10, 'y': 8}},
        bundle_transform=prepare, seed='MGR-T16-REVIEW-WALL-'+tmp_path.name)
    action(table, mid, 'Review geometry')
    action(table, mid, 'run up or along a wall')
    action(table, mid, 'record GM approval for a creature wall')
    return combat, table, mid


def test_elevated_creature_surface_stops_at_its_actual_bottom(tmp_path):
    from combat.roof_movement import faces
    combat, table, mid = wall_game(tmp_path, elevated=True)
    engine = reload(tmp_path, mid)
    owner, host = engine.state.actors[OWNER], engine.state.actors[FOE]
    face_id = 'creature:' + FOE
    for z in range(host.position.z):
        assert face_id not in {f.id for f in faces(engine, owner, Position(x=3, y=3, z=z))}
    assert face_id in {f.id for f in faces(engine, owner, owner.position)}
    # A real flight down into the gap stays available but cannot become a climb.
    c = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind == CandidateKind.MOVE
             and c.destination == Position(x=3, y=3, z=5) and c.metadata.get('movement_mode') == 'fly')
    settle(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    assert not any(c.kind == CandidateKind.MOVE and c.metadata.get('movement_mode') == 'climb'
                   for c in engine.legal_candidates())


def test_flight_beside_approved_wall_does_not_spend_its_reaction(tmp_path):
    combat, table, mid = wall_game(tmp_path)
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE
             and c.destination == Position(x=3, y=3, z=1) and c.metadata.get('movement_mode') == 'fly')
    settle(table, mid, c.candidate_id, picks={'reaction:typed.opportunity_attack': 'first'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].reaction_available
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE for e in engine.events)
