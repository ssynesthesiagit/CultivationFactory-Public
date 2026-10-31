"""Areas that are laid down at the point the user aims at, rather than running out from the user (hunt 68).

Found 2026-10-02: a printed Range longer than a line's or cone's own length is a *placement* range, not a length.
Earthbind Line reads "Range: 60 feet, subject to Path restrictions" with "Area: 20-foot line on a solid or earthen
surface", but the table compiled the reach as the line's own 20 feet, and even with the longer reach the shape was
still measured from the caster: a creature at the chosen point was outside the area and one standing next to the
caster was inside it, so a distant attack hit the wrong creature or was not offered at all.

These tests run the shipped abilities on a real compiled character, at the level the bug showed -- the table's
candidates, the AI's scoring, the preview a player sees, and a persistent line across a commit and reload.
``tests/test_area_shapes.py`` covers the geometry itself and which typed rows the rule moves.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.tabletop_service import TabletopService
from combat.typed_executor import _area_targets, area_cells
from tests.h1_support import ME, bundle, ready
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
RESONANT_SHATTER = "TAL_SOUND_RESONANT_SHATTER"   # 30-foot line, Range 90 feet: a save on the creatures it covers
EARTHBIND_LINE = "TAL_EARTH_EARTHBIND_LINE"       # 20-foot line, Range 60 feet: leaves a line of ground behind
ALLY = "actor:factory.placed.ally"


def _fight(mids, seed):
    """The compiled character owning ``mids``, on their turn, with two hostiles to place at either end of a line."""
    bundles = [bundle(mids)]
    engine = Gate4ControllerEngine(
        ROOT, match_seed=seed, typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [ME, AN, LEE], "team_by_actor": {ME: "team:a", AN: "team:b", LEE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, LEE: {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    ready(engine)
    return engine


def _action(engine, display_name: str):
    return next(action for action in engine.action_catalog.values() if action.display_name.startswith(display_name))


def _foes(engine):
    actor = engine.state.actors[ME]
    return [other for other in engine.state.actors.values() if other.team_id != actor.team_id]


def _placed_area(action) -> dict:
    return (action.parameters.get("typed") or {}).get("area") or {}


# ------------------------------------------------------------------ the compiled action
def test_a_line_whose_printed_range_exceeds_its_length_is_aimed_at_that_range():
    """Resonant Shatter: "Range: 90 feet" for a 30-foot line. The point the user picks is up to 90 feet away."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-COMPILE")
    action = _action(engine, "Resonant Shatter")
    assert action.target_kind == "CELL" and action.range_ft == 90
    assert _placed_area(action) == {"shape": "line", "size_ft": 30, "centered_on_self": False, "placed": True,
                                   "recipients": "all", "exclude_self": False, "include_self": True}


def test_earthbind_line_keeps_its_20_foot_length_while_reaching_60_feet():
    engine = _fight(EARTHBIND_LINE, seed="PLACED-EARTHBIND")
    action = _action(engine, "Earthbind Line")
    assert action.range_ft == 60
    assert _placed_area(action)["size_ft"] == 20 and _placed_area(action)["placed"] is True


# ------------------------------------------------------------------ the table resolves the placed shape
def test_a_placed_line_hits_the_creature_at_the_chosen_point_not_the_one_beside_its_caster():
    """The bug: a creature standing next to the caster was inside a line aimed 90 feet away, and the creature at
    the chosen point was outside it."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-RESOLVE")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    foes = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    assert len(foes) >= 2
    far, near = foes[0], foes[1]
    far.position, near.position = Position(x=17, y=6), Position(x=5, y=6)   # 70 ft and 10 ft from the caster
    area = _placed_area(_action(engine, "Resonant Shatter"))
    aim = Position(x=15, y=6)   # 60 ft away, far outside the line's own 30-foot length

    covered = {other.entity_id for other in _area_targets(engine, actor, aim, area)}
    assert far.entity_id in covered, "the creature at the chosen point must be inside the line"
    assert near.entity_id not in covered, "a creature beside the caster is not inside a line placed 90 ft away"


def test_the_same_line_aimed_close_by_does_reach_the_nearby_creature():
    """The control: the shape follows the point it is aimed at, so aiming next to the caster covers that square."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-RESOLVE-NEAR")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    foes = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    near, far = foes[0], foes[1]
    near.position, far.position = Position(x=6, y=6), Position(x=17, y=6)
    area = _placed_area(_action(engine, "Resonant Shatter"))

    covered = {other.entity_id for other in _area_targets(engine, actor, Position(x=6, y=6), area)}
    assert near.entity_id in covered and far.entity_id not in covered


def test_a_placed_cone_widens_from_the_chosen_point():
    """A cone is laid down at the aim point too: it is widest at its far end, measured from where it starts."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-CONE")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    foes = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    wide, narrow = foes[0], foes[1]
    wide.position, narrow.position = Position(x=15, y=8), Position(x=15, y=10)  # 20 ft along: 10 ft half-width
    area = {**_placed_area(_action(engine, "Resonant Shatter")), "shape": "cone", "size_ft": 30}

    covered = {other.entity_id for other in _area_targets(engine, actor, Position(x=11, y=6), area)}
    assert wide.entity_id in covered and narrow.entity_id not in covered


def test_a_self_origin_cone_still_starts_at_its_caster():
    """The control the compiler keeps: a cone the authority marks as coming from its user is unaffected."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-SELF-ORIGIN")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    foes = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    close, far = foes[0], foes[1]
    close.position, far.position = Position(x=5, y=7), Position(x=11, y=6)
    area = {"shape": "cone", "size_ft": 30}  # no "placed": a cone that runs out from its user

    covered = {other.entity_id for other in _area_targets(engine, actor, Position(x=11, y=6), area)}
    assert close.entity_id in covered, "a self-origin cone reaches the creature near its user"
    assert far.entity_id not in covered, "and does not reach 90 feet out"


# ------------------------------------------------------------------ the AI offers and scores the distant square
def test_the_ai_counts_the_enemy_in_the_placed_line_not_the_one_beside_its_caster():
    """The AI's damage estimate has to describe the line the table will actually draw, or it picks the wrong square."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-AI")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    far, near = _foes(engine)[:2]
    far.position, near.position = Position(x=17, y=6), Position(x=5, y=6)
    area = _placed_area(_action(engine, "Resonant Shatter"))
    ready(engine)

    candidates = {c.destination: c for c in engine.legal_candidates() if c.display_name.startswith("Resonant Shatter")}
    far_aim = Position(x=15, y=6)      # 60 ft out, where the far creature stands inside the line
    assert far_aim in candidates, "a 90-foot placement range must offer a square 60 feet away"
    caught = {other.entity_id for other in _area_targets(engine, actor, far_aim, area)}
    assert far.entity_id in caught and near.entity_id not in caught
    assert (candidates[far_aim].metadata or {})["hostiles_in_area"] == len(caught) == 1
    # Aiming beside the caster is still legal, and catches the creature next to them rather than the distant one.
    near_aim = Position(x=5, y=6)
    assert near_aim in candidates
    assert (candidates[near_aim].metadata or {})["hostiles_in_area"] == 1


def test_the_ai_and_the_table_agree_on_which_enemies_a_placed_line_catches():
    """One geometry, so the AI's damage estimate and the resolved effect can never disagree about who is caught."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-AI-AGREE")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    foes = [other for other in engine.state.actors.values() if other.team_id != actor.team_id]
    foes[0].position = Position(x=17, y=6)
    area = _placed_area(_action(engine, "Resonant Shatter"))
    ready(engine)
    for candidate in engine.legal_candidates():
        if not candidate.display_name.startswith("Resonant Shatter") or candidate.destination is None:
            continue
        counted = int((candidate.metadata or {}).get("hostiles_in_area") or 0)
        actual = sum(1 for other in _area_targets(engine, actor, candidate.destination, area)
                     if other.team_id != actor.team_id)
        assert counted == actual, f"the AI scored {counted} at {candidate.destination}, the engine catches {actual}"


# ------------------------------------------------------------------ the preview the player sees
def test_the_table_preview_draws_the_placed_line_where_it_will_land():
    """The squares the table highlights are the ones the engine will use, so the player sees the real placement."""
    engine = _fight(RESONANT_SHATTER, seed="PLACED-PREVIEW")
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6)
    action = _action(engine, "Resonant Shatter")
    aim = Position(x=15, y=6)   # 60 ft from the caster
    menu = {"actor_id": ME, "actions": [{"source_definition_id": action.source_definition_id,
                                         "options": [{"area": _placed_area(action),
                                                      "destination": {"x": aim.x, "y": aim.y}}]}]}
    TabletopService._round_areas(menu, engine)
    preview = {(cell["x"], cell["y"]) for cell in menu["actions"][0]["options"][0]["area"]["affected_cells"]}
    resolved = {(cell.x, cell.y) for cell in area_cells(engine, actor.position, aim, _placed_area(action))}

    assert preview == resolved and preview, "the preview must not be empty"
    assert min(preview)[0] == aim.x, "the placed line starts at the chosen point, not at the caster"
    assert max(cell[0] for cell in preview) > aim.x, "and runs on away from the caster"
    assert not any(cell[0] < 15 for cell in preview), "and does not cover the squares beside the caster"


# ------------------------------------------------------------------ the service, on the real board
CASTER = "actor:factory.left"
FAR = "actor:factory.right"
NEAR = "actor:factory.foe2"
ORIGIN = Position(x=2, y=5)      # the west end of row 5, the one row of the shipped board with no obstacles
AIM = Position(x=11, y=5)        # 45 ft away: well past Resonant Shatter's own 30-foot length, room for the
NEAR_SQUARE = Position(x=2, y=3) # whole shape to run east to x=17, and clear line of sight to AIM


def _service(tmp_path, talent, sphere, *, foes, seed):
    """A real fight on the shipped 20x14 board: the caster and ``foes`` opponents, all under manual control."""
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": [talent]}}
    for project in ("left", "right", "foe2"):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    from combat.gate5_service import CombatService

    service = CombatService(ROOT, tmp_path)
    actor_ids = [CASTER, FAR, NEAR][:1 + foes]
    match_id = service.create_factory_match(
        project_ids=["left"], opponent_actor_ids=actor_ids[1:], match_seed=seed,
        control_modes={actor: "MANUAL" for actor in actor_ids},
    )["match_id"]
    return service, match_id, service._load_session(match_id)


def _placed_at(session, destinations):
    """Put the caster and its foes on named squares and hand the caster the turn, then return the live actors."""
    actors = session.engine.state.actors
    for actor_id, position in destinations.items():
        actors[actor_id].position = position
    caster = actors[CASTER]
    session.engine.state.current_slot_index = session.engine.state.initiative_order.index(CASTER)
    session.engine.state.current_actor_id = CASTER  # every fighter here is built from the same sheet, so the
    caster.action_available, caster.bonus_action_available, caster.reaction_available = True, True, True
    return actors  # decision must be read as the caster's, never an identical rival's


def _offered(context, display_name, destination):
    """The table's choice for ``display_name`` aimed at exactly ``destination``."""
    return next((c for c in context["legal_candidates"]
                 if c.get("actor_id") == CASTER and c["display_name"].startswith(display_name) and c.get("destination")
                 and (c["destination"]["x"], c["destination"]["y"]) == (destination.x, destination.y)), None)


def _earthbind_match(tmp_path, seed):
    return _service(tmp_path, EARTHBIND_LINE, "tianxia.sphere.earth", foes=1, seed=seed)


def test_the_table_does_not_offer_a_line_aimed_at_the_caster_own_square(tmp_path):
    """The one case the printed rules leave open. A line is a path, so it needs a direction to run in, and the
    caster's own square gives none -- with no printed rule for which way a line under your own feet should run,
    that aim is not a choice, so the action is never spent on it."""
    service, match_id, session = _earthbind_match(tmp_path, "PLACED-DIRECTION")
    actors = _placed_at(session, {CASTER: ORIGIN})
    context = service.decision(match_id, session=session)["context"]
    caster = actors[CASTER]
    origin = (caster.position.x, caster.position.y)
    offered = {(c["destination"]["x"], c["destination"]["y"]) for c in context["legal_candidates"]
               if c.get("actor_id") == CASTER and c["display_name"].startswith("Earthbind Line") and c.get("destination")}

    assert origin not in offered, "a line has no direction on the square its own user stands on"
    # Only that square is withheld: a line placed one square away is still offered, and a preview of it is drawn.
    beside = [c for c in context["legal_candidates"]
              if c.get("actor_id") == CASTER and c["display_name"].startswith("Earthbind Line") and c.get("destination")
              and (c["destination"]["x"], c["destination"]["y"]) in {(origin[0] + 1, origin[1]), (origin[0], origin[1] + 1)}]
    assert len(beside) == 2, "both neighbouring squares are legal placements, so only the directionless aim is refused"


def test_spending_an_action_on_a_directionless_aim_pays_nothing(tmp_path):
    """Submit the actual coincident candidate, not another square's mismatched identity."""
    from combat.gate2_engine import Gate2Engine
    from combat.gate5_service import CombatService, CombatServiceError

    service, match_id, session = _earthbind_match(tmp_path, "PLACED-DIRECTION-COST")
    engine = session.engine
    _placed_at(session, {CASTER: ORIGIN})
    # Persist the arranged turn so reload is compared to this state, not the initial roster.
    session.mechanical.explicit_snapshot()
    context = service.decision(match_id, session=session)["context"]
    # Gate2 issues the pre-filter candidate. Gate4's plug-in must refuse this exact identity.
    coincident = next(c for c in Gate2Engine.legal_candidates(engine)
                      if c.actor_id == CASTER and c.display_name.startswith("Earthbind Line")
                      and c.destination == ORIGIN)
    before = engine.state.model_dump(mode="json")
    assert "resource:core.qi" in before["actors"][CASTER]["resources"]
    assert before["actors"][CASTER]["action_available"] is True

    with pytest.raises(CombatServiceError) as rejected:
        service.submit_intent(match_id, {
            "intent_id": "placed-own-square", "decision_id": context["decision_id"],
            "candidate_id": coincident.candidate_id, "state_version": context["state_version"],
            "actor_id": CASTER, "target_ids": list(coincident.target_ids),
            "destination": coincident.destination.model_dump(mode="json"),
        }, [], None, session=session)
    assert rejected.value.diagnostic.code == "COMBAT_DECISION_STALE"
    assert rejected.value.status_code == 409

    # Full state equality includes Stamina, CP and all resources, action/bonus/reaction,
    # turn owner, slot, round, event/state versions, positions and absence of zones.
    assert engine.state.model_dump(mode="json") == before
    after = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert after.engine.state.model_dump(mode="json") == before


@pytest.mark.parametrize("shape", ["line", "cone"])
@pytest.mark.parametrize("marker", [None, False])
def test_unplaced_older_areas_keep_their_own_square_candidate(tmp_path, shape, marker):
    """An absent/false placement opt-in preserves the older CELL terrain menu."""
    service, match_id, session = _earthbind_match(tmp_path, "UNPLACED-CONTROL")
    _placed_at(session, {CASTER: ORIGIN})
    area = _placed_area(_action(session.engine, "Earthbind Line"))
    area["shape"] = shape
    if marker is None:
        area.pop("placed")
    else:
        area["placed"] = marker
    context = service.decision(match_id, session=session)["context"]
    assert _offered(context, "Earthbind Line", ORIGIN) is not None


def test_a_placed_line_hits_the_distant_creature_and_not_the_nearby_one_through_the_service(tmp_path):
    """The bug at table level, as a real cast: the creature standing in the line 45 feet away is hit, the one
    beside the caster is not, and the fight keeps both outcomes across a commit and a reload."""
    from combat.gate5_service import CombatService

    service, match_id, session = _service(tmp_path, RESONANT_SHATTER, "tianxia.sphere.sound", foes=2, seed="PLACED-DAMAGE")
    actors = _placed_at(session, {CASTER: ORIGIN, FAR: Position(x=14, y=5), NEAR: NEAR_SQUARE})
    context = service.decision(match_id, session=session)["context"]
    candidate = _offered(context, "Resonant Shatter", AIM)
    assert candidate is not None, "a point 45 feet out must be a legal placement for a 90-foot range"
    # The whole shape, spelled out: it starts at the chosen point and runs 30 feet on away from the caster.
    expected = {(x, 5) for x in range(AIM.x, AIM.x + 7)}
    assert (actors[FAR].position.x, actors[FAR].position.y) in expected
    assert (actors[NEAR].position.x, actors[NEAR].position.y) not in expected

    service.submit_intent(match_id, {
        "intent_id": "placed-shatter", "decision_id": context["decision_id"],
        "candidate_id": candidate["candidate_id"], "state_version": context["state_version"],
        "actor_id": CASTER, "target_ids": list(candidate["target_ids"]),
        "destination": {"x": AIM.x, "y": AIM.y},
    }, [], None, session=session)

    after = CombatService(ROOT, tmp_path)._load_session(match_id).engine.state.actors
    assert after[FAR].current_hp < 60, "the creature standing in the line 45 feet away is hit by it"
    assert after[NEAR].current_hp == 60, "the creature beside the caster is not, even though it is nearer"
    marked = lambda actor: any("resonance" in c.condition_id for c in actor.conditions.values())
    assert marked(after[FAR]), "the failed save's mark lands on the creature in the line"
    assert not marked(after[NEAR]), "and on nothing else"


def test_a_persistent_line_is_laid_where_aimed_and_survives_a_commit_and_reload(tmp_path):
    """Earthbind Line leaves its line of ground behind. The squares must be exactly the placed ones -- the whole
    20-foot shape at a fixed interior point, not a truncated one -- and the same squares after the fight is
    written to disk and read back (checklist 7)."""
    from combat.gate5_service import CombatService

    service, match_id, session = _earthbind_match(tmp_path, "PLACED-ZONE")
    actors = _placed_at(session, {CASTER: ORIGIN})
    context = service.decision(match_id, session=session)["context"]
    origin = actors[CASTER].position
    candidate = _offered(context, "Earthbind Line", AIM)
    assert candidate is not None, "Earthbind Line must be offered 45 feet out"

    service.submit_intent(match_id, {
        "intent_id": "placed-earthbind", "decision_id": context["decision_id"],
        "candidate_id": candidate["candidate_id"], "state_version": context["state_version"],
        "actor_id": CASTER, "target_ids": list(candidate["target_ids"]),
        "destination": {"x": AIM.x, "y": AIM.y},
    }, [], None, session=session)

    expected = {(x, 5) for x in range(AIM.x, AIM.x + 5)}
    live_zone = next(row for row in session.engine.state.zones.values()
                     if row.source_definition_id == candidate["source_definition_id"])
    assert {(cell.x, cell.y) for cell in live_zone.affected_cells} == expected
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    zone = next((row for row in reloaded.engine.state.zones.values()
                 if row.source_definition_id == candidate["source_definition_id"]), None)
    assert zone is not None, "Earthbind Line must leave its ground behind"
    # The whole 20-foot line, spelled out: it starts at the chosen point and runs four cells on away from the
    # caster, so it is five squares, none of them anywhere near the caster's own side of the board.
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    assert cells == expected, f"the placed line must be {sorted(expected)}, not {sorted(cells)}"
    assert zone.center == AIM, "the ground is centred on the point that was chosen"
    assert all(cell[0] > origin.x for cell in cells), "and never reaches back across the caster's own squares"
    # The reloaded fight re-derives exactly the same squares from the stored shape (checklist 7: persistence).
    assert {(cell.x, cell.y) for cell in zones.area_cells(reloaded.engine, zone)} == expected

    # Missing/coincident owners cannot reconstruct a direction. Preserve stored cells,
    # including after a suppression; this fallback does not restore removed squares.
    owner = reloaded.engine.state.actors[zone.owner_id]
    owner.position = zone.center
    assert zones.area_cells(reloaded.engine, zone) == zone.affected_cells
    zone.affected_cells = zone.affected_cells[1:]
    assert zones.area_cells(reloaded.engine, zone) == zone.affected_cells
    del reloaded.engine.state.actors[zone.owner_id]
    assert zones.area_cells(reloaded.engine, zone) == zone.affected_cells


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
