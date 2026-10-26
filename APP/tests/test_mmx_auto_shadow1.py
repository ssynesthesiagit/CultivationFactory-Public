"""MMXAUTO-SHADOW1: the Shadow sphere's Shadowed Space clauses, run by the table.

Every test below drives the real engine path: a compiled character, the engine's own target
menu, the real damage-reaction path and a real attack. Each one fails on the typing the
authority carried before this lane -- the Shadowed Space clauses were Game Master riders
because Dim Light, Darkness and Cast Shadows were not tracked. The self path already asked the player for a
landing square; the ally's question was asked after payment and capped at 16 squares.

Records wired here: tianxia.talent.shadow.shadow_ward, TAL_SHADOW_SHADOW_BIND,
TAL_SHADOW_SHADOW_STEP, TAL_SHADOW_SHADOW_EXCHANGE, TAL_SHADOW_SHADOWLESS_REVERSAL.
Plug-ins: combat/ext/shadow.py and the shared helper combat/ext/shadowed_space.py.
"""

import importlib.util
import json
from pathlib import Path

from combat.gate2_runtime_models import ReactionDecision
from tests import test_auto_lane4 as L4

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"

_SPEC = importlib.util.spec_from_file_location("review_sw_force", ROOT / "tests/test_review_sw-force.py")
SWF = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SWF)

S = "TAL_SHADOW_"
SH = "tianxia.talent.shadow."
SHADOW = "tianxia.sphere.shadow"
WARD = SH + "shadow_ward"
BIND = S + "SHADOW_BIND"
STEP = S + "SHADOW_STEP"
EXCHANGE = S + "SHADOW_EXCHANGE"
REVERSAL = S + "SHADOWLESS_REVERSAL"

#: A map that declares its light: one torch in a bright room and one patch of shade.
#: An undeclared map is Bright (combat/lighting.py, OQ-1): it has no Dim squares, so only the
#: owner's anchors and cast shadows are Shadowed Spaces.
LIT = {"tabletop": {"ambient": {"time_of_day": "day", "level": "bright"},
       "lights": [{"id": "l1", "name": "Torch", "x": 2, "y": 2, "bright_ft": 10, "dim_ft": 0}],
       "ambient_regions": [{"id": "r1", "name": "Shade", "level": "dim",
                            "cells": [[5, 5], [6, 5], [7, 5], [5, 6], [6, 6], [7, 6], [5, 7], [6, 7], [7, 7]]}]}}

#: A room with a torch and a shaded corner, far from the fighters: the shade is a patch of
#: Dim Light, so every square of it is a Shadowed Space.
LIT_CORNER = {"tabletop": {"ambient": {"time_of_day": "day", "level": "bright"},
              "lights": [{"id": "l1", "name": "Torch", "x": 2, "y": 2, "bright_ft": 10, "dim_ft": 0}],
              "ambient_regions": [{"id": "r1", "name": "Shade", "level": "dim",
                                   "cells": [[10, 2]]}]}}


def _authority():
    return json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"]


def _shadowed_cells(engine, owner):
    """The squares the table knows as Shadowed Spaces for the given owner."""
    from combat.ext import shadowed_space

    cells = shadowed_space.shadowed_cells(engine, owner)
    return None if cells is None else {(x, y) for x, y in cells}


def _roll(engine, feature_id):
    """The last roll the given feature made."""
    rolls = [r for r in engine.rolls if str(r.reason).startswith("GENERIC_AMOUNT") and feature_id in str(r.reason)]
    assert rolls, [r.reason for r in engine.rolls]
    return rolls[-1]


# ================================================================================================== Shadow Ward
def test_shadow_ward_adds_its_proficiency_bonus_only_while_the_protected_creature_stands_in_a_shadowed_space():
    """Shadow Ward: "Reduce the triggering damage: 1d8 + Path key ability modifier ... If the protected
    creature occupies one of your Shadowed Spaces, add your Proficiency Bonus to the reduction."
    The typed row carried the clause as a Game Master rider ("Dim Light, Darkness and Cast Shadows
    are not tracked"), so the table never added the Proficiency Bonus."""
    from combat import typed_reactions as tr

    _, engine, me, foe = SWF.fight(WARD, cl=20, dc=50)
    engine.battlefield_document = LIT_CORNER
    row = next(r for r in engine.typed_reaction_rows[me.entity_id] if r.get("feature_id") == WARD)
    assert row["numbers"]["pb"] == me.proficiency_bonus == 4

    # A creature in the bright room is in no Shadowed Space: the reduction is the printed dice only.
    plain = tr.on_damage(engine, me, 100, 0, source_actor_id=SWF.AN)
    assert plain == 100 - _roll(engine, WARD).total

    # Standing on one of your own Shadow Anchors: the Proficiency Bonus joins the reduction.
    me.reaction_available = True
    SWF.cast(engine, "Second Silhouette: Shadow Anchor", at=(6, 6))
    me.position = me.position.model_copy(update={"x": 6, "y": 6})
    anchored = tr.on_damage(engine, me, 100, 0, source_actor_id=SWF.AN)
    assert anchored == 100 - (_roll(engine, WARD).total + me.proficiency_bonus)

    # A square in Dim Light is a Shadowed Space as well.
    me.reaction_available = True
    me.position = me.position.model_copy(update={"x": 10, "y": 2})
    dim = tr.on_damage(engine, me, 100, 0, source_actor_id=SWF.AN)
    assert dim == 100 - (_roll(engine, WARD).total + me.proficiency_bonus)


# ================================================================================================== Shadow Bind
def test_shadow_bind_only_offers_a_creature_bearing_your_mark_or_standing_in_a_shadowed_space():
    """Shadow Bind: "Choose one creature bearing your Shadow Mark or standing inside one of your
    Shadowed Spaces." The typed row left the choice of target to the Game Master."""
    from combat import typed_executor as te

    _, engine, me, foe = SWF.fight(BIND, cl=20, dc=50)
    engine.battlefield_document = LIT_CORNER

    def offered():
        return [c for c in engine.legal_candidates() if c.display_name == "Shadow Bind"]

    # A creature in the bright room bears no Shadow Mark: it is not a legal target.
    assert not offered()

    # A creature bearing your Shadow Mark is a legal target.
    engine._apply_condition(foe, te.mark_condition_id("Shadow Mark", me.entity_id), "test", me.entity_id,
                            expires_on="UNTIL_REMOVED")
    assert offered() and foe.entity_id in offered()[0].target_ids

    # A creature standing in Dim Light is a legal target without the mark.
    foe.conditions.clear()
    foe.position = foe.position.model_copy(update={"x": 10, "y": 2})
    assert offered() and foe.entity_id in offered()[0].target_ids


# ================================================================================================ Shadow Step
def test_shadow_step_needs_a_shadowed_origin_and_only_offers_shadowed_destinations():
    """Shadow Step: "Teleport from a Shadowed Space you occupy into another Shadowed Space you can
    see." The typed row let the player pick any square in range; the table never checked."""
    _, engine, me, foe = SWF.fight(STEP, cl=20, dc=50)
    engine.battlefield_document = LIT_CORNER

    def destinations():
        return {(c.destination.x, c.destination.y) for c in engine.legal_candidates()
                if c.display_name.startswith("Shadow Step") and c.destination is not None}

    # A caster in the bright room occupies no Shadowed Space: Shadow Step is not offered at all.
    assert not destinations()

    # Standing on one of your own Shadow Anchors, the destinations are Shadowed Spaces only.
    SWF.cast(engine, "Second Silhouette: Shadow Anchor", at=(5, 5))
    me.position = me.position.model_copy(update={"x": 5, "y": 5})
    offered = destinations()
    assert offered
    shadowed = _shadowed_cells(engine, me)
    assert shadowed is not None and offered <= shadowed
    assert all(engine.grid.distance_ft(cell, me.position) <= engine._effective_speed(me) // 2
               for cell in (type(me.position)(x=x, y=y) for x, y in offered))


# ============================================================================================ Shadow Exchange
def _slip_duel(talent):
    engine = L4._duel([talent], subject_sphere=SHADOW, attacker_kit=L4.t.AXE_KIT)
    engine.battlefield_document = LIT
    engine.typed_control_modes = {L4.SUBJ: "MANUAL"}
    return engine, engine.state.actors[L4.SUBJ]


def _answering_provider(asked):
    """The table's own choice transport: it answers every question and records what it was asked."""
    def provider(request):
        asked.append(request)
        options = list((request.get("choice_trigger") or {}).get("needle_options") or [])
        pick = options[0] if options else None
        if pick is None:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(pick,)), None

    return provider


def test_shadow_exchange_offers_the_player_a_shadowed_space_outside_the_attacking_reach():
    """Shadow Exchange: "Teleport the protected creature into one visible, unoccupied Shadowed Space
    within 20 feet" and out of the triggering attack's reach, line or area. The typed row chose the
    square by itself and left the Shadowed Space, the visibility and the player's own choice to the
    Game Master."""
    engine, subject = _slip_duel(EXCHANGE)
    asked = []
    engine._gate4_reaction_provider = _answering_provider(asked)
    L4._script(engine, [15, 6])
    events = L4._use(engine, "Fu (Short Axe) attack")

    assert L4._hp_lost(events) == 0
    destination = [r for r in asked if str(r["reaction_source_id"]).endswith("teleport_destination")]
    assert destination, [r["reaction_source_id"] for r in asked]
    offered = list((destination[0].get("choice_trigger") or {}).get("needle_options") or [])
    assert offered
    shadowed = _shadowed_cells(engine, subject)
    assert shadowed is not None
    attacker = engine.state.actors[L4.ME]
    for option in offered:
        x, y = (int(part) for part in option.split(":")[1].split(","))
        assert (x, y) in shadowed, option
        assert engine.grid.distance_ft(type(subject.position)(x=x, y=y), attacker.position) > 5
    assert (subject.position.x, subject.position.y) == (5, 5)


# ========================================================================================= Shadowless Reversal
def test_shadowless_reversal_offers_the_player_a_shadowed_space_outside_the_attacking_reach():
    """Shadowless Reversal: "Leave a false silhouette behind and use Shadow Step immediately. If you
    move outside the attack's reach, the attack misses that creature." The typed row chose the square
    by itself and left both spaces, the visibility, the line or area attacks and the player's own
    choice to the Game Master."""
    engine, subject = _slip_duel(REVERSAL)
    asked = []
    engine._gate4_reaction_provider = _answering_provider(asked)
    L4._script(engine, [15, 6])
    events = L4._use(engine, "Fu (Short Axe) attack")

    assert L4._hp_lost(events) == 0
    destination = [r for r in asked if str(r["reaction_source_id"]).endswith("teleport_destination")]
    assert destination, [r["reaction_source_id"] for r in asked]
    offered = list((destination[0].get("choice_trigger") or {}).get("needle_options") or [])
    assert offered
    shadowed = _shadowed_cells(engine, subject)
    assert shadowed is not None
    attacker = engine.state.actors[L4.ME]
    for option in offered:
        x, y = (int(part) for part in option.split(":")[1].split(","))
        assert (x, y) in shadowed, option
        assert engine.grid.distance_ft(type(subject.position)(x=x, y=y), attacker.position) > 5
    assert not subject.reaction_available


# ============================================================================================== The authority
def test_the_shadowed_space_clauses_the_table_runs_are_no_longer_gm_riders():
    """The five Shadow records this lane wired are typed without a Game Master rider."""
    mechanics = _authority()
    for key in (WARD, BIND, STEP, EXCHANGE, REVERSAL):
        assert mechanics[key]["riders"] == [], (key, mechanics[key]["riders"])
        assert mechanics[key]["coverage"] == "FULL", (key, mechanics[key]["coverage"])

# ========================================================================= Finding 1: the map's light, not its sources
BRIGHT_MAP = {"tabletop": {"ambient": {"time_of_day": "day", "level": "bright"}}}
DIM_MAP = {"tabletop": {"ambient": {"time_of_day": "night", "level": "dim"}}}


def test_an_undeclared_map_has_no_dim_squares_so_no_square_is_shadowed_by_default():
    """No battlefield document at all: the ambient is Bright (OQ-1), so no square is Dim and nothing is a Shadowed Space.
    An undeclared map contributes only anchors and cast shadows (guards the shipped behaviour the reviewer notes misdescribed)."""
    engine = L4._duel([], subject_sphere=SHADOW, attacker_kit=L4.t.AXE_KIT)
    subject = engine.state.actors[L4.SUBJ]
    assert _shadowed_cells(engine, subject) == set()
    from combat.ext import shadowed_space
    assert not shadowed_space.is_shadowed(engine, subject, subject.position)


def test_a_map_that_declares_bright_with_no_light_sources_has_no_dim_squares():
    """A map whose ambient is explicitly "bright" and which declares no lights or regions: still no Shadowed Space."""
    engine = L4._duel([], subject_sphere=SHADOW, attacker_kit=L4.t.AXE_KIT)
    engine.battlefield_document = BRIGHT_MAP
    subject = engine.state.actors[L4.SUBJ]
    assert _shadowed_cells(engine, subject) == set()
    from combat.ext import shadowed_space
    assert not shadowed_space.is_shadowed(engine, subject, subject.position)


def _cp(actor):
    """The Chi (Qi/CP) pool the Shadow reactions pay from, and its current amount."""
    from combat.ext.rider_support import cp_pool
    pool = cp_pool(actor)
    return pool, int(actor.resources.get(pool, 0))


# ========================================================================= Findings 2 and 3: the ally's Shadow Exchange
ALLY = "actor:factory.ally"


def _ally_duel(battlefield):
    """ME (a Brute) attacks SUBJ; ALLY (a Shadow creature holding Shadow Exchange, under the table's manual control) stands
    beside SUBJ, so ALLY's reaction moves SUBJ: the ally branch, not the self path."""
    mine = L4.compile_character(L4.t._sheet(L4.BRUTE, [], L4.t.AXE_KIT, cl=10), actor_id=L4.ME)
    theirs = L4.compile_character(L4.t._sheet(SHADOW, [], {}, cl=10), actor_id=L4.SUBJ)
    ally = L4.compile_character(L4.t._sheet(SHADOW, [EXCHANGE], {}, cl=10), actor_id=ALLY)
    engine = L4.Gate4ControllerEngine(L4.ROOT, match_seed="LANE4", typed_bundles=(mine, theirs, ally),
                                      roster_setup={"primary_actor_ids": [L4.ME, L4.SUBJ, ALLY],
                                                    "team_by_actor": {L4.ME: "team:a", L4.SUBJ: "team:b", ALLY: "team:b"},
                                                    "starting_positions": {L4.ME: {"x": 3, "y": 6}, L4.SUBJ: {"x": 4, "y": 6},
                                                                           ALLY: {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(L4.ME)
    engine.state.current_actor_id = L4.ME
    engine._system_start_turn()
    L4.t._ready(engine)
    engine.battlefield_document = battlefield
    engine.typed_control_modes = {ALLY: "MANUAL"}
    return engine


def _ally_provider(asked, landing):
    """Says "use" to the slip question and picks `landing` on the slip-spot question (None declines it)."""
    def provider(request):
        asked.append(request)
        blob = json.dumps(request, default=str)
        options = list((request.get("choice_trigger") or {}).get("needle_options") or [])
        if "shadow_slip_spot" in blob:
            pick = landing
        elif "needle.shadow_slip" in blob and "use" in options:
            pick = "use"
        else:
            pick = None
        if pick is None:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=(pick,)), None

    return provider


def _slip_question(asked):
    found = [r for r in asked if "shadow_slip_spot" in json.dumps(r, default=str)]
    assert found, [r.get("reaction_source_id") for r in asked]
    return found[0].get("choice_trigger") or {}


def test_the_ally_slip_question_offers_every_landing_not_only_sixteen_and_defaults_to_one_of_them():
    """Finding 2: the ally question lists every legal landing (far more than 16 on a Dim map), its default is an
    offered square, and its labels and title are Shadow Exchange's. Before the fix it was capped at the 16 nearest."""
    engine = _ally_duel(DIM_MAP)
    asked = []
    engine._gate4_reaction_provider = _ally_provider(asked, None)
    L4._script(engine, [15, 6])
    L4._use(engine, "Fu (Short Axe) attack")

    question = _slip_question(asked)
    options = list(question.get("needle_options") or [])
    assert len(options) > 16, len(options)
    preferred = list(question.get("preferred") or [])
    assert preferred and set(preferred) <= set(options), (preferred, options[:3])
    labels = question.get("labels") or {}
    assert all(str(labels.get(option, "")).startswith("Slip to ") for option in options), list(labels.items())[:3]
    assert question.get("name") == "Shadow Exchange"


def test_declining_the_ally_slip_question_spends_nothing_and_the_attack_proceeds():
    """Finding 3: the question is asked before the Chi and the reaction are paid, so declining costs nothing."""
    engine = _ally_duel(DIM_MAP)
    ally = engine.state.actors[ALLY]
    subject = engine.state.actors[L4.SUBJ]
    pool, before = _cp(ally)
    start = (subject.position.x, subject.position.y)
    asked = []
    engine._gate4_reaction_provider = _ally_provider(asked, None)
    L4._script(engine, [15, 6])
    L4._use(engine, "Fu (Short Axe) attack")

    assert _slip_question(asked)
    assert (subject.position.x, subject.position.y) == start
    assert ally.reaction_available
    assert _cp(ally) == (pool, before)


def test_accepting_the_ally_slip_question_pays_once_and_moves_the_creature_to_the_chosen_square():
    """Accepting pays the cost and the reaction once and places SUBJ on the square the owner picked."""
    probe = _ally_duel(DIM_MAP)
    asked = []
    probe._gate4_reaction_provider = _ally_provider(asked, None)
    L4._script(probe, [15, 6])
    L4._use(probe, "Fu (Short Axe) attack")
    pick = list(_slip_question(asked).get("needle_options") or [])[-1]

    engine = _ally_duel(DIM_MAP)
    ally = engine.state.actors[ALLY]
    subject = engine.state.actors[L4.SUBJ]
    pool, before = _cp(ally)
    engine._gate4_reaction_provider = _ally_provider([], pick)
    L4._script(engine, [15, 6])
    L4._use(engine, "Fu (Short Axe) attack")

    x, y = (int(part) for part in pick.split(":")[1].split(","))
    assert (subject.position.x, subject.position.y) == (x, y)
    assert not ally.reaction_available
    assert _cp(ally) == (pool, before - 4)


# ========================================================================= Finding 4: a light on a Dim or Dark map
TORCH = {"id": "l1", "name": "Torch", "x": 2, "y": 2, "bright_ft": 10, "dim_ft": 0}


def _lit_map(ambient_level, lights=(TORCH,)):
    return {"tabletop": {"ambient": {"time_of_day": "night", "level": ambient_level}, "lights": list(lights)}}


def test_a_torch_lit_square_on_a_dim_map_is_bright_not_a_shadowed_space():
    """Finding 4 (F1R2): the Dim ambient made every square a Shadowed Space, including the squares a torch lights to
    Bright. The lit squares are Bright and are not Shadowed Spaces; the unlit far corner still is.
    Before the fix the torch square (2,2) was in the set."""
    engine = L4._duel([], subject_sphere=SHADOW, attacker_kit=L4.t.AXE_KIT)
    engine.battlefield_document = _lit_map("dim")
    subject = engine.state.actors[L4.SUBJ]
    cells = _shadowed_cells(engine, subject)
    far = (engine.grid.width - 1, engine.grid.height - 1)
    assert (2, 2) not in cells
    assert far in cells
    from combat.lighting import BRIGHT, base
    assert base(engine, 2, 2) == BRIGHT


def test_a_torch_lit_square_on_a_dark_map_is_bright_not_a_shadowed_space():
    """Finding 4 (F1R2), Darkness: a light source still lights its own squares on a Dark map."""
    engine = L4._duel([], subject_sphere=SHADOW, attacker_kit=L4.t.AXE_KIT)
    engine.battlefield_document = _lit_map("dark")
    subject = engine.state.actors[L4.SUBJ]
    cells = _shadowed_cells(engine, subject)
    assert (2, 2) not in cells
    assert (engine.grid.width - 1, engine.grid.height - 1) in cells


def test_darkness_zone_cells_are_shadowed_on_a_bright_map():
    """Darkness zones use visual.darkness, not a nonexistent heavily_obscured flag."""
    from types import SimpleNamespace
    from combat.ext.shadowed_space import _dim_cells

    engine = L4._duel([], subject_sphere=SHADOW, attacker_kit=L4.t.AXE_KIT)
    engine.battlefield_document = BRIGHT_MAP
    zone = SimpleNamespace(active=True, trigger_profile={"visual": {"darkness": True}},
                           affected_cells=(type(engine.state.actors[L4.SUBJ].position)(x=8, y=4),))
    original = engine.state.zones
    engine.state.zones = {"darkness": zone}
    try:
        assert (8, 4) in _dim_cells(engine)
    finally:
        engine.state.zones = original


def test_no_reviewer_note_claims_an_undeclared_map_leaves_every_square_a_shadowed_space():
    """Finding 2 (F1R2): the five Shadow records' reviewer notes said a fight that declares no light keeps every square a
    legal Shadowed Space. Shipped behaviour is the opposite: an undeclared map is Bright and contributes no Dim or Dark
    square. The stale sentence must be gone from every reviewed-final note."""
    stale = "every square stays a legal Shadowed Space"
    notes = sorted((ROOT / "authority/typed_mechanics/reviewed_final.d").glob("*.json"))
    assert notes
    hits = [p.name for p in notes if stale in p.read_text(encoding="utf-8")]
    assert hits == [], hits
