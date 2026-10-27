"""Palm source contracts: acquired sheets -> compile -> table -> cold replay.

No model transport, browser or injected mark. Possession Trance supplies a
real Guest Seat and its native speed consumer. Explicit source-action fixtures
separately guard the reusable expression/protection contracts.
"""
import copy

import pytest

from combat.factory_compiler import compile_character
from combat.source_acquisition import acquire_feature, SourceAcquisitionStore
from combat.ext import source_records
from combat import typed_executor
from combat.gate5_service import CombatService
from combat.ext.last_inch_palm import PALM, SUBJECT
from test_riders_c8 import ROOT, authority, sheet
from test_a2_group_traditions_3 import ENEMY, LI, ME, MIND_SPIKE, advance, chooser, reload, service_commit, table

IDS = [MIND_SPIKE, LI + "the_last_inch", PALM]
TRANCE = "tianxia.tradition.spirit.mudang.feature.possession_trance"
DANCE = "tianxia.tradition.spirit.mudang.feature.spirit_dance"
SEAT = "condition:typed.guest_seat"


def compile_sheet(ids, actor=ME, *, cl=10, dc=40, effective=None, **kw):
    document = sheet([fid for fid in ids if fid != PALM], cl=cl, dc=dc, **kw)
    if PALM in ids:
        document = acquire_feature(document, PALM, actor_id=actor, occurrence_id="earned:palm:10",
            access_record={"kind": "restricted_spirit_tradition", "basis": "prison_breaker_inheritance", "record_id": "owner:inheritance-access"})
    if effective is not None:
        document["identity"]["effective_cultivation_level"] = effective
    return compile_character(document, actor_id=actor, typed_authority=authority())


def record(category="possession_entry", scope="contact_expression", **kw):
    return {"id": "road_guest", "name": "Possession Trance: Road Guest",
        "source_record_id": TRANCE, "condition_id": SEAT, "category": category,
        "scope": scope, "source_cl": 6, "ordinary": 1,
        "data_match": {"seat": "Road Guest"}, "known_to": [ME], **kw}


def target_bundle(rec=None, *, size="Medium", types=(), cl=6, dc=-40, saves=None):
    document = sheet([MIND_SPIKE, DANCE, TRANCE], cl=cl, dc=dc)
    document["identity"].update(size=size, creature_types=list(types))
    if saves is not None:
        document["ability_scores_and_statistics"]["saving_throws"] = saves
    if rec is not None:
        document = source_records.acquire(document, rec)
    return compile_character(document, actor_id=ENEMY, typed_authority=authority())


def mark(svc, session, meta):
    advance(svc, session, meta, ME)
    assert not [c for c in session.engine.legal_candidates() if "Palm Across Emptiness" in c.display_name]
    service_commit(svc, session, meta, "Mind Spike", ENEMY, choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)


def guest(svc, session, meta):
    advance(svc, session, meta, ENEMY)
    # Earn the actual Trance Rhythm cost by dancing and moving ten feet.
    service_commit(svc, session, meta, "Spirit Dance: Warding Step", choose=chooser)
    position = session.engine.state.actors[ENEMY].position
    movement = next(c for c in session.engine.legal_candidates() if c.destination is not None
                    and c.destination.x == position.x and c.destination.y == position.y + 2)
    service_commit(svc, session, meta, movement.display_name, choose=chooser)
    assert session.engine.state.actors[ENEMY].resources["resource:named.trance_rhythm"] == 1
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ENEMY)
    name = next(c.display_name for c in session.engine.legal_candidates() if "Possession Trance" in c.display_name and "Road Guest" in c.display_name)
    service_commit(svc, session, meta, name, choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)


@pytest.mark.parametrize("size,save,limited", [("Large", True, False), ("Huge", True, True), ("Huge", False, False)])
def test_draw_size_optional_save_is_target_owned(tmp_path, size, save, limited):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS),
        enemy=target_bundle(size=size, saves={"STR": 100, "WIS": -100}), allies=False)
    mark(svc, session, meta)
    before = session.engine.state.actors[ENEMY].position
    prompts = []
    def choose(context):
        if context.reaction_source_id.endswith("draw_save"):
            prompts.append(context)
            assert context.reactor_id == ENEMY
            assert "Palm Across Emptiness" in context.choice_trigger["prompt"]
            return ("save",) if save else ()
        return chooser(context)
    events, _, _ = service_commit(svc, session, meta, "Palm Across Emptiness: Draw Into the Palm", ENEMY, choose=choose)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and str(e.payload.get("reason", "")).endswith(":STR")]
    assert bool(prompts) == (size == "Huge")
    assert bool(saves) == (size == "Huge" and save)
    if limited:
        assert session.engine.grid.distance_ft(before, target.position) <= 10
    else:
        assert session.engine._distance_actor_to_actor(target, session.engine.state.actors[ME]) == 5


def test_native_bodily_protection_grants_draw_save_without_size(tmp_path):
    rooted = "tianxia.subpath.body.sumo.feature.rooted_stance"
    document = sheet([MIND_SPIKE, rooted], cl=10, dc=-40)
    document["ability_scores_and_statistics"]["saving_throws"] = {"STR": 100, "WIS": -100}
    other = compile_character(document, actor_id=ENEMY, typed_authority=authority())
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=other, allies=False)
    advance(svc, session, meta, ENEMY)
    service_commit(svc, session, meta, "Rooted Stance", choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    mark(svc, session, meta)
    session = reload(svc, session)
    assert source_records.live(session.engine, session.engine.state.actors[ENEMY], scope="forced_movement")
    prompts = []
    def choose(context):
        if context.reaction_source_id.endswith("draw_save"):
            prompts.append(context)
            return ("save",)
        return chooser(context)
    service_commit(svc, session, meta, "Palm Across Emptiness: Draw Into the Palm", ENEMY, choose=choose)
    session = reload(svc, session)
    assert prompts
    # Its own five-foot forced-movement reduction is still a separate consumer.
    assert session.engine.state.actors[ENEMY].position.x >= 9


@pytest.mark.parametrize("effective,allowed", [(9, False), (10, True)])
def test_effective_cl_gates_only_available_palm_after_earned_acquisition(tmp_path, effective, allowed):
    mine = compile_sheet(IDS, cl=14, effective=effective)
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=mine, enemy=target_bundle(), allies=False)
    mark(svc, session, meta)
    session = reload(svc, session)
    palms = [c for c in session.engine.legal_candidates() if "Palm Across Emptiness" in c.display_name]
    assert bool(palms) == allowed


@pytest.mark.parametrize("source_cl,grants_save", [(9, False), (10, False), (11, True)])
def test_draw_generic_separation_requires_higher_source_authority(tmp_path, source_cl, grants_save):
    """An explicit source classification guards the generic authority boundary."""
    rec = record(category="separation", scope="forced_movement", source_cl=source_cl)
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS),
        enemy=target_bundle(rec, cl=source_cl), allies=False)
    guest(svc, session, meta)
    mark(svc, session, meta)
    prompts = []
    def choose(context):
        if context.reaction_source_id.endswith("draw_save"):
            prompts.append(context)
        return chooser(context)
    service_commit(svc, session, meta, "Palm Across Emptiness: Draw Into the Palm", ENEMY, choose=choose)
    reload(svc, session)
    assert bool(prompts) == grants_save


@pytest.mark.parametrize("types,allowed", [
    (["ordinary object"], False), (["spiritually empty corpse"], False),
    (["construct", "mindless", "nonspiritual"], False),
    (["construct", "mindless", "nonspiritual", "external anchor", "spirit techniques affectable"], True),
    (["ordinary object", "cultivation asset", "spirit techniques affectable"], True),
    (["internal soul anchor", "external anchor", "spirit techniques affectable"], False),
])
def test_explicit_external_spiritual_profiles_and_exclusions(tmp_path, types, allowed):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(types=types), allies=False)
    mark(svc, session, meta)
    session = reload(svc, session)
    assert any("Palm Across Emptiness" in c.display_name for c in session.engine.legal_candidates()) == allowed
    if allowed:
        service_commit(svc, session, meta, "Palm Across Emptiness: Hold at the Last Inch", ENEMY, choose=chooser)
        reload(svc, session)


def test_restricted_access_and_minimum_cl_are_explicit_owner_facts():
    for document, access in [(sheet([MIND_SPIKE], cl=9), {"kind": "restricted_spirit_tradition", "basis": "prison_breaker_inheritance", "record_id": "owner:access"}),
                             (sheet([MIND_SPIKE], cl=10), None)]:
        with pytest.raises(ValueError):
            acquire_feature(document, PALM, actor_id=ME, occurrence_id="palm", access_record=access)
    with pytest.raises(ValueError, match="Effective"):
        compile_sheet(IDS, effective=11)


@pytest.mark.parametrize("expression", ["Draw Into the Palm", "Cast Beyond Contact", "Hold at the Last Inch"])
def test_success_is_half_declared_damage_short_subject_no_expression(tmp_path, expression):
    # This native seed rolls 1 for Mind Spike and 20 for Palm. DC17 makes
    # the real first save fail and the real second save succeed; no die patch.
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS, dc=17), enemy=target_bundle(), allies=False)
    mark(svc, session, meta)
    before = session.engine.state.actors[ENEMY].position
    events, _, _ = service_commit(svc, session, meta, "Palm Across Emptiness: " + expression, ENEMY, choose=chooser)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == ENEMY]
    assert saves[0].payload["success"]
    assert target.position == before and session.engine._effective_speed(target) == 30
    assert not any(r.get("no_reactions") for r in typed_executor.condition_rules(target))
    damage = next(e.payload for e in events if e.event_type == "DAMAGE_COMMITTED")
    rolled = [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert damage["hp_damage"] == rolled[0]["total"] // 2
    subject = next(c for c in target.conditions.values() if c.condition_id == SUBJECT)
    assert subject.expires_on != "UNTIL_REMOVED"
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    assert any(c.condition_id == SUBJECT for c in session.engine.state.actors[ENEMY].conditions.values())
    service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    assert not any(c.condition_id == SUBJECT for c in session.engine.state.actors[ENEMY].conditions.values())


@pytest.mark.parametrize("gap", [True, False])
def test_spiritual_opening_and_body_size_are_independent(tmp_path, gap):
    import json
    battlefield = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    battlefield["terrain_regions"] = [{"region_id": "wall", "terrain_type": "BLOCKED", "movement_cost": 0,
        "cells": [{"x": 8, "y": y} for y in range(14) if not gap or y != 6]}]
    # A one-cell opening permits the contact ray, never a Huge body's passage.
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS),
        enemy=target_bundle(size="Huge"), allies=False, battlefield=battlefield)
    advance(svc, session, meta, ME)
    if not gap:
        assert not any("Mind Spike" == c.display_name for c in session.engine.legal_candidates())
        reload(svc, session)
        return
    mark(svc, session, meta)
    before = session.engine.state.actors[ENEMY].position
    assert session.engine._footprint(session.engine.state.actors[ENEMY]).width_cells == 3
    def choose(context):
        if context.reaction_source_id.endswith("draw_destination"):
            assert "cell:9,6" in context.extension_choice.option_ids
            return ("cell:9,6",)
        return chooser(context)
    service_commit(svc, session, meta, "Palm Across Emptiness: Draw Into the Palm", ENEMY, choose=choose)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    assert target.position.x >= 9
    assert session.engine.grid.distance_ft(before, target.position) == 5
    assert session.engine._distance_actor_to_actor(target, session.engine.state.actors[ME]) == 15


def test_scene_subject_ends_before_native_terminal_event(tmp_path):
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed="A2GTRA3-EXACT", maximum_rounds=3,
        typed_bundles=(compile_sheet(IDS), target_bundle()),
        roster_setup={"primary_actor_ids": [ME, ENEMY], "team_by_actor": {ME: "team:a", ENEMY: "team:b"},
            "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 10, "y": 6}}})
    meta = {"participant_control_modes": {ME: "MANUAL", ENEMY: "MANUAL"}}
    mark(svc, session, meta)
    service_commit(svc, session, meta, "Palm Across Emptiness: Hold at the Last Inch", ENEMY, choose=chooser)
    assert any(c.condition_id == SUBJECT for c in session.engine.state.actors[ENEMY].conditions.values())
    for _ in range(8):
        if session.engine.state.terminal_result is not None:
            break
        service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    assert session.engine.state.terminal_result is not None
    assert session.engine.events[-1].event_type == "MATCH_ENDED"
    assert not any(c.condition_id == SUBJECT for c in session.engine.state.actors[ENEMY].conditions.values())


@pytest.mark.parametrize("blocks", [False, True])
@pytest.mark.parametrize("expression", ["Draw Into the Palm", "Cast Beyond Contact", "Hold at the Last Inch"])
def test_native_external_object_acquires_subject_then_palm_and_cold_reload(tmp_path, expression, blocks):
    import json
    from combat.ext import object_subjects
    battlefield = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    battlefield["map_objects"] = [{"id": 1, "name": "External spirit anchor", "x": 7, "y": 6,
        "size": "small", "material": "stone", "ac": 1, "hp": 1000, "blocks": blocks,
        "spiritual_profile": {"external_anchor": 1, "affectable": 1, "known_to": [ME]}}]
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(), allies=False, battlefield=battlefield)
    advance(svc, session, meta, ME)
    oid = next(iter(session.engine.state.objects))
    def choose(context):
        if context.reaction_source_id.endswith("object_designate"):
            return ("designate",)
        return chooser(context)
    for _ in range(3):
        service_commit(svc, session, meta, "Spirit-Touch Unarmed Strike", oid, choose=choose)
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            break
    session = reload(svc, session)
    assert object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME)
    hp = session.engine.state.objects[oid].current_hp
    service_commit(svc, session, meta, "Palm Across Emptiness: " + expression, oid, choose=chooser)
    session = reload(svc, session)
    obj = session.engine.state.objects[oid]
    assert obj.current_hp < hp
    assert object_subjects.records(obj, "handspan_subject", ME)[0]["boundary"] == "scene"
    if expression.startswith("Hold"):
        assert object_subjects.movement_held(obj)
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
        session = reload(svc, session)
        assert not object_subjects.movement_held(session.engine.state.objects[oid])
    elif expression.startswith("Draw"):
        assert session.engine.grid.distance_ft(obj.position, session.engine.state.actors[ME].position) == 5
    else:
        assert session.engine.grid.distance_ft(obj.position, session.engine.state.actors[ME].position) == 25


def test_reduced_object_draw_keeps_the_ten_foot_cap_when_no_capped_route_exists(tmp_path):
    """A successful object Strength save caps the pull at 10 feet.

    With a barrier that hides every legal square inside that cap, the object stays
    where it is -- the unlimited nearest fallback belongs only to a full Draw, so no
    destination beyond the save's cap is ever offered.
    """
    import json
    from combat.ext import object_subjects
    battlefield = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    battlefield["terrain_regions"] = [{"region_id": "wall", "terrain_type": "BLOCKED", "movement_cost": 0,
        "cells": [{"x": 8, "y": 4}, {"x": 8, "y": 6}, {"x": 9, "y": 5}]}]
    battlefield["map_objects"] = [{"id": 1, "name": "External spirit anchor", "x": 9, "y": 6,
        "size": "huge", "width_cells": 1, "length_cells": 1,
        "material": "stone", "ac": 1, "hp": 1000, "blocks": False,
        "spiritual_profile": {"external_anchor": 1, "affectable": 1, "known_to": [ME],
            "saving_throws": {"WIS": -100, "STR": 100}}}]
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(),
        allies=False, battlefield=battlefield, positions={ME: {"x": 9, "y": 7}, ENEMY: {"x": 16, "y": 1}})
    advance(svc, session, meta, ME)
    oid = next(iter(session.engine.state.objects))
    def choose(context):
        if context.reaction_source_id.endswith("object_designate"):
            return ("designate",)
        return chooser(context)
    for _ in range(3):
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            break
        service_commit(svc, session, meta, "Spirit-Touch Unarmed Strike", oid, choose=choose)
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            move = next(c for c in session.engine.legal_candidates() if c.destination is not None
                        and c.destination.x == 6 and c.destination.y == 4)
            service_commit(svc, session, meta, move.display_name, choose=chooser)
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
    assert object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME)
    proxy = object_subjects.geometry(session.engine, session.engine.state.objects[oid])
    assert session.engine._distance_actor_to_actor(session.engine.state.actors[ME], proxy) == 15
    before = session.engine.state.objects[oid].position
    offered = []
    def draw_choose(context):
        if context.reaction_source_id.endswith("object_contact_destination"):
            offered.append(list(context.extension_choice.option_ids))
        if context.reaction_source_id.endswith("damage_declaration"):
            return ("FORCE",)
        return chooser(context)
    events, _, _ = service_commit(svc, session, meta, "Palm Across Emptiness: Draw Into the Palm", oid, choose=draw_choose)
    session = reload(svc, session)
    str_saves = [e for e in events if e.event_type == "SAVE_ROLLED" and str(e.payload.get("reason", "")).endswith(":STR")]
    assert str_saves and str_saves[0].payload["success"]  # the reduced (successful) Strength save is what is tested
    assert offered == []  # no square inside the 10-foot cap, and the cap is not widened
    assert session.engine.state.objects[oid].position == before


@pytest.mark.parametrize("dims,rotation,expected", [((2, 2), 0, (2, 2)), ((3, 1), 0, (3, 1)), ((3, 1), 90, (1, 3))])
def test_object_geometry_honors_explicit_dimensions_and_rotation(tmp_path, dims, rotation, expected):
    import json
    from combat.ext import object_subjects
    battlefield = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    battlefield["map_objects"] = [{"id": 1, "name": "External spirit anchor", "x": 9, "y": 6,
        "size": "small", "width_cells": dims[0], "length_cells": dims[1], "rotation": rotation,
        "material": "stone", "ac": 1, "hp": 1000, "blocks": False,
        "spiritual_profile": {"external_anchor": 1, "affectable": 1, "known_to": [ME]}}]
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(),
        allies=False, battlefield=battlefield)
    advance(svc, session, meta, ME)
    oid = next(iter(session.engine.state.objects))
    obj = session.engine.state.objects[oid]
    footprint = session.engine._footprint(object_subjects.geometry(session.engine, obj))
    assert (footprint.width_cells, footprint.height_cells) == expected
    assert set(footprint.occupied_cells(obj.position)) == {
        (obj.position.x + x, obj.position.y + y) for y in range(expected[1]) for x in range(expected[0])}


def test_rectangular_object_cannot_squeeze_through_a_one_cell_gap(tmp_path):
    """Native sealed dimensions drive the pull, so a 2x2 anchor cannot cross a 1-cell gap."""
    import json
    from combat.ext import object_subjects
    battlefield = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    battlefield["terrain_regions"] = [{"region_id": "wall", "terrain_type": "BLOCKED", "movement_cost": 0,
        "cells": [{"x": 7, "y": y} for y in range(14) if y != 6]}]
    battlefield["map_objects"] = [{"id": 1, "name": "External spirit anchor", "x": 9, "y": 6,
        "size": "small", "width_cells": 2, "length_cells": 2,
        "material": "stone", "ac": 1, "hp": 1000, "blocks": False,
        "spiritual_profile": {"external_anchor": 1, "affectable": 1, "known_to": [ME]}}]
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(),
        allies=False, battlefield=battlefield, positions={ME: {"x": 8, "y": 6}, ENEMY: {"x": 16, "y": 1}})
    advance(svc, session, meta, ME)
    oid = next(iter(session.engine.state.objects))
    def choose(context):
        if context.reaction_source_id.endswith("object_designate"):
            return ("designate",)
        return chooser(context)
    for _ in range(3):
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            break
        service_commit(svc, session, meta, "Spirit-Touch Unarmed Strike", oid, choose=choose)
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            move = next(c for c in session.engine.legal_candidates() if c.destination is not None
                        and c.destination.x == 5 and c.destination.y == 6)
            service_commit(svc, session, meta, move.display_name, choose=chooser)
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
    assert object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME)
    service_commit(svc, session, meta, "Palm Across Emptiness: Draw Into the Palm", oid, choose=chooser)
    session = reload(svc, session)
    obj = session.engine.state.objects[oid]
    footprint = session.engine._footprint(object_subjects.geometry(session.engine, obj))
    assert (footprint.width_cells, footprint.height_cells) == (2, 2)
    assert all(x >= 8 for x, _ in footprint.occupied_cells(obj.position))  # never crossed the one-cell gap


@pytest.mark.parametrize("link_category", ["external_control", "disguise_body", "possession_entry", "incorporeal_passage"])
def test_object_expression_seam_is_exact_persisted_and_source_clocked(tmp_path, link_category):
    """General producer guard uses an explicit source-action fixture.

    This is not a claim that Mind Spike grants these expressions. The separate
    Guest Seat tests prove the production owner-rule acquisition/consumer.
    """
    import json
    from combat.ext import object_subjects
    fixture = copy.deepcopy(authority())
    fixture["mechanics"][MIND_SPIKE]["effects"] = [
        {"type": "object_source_expression", "id": identity, "name": name,
         "category": category, "ordinary": 1, "known_to": [ME]}
        for identity, name, category in [("link", "One named spiritual expression", link_category),
            ("passage", "One incorporeal passage", "incorporeal_passage")]]
    fixture["mechanics"][MIND_SPIKE]["effects"].append({"type": "source_protection", "applies_to": "target",
        "condition_id": "condition:typed.fixture_object_anchor", "name": "One bodily anchor",
        "category": "bodily", "scope": "forced_movement", "ordinary": 1, "duration": {"kind": "scene"}})
    other = compile_character(sheet([MIND_SPIKE], cl=6, dc=-40), actor_id=ENEMY, typed_authority=fixture)
    battlefield = json.loads((ROOT / "combat_gate1/generated/Battlefield.json").read_text())
    battlefield["map_objects"] = [{"id": 1, "name": "External spirit anchor", "x": 7, "y": 6,
        "size": "small", "material": "stone", "ac": 1, "hp": 1000, "blocks": False,
        "spiritual_profile": {"external_anchor": 1, "affectable": 1, "known_to": [ME, ENEMY]}}]
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=other, allies=False, battlefield=battlefield)
    oid = next(iter(session.engine.state.objects))
    advance(svc, session, meta, ENEMY)
    assert {tuple(c.target_ids) for c in session.engine.legal_candidates()
            if c.display_name == "Mind Spike"} == {(oid,)}
    service_commit(svc, session, meta, "Mind Spike", oid, choose=chooser)
    proxy = object_subjects.geometry(session.engine, session.engine.state.objects[oid])
    assert source_records.live(session.engine, proxy, scope="forced_movement")
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    def choose(context):
        if context.reaction_source_id.endswith("object_designate"):
            return ("designate",)
        if context.reaction_source_id.endswith("object_touch"):
            return context.extension_choice.option_ids[:1]
        return chooser(context)
    for _ in range(3):
        service_commit(svc, session, meta, "Spirit-Touch Unarmed Strike", oid, choose=choose)
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            break
    service_commit(svc, session, meta, "Palm Across Emptiness: Touch the Spirit, Not the Flesh", oid, choose=choose)
    session = reload(svc, session)
    obj = session.engine.state.objects[oid]
    assert not object_subjects.expression_active(obj, "link", ENEMY)
    assert object_subjects.expression_active(obj, "passage", ENEMY)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    assert not object_subjects.expression_active(session.engine.state.objects[oid], "link", ENEMY)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    assert object_subjects.expression_active(session.engine.state.objects[oid], "link", ENEMY)


@pytest.mark.parametrize("x,allowed", [(12, True), (13, False)])
def test_thirty_foot_range_boundary_after_native_mark(tmp_path, x, allowed):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(),
        allies=False, positions={ENEMY: {"x": x, "y": 6}})
    mark(svc, session, meta)
    session = reload(svc, session)
    assert any("Palm Across Emptiness" in c.display_name for c in session.engine.legal_candidates()) == allowed


def test_another_owner_cannot_borrow_saved_resonance_mark(tmp_path):
    """Only the owner whose action placed the mark may target it.

    A third creature hostile to both Palm owners is really marked by the first
    owner's Mind Spike; after a cold reload the mark's owner can target it while
    the other owner -- equally capable, in range and with line of effect -- cannot.
    Removing the owner qualification from Palm's mark check fails this test.
    """
    third = "actor:factory.palm_marked_bystander"
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed="A2GTRA3-EXACT", maximum_rounds=20,
        typed_bundles=(compile_sheet(IDS), compile_sheet(IDS, actor=ENEMY),
            compile_character(sheet([MIND_SPIKE], cl=6, dc=-40), actor_id=third, typed_authority=authority())),
        roster_setup={"primary_actor_ids": [ME, ENEMY, third],
            "team_by_actor": {ME: "team:a", ENEMY: "team:c", third: "team:b"},
            "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 6, "y": 8}, third: {"x": 9, "y": 6}}})
    meta = {"participant_control_modes": {a: "MANUAL" for a in (ME, ENEMY, third)}}
    advance(svc, session, meta, ME)
    service_commit(svc, session, meta, "Mind Spike", third, choose=chooser)
    session = reload(svc, session)
    marked = session.engine.state.actors[third]
    assert typed_executor.bears_mark(marked, ME, "Resonance")
    assert not typed_executor.bears_mark(marked, ENEMY, "Resonance")

    def palms(actor):
        return [c for c in session.engine.legal_candidates()
                if "Palm Across Emptiness" in c.display_name and third in (c.target_ids or ())]

    # Every other target requirement holds for the non-owner: hostile, in range, seen, owns Palm.
    enemy_actor = session.engine.state.actors[ENEMY]
    assert enemy_actor.team_id != marked.team_id
    assert any(a.owner_id == ENEMY and "Palm Across Emptiness" in a.display_name
               for a in session.engine.action_catalog.values())
    assert session.engine._distance_actor_to_actor(enemy_actor, marked) <= 30
    assert session.engine._line_of_sight_actor_to_actor(enemy_actor, marked)

    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ENEMY)
    assert session.engine.state.current_actor_id == ENEMY
    assert palms(ENEMY) == []  # the other owner cannot borrow the saved mark
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    assert palms(ME)  # its owner still can


@pytest.mark.parametrize("category,cl", [("domain_contact_denial", 6), ("separation", 11)])
def test_scoped_contact_producer_suppresses_relationship_without_erasing_it(tmp_path, category, cl):
    """Source-protection primitive guard; fixture explicitly assigns the scope."""
    fixture = copy.deepcopy(authority())
    fixture["mechanics"][MIND_SPIKE]["target"] = {"text": "Self"}
    fixture["mechanics"][MIND_SPIKE]["effects"] = [{"type": "source_protection", "applies_to": "self",
        "condition_id": "condition:typed.fixture_contact_boundary", "name": "A source that denies spiritual contact",
        "category": category, "scope": "spiritual_contact", "ordinary": 0,
        "duration": {"kind": "until_start_of_your_next_turn"}}]
    other = compile_character(sheet([MIND_SPIKE], cl=cl, dc=-40), actor_id=ENEMY, typed_authority=fixture)
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=other, allies=False)
    mark(svc, session, meta)
    service_commit(svc, session, meta, "Palm Across Emptiness: Hold at the Last Inch", ENEMY, choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ENEMY)
    service_commit(svc, session, meta, "Mind Spike", choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    subject = next(c for c in target.conditions.values() if c.condition_id == SUBJECT)
    assert subject.data["contact_status"] == "CONTACT_DENIED"
    assert not any("Palm Across Emptiness" in c.display_name for c in session.engine.legal_candidates())
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    session = reload(svc, session)
    subject = next(c for c in session.engine.state.actors[ENEMY].conditions.values() if c.condition_id == SUBJECT)
    assert subject.data["contact_status"] == "ACTIVE"
    assert any("Palm Across Emptiness" in c.display_name for c in session.engine.legal_candidates())


def test_native_legion_asset_hold_blocks_only_its_source_movement_until_expiry(tmp_path):
    from combat.ext import object_subjects
    ancestral = "tianxia.tradition.spirit.ancestral_channeler.feature."
    ids = [*IDS, ancestral + "council_of_the_remembered", ancestral + "ancestral_legion"]
    svc, session, meta = table(tmp_path, ids, "MANUAL", mine=compile_sheet(ids, cl=14, dc=18), enemy=target_bundle(), allies=False)
    advance(svc, session, meta, ME)
    destinations = iter(["cell:7,6,0", "cell:7,7,0", "cell:6,7,0"])
    def place(context):
        if context.reaction_source_id.endswith("spirit_asset.space") and "place" in context.choice_trigger["prompt"]:
            cell = next(destinations)
            assert cell in context.extension_choice.option_ids
            return (cell,)
        return chooser(context)
    service_commit(svc, session, meta, "Ancestral Legion", choose=place)
    oid = min(session.engine.state.objects)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    def designate_object(context):
        if context.reaction_source_id.endswith("object_designate"):
            return ("designate",)
        return chooser(context)
    for _ in range(3):
        service_commit(svc, session, meta, "Spirit-Touch Unarmed Strike", oid, choose=designate_object)
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
        if object_subjects.records(session.engine.state.objects[oid], "handspan_subject", ME):
            break
    service_commit(svc, session, meta, "Palm Across Emptiness: Hold at the Last Inch", oid, choose=chooser)
    session = reload(svc, session)
    obj = session.engine.state.objects[oid]
    assert not obj.destroyed and object_subjects.movement_held(obj)
    name = obj.component["name"]
    prompts = []
    def observe(context):
        if context.reaction_source_id.endswith("spirit_asset.space"):
            prompts.append(context.choice_trigger["prompt"])
        return chooser(context)
    service_commit(svc, session, meta, "End turn", choose=observe)
    assert prompts and all(name not in prompt for prompt in prompts)
    advance(svc, session, meta, ME)
    session = reload(svc, session)
    assert not object_subjects.movement_held(session.engine.state.objects[oid])
    prompts.clear()
    service_commit(svc, session, meta, "End turn", choose=observe)
    assert any(name in prompt for prompt in prompts)
    reload(svc, session)


def test_failed_save_designates_even_when_palm_damage_defeats_target(tmp_path):
    document = sheet([MIND_SPIKE], cl=6, dc=-40)
    document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 21
    third = "actor:factory.palm_other_enemy"
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed="A2GTRA3-EXACT", maximum_rounds=20,
        typed_bundles=(compile_sheet(IDS), compile_character(document, actor_id=ENEMY, typed_authority=authority()),
            compile_sheet([MIND_SPIKE], actor=third)),
        roster_setup={"primary_actor_ids": [ME, ENEMY, third], "team_by_actor": {ME: "team:a", ENEMY: "team:b", third: "team:b"},
            "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 10, "y": 5}, third: {"x": 16, "y": 1}}})
    meta = {"participant_control_modes": {a: "MANUAL" for a in (ME, ENEMY, third)}}
    mark(svc, session, meta)
    assert session.engine.state.actors[ENEMY].active
    service_commit(svc, session, meta, "Palm Across Emptiness: Hold at the Last Inch", ENEMY, choose=chooser)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    assert not target.active and session.engine.state.terminal_result is None
    assert any(c.condition_id == SUBJECT and c.expires_on == "UNTIL_REMOVED" for c in target.conditions.values())


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("expression", ["Draw Into the Palm", "Cast Beyond Contact", "Hold at the Last Inch"])
def test_native_palm_declaration_payment_and_reload(tmp_path, control, expression):
    svc, session, meta = table(tmp_path, IDS, control, mine=compile_sheet(IDS), enemy=target_bundle(), allies=False)
    mark(svc, session, meta)
    session = reload(svc, session)
    meta["participant_control_modes"][ME] = control
    before = session.engine.state.actors[ME].resources["resource:core.resonance"]
    prompts = []
    def choose(context):
        if context.reaction_source_id.endswith("damage_declaration"):
            prompts.append(context)
            assert set(context.extension_choice.option_ids) == {"PSYCHIC", "FORCE"}
            # The preview pauses before the real Wisdom save.
            assert "before its saving throw" in context.choice_trigger["prompt"]
            return ("FORCE",)
        return chooser(context)
    events, _, _ = service_commit(svc, session, meta, "Palm Across Emptiness: " + expression, ENEMY, choose=choose)
    session = reload(svc, session)
    actor, victim = (session.engine.state.actors[a] for a in (ME, ENEMY))
    assert actor.resources["resource:core.resonance"] == before - 5
    assert not actor.action_available
    held = next(c for c in victim.conditions.values() if c.condition_id == SUBJECT and c.source_actor_id == ME)
    assert held.expires_on == "UNTIL_REMOVED" and held.data["origin_feature"] == PALM
    assert held.data["source_cl"] == 10
    assert bool(prompts) == (control == "MANUAL")
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert damage and ("FORCE" if control == "MANUAL" else "PSYCHIC") in str([e.payload for e in damage])
    distance = session.engine._distance_actor_to_actor(actor, victim)
    if expression.startswith("Draw"):
        assert distance == 5
    elif expression.startswith("Cast"):
        assert distance == 40
    else:
        assert session.engine._effective_speed(victim) == 0
        service_commit(svc, session, meta, "End turn", choose=chooser)
        advance(svc, session, meta, ME)
        session = reload(svc, session)
        assert session.engine._effective_speed(session.engine.state.actors[ENEMY]) == 30


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
def test_touch_suppresses_native_guest_speed_and_restores_exact_instance(tmp_path, control):
    other = target_bundle(record())
    svc, session, meta = table(tmp_path, IDS, control, mine=compile_sheet(IDS), enemy=other, allies=False)
    guest(svc, session, meta)
    mark(svc, session, meta)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    original = next(c for c in target.conditions.values() if c.condition_id == SEAT).model_dump(mode="json")
    assert session.engine._effective_speed(target) == 40
    meta["participant_control_modes"][ME] = control
    events, _, _ = service_commit(svc, session, meta, "Palm Across Emptiness: Touch the Spirit, Not the Flesh", ENEMY, choose=chooser)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    assert not any(c.condition_id == SEAT for c in target.conditions.values())
    assert session.engine._effective_speed(target) == 30
    assert not [e for e in events if e.event_type == "CHECK_ROLLED"]  # strictly lower ordinary authority
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    assert not any(c.condition_id == SEAT for c in session.engine.state.actors[ENEMY].conditions.values())
    service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    target = session.engine.state.actors[ENEMY]
    restored = next(c for c in target.conditions.values() if c.condition_id == SEAT)
    assert restored.instance_id == original["instance_id"]
    assert restored.source_actor_id == original["source_actor_id"]
    assert restored.data == original["data"]
    assert session.engine._effective_speed(target) == 40


@pytest.mark.parametrize("rec", [None, record(ordinary=0), record(known_to=[]), record(data_match={"seat": "Healing Guest"})])
def test_touch_unknown_protected_wrong_instance_remains_unavailable(tmp_path, rec):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(rec), allies=False)
    guest(svc, session, meta)
    mark(svc, session, meta)
    session = reload(svc, session)
    assert not any("Touch the Spirit, Not the Flesh" in c.display_name for c in session.engine.legal_candidates())
    assert session.engine._effective_speed(session.engine.state.actors[ENEMY]) == 40


@pytest.mark.parametrize("source_cl,dc,expected", [(10, -40, True), (11, 100, False)])
def test_touch_equal_higher_authority_uses_cultivation_check(tmp_path, source_cl, dc, expected):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS),
        enemy=target_bundle(record(source_cl=source_cl), cl=source_cl, dc=dc), allies=False)
    guest(svc, session, meta)
    mark(svc, session, meta)
    events, _, _ = service_commit(svc, session, meta, "Palm Across Emptiness: Touch the Spirit, Not the Flesh", ENEMY, choose=chooser)
    session = reload(svc, session)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and "Touch" in str(e.payload)]
    assert len(checks) == 1 and checks[0].payload["success"] == expected
    assert bool([c for c in session.engine.state.actors[ENEMY].conditions.values() if c.condition_id == SEAT]) != expected


@pytest.mark.parametrize("distance", [0, 5, 10, 15, 20])
def test_cast_keeps_every_legal_distance_player_owned(tmp_path, distance):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(), allies=False)
    mark(svc, session, meta)
    offered = []
    def choose(context):
        if context.reaction_source_id.endswith("cast_destination"):
            options = context.extension_choice.option_ids
            for n in range(5):
                assert f"cell:{10+n},6" in options
            offered.append(True)
            return (f"cell:{10+distance//5},6",)
        return chooser(context)
    service_commit(svc, session, meta, "Palm Across Emptiness: Cast Beyond Contact", ENEMY, choose=choose)
    session = reload(svc, session)
    assert offered
    assert session.engine.state.actors[ENEMY].position.x == 10 + distance // 5


def test_source_acquisition_rejects_unowned_or_incomplete_authority():
    unowned = sheet([MIND_SPIKE])
    with pytest.raises(ValueError, match="acquired"):
        source_records.acquire(unowned, record())
    owned = sheet([TRANCE])
    for change in ({"source_cl": None}, {"ordinary": True}, {"scope": "anything"}):
        with pytest.raises(ValueError):
            source_records.acquire(owned, record(**change))
    original = copy.deepcopy(owned)
    assert source_records.acquire(owned, record())["combat_source_records"]
    assert owned == original


def test_replacing_suppressed_guest_cannot_restore_a_second_seat(tmp_path):
    svc, session, meta = table(tmp_path, IDS, "MANUAL", mine=compile_sheet(IDS), enemy=target_bundle(record()), allies=False)
    guest(svc, session, meta)
    mark(svc, session, meta)
    service_commit(svc, session, meta, "Palm Across Emptiness: Touch the Spirit, Not the Flesh", ENEMY, choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ENEMY)
    movement = next(c for c in session.engine.legal_candidates() if c.destination is not None
                    and c.destination.x == 10 and c.destination.y == 6)
    service_commit(svc, session, meta, movement.display_name, choose=chooser)
    service_commit(svc, session, meta, "Possession Trance: Guardian Guest", choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    seats = [c for c in session.engine.state.actors[ENEMY].conditions.values() if c.condition_id == SEAT]
    assert len(seats) == 1 and seats[0].data["seat"] == "Guardian Guest"


def test_suppressed_scene_guest_restores_after_nonlethal_defeat(tmp_path):
    document = source_records.acquire(sheet([MIND_SPIKE, DANCE, TRANCE], cl=6, dc=-40), record())
    document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 31
    third = "actor:factory.palm_other_enemy"
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed="A2GTRA3-EXACT", maximum_rounds=20,
        typed_bundles=(compile_sheet(IDS), compile_character(document, actor_id=ENEMY, typed_authority=authority()),
            compile_sheet([MIND_SPIKE], actor=third)),
        roster_setup={"primary_actor_ids": [ME, ENEMY, third], "team_by_actor": {ME: "team:a", ENEMY: "team:b", third: "team:b"},
            "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 10, "y": 6}, third: {"x": 16, "y": 1}}})
    meta = {"participant_control_modes": {a: "MANUAL" for a in (ME, ENEMY, third)}}
    guest(svc, session, meta)
    mark(svc, session, meta)
    original = next(c.instance_id for c in session.engine.state.actors[ENEMY].conditions.values() if c.condition_id == SEAT)
    service_commit(svc, session, meta, "Palm Across Emptiness: Touch the Spirit, Not the Flesh", ENEMY, choose=chooser)
    service_commit(svc, session, meta, "End turn", choose=chooser)
    advance(svc, session, meta, ME)
    if session.engine.state.actors[ENEMY].active:
        service_commit(svc, session, meta, "Mind Spike", ENEMY, choose=chooser)
    assert not session.engine.state.actors[ENEMY].active
    service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    assert session.engine.state.terminal_result is None
    assert session.engine.state.actors[ENEMY].conditions[original].data["seat"] == "Road Guest"


def test_scene_end_retires_a_suppressed_scene_expression_without_restoring_it(tmp_path):
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed="A2GTRA3-EXACT", maximum_rounds=4,
        typed_bundles=(compile_sheet(IDS), target_bundle(record())),
        roster_setup={"primary_actor_ids": [ME, ENEMY], "team_by_actor": {ME: "team:a", ENEMY: "team:b"},
            "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 10, "y": 6}}})
    meta = {"participant_control_modes": {ME: "MANUAL", ENEMY: "MANUAL"}}
    guest(svc, session, meta)
    mark(svc, session, meta)
    service_commit(svc, session, meta, "Palm Across Emptiness: Touch the Spirit, Not the Flesh", ENEMY, choose=chooser)
    assert any((c.data.get("condition") or {}).get("condition_id") == SEAT for c in session.engine.state.actors[ENEMY].conditions.values())
    for _ in range(8):
        if session.engine.state.terminal_result is not None:
            break
        service_commit(svc, session, meta, "End turn", choose=chooser)
    session = reload(svc, session)
    assert session.engine.state.terminal_result is not None
    assert not any(c.condition_id == SEAT or (c.data.get("condition") or {}).get("condition_id") == SEAT
                   for c in session.engine.state.actors[ENEMY].conditions.values())


def test_persisted_owner_admission_load_compile_commit_and_cold_replay(tmp_path):
    bare = sheet([MIND_SPIKE, LI + "the_last_inch"], cl=10, dc=40)
    access = {"kind": "restricted_spirit_tradition", "basis": "contact_boundary_teacher", "record_id": "owner:teacher-admission"}
    store = SourceAcquisitionStore(tmp_path / "owner-admission")
    admitted = store.acquire(bare, PALM, actor_id=ME, occurrence_id="owner:palm:10", access_record=access)
    assert "earned_feature_occurrences" not in admitted["path_and_subpath"]
    fresh = SourceAcquisitionStore(tmp_path / "owner-admission").load_into(bare, actor_id=ME)
    assert fresh == admitted and bare.get("combat_acquisitions") is None
    with pytest.raises(ValueError, match="another creature"):
        compile_character(fresh, actor_id=ENEMY, typed_authority=authority())
    stale = copy.deepcopy(fresh)
    stale["combat_acquisitions"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="changed"):
        compile_character(stale, actor_id=ME, typed_authority=authority())
    mine = compile_character(fresh, actor_id=ME, typed_authority=authority())
    svc, session, meta = table(tmp_path / "fight", IDS, "MANUAL", mine=mine, enemy=target_bundle(), allies=False)
    mark(svc, session, meta)
    service_commit(svc, session, meta, "Palm Across Emptiness: Hold at the Last Inch", ENEMY, choose=chooser)
    session = reload(svc, session)
    saved = next(b for b in session.engine.typed_bundle_documents if b["actor_id"] == ME)
    assert saved["source_acquisitions"][0]["access_record"] == access
