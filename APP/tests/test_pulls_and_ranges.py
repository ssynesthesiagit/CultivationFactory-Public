"""Hunt 3 (2026-09-29), bugs 1, 7 and 8: pulls that ran as pushes, "reduce forced movement" typed as free movement, and ranges the
parser never read.

1. A forced_movement row without a ``direction`` moves its target away from the caster, and the models' rows have no direction, so
   Chain Counter, Chain Lash, Wind Lash, Cyclone Prison, Collapsing Gap and Gate of the Inner Sea "pulled" by pushing.  The build now
   reads the direction off the printed words (factory_authoring/typed_structure.derive_forced_movement_directions): "toward you" and
   "away from you" are the caster, "toward the center" and "away from the point of origin" are the centre of the area the effect fills
   (combat/typed_executor passes it through as ``_area_centre``; combat/zones does the same for a zone's triggers).
2. "Reduce forced movement affecting you by 10 feet" was typed as ``movement`` and granted free movement (Chain Armor +10 feet, Deep Root
   Stance -5).  The engine reduces a push or pull only in the forced_moved reaction, so the row is now a GM rider
   (typed_structure.movement_that_reduces_forced_movement).
3. Ember Talisman ("Range: 60 feet") and Binding Talisman ("Range: 30 feet, or thrown 20/60 feet") print Rank / Family / Activation lines
   above their Range; every unrecognised header line ended the header, so the range was never read and the attack was classed melee
   (5 feet).  factory_authoring/typed_mechanics.parse_header now knows those lines.

The engine tests run the real authority through the real compiler; the old rows are checked against the build's own passes.
"""

import copy
import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

import combat.factory_compiler as factory_compiler
from combat import typed_executor, typed_reactions, zones
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from factory_authoring import typed_structure
from factory_authoring.typed_mechanics import _range, parse_header, type_mechanic
from tests import test_forced_movement_reactions as pushes
from tests import test_zones

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.pulls"
FAIL, PASS = 50, -40  # technique save DC that makes the foe fail / succeed every save
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
CHAINS, VOID, TALISMANS, EARTH = ("tianxia.sphere.chains", "tianxia.sphere.void", "tianxia.sphere.talismans", "tianxia.sphere.earth")
CHAIN_COUNTER, CHAIN_ARMOR = "tianxia.talent.chains.chain_counter", "tianxia.talent.chains.chain_armor"
COLLAPSING_GAP, DEEP_ROOT_STANCE = "TAL_VOID_COLLAPSING_GAP", "TAL_EARTH_DEEP_ROOT_STANCE"
EMBER, BINDING = "tianxia.talent.talismans.ember_talisman", "tianxia.talent.talismans.binding_talisman"


# ------------------------------------------------------------------------------------------------------- harness


@lru_cache(maxsize=1)
def _authority() -> dict:
    return json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"]


@lru_cache(maxsize=1)
def _printed() -> dict:
    return json.loads((ROOT / "authority" / "typed_mechanics" / "rules_text.json").read_bytes())


def _sheet(sphere: str, talents: list[str], *, dc: int = 16) -> dict:
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 80},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [KIT],
        "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": list(talents),
                                "automatic_sphere_component_record_ids": []},
    }


def _bundle(sphere: str, talents: list[str], *, dc: int = 16, **kwargs) -> dict:
    return compile_character(_sheet(sphere, talents, dc=dc), actor_id=ME, **kwargs)


def _engine(bundle: dict, *, foe_at: tuple[int, int]) -> Gate4ControllerEngine:
    """The caster at 3,6 on its own turn (every action ready), the foe at ``foe_at`` with an AC nothing misses."""
    engine = Gate4ControllerEngine(ROOT, match_seed="PULLS", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50
    me = engine.state.actors[ME]
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return engine


def _use(engine: Gate4ControllerEngine, name: str, *, aim: tuple[int, int] | None = None) -> list:
    """Uses the legal action ``name`` (an area action: the one aimed at ``aim``); returns the events it produced."""
    legal = [c for c in engine.legal_candidates() if c.display_name == name or (aim and c.display_name.startswith(f"{name} at "))]
    if aim:
        legal = [c for c in legal if c.destination is not None and (c.destination.x, c.destination.y) == aim]
    assert legal, f"{name!r} (aim {aim}) is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates()})[:24]}"
    candidate = legal[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=candidate.target_ids or (), destination=candidate.destination))
    return engine.events[before:]


def _kinds(events: list) -> list[str]:
    return [e.event_type for e in events]


def _at(engine: Gate4ControllerEngine) -> tuple[int, int]:
    foe = engine.state.actors[AN]
    return foe.position.x, foe.position.y


# ------------------------------------------------------------------------------------------------ bug 1: pulls


def test_chain_counter_pulls_the_attacker_it_answers_toward_the_holder():
    """"Pull 10 Feet": the attacker two squares away ended three squares farther, pushed 10 feet away from the chain that caught it.
    The pull stops against the holder instead of running on (the holder's square is taken)."""
    options = _authority()[CHAIN_COUNTER]["options"]
    pick = next(i for i, option in enumerate(options) if option["label"] == "Pull 10 Feet")
    for dc, label in ((FAIL, "failed save: 10 feet"), (PASS, "successful save: 5 feet")):
        bundle = _bundle(CHAINS, [CHAIN_COUNTER], dc=dc, reaction_plan={"options": {CHAIN_COUNTER: pick}})
        engine = _engine(bundle, foe_at=(5, 6))  # the holder is at 3,6: the attacker is 10 feet off, inside the reaction's range
        engine.state.current_actor_id = AN
        before = len(engine.events)
        typed_reactions.on_d20_pending(engine, engine.state.actors[AN], "attack")
        events = engine.events[before:]
        assert "REACTION_RESOLVED" in _kinds(events) and "MOVEMENT_COMMITTED" in _kinds(events), label
        assert _at(engine) == (4, 6), label  # pulled toward the holder; a push would have left it at 7,6 (or 6,6)
        assert not engine.state.actors[ME].reaction_available


def test_collapsing_gap_pulls_toward_the_centre_and_stops_on_it():
    """"Pull the creature up to 20 feet toward the center" of the 20-foot sphere it is aimed at.  The pull is measured from the
    point the sphere is aimed at, not from the caster, and a creature that reaches the centre stops there."""
    for aim, foe_at, dc, expected in (
        ((8, 6), (11, 6), FAIL, (8, 6)),   # 15 feet from the centre, pulled up to 20: it arrives (the caster is on the far side)
        ((13, 6), (11, 6), FAIL, (13, 6)),  # the centre lies beyond the foe: pulled away from the caster, toward the centre
        ((9, 5), (11, 6), FAIL, (9, 5)),   # diagonal: one step each way, then along the column
        ((8, 6), (11, 6), PASS, (10, 6)),  # a successful save pulls 5 feet
    ):
        engine = _engine(_bundle(VOID, [COLLAPSING_GAP], dc=dc), foe_at=foe_at)
        engine.grid.qi_hazard.clear()  # Isolate the intended centre/distance geometry.
        events = _use(engine, "Collapsing Gap", aim=aim)
        assert "MOVEMENT_COMMITTED" in _kinds(events), (aim, foe_at, dc)
        assert _at(engine) == expected, (aim, foe_at, dc)


def test_a_zone_trigger_pulls_toward_the_centre_of_its_zone():
    """Cyclone Prison and Gate of the Inner Sea leave zones that pull "toward the center": a zone's trigger has no aim point of its
    own, so the zone's centre is what the pull is measured from (combat/zones._run)."""
    engine = test_zones._engine()
    test_zones._cast(engine, "Ashfall", Position(x=13, y=6))
    [zone] = zones.typed_zones(engine)
    foe = engine.state.actors[AN]
    foe.position = Position(x=16, y=6)
    pull = {"id": "test:pull", "name": "Pull", "effects": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10,
                                                            "direction": "toward_center", "evidence": "pulled 10 feet toward the center"}]}
    zones._run(engine, zone, foe, pull, "test")
    assert (foe.position.x, foe.position.y) == (14, 6)  # the owner is at 3,6: an undirected push would have run it out to 18,6


def _pusher(engine: Gate2Engine, *, caster: tuple[int, int], centre: tuple[int, int] | None) -> typed_executor.Context:
    engine.state.actors[LEE].position = Position(x=0, y=0)  # out of the way
    engine.state.actors[AN].position = Position(x=caster[0], y=caster[1])
    actor = engine.state.actors[AN]
    action = next(engine.action_catalog[a] for a in actor.action_ids)
    typed = {"numbers": {}, "effects": []}
    if centre:
        typed["_area_centre"] = centre
    return typed_executor.Context(engine, actor, action, None, typed, [], None, {})


@pytest.mark.parametrize("pull, centred, caster, centre, expected", [
    # the target stands at 9,6 and is moved up to four squares
    (True, True, (12, 6), (6, 6), (6, 6)),    # toward the centre: arrives after three squares, and stops there
    (True, False, (12, 6), (6, 6), (11, 6)),  # toward the caster instead (the same row, no centre asked for): stops against it
    (False, True, (2, 6), (12, 6), (5, 6)),   # away from the centre (east of it): four squares west, past the caster's side
    (False, False, (2, 6), (12, 6), (13, 6)),  # away from the caster (west of it): four squares east, through the centre
    (True, True, (12, 6), None, (11, 6)),     # centred, but the effect has no centre (a line, a cone, one target): the caster
])
def test_a_push_or_pull_aims_at_the_caster_or_the_centre_of_the_area(pull, centred, caster, centre, expected):
    engine = pushes._engine([])
    engine.grid.qi_hazard.clear()  # Isolate direction and distance from damaging terrain.
    ctx = _pusher(engine, caster=caster, centre=centre)
    target = engine.state.actors[pushes.REACTOR]
    target.position = Position(x=9, y=6)
    typed_executor._push(ctx, target, 20, pull=pull, centred=centred)
    assert (target.position.x, target.position.y) == expected


def test_a_pull_stops_when_it_reaches_the_creature_pulling():
    engine = pushes._engine([])
    ctx = _pusher(engine, caster=(6, 6), centre=None)
    target = engine.state.actors[pushes.REACTOR]
    target.position = Position(x=9, y=6)
    typed_executor._push(ctx, target, 30, pull=True)  # six squares asked, the caster stands three away
    assert (target.position.x, target.position.y) == (7, 6)  # ... and its square is taken


# ---------------------------------------------- bug 1: the build reads the direction from the printed words


def _direction(evidence: str, text: str = "") -> tuple[str | None, str]:
    return typed_structure.forced_movement_direction(evidence, typed_structure._read(text).lines)


@pytest.mark.parametrize("evidence, text, expected", [
    ("Pull the target 5 feet toward you", "", ("toward", "evidence")),
    ("pulled 10 feet toward the center", "", ("toward_center", "evidence")),
    ("Push the target 10 feet away from you", "", ("away", "evidence")),
    ("push it 10 feet away from the point of origin", "", ("away_center", "evidence")),
    # the row's own quote names no direction: the phrase after the same verb in the ability's printed line
    ("pull the target 10 feet", "Failed Save: pull the target 10 feet toward you.", ("toward", "line")),
    ("Pull it 15 feet.", "Failed Save: Pull it 15 feet toward the center.\nSuccessful Save: Pull it 5 feet.", ("toward_center", "line")),
    # a push or a pull that names no direction anywhere
    ("push the target 10 feet", "", ("away", "bare")),
    ("pull the target 10 feet", "", ("toward", "bare")),
    # words that do not settle it are left open, and say why
    ("push or pull the target 10 feet", "", (None, "push-or-pull")),
    ("reduce forced movement against you by 10 feet", "", (None, "modifier")),
    ("Pull the creature 10 feet toward the damaged creature", "", (None, "other-anchor")),
    ("move the target 5 feet", "", (None, "reposition")),
    ("push the target 10 feet in a direction of your choice", "", (None, "other-way")),
])
def test_the_printed_words_give_the_direction(evidence, text, expected):
    assert _direction(evidence, text) == expected


def test_a_phrase_after_another_verb_is_that_verbs_not_the_pulls():
    text = "Pull the target 10 feet, then move yourself 20 feet toward it."
    assert _direction("Pull the target 10 feet", text) == ("toward", "bare")  # "toward it" belongs to "move yourself"


def test_a_pull_toward_two_different_anchors_is_left_open():
    text = "Pull the target 15 feet toward you or toward one anchored point you can see."
    assert _direction("pull the target up to 15 feet toward you or toward one anchored point you can see", text)[0] is None


def _mechanic() -> dict:
    row = lambda evidence, **extra: {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "evidence": evidence, **extra}  # noqa: E731
    return {"mechanic_id": "M", "effects": [{"type": "save", "on_fail": [row("pull the target 10 feet")],
                                             "on_success": [row("push or pull the target 5 feet")]}],
            "options": [{"label": "kept", "effects": [row("pull the target 5 feet", direction="away")]}],
            "modifier": {"effects": [row("Push the target 10 feet away from you")]}}


def test_the_pass_directs_every_row_it_can_and_keeps_the_rest_as_they_were():
    mechanic = _mechanic()
    looked = typed_structure.derive_forced_movement_directions(mechanic, "Failed Save: pull the target 10 feet toward you.")
    assert mechanic["effects"][0]["on_fail"][0]["direction"] == "toward"  # from the printed line
    assert "direction" not in mechanic["effects"][0]["on_success"][0]  # "push or pull": the words leave it open
    assert mechanic["options"][0]["effects"][0]["direction"] == "away"  # an explicit direction is never overwritten
    assert mechanic["modifier"]["effects"][0]["direction"] == "away"  # rows anywhere in the mechanic are read
    assert [(row["evidence"], why) for row, direction, why in looked if not direction] == [("push or pull the target 5 feet", "push-or-pull")]
    assert len(looked) == 3  # the explicitly directed row was not looked at


def test_the_passes_have_nothing_left_to_change_in_the_built_authority():
    """The committed authority is what the build produces: run the passes over it again and nothing moves."""
    printed, changed = _printed(), []
    for mid, mechanic in _authority().items():
        copied = copy.deepcopy(mechanic)
        text = printed.get(mid) or printed.get(mid.split("#")[0]) or ""
        changed += [(mid, row.get("evidence")) for row, direction, _ in typed_structure.derive_forced_movement_directions(copied, text) if direction]
        changed += [(mid, "reduction") for _ in typed_structure.movement_that_reduces_forced_movement(copied)]
    assert not changed, f"rebuild the authority (python tools/build_typed_mechanics_authority.py): {changed[:5]}"


def test_no_row_that_says_pull_toward_or_away_from_you_or_the_centre_says_the_opposite():
    checks = ((r"\btowards? (?:you|yourself)\b", "toward"), (r"\baway from (?:you|yourself)\b", "away"),
              (r"\btowards? (?:the|that|this) (?:[a-z0-9]+ ){0,4}?(?:center|centre)\b", "toward_center"),
              (r"\baway from (?:the|that|this) (?:[a-z0-9]+ ){0,4}?(?:center|centre|origin)\b", "away_center"))
    wrong = []
    for mid, mechanic in _authority().items():
        for row in typed_structure._forced_movement_rows(mechanic):
            words, direction = " ".join(str(row.get("evidence") or "").lower().split()), row.get("direction")
            if " or toward" in words or "push" in words and "pull" in words:
                continue  # two anchors, or a choice of pushing or pulling: left open on purpose
            if typed_structure._FM_ADJUSTS.search(words) and not typed_structure._FM_STARTS.match(words):
                continue  # "reduce the movement to 10 feet toward you" changes a move, it is not one
            wrong += [(mid, words, direction) for pattern, want in checks if re.search(pattern, words) and direction != want]
    assert not wrong, wrong[:6]


@pytest.mark.parametrize("mid, expected", [
    ("tianxia.talent.chains.chain_counter", {"toward"}),
    ("TAL_VOID_COLLAPSING_GAP", {"toward_center"}),
    ("tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea", {"toward_center"}),
    ("TAL_CHAINS_CHAIN_LASH_BASE", {"toward", "away"}),
    ("AIR_BASE_WIND_LASH", {"toward", "away"}),  # the Air review (sw-air) made its object-moving Scatter row a rider
])
def test_the_pulls_the_hunt_named_are_typed_as_pulls(mid, expected):
    assert {row.get("direction") for row in typed_structure._forced_movement_rows(_authority()[mid])} == expected


# ----------------------------------------------------- bug 7: "reduce forced movement" is not free movement


REDUCE = "reduce forced movement affecting you by 10 feet"


def test_chain_armor_and_deep_root_stance_grant_no_movement():
    """Chain Armor granted +10 feet of movement, Deep Root Stance -5: the row was typed ``movement``.

    Neither may hand out free movement. Chain Armor has since had its printed "reduce forced
    movement affecting you by 10 feet" resolved at the table (AUTO26: the Chains plug-in holds a
    ``chains_anchor`` reduction the engine applies on a push or pull), so its line is no longer a
    GM reminder; Deep Root Stance still has no reduction mechanism and keeps the printed words.
    """
    for sphere, talent, name, foe_at, still_a_rider in (
            (CHAINS, CHAIN_ARMOR, "Chain Armor", (8, 6), False),
            (EARTH, DEEP_ROOT_STANCE, "Deep Root Stance", (4, 6), True)):
        engine = _engine(_bundle(sphere, [talent]), foe_at=foe_at)  # (the stance is aimed at an adjacent creature)
        me = engine.state.actors[ME]
        speed = me.movement_remaining_ft
        events = _use(engine, name)
        assert "MOVEMENT_GRANTED" not in _kinds(events), name
        assert me.movement_remaining_ft == speed, name
        riders = " / ".join(str((getattr(e, "payload", None) or {}).get("rider")) for e in events if e.event_type == "GM_RIDER")
        assert ("reduce forced movement" in riders.lower()) is still_a_rider, name


def test_no_movement_row_in_the_authority_reduces_forced_movement():
    def rows(node):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from rows(value)
        elif isinstance(node, list):
            for value in node:
                yield from rows(value)

    left = [(mid, row["evidence"]) for mid, mechanic in _authority().items() for row in rows(mechanic)
            if row.get("type") == "movement" and typed_structure._REDUCES_FORCED_MOVEMENT.search(str(row.get("evidence") or ""))]
    assert not left, left


def test_the_reduction_pass_makes_the_row_a_gm_rider():
    mechanic = {"riders": ["Chains coil."], "effects": [{"type": "ac_bonus", "amount": 1, "evidence": "+1 AC"},
                                                       {"type": "movement", "distance_ft": 10, "applies_to": "self", "evidence": REDUCE}]}
    taken = typed_structure.movement_that_reduces_forced_movement(mechanic)
    assert [row["evidence"] for row in taken] == [REDUCE]
    assert [row["type"] for row in mechanic["effects"]] == ["ac_bonus"]
    assert mechanic["riders"] == ["Chains coil.", REDUCE]
    assert not typed_structure.movement_that_reduces_forced_movement(mechanic)  # nothing left to take, no second rider


def test_the_reduction_pass_leaves_a_move_that_is_a_move():
    move = {"type": "movement", "distance_ft": 10, "applies_to": "self", "evidence": "you may move 10 feet without provoking"}
    mechanic = {"riders": [], "effects": [dict(move)]}
    assert typed_structure.movement_that_reduces_forced_movement(mechanic) == []
    assert mechanic["effects"] == [move] and mechanic["riders"] == []


def test_the_reduction_pass_drops_a_row_the_ability_already_types_as_a_reduction():
    """Gravity Anchor Stance's reaction types the reduction as forced_movement (typed_reactions.on_forced_movement reads it)."""
    reduction = {"type": "forced_movement", "distance_ft": 10, "applies_to": "self", "evidence": f"you {REDUCE}"}
    mechanic = {"riders": [], "effects": [reduction, {"type": "movement", "distance_ft": 10, "applies_to": "self", "evidence": REDUCE}]}
    assert len(typed_structure.movement_that_reduces_forced_movement(mechanic)) == 1
    assert mechanic["effects"] == [reduction] and mechanic["riders"] == []


def test_the_reduction_pass_reads_options_and_modifiers():
    row = {"type": "movement", "distance_ft": 5, "applies_to": "self", "evidence": REDUCE}
    mechanic = {"riders": [], "effects": [], "options": [{"label": "Brace", "effects": [dict(row)]}],
                "modifier": {"effects": [dict(row)], "options": [{"label": "Hold", "effects": [dict(row)]}]}}
    assert len(typed_structure.movement_that_reduces_forced_movement(mechanic)) == 3
    assert mechanic["options"][0]["effects"] == [] and mechanic["modifier"]["effects"] == [] and mechanic["modifier"]["options"][0]["effects"] == []
    assert mechanic["riders"] == [REDUCE]  # said once


# ------------------------------------------------------------------------- bug 8: printed ranges are typed


def test_ember_talisman_is_a_ranged_attack():
    """"Range: 60 feet" was never read, so the attack had no range (5 feet), was legal only against an adjacent creature and counted
    as a melee attack to every reaction and AC bonus that asks."""
    bundle = _bundle(TALISMANS, [EMBER], dc=FAIL)
    assert next(row for row in bundle["action_catalog"] if row["display_name"] == "Ember Talisman")["range_ft"] == 60
    for guard, hits in (("armor_class_vs_melee", True), ("armor_class_vs_ranged", False)):
        engine = _engine(bundle, foe_at=(11, 6))  # 40 feet away
        engine.typed_actor_ids = {*engine.typed_actor_ids, AN}  # the engine asks a typed creature's AC guards (typed_reactions.on_attack_hit)
        foe = engine.state.actors[AN]
        engine._add_modifier(foe, "test:guard", guard, "ADD", 200, "SELF", expires_on="UNTIL_REMOVED")  # a guard against one kind only
        events = _use(engine, "Ember Talisman")
        rolled = next(e for e in events if e.event_type == "ATTACK_ROLLED")
        assert rolled.payload["natural_result"] != 20  # (a natural 20 hits through any guard: the seed above rolls a 7)
        assert ("DAMAGE_COMMITTED" in _kinds(events)) is hits, guard  # a ranged attack ignores the melee guard, and meets the other
        assert ("PASSIVE_TRIGGERED" in _kinds(events)) is not hits, guard


def test_binding_talisman_reaches_thirty_feet_and_no_farther():
    bundle = _bundle(TALISMANS, [BINDING], dc=FAIL)
    assert next(row for row in bundle["action_catalog"] if row["display_name"] == "Binding Talisman")["range_ft"] == 30
    near = _engine(bundle, foe_at=(9, 6))  # six squares: 30 feet
    events = _use(near, "Binding Talisman")
    assert "SAVE_ROLLED" in _kinds(events) and "typed.restrained" in {c.condition_id.removeprefix("condition:") for c in near.state.actors[AN].conditions.values()}
    far = _engine(bundle, foe_at=(10, 6))  # 35 feet
    assert "Binding Talisman" not in {c.display_name for c in far.legal_candidates()}


def test_no_printed_range_line_is_left_untyped():
    """Every "Range: N feet" the printed text gives an ability is its range.  (Daemonic Cultivation's bundled base abilities print it
    inside one of their sub-abilities, which is not the record's own range.)"""
    import re

    printed_range = re.compile(r"^[ \t]*Range:[ \t]*(\d+)[ \t]*(?:feet|ft)\b", re.I | re.M)
    untyped = {mid for mid, mechanic in _authority().items()
               if mechanic.get("range") is None and printed_range.search(_printed().get(mid) or "")}
    assert untyped == {"TAL_DAEMONIC_CULTIVATION_BASE_SPHERE_ABILITIES"}, untyped


@pytest.mark.parametrize("mid, feet", [(EMBER, 60), (BINDING, 30), ("TAL_ALCHEMY_EXPLOSIVE_PILL", 60)])
def test_the_authority_types_the_range_the_header_prints(mid, feet):
    assert _authority()[mid]["range"]["feet"] == feet and _authority()[mid]["range"]["kind"] in ("feet", "special")


def test_a_header_printed_beneath_label_lines_still_gives_its_range():
    ember = _printed()[EMBER]  # Rank / Family / Activation lines above Range, Target and Consumed
    header, body = parse_header(ember.splitlines())
    assert header == {"range": "60 feet", "target": "one creature or object"}
    assert body[0] == "You learn the Ember Talisman formula." and not any(line.startswith(("Rank", "Family", "Consumed")) for line in body)
    mechanic = type_mechanic(EMBER, "Ember Talisman", ember, kind="talent", sphere_id="s", source={"text_sha256": "h"})
    assert mechanic["range"] == {"kind": "feet", "feet": 60} and mechanic["target"] == {"text": "one creature or object"}


def test_a_second_cost_line_does_not_close_the_header_before_its_range():
    """Explosive Pill prints an Ingredient "Cost:" and then a Refinement "Cost:" above its Action Type, Range and Area."""
    pill = _printed()["TAL_ALCHEMY_EXPLOSIVE_PILL"]
    mechanic = type_mechanic("PILL", "Explosive Pill", pill, kind="talent", sphere_id="s", source={"text_sha256": "h"})
    assert mechanic["range"] == {"kind": "feet", "feet": 60}
    assert mechanic["area"] == {"shape": "sphere", "size_ft": 10, "centered_on_self": False}


def test_a_field_after_an_intro_still_belongs_to_the_header_but_only_a_few_lines_after():
    lines = ["Intro one.", "Intro two.", "Range: 30 feet", "Body."]
    assert parse_header(lines)[0] == {"range": "30 feet"}
    lines = ["Intro one.", "Intro two.", "Intro three.", "Intro four.", "Range: 30 feet"]
    assert parse_header(lines)[0] == {}  # too far down: a sentence of the body that happens to start with the word


@pytest.mark.parametrize("value, expected", [
    ("A point within 60 feet", {"kind": "feet", "feet": 60}),
    ("An unoccupied space within 120 feet", {"kind": "feet", "feet": 120}),
    ("within 30 feet of you", {"kind": "feet", "feet": 30}),
    ("60 feet", {"kind": "feet", "feet": 60}),
    # two reaches, or a second distance, are the ability's own condition: left as text, not guessed
    ("Melee reach or 60 feet", {"kind": "special", "feet": None, "text": "Melee reach or 60 feet"}),
    ("30/90 feet", {"kind": "special", "feet": None, "text": "30/90 feet"}),
])
def test_a_range_written_as_within_n_feet_is_that_many_feet(value, expected):
    assert _range(value) == expected
