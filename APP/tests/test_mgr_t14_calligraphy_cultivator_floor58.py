"""Calligraphy acquisition -> paid table intent -> commit -> cold replay.

The access source is admitted by NS1R; no fixture-owned feature list, manually
inserted condition or synthetic action stands in for the source acquisition.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from app.core import Database, Settings, FoundryError
from non_sphere_authority import NonSphereAuthorityService
from combat.ext import effect
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award, commit_authority_event
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

ROOT = Path(__file__).resolve().parents[1]
QI = 'tianxia.path.qi_cultivation'
SUBPATH = 'tianxia.subpath.qi.calligraphy_cultivator'
BINDING = SUBPATH + '.feature.character_of_binding'
DUST = 'tianxia.subpath.qi.dust_cultivator.feature.choking_dust'
LIVING = SUBPATH + '.feature.living_character'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp('calligraphy-acquisition') / 'data')
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = 'calligraphy-restricted-scripture'
    insert_project(db, project, 18)
    service.initialize_for_project(project, target_cl=18, path_ids=[QI], method_id='METHOD-001')
    service.allocate_advancement(project, {QI: 17},
        evidence_id=ap_award(db, service, project, 'METHOD-001', 18, 17),
        idempotency_key=project + '-advance')
    with pytest.raises(FoundryError):
        service.select_subpath(project, QI, SUBPATH)
    receipt = commit_authority_event(db, service, project, 'subpath_access', {'selection_id': SUBPATH})
    service.select_subpath(project, QI, SUBPATH, access_source_records=[{'evidence_id': receipt}])
    state = NonSphereAuthorityService(db).get_state(project)
    doc = sheet([], cl=18, name='Calligraphy writer')
    doc['path_and_subpath'] = {'paths': state['paths']}
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    return doc


def set_effective_cl(doc, cl):
    """Set the Qi Path's effective CL. NS1R's state lists every Path (Body Refining and
    Spirit Awakening come first), so the Qi row is found by id, never by position."""
    row = next(row for row in doc['path_and_subpath']['paths'] if row.get('path_id') == QI)
    row['effective_cl'] = cl
    return doc


def scenario(tmp_path, acquired, *, dc=100, effective_cl=None):
    doc = deepcopy(acquired)
    doc['ability_scores_and_statistics']['technique_save_dc'] = dc
    if effective_cl is not None:
        set_effective_cl(doc, effective_cl)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    return fixture(tmp_path, [], cl=18, owner_bundle=owner, seed='MGR-T14-CALLIGRAPHY')


CELL = 'choice:needle.qi_calligraphy_cell'


def legal_cells(tmp_path, mid, origin, feet):
    from combat.ext.qi_subpaths_four import legal_anchor_cells
    engine = reload(tmp_path, mid)
    return engine, [p for p in legal_anchor_cells(engine, origin, feet) if p != origin]


def placement(tmp_path, mid, target):
    """The explicit, nearest legal Anchor cell beside the target: a real choice, never the menu default."""
    from combat.ext.needle import cell_id
    engine = reload(tmp_path, mid)
    _, cells = legal_cells(tmp_path, mid, engine.state.actors[target].position, 5)
    return {CELL: cell_id(cells[0], include_altitude=True)}


def destination(tmp_path, mid, anchor, foe):
    """A Rewrite destination different from the Anchor's current cell and still within 30 feet of the target."""
    from combat.ext.needle import cell_id
    engine, cells = legal_cells(tmp_path, mid, anchor, 15)
    cells = [p for p in cells if engine.grid.distance_ft(p, engine.state.actors[foe].position) <= 30]
    assert cells and all(p != anchor for p in cells)
    return {CELL: cell_id(cells[-1], include_altitude=True)}


def binding_candidates(engine, owner):
    """Offered Character of Binding candidates for an owner (availability, not the catalog listing)."""
    out = []
    for c in engine.legal_candidates():
        action = engine.action_catalog.get(c.source_definition_id)
        if (action is not None and action.owner_id == owner and action.display_name == 'Character of Binding'
                and not action.parameters.get('qi_binding_rewrite')):
            out.append(c)
    return out


def anchors(engine):
    return [o for o in engine.state.objects.values()
            if not o.destroyed and (o.component or {}).get('qi_calligraphy_binding')]


def rewrites(engine, owner):
    """Offered Rewrite the Boundary candidates (availability, not the catalog listing)."""
    out = []
    for c in engine.legal_candidates():
        action = engine.action_catalog.get(c.source_definition_id)
        if action is not None and action.owner_id == owner and action.display_name == 'Rewrite the Boundary':
            out.append(c)
    return out


def seal_alcove(arena):
    """Pillar shell around the four free squares of the map corner (0..1, 0..1): the writer, its
    target and the legal Anchor cell stay inside, with a clear line of sight between writer and target
    (the diagonal runs past the open (1, 1) corner); every square the Rewrite's own geometry could
    reach is blocked terrain."""
    arena['terrain_regions'] = [{'region_id': 'test.rewrite-alcove', 'terrain_type': 'BLOCKED',
                                'movement_cost': 0,
                                'cells': [{'x': x, 'y': y} for x in range(4) for y in range(4)
                                          if (x, y) not in {(0, 0), (0, 1), (1, 0), (1, 1)}],
                                'description': 'Test pillars sealing a three-square alcove at the map corner.'}]


CAPS = 'action:test.mgr_t14_calligraphy.rewrite_caps'


@effect('test_floor58_rewrite_caps')
def rewrite_caps(ctx, row):
    """Evented test setup inside a real table commit (a2_death's pattern): the caps are in the
    journal and survive cold replay, so the cramped alcove is real committed state."""
    from combat.gate2_runtime_models import Position, RuntimeObjectState
    # Ground-level (1, 1) is filled too, so the Anchor's neighbourhood holds no free square.
    ctx.engine._update_object(RuntimeObjectState(
        object_id='object:test.rewrite-cap.0.1.1', object_kind='DOOR',
        position=Position(x=1, y=1, z=0), ac=10, current_hp=1, maximum_hp=1,
        unattended=True, flammable=False,
        component={'name': 'Test fill', 'blocks': True, 'material': 'stone', 'size': 'small'}),
        ctx.source)
    for x, y in [(0, 0), (0, 1), (1, 0), (1, 1)]:
        for z in (1, 2, 3):
            ctx.engine._update_object(RuntimeObjectState(
                object_id=f'object:test.rewrite-cap.{z}.{x}.{y}', object_kind='DOOR',
                position=Position(x=x, y=y, z=z), ac=10, current_hp=1, maximum_hp=1,
                unattended=True, flammable=False,
                component={'name': 'Test fill', 'blocks': True, 'material': 'stone', 'size': 'small'}),
                ctx.source)


def seal_caps(bundle):
    """Seal the scenario-only caps setup action onto the owner's bundle (test-only free action)."""
    bundle['action_catalog'].append({
        'source_definition_id': CAPS, 'display_name': 'Place test rewrite caps', 'owner_id': bundle['actor_id'],
        'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF', 'costs': [],
        'parameters': {'typed': {'effects': [{'type': 'test_floor58_rewrite_caps'}],
                                 'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []},
                       'expected_damage': 0, 'free_primary': True}})
    bundle['actor_template']['action_ids'].append(CAPS)
    bundle['summons'] = []
    return bundle


@pytest.mark.parametrize('dc,restrained,speed', [(100, True, 0), (-100, False, 20)])
def test_binding_native_acquisition_anchor_save_cost_and_cold_replay(tmp_path, acquired, dc, restrained, speed):
    combat, table, mid = scenario(tmp_path, acquired, dc=dc)
    cast = candidate(combat, mid, 'Character of Binding', target=FOE)
    settle(table, mid, cast.candidate_id, choices=placement(tmp_path, mid, FOE))
    engine = reload(tmp_path, mid)
    held = engine.state.actors[FOE]
    assert bool([c for c in held.conditions.values() if c.data.get('qi_calligraphy_binding')]) is restrained
    assert engine._effective_speed(held) == speed
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 95
    anchor, = anchors(engine)
    assert anchor.ac == 15 and anchor.maximum_hp == 54
    assert anchor.component['source_cl'] == 18 and anchor.component['size'] == 'tiny'
    assert set(anchor.component['resist']) == {'BLUDGEONING', 'PIERCING', 'SLASHING'}
    assert set(anchor.damage_immunities) >= {'POISON', 'PSYCHIC'}
    assert engine.grid.distance_ft(anchor.position, held.position) == 5
    assert not any(e.event_type in {'GM_RIDER', 'GM_ADJUDICATION_REQUIRED'}
                   and e.source_definition_id == cast.source_definition_id for e in engine.events)
    rewrite = candidate(combat, mid, 'Rewrite the Boundary')
    before = anchor.position
    settle(table, mid, rewrite.candidate_id, choices=destination(tmp_path, mid, before, FOE))
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources['resource:core.qi'] == 94
    moved, = anchors(after)
    assert after.grid.distance_ft(before, moved.position) <= 15
    assert after.grid.distance_ft(moved.position, after.state.actors[FOE].position) <= 30
    # Each target turn performs the real end-turn save, including cold replay.
    turn(table, mid, FOE)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.actor_id == FOE and e.source_definition_id == cast.source_definition_id]
    assert len(saves) == (2 if restrained else 1)
    if not restrained:
        turn(table, mid, OWNER)
        assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[FOE]) == 30


def test_parent_attainment_and_wrong_owner_leave_binding_unavailable(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired, effective_cl=13)
    engine = reload(tmp_path, mid)
    assert not binding_candidates(engine, OWNER)
    assert not binding_candidates(engine, ALLY)
    assert not anchors(engine)


def test_recasting_binding_retires_only_the_previous_anchor_and_restraint(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    first = candidate(combat, mid, 'Character of Binding', target=FOE)
    settle(table, mid, first.candidate_id, choices=placement(tmp_path, mid, FOE))
    old, = anchors(reload(tmp_path, mid))
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    second = candidate(combat, mid, 'Character of Binding', target=ALLY)
    settle(table, mid, second.candidate_id, choices=placement(tmp_path, mid, ALLY))
    engine = reload(tmp_path, mid)
    new, = anchors(engine)
    assert new.object_id != old.object_id
    assert engine.state.objects[old.object_id].destroyed
    assert not any(c.data.get('qi_calligraphy_binding') for c in engine.state.actors[FOE].conditions.values())
    assert any(c.data.get('qi_calligraphy_binding') for c in engine.state.actors[ALLY].conditions.values())


def test_binding_cannot_outlive_its_native_one_minute_deadline(tmp_path, acquired):
    combat, table, mid = scenario(tmp_path, acquired)
    cast = candidate(combat, mid, 'Character of Binding', target=FOE)
    settle(table, mid, cast.candidate_id, choices=placement(tmp_path, mid, FOE))
    started = reload(tmp_path, mid).state.actors[OWNER].turns_started
    for _ in range(10):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turns_started == started + 10
    assert not anchors(engine)
    assert not any(c.data.get('qi_calligraphy_binding') for c in engine.state.actors[FOE].conditions.values())


def test_earned_occurrence_cannot_admit_binding_below_subpath_minimum(tmp_path, acquired):
    """Regression for the admission order: an earned occurrence naming Binding is filtered by the same
    source-level Subpath gate, so a below-minimum Subpath leaves Binding unavailable."""
    doc = set_effective_cl(deepcopy(acquired), 13)
    doc['path_and_subpath']['earned_feature_occurrences'] = [{'feature_id': BINDING, 'occurrence_id': 'occ-binding'}]
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=owner, seed='MGR-T14-CALLIGRAPHY')
    engine = reload(tmp_path, mid)
    assert not binding_candidates(engine, OWNER)


def test_anchor_placement_offers_every_legal_height_within_reach(tmp_path, acquired):
    """Regression for the altitude enumeration: Anchor and Rewrite cells are not limited to the origin's height."""
    combat, table, mid = scenario(tmp_path, acquired)
    engine, cells = legal_cells(tmp_path, mid, reload(tmp_path, mid).state.actors[FOE].position, 5)
    origin = engine.state.actors[FOE].position
    assert any(p.z != origin.z for p in cells)


def test_binding_scales_by_subpath_cl_not_character_cl(tmp_path, acquired):
    """The Binding action carries the Calligraphy CL (16) even though the character is CL 18."""
    doc = set_effective_cl(deepcopy(acquired), 16)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=owner, seed='MGR-T14-CALLIGRAPHY')
    engine = reload(tmp_path, mid)
    rows = [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.display_name == 'Character of Binding'
            and not a.parameters.get('qi_binding_rewrite')]
    assert rows and rows[0].parameters['typed']['numbers']['cl'] == 16


def test_subpath_cl_basis_scales_any_subpath_feature():
    """The compiler keys a Subpath feature's numbers CL on the record's printed Source CL basis
    (the Subpath index feature_progression, read by subpath_acquisition), never on one Subpath's
    id: a non-Calligraphy Subpath scales exactly like the Calligraphy features do, and a feature
    below the Subpath's minimum stays out of the set."""
    sheet = {
        'identity': {'proficiency_bonus': 4, 'cultivation_level': 18, 'path': 'Qi Cultivation',
                     'key_ability': 'CON', 'name': 'Dual-script writer'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 100}, 'armor_class': {'base_value': 14},
            'hit_points': {'maximum': 60}, 'speed': {'walking_ft': 30},
            'technique_save_dc': 100, 'technique_attack_bonus': 8},
        'path_and_subpath': {
            'paths': [{'path_id': QI, 'attainment': 8, 'effective_cl': 8}],
            'subpaths': [{'subpath_id': SUBPATH, 'owning_path_id': QI},
                         {'subpath_id': 'tianxia.subpath.qi.dust_cultivator', 'owning_path_id': QI}]},
    }
    bundle = compile_character(sheet, actor_id=OWNER)
    cl = {}
    for action in bundle['action_catalog']:
        params = action['parameters'] if isinstance(action, dict) else action.parameters
        typed = (params.get('typed') or {}) if isinstance(params, dict) else (params.typed or {})
        if typed.get('source') in (DUST, LIVING):
            cl[typed['source']] = typed['numbers']['cl']
    assert cl == {DUST: 8, LIVING: 8}


def test_boxed_anchor_offers_no_rewrite(tmp_path, acquired):
    """Rewrite the Boundary moves the Anchor only to a legal unoccupied space within 15 feet of it
    that is still within 30 feet of the held target. With the Anchor's whole neighbourhood spent (the
    writer and target in the only other ground squares, the height above them capped after the cast),
    the option is unavailable instead of payable-and-inert: no candidate, the Bonus Action unused and
    the 1 Qi never spent."""
    owner = seal_caps(compile_character(deepcopy(acquired), actor_id=OWNER, reaction_plan={'ask': True}))
    combat, table, mid = fixture(
        tmp_path, [], cl=18, owner_bundle=owner, seed='MGR-T14-CALLIGRAPHY',
        battlefield_transform=seal_alcove,
        positions={OWNER: {'x': 1, 'y': 0}, ALLY: {'x': 10, 'y': 10}, FOE: {'x': 0, 'y': 1}})
    cast = candidate(combat, mid, 'Character of Binding', target=FOE)
    settle(table, mid, cast.candidate_id, choices=placement(tmp_path, mid, FOE))
    # Caps go up after the Anchor exists: a grid cell is occupied at every height, so putting them
    # first would leave the Character nowhere to create its Anchor at all.
    settle(table, mid, candidate(combat, mid, 'Place test rewrite caps').candidate_id)
    engine = reload(tmp_path, mid)
    anchor, = anchors(engine)
    assert (anchor.position.x, anchor.position.y, anchor.position.z) == (0, 0, 0)
    me = engine.state.actors[OWNER]
    assert me.bonus_action_available and me.resources['resource:core.qi'] == 95
    assert not rewrites(engine, OWNER)


def seal_open_pit(arena):
    """Blocked ground around the writer's corner: only the writer's and the target's squares stay open
    at ground level; the target sits at (0, 1). Capping heights 1-3 (seal_pit_caps) leaves no legal
    Anchor square within 5 feet of the target."""
    arena['terrain_regions'] = [{'region_id': 'test.binding-pit', 'terrain_type': 'BLOCKED',
                                'movement_cost': 0,
                                'cells': [{'x': x, 'y': y} for x in range(4) for y in range(4)
                                          if (x, y) not in {(0, 0), (0, 1)}],
                                'description': 'Test pillars leaving no free square beside the target.'}]


PIT_CAPS = 'action:test.mgr_t14_calligraphy.pit_caps'


@effect('test_floor58_pit_caps')
def pit_caps(ctx, row):
    """Caps every square of the test pit at heights 1-3 inside a real commit (journal-backed, like rewrite_caps)."""
    from combat.gate2_runtime_models import Position, RuntimeObjectState
    for x in range(4):
        for y in range(4):
            for z in (1, 2, 3):
                ctx.engine._update_object(RuntimeObjectState(
                    object_id=f'object:test.pit-cap.{z}.{x}.{y}', object_kind='DOOR',
                    position=Position(x=x, y=y, z=z), ac=10, current_hp=1, maximum_hp=1,
                    unattended=True, flammable=False,
                    component={'name': 'Test fill', 'blocks': True, 'material': 'stone', 'size': 'small'}),
                    ctx.source)


def seal_pit_caps(bundle):
    bundle['action_catalog'].append({
        'source_definition_id': PIT_CAPS, 'display_name': 'Place test pit caps', 'owner_id': bundle['actor_id'],
        'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF', 'costs': [],
        'parameters': {'typed': {'effects': [{'type': 'test_floor58_pit_caps'}],
                                 'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []},
                       'expected_damage': 0, 'free_primary': True}})
    bundle['actor_template']['action_ids'].append(PIT_CAPS)
    bundle['summons'] = []
    return bundle


def test_binding_not_offered_without_a_legal_adjacent_anchor(tmp_path, acquired):
    """Regression for the Binding gate: Character of Binding needs a legal unoccupied Anchor space within
    5 feet of its target at any height. Open ground offers the option; once every square within reach of
    the target is blocked or capped, the option is not offered, no Qi is spent and no Anchor is placed."""
    owner = seal_pit_caps(compile_character(deepcopy(acquired), actor_id=OWNER, reaction_plan={'ask': True}))
    combat, table, mid = fixture(
        tmp_path, [], cl=18, owner_bundle=owner, seed='MGR-T14-CALLIGRAPHY',
        battlefield_transform=seal_open_pit,
        positions={OWNER: {'x': 0, 'y': 0}, ALLY: {'x': 10, 'y': 10}, FOE: {'x': 0, 'y': 1}})
    assert binding_candidates(reload(tmp_path, mid), OWNER)  # open air above and beside the target
    settle(table, mid, candidate(combat, mid, 'Place test pit caps').candidate_id)
    engine = reload(tmp_path, mid)
    assert not binding_candidates(engine, OWNER)
    assert not anchors(engine)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100


def test_bound_anchor_identity_survives_cold_reload(tmp_path, acquired):
    """Regression for the note that bound-object IDs must persist: the Anchor keeps its object ID and its
    exact marker/restraint instance record after a cold reload, and every recorded instance is still live."""
    combat, table, mid = scenario(tmp_path, acquired)
    cast = candidate(combat, mid, 'Character of Binding', target=FOE)
    settle(table, mid, cast.candidate_id, choices=placement(tmp_path, mid, FOE))
    first = reload(tmp_path, mid)
    anchor, = anchors(first)
    record = dict(anchor.component['qi_calligraphy_binding'])
    second = reload(tmp_path, mid)
    again, = anchors(second)
    assert again.object_id == anchor.object_id
    assert again.component['qi_calligraphy_binding'] == record
    live = {c.instance_id for actor in second.state.actors.values() for c in actor.conditions.values()}
    assert set(record['instances']) <= live

