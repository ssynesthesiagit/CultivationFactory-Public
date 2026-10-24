"""AUTO43: the printed Smoke Veil lines a fight now resolves (Smoke sphere automation, 2026-10-05).

Each case is a fight-level check on a real Gate4 engine -- a compiled bundle, a submitted intent, the map and the
event log -- of a line the owner's printed Smoke text states and the table used to leave to the GM:

  Smoke Veil        "At CL 5, the area becomes two connected 10-foot cubes. At CL 11, it becomes three connected 10-foot
                    cubes. At CL 17, it becomes four connected 10-foot cubes."  (one cube at every CL)
  Dense Veil        "When you create or move your Smoke Veil, it becomes Dense ... if you maintain the same Smoke Veil
                    without moving it on your next turn, it remains Dense."  (the veil's concealment never changed)
  Second Veil       "create one additional 5-foot cube of smoke within 30 feet of the original veil"  (never made)
  Blacken the Flame "The reduction increases to 2d6 at CL 5, 3d6 at CL 11, and 4d6 at CL 17."  (always 1d6, never ran)
  Smother the Breath "Failed Save: ... It has Disadvantage on the triggering d20 Test if the trigger includes one. If the
                    trigger does not include a d20 Test, the creature cannot take Reactions until the start of its next
                    turn."  (the failed save did nothing at all)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = __import__("importlib").import_module("test_review_sw-athletics")

from combat import zones
from combat.ext import smoke_veil
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.typed_executor import bears_mark, mark_condition_id

ME, AN = t.ME, t.AN
SMOKE = "tianxia.sphere.smoke"
VEIL, DENSE, SECOND = "SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_DENSE_VEIL", "TAL_SMOKE_SECOND_VEIL"
BLACKEN, SMOTHER = "TAL_SMOKE_BLACKEN_THE_FLAME", "TAL_SMOKE_SMOTHER_THE_BREATH"
WITNESS = "TAL_SMOKE_SOOT_MARKED_WITNESS"
BASES = ["SMOKE_BASE_SMOKE_RESPONSES", "SMOKE_BASE_SMOKE_TRACE"]
FAIL = 50  # technique save DC that makes the foe fail every save


def _fight(talents=(), cl=10, dc=FAIL, foe_at=(4, 6)):
    engine = t._engine(t._bundle(SMOKE, [VEIL, *BASES, *talents], {}, cl=cl, dc=dc), foe_at=foe_at, foe_hp=400)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _place_veil(engine, at):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name.startswith("Smoke Veil")
             and c.destination is not None and (c.destination.x, c.destination.y) == at]
    assert found, f"no Smoke Veil aim at {at}"
    candidate = min(found, key=lambda c: len(c.display_name))
    engine.execute_intent(ActionIntent(intent_id="veil", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return [(cell.x, cell.y) for cell in zones.typed_zones(engine)[0].affected_cells]


def _use(engine, name, target=AN):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name and c.actor_id == ME
             and (target is None or not c.target_ids or target in c.target_ids)]
    assert found, f"{name!r} is not legal"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"a43-{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def _accept(request, options):
    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(options)), None


def _decline(request):
    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=())


@pytest.mark.parametrize("cl,squares", [(4, 4), (5, 8), (11, 12), (17, 16)])
def test_smoke_veil_is_the_printed_run_of_connected_cubes(cl, squares):
    """A 10-foot cube is four 5-foot squares, so N connected cubes are 4N squares, each sharing a face with the rest."""
    engine, _, _ = _fight(cl=cl)
    cells = set(_place_veil(engine, (6, 6)))
    assert len(cells) == squares, f"CL {cl}: {sorted(cells)}"
    reached = {(6, 6)}  # one connected run of cubes, not N loose ones
    while True:
        wider = reached | {(x + dx, y + dy) for x, y in reached for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} & cells
        if wider == reached:
            break
        reached = wider
    assert reached == cells


def test_smoke_veil_keeps_its_printed_run_when_it_is_moved():
    engine, _, _ = _fight(cl=11)
    assert len(_place_veil(engine, (6, 6))) == 12
    _use(engine, "Smoke Veil: move it 10 feet")
    cells = {(cell.x, cell.y) for cell in zones.typed_zones(engine)[0].affected_cells}
    assert len(cells) == 12, f"{sorted(cells)}"


def test_dense_veil_makes_the_veil_heavily_obscured_and_keeps_it_there_when_moved():
    engine, _, _ = _fight([DENSE])
    _place_veil(engine, (6, 6))
    veil = zones.typed_zones(engine)[0]
    assert veil.trigger_profile["obscured"] == "heavy" and veil in zones._heavy(engine)
    _use(engine, "Smoke Veil: move it 10 feet")
    assert zones.typed_zones(engine)[0].trigger_profile["obscured"] == "heavy"


def test_a_veil_without_dense_veil_is_only_lightly_obscured():
    engine, _, _ = _fight()
    _place_veil(engine, (6, 6))
    veil = zones.typed_zones(engine)[0]
    assert veil.trigger_profile["obscured"] == "light" and veil not in zones._heavy(engine)


@pytest.mark.parametrize("take", [True, False])
def test_second_veil_adds_the_cube_the_owner_picks_or_leaves_one_veil(take):
    engine, _, _ = _fight([SECOND], cl=4, foe_at=(14, 6))
    engine.set_reaction_provider(lambda request: _accept(request, request["legal_option_ids"][:1]) if take
                                 else (_decline(request), None))
    _place_veil(engine, (6, 6))
    veils = smoke_veil.veils(engine, engine.state.actors[ME])
    assert len(veils) == (2 if take else 1)
    if take:
        extra = next(zone for zone in veils if zone.trigger_profile.get("second_veil"))
        first = next(zone for zone in veils if not zone.trigger_profile.get("second_veil"))
        assert extra.trigger_profile["size_ft"] == 5 and extra.concentration_link  # shares the veil's Concentration
        assert len(extra.affected_cells) == 1
        assert not {(cell.x, cell.y) for cell in extra.affected_cells} & {(cell.x, cell.y) for cell in first.affected_cells}


def test_blacken_the_flame_soots_fire_damage_by_the_printed_dice_and_spends_the_trace():
    engine, me, foe = _fight([BLACKEN], cl=11, foe_at=(4, 6))
    _place_veil(engine, (4, 6))  # the foe's own square is inside the veil
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    assert bears_mark(foe, ME, "Smoke Trace")
    answered = []

    def provider(request):
        answered.append(request["reaction_source_id"])
        if not str(request["reaction_source_id"]).startswith("choice:needle."):
            return _decline(request), None
        return _accept(request, request["legal_option_ids"][:1])

    engine.set_reaction_provider(provider)
    engine._active_intent = _intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert "choice:needle.smoke_blacken_the_flame" in answered, answered
    taken = before - foe.current_hp
    cuts = [r for r in engine.rolls if r.reason == "DAMAGE_REDUCED"]
    assert cuts and len(cuts[0].dice) == 3, f"CL 11 reduces by 3d6: {cuts}"
    assert taken < 20, f"{taken} damage taken: the soot took nothing off"
    assert not bears_mark(foe, ME, "Smoke Trace")  # the Smoke Trace paid for it


def test_blacken_the_flame_leaves_other_damage_and_an_untraced_veil_alone():
    engine, me, foe = _fight([BLACKEN], cl=11)
    _place_veil(engine, (4, 6))
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    engine.set_reaction_provider(lambda request: (_decline(request), None))
    engine._active_intent = _intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 12, "slashing", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert foe.current_hp == before - 12, "only Fire damage is sooted"
    assert bears_mark(foe, ME, "Smoke Trace")


def _intent(engine):
    t._ready(engine)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name.startswith("Cinder Wisp")) \
        if any(c.display_name.startswith("Cinder Wisp") for c in engine.legal_candidates()) else None
    if candidate is None:
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME)
    return ActionIntent(intent_id="a43", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                        destination=candidate.destination)


def test_a_smolder_who_fails_loses_its_reaction_and_the_success_branch_is_unchanged():
    engine, me, foe = _fight([SMOTHER, "TAL_SMOKE_SMOTHERING_MANDATE"], cl=10, foe_at=(4, 6))
    _place_veil(engine, (4, 6))
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    row = next(r for r in engine.typed_reaction_rows[ME] if r["feature_id"] == SMOTHER)
    from combat import typed_reactions

    typed_reactions._run_generic_effects(engine, me, foe, row, row["effects"])
    assert not bears_mark(foe, ME, "Smoke Trace")  # "Spend the Smoke Trace."
    assert any(condition.condition_id == "condition:typed.reaction_denied" for condition in foe.conditions.values()), \
        sorted(condition.condition_id for condition in foe.conditions.values())

def test_soot_marked_witness_marks_the_creature_without_uncovering_it():
    """Soot-Marked Witness: "Until the start of your next turn, the target cannot be Hidden from you solely because it
    is concealed by smoke, fog, mist, steam, or nonmagical darkness."

    The table puts the mark on, and does not clear Hidden. The printed benefit is conditional on that concealment being
    the *only* reason, and says outright it "does not defeat Total Cover, unrelated invisibility, concealment from
    another source, an effect such as Truesight, or a Hide supported by circumstances other than the listed
    concealment" -- and one Hidden condition with no stated cause cannot tell those apart."""
    from combat import stealth

    engine, me, foe = _fight([WITNESS], cl=10, foe_at=(4, 6))
    _place_veil(engine, (4, 6))
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    assert not stealth.can_hide(engine, foe)  # the engine sees it, so it cannot Hide there in the first place
    engine._apply_condition(foe, stealth.HIDDEN, "test:hides", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 30})
    assert stealth.hidden(foe) is not None
    _run_ability(engine, "Soot-Marked Witness")
    assert stealth.hidden(foe) is not None, "the table must not clear Hidden it cannot explain"
    assert not bears_mark(foe, ME, "Smoke Trace")
    assert any(condition.condition_id == "condition:typed.smoke_witness_reveal" for condition in foe.conditions.values())


def test_soot_marked_witness_lasts_to_the_start_of_the_owners_next_turn_not_the_targets():
    """"Until the start of your next turn" -- the owner's. The target's next turn is a different moment, and the mark
    must not end with it (START_OF_TARGET_NEXT_TURN would)."""
    engine, me, foe = _fight([WITNESS], cl=10, foe_at=(4, 6))
    _place_veil(engine, (4, 6))
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    _run_ability(engine, "Soot-Marked Witness")
    mark = next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.smoke_witness_reveal")
    assert mark.expires_on == "START_OF_SOURCE_NEXT_TURN", mark.expires_on


def _run_ability(engine, name, target=AN):
    """Run one of this fighter's own compiled abilities against ``target`` on the live engine.

    A Hidden creature is not a legal target on this table (the engine's candidate gate refuses one), so the mark is
    spent through its own compiled row the way combat/typed_reactions.py runs a reaction row: the printed ability, this
    fighter, this target, this fight."""
    from combat.typed_executor import Context

    action = next(row for row in engine.action_catalog.values()
                  if row.owner_id == ME and row.display_name.split(" at ")[0] == name)
    t._ready(engine)
    typed = dict(action.parameters["typed"])
    subject = engine.state.actors[target]
    context = Context(engine, engine.state.actors[ME], action, engine._active_intent, typed, [subject], subject)
    from combat.typed_executor import run_effects

    run_effects(context, typed["effects"])


# ------------------------------------------------------------------ Blacken the Flame is a Reaction
def _blacken_ready(engine, foe, *, at=(4, 6), cl=11):
    _place_veil(engine, at)  # the foe's own square is inside the veil
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    return foe


def _soot_answer(request, take=True):
    """The engine wraps whatever the fight's reaction provider returns into ``(decision, record)`` itself, so a
    provider answers with the decision (combat/choice_checkpoints.py)."""
    if not str(request["reaction_source_id"]).startswith("choice:needle."):
        return _decline(request), None
    return _accept(request, request["legal_option_ids"][:1]) if take else _decline(request)


def test_blacken_the_flame_needs_a_reaction_and_spends_the_one_it_uses():
    """"Action Type: Reaction" -- so a fighter with no Reaction left this round cannot soot at all, and one that does
    soot has spent its Reaction. Neither half was true before: the reduction ran whether or not the owner had a
    Reaction, so a Smoke fighter could soot once per fire packet, every round."""
    engine, me, foe = _fight([BLACKEN], cl=11)
    _blacken_ready(engine, foe)
    engine.set_reaction_provider(lambda request: _soot_answer(request))
    engine._active_intent = _intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert foe.current_hp < before, "the soot did nothing"
    assert not me.reaction_available, "a Reaction ability must spend the owner's Reaction"
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == BLACKEN for e in engine.events), \
        "the use is recorded as a reaction use"


def test_blacken_the_flame_cannot_answer_without_a_reaction_or_when_reactions_are_denied():
    engine, me, foe = _fight([BLACKEN], cl=11)
    _blacken_ready(engine, foe)
    engine.set_reaction_provider(lambda request: _soot_answer(request))
    engine._active_intent = _intent(engine)
    me.reaction_available = False  # the owner's Reaction is already spent this round
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert foe.current_hp == before - 20, "no Reaction, no soot"
    assert bears_mark(foe, ME, "Smoke Trace"), "an answer it never gave spends nothing"
    me.reaction_available = True
    engine._apply_condition(me, "condition:typed.reaction_denied", BLACKEN, AN, expires_on="UNTIL_REMOVED")
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert foe.current_hp == before - 20, "a creature denied Reactions cannot soot either"
    assert bears_mark(foe, ME, "Smoke Trace")


def test_an_unanswered_blacken_the_flame_spends_neither_the_reaction_nor_the_trace():
    """A fight nobody is answering must not quietly spend the owner's Reaction and Smoke Trace: the choice falls back to
    declining, and declining spends nothing."""
    engine, me, foe = _fight([BLACKEN], cl=11)
    _blacken_ready(engine, foe)
    engine._active_intent = _intent(engine)  # no reaction provider: nobody is answering
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert foe.current_hp == before - 20, "damage lands as it is"
    assert me.reaction_available, "declining keeps the Reaction"
    assert bears_mark(foe, ME, "Smoke Trace"), "declining keeps the Smoke Trace"


def test_blacken_the_flame_also_soots_fire_that_travels_through_the_veil():
    """"Fire damage is dealt inside your Smoke Veil or through your Smoke Veil" -- the second half answers a packet whose
    source and target both stand outside, because its line of effect runs through the smoke."""
    engine, me, foe = _fight([BLACKEN], cl=11, foe_at=(6, 9))  # the foe stands beyond the veil, not in it
    _place_veil(engine, (6, 6))  # a CL 11 veil is a three-cube run through (6, 6)
    veil_cells = {(c.x, c.y) for c in zones.typed_zones(engine)[0].affected_cells}
    assert (foe.position.x, foe.position.y) not in veil_cells, "the foe is outside the veil for this case"
    engine._apply_condition(foe, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})
    shooter = _clone_actor(engine, foe, "actor:factory.shooter", (6, 3))
    assert smoke_veil._through_veil(engine, me, shooter, foe), "the line from the shooter to the foe crosses the veil"
    engine.set_reaction_provider(lambda request: _soot_answer(request))
    engine._active_intent = _intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", shooter.entity_id, engine._active_intent, reaction_depth=2)
    assert foe.current_hp < before, "fire that passes through the smoke is sooted too"
    assert not bears_mark(foe, ME, "Smoke Trace")


def _clone_actor(engine, source, entity_id, at):
    """A second foe for a printed "or through" trigger: the same fighter standing on the other side of the veil."""
    clone = source.model_copy(update={"entity_id": entity_id, "display_name": "An Eui's Ally",
                                     "position": source.position.model_copy(update={"x": at[0], "y": at[1]})})
    engine.state.actors[entity_id] = clone
    return clone


# ------------------------------------------------------------------ Second Veil: the printed CL size
@pytest.mark.parametrize("cl,side,squares", [(4, 5, 1), (5, 10, 4), (11, 10, 4)])
def test_second_veil_is_a_5_foot_cube_until_cl5_and_10_foot_after(cl, side, squares):
    """"create one additional 5-foot cube of smoke ... At CL 5, the second veil becomes a 10-foot cube." The size was
    fixed at 5 feet at every Cultivation Level, so a CL 5+ fighter's second veil was a quarter of the size the printed
    line says."""
    engine, me, _ = _fight([SECOND], cl=cl, foe_at=(14, 6))
    engine.set_reaction_provider(lambda request: _accept(request, request["legal_option_ids"][:1]))
    _place_veil(engine, (6, 6))
    extra = next((zone for zone in smoke_veil.veils(engine, me) if zone.trigger_profile.get("second_veil")), None)
    assert extra is not None, "the second veil was not created"
    assert extra.trigger_profile["size_ft"] == side, extra.trigger_profile["size_ft"]
    assert len(extra.affected_cells) == squares, sorted((c.x, c.y) for c in extra.affected_cells)


def test_the_second_veil_stands_on_the_square_its_owner_picked():
    """Its recorded centre is the square the owner chose, not the first cell of a four-square footprint -- a corner
    would put a later re-centring a whole cube off."""
    engine, me, _ = _fight([SECOND], cl=5, foe_at=(14, 6))
    engine.set_reaction_provider(lambda request: _accept(request, [request["legal_option_ids"][-1]]))
    _place_veil(engine, (6, 6))
    extra = next(zone for zone in smoke_veil.veils(engine, me) if zone.trigger_profile.get("second_veil"))
    assert len(extra.affected_cells) == 4, "a 10-foot cube is four 5-foot squares"
    assert (extra.center.x, extra.center.y) in {(c.x, c.y) for c in extra.affected_cells}
    # the stored centre is the middle of the 2x2 the owner picked, not its first cell
    corners = {(c.x, c.y) for c in extra.affected_cells}
    assert sum(1 for c in extra.affected_cells if c.x == extra.center.x) == 2
    assert sum(1 for c in extra.affected_cells if c.y == extra.center.y) == 2
    assert corners


def test_a_moved_run_of_cubes_keeps_the_direction_it_was_made_with():
    """Moving the veil re-centres it, and the run used to take whatever direction its owner happened to face
    afterwards -- a three-cube wall turning across the map. The direction it was made with is stored on the area and
    read back, so a moved run is the same run translated."""
    engine, me, _ = _fight(cl=11)
    _place_veil(engine, (6, 6))
    before = zones.typed_zones(engine)[0]
    axis = before.trigger_profile["blocks_along"]
    before_cells = {(c.x, c.y) for c in before.affected_cells}
    _use(engine, "Smoke Veil: move it 10 feet")
    after = zones.typed_zones(engine)[0]
    after_cells = {(c.x, c.y) for c in after.affected_cells}
    assert after.trigger_profile["blocks_along"] == axis, "the stored direction is kept"
    assert after_cells != before_cells, "the veil actually moved"
    corners_before = (min(x for x, _ in before_cells), min(y for _, y in before_cells))
    corners_after = (min(x for x, _ in after_cells), min(y for _, y in after_cells))
    shape_before = {(x - corners_before[0], y - corners_before[1]) for x, y in before_cells}
    shape_after = {(x - corners_after[0], y - corners_after[1]) for x, y in after_cells}
    assert shape_after == shape_before, f"{sorted(shape_after)} is not {sorted(shape_before)}"


# ------------------------------------------------------------------ persistence
def test_the_veil_shape_survives_a_state_commit_and_reload():
    """Checklist item 7: what the area stores -- the block count, the run's direction, the second veil's own squares --
    is integers and strings only, and comes back identical through a JSON round trip of the whole fight state."""
    import json

    from combat.gate2_runtime_models import MatchState

    engine, me, _ = _fight([SECOND], cl=11, foe_at=(14, 6))
    engine.set_reaction_provider(lambda request: _accept(request, request["legal_option_ids"][:1]))
    _place_veil(engine, (6, 6))
    live = {(z.zone_id, json.dumps(z.center.model_dump(), sort_keys=True),
             tuple(sorted((c.x, c.y) for c in z.affected_cells)),
             json.dumps(z.trigger_profile, sort_keys=True, default=str))
            for z in smoke_veil.veils(engine, me)}
    saved_state = json.loads(engine.state.model_dump_json())
    saved_state.pop("schema_name", None)  # the model's own class, not a field
    reloaded = MatchState.model_validate(saved_state)
    names = {i for i, *_ in live}
    saved = {(z.zone_id, json.dumps(z.center.model_dump(), sort_keys=True),
              tuple(sorted((c.x, c.y) for c in z.affected_cells)),
              json.dumps(z.trigger_profile, sort_keys=True, default=str))
             for z in reloaded.zones.values() if z.zone_id in names}
    assert saved == live, "a reloaded fight covers the same squares with the same stored values"
    profiles = [json.loads(profile) for *_, profile in live]
    stored = ("blocks", "blocks_along", "second_veil", "size_ft", "shape")
    assert all(isinstance(profile.get(key), (int, str)) for profile in profiles for key in stored
               if profile.get(key) is not None), "the values this lane puts on the area are integers and strings"
    assert any(profile.get("blocks") for profile in profiles), "the printed run of cubes is stored on the area"
    runs = [profile for profile in profiles if int(profile.get("blocks") or 1) > 1]
    assert runs and all(profile.get("blocks_along") in {"x", "y"} for profile in runs), \
        "every run stores the direction it was made with"
    assert any(profile.get("second_veil") for profile in profiles), "the second veil is stored too"


def test_a_fighter_without_the_smoke_talents_keeps_the_veil_unchanged_and_never_answers_blacken():
    """Checklist items 3 and 12: the plug-in is inert for a character that does not own its abilities, so an existing AI
    fight replays the same way. The printed plain veil (one 10-foot cube, Lightly Obscured) is untouched, no area gains a
    block count or a direction, and no Blacken the Flame row exists to answer damage."""
    engine, me, foe = _fight(cl=4)  # no Dense Veil, no Second Veil, no Blacken the Flame
    cells = _place_veil(engine, (6, 6))
    assert len(set(cells)) == 4, "below CL 5 the printed veil is the same single 10-foot cube it always was"
    veil = zones.typed_zones(engine)[0]
    assert "blocks" not in veil.trigger_profile and "blocks_along" not in veil.trigger_profile, \
        "a single cube needs no run and stores no direction"
    assert veil.trigger_profile["obscured"] == "light", "Lightly Obscured, as printed, with no Dense Veil"
    from combat.ext.fight_ownership import block_rows

    assert block_rows(engine, me, BLACKEN_BLOCK := "smoke_fire_soot") == [], "no Blacken the Flame row to answer with"
    engine.set_reaction_provider(lambda request: _soot_answer(request))
    engine._active_intent = _intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    assert foe.current_hp == before - 20, "Fire damage is untouched without the talent"
