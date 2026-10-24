"""Sphere typing review, sweep batch sw-weather (Weather, Wrestling, Yang; 2026-09-28).

Every test compiles a corrected talent from the shipped typed authority and runs it through a real fight. Each one fails on the typing
this review replaced (the authority at commit 58231d8) -- the sort of error only a fight shows: an ability offered when its printed
target condition is unmet, a save rolled with the wrong ability, a zone that blinds and marks the enemy, a Reaction that heals 1 Hit
Point instead of holding a creature at 1, a Kindled Mark that lands on the attacker.
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_reactions
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ALLY = "actor:factory.ally"
FAILS, PASSES = 30, 1  # technique_save_dc: the foe's saves top out at +4, so 30 always fails and 1 always passes
TOUGH = 900  # foe Hit Points that a 10d10 hit cannot empty
_AUTH = json.loads(TYPED_AUTHORITY.read_text())["mechanics"]


def _bases(sphere_id):
    return [k for k, v in _AUTH.items() if v.get("sphere_id") == sphere_id and v["kind"] == "base_ability" and "#" not in k]


@lru_cache(maxsize=None)
def _compiled(sphere, talents, cl=20, dc=FAILS):
    sid = f"tianxia.sphere.{sphere}"
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    sheet = {**SHEET, "equipment": [], "identity": {**SHEET["identity"], "cultivation_level": cl}, "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sid], "automatic_sphere_component_record_ids": _bases(sid),
                                     "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=ME)


@lru_cache(maxsize=None)
def _ally_bundle():
    sheet = {**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    return compile_character(sheet, actor_id=ALLY)


def _fight(bundle, ally=False, foe_at=(4, 6)):
    """The caster and a foe (the shared support-fight setup), plus an ally of the caster's when asked."""
    if not ally:
        return _engine(copy.deepcopy(bundle), foe_at=foe_at)
    engine = Gate4ControllerEngine(ROOT, match_seed="SWWEATHER", typed_bundles=(copy.deepcopy(bundle), copy.deepcopy(_ally_bundle())),
                                   roster_setup={"primary_actor_ids": [ME, ALLY, AN], "team_by_actor": {ME: "team:a", ALLY: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _cast(engine, prefix, target=None):
    """Use the offered candidate whose name starts with ``prefix`` (aimed at ``target`` when given, else nearest the foe)."""
    foe = engine.state.actors[AN].position
    where = lambda c: 0 if c.destination is None else abs(c.destination.x - foe.x) + abs(c.destination.y - foe.y)
    found = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix) and (target is None or target in c.target_ids)]
    assert found, f"{prefix} is not offered"
    c = min(found, key=where)
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
                                       actor_id=ME, target_ids=c.target_ids, destination=c.destination))


def _offered(engine):
    return sorted({c.display_name for c in engine.legal_candidates() if not c.display_name.startswith("Move to")})


def _conds(actor):
    return sorted((c.condition_id.removeprefix(CONDITION_PREFIX), c.expires_on) for c in actor.conditions.values())


def _names(actor):
    return [name for name, _ in _conds(actor)]


def _events(engine, *kinds):
    return [event for event in engine.events if event.event_type in kinds]


def _grapple(engine):
    engine._apply_condition(engine.state.actors[AN], CONDITION_PREFIX + "grappled", "test:grapple", ME, expires_on="UNTIL_REMOVED")


def _row(bundle, prefix):
    rows = [r for r in bundle["action_catalog"] if r["display_name"].startswith(prefix)]
    assert rows, f"{prefix} is not an action of this build"
    return rows[0]


def _hit(engine, who, damage=30):
    return typed_reactions.on_damage(engine, who, damage, 0, source_definition_id="action:test.attack", source_actor_id=AN)


def _kindled(owner=ME):
    return f"mark.kindled_mark.{owner}"


# ------------------------------------------------------------------ Weather
def test_four_season_reversal_is_immunity_once_per_long_rest():
    # "Use Limit: Once per Long Rest ... You gain immunity to the triggering damage and condition until the end of the current turn."
    # Typed as an unlimited damage_modifier "half": the hit still hurt, and it answered every hit.
    bundle = _compiled("weather", ("TAL_WEATHER_FOUR_SEASON_REVERSAL",))
    assert next(r for r in bundle["typed_reactions"] if r["feature_id"] == "TAL_WEATHER_FOUR_SEASON_REVERSAL")["use_limit"] == "once_per_long_rest"
    engine = _fight(bundle)
    me = engine.state.actors[ME]
    assert _hit(engine, me, 20) == 0
    me.reaction_available = True
    assert _hit(engine, me, 20) == 20  # the once-per-long-rest use is spent


def test_heaven_breaks_the_banner_is_its_own_nine_cp_once_per_long_rest_action():
    # "Cost: 6 additional CP ... Use Limit: Once per Long Rest ... Creatures in a 10-foot-radius sphere ... Dexterity save: 10d10 lightning
    # and Stunned until the end of its next turn; on a success, half damage and not Stunned." It rode on Stormlord's Finger as a free,
    # passive 10-foot area upgrade with the Finger's own save.
    talents = ("TAL_WEATHER_STORMLORD_S_FINGER", "TAL_WEATHER_HEAVEN_BREAKS_THE_BANNER")
    bundle = _compiled("weather", talents)
    row = _row(bundle, "Heaven Breaks the Banner")
    assert row["costs"][0] == ["resource:core.qi", 9]
    assert row["costs"][1][0].startswith("resource:uses.action:")  # once per long rest
    assert row["parameters"]["typed"]["area"]["size_ft"] == 10
    assert _row(bundle, "Stormlord")["parameters"]["typed"]["area"]["size_ft"] == 5  # the Finger keeps its own 5-foot area
    for dc, stunned in ((FAILS, True), (PASSES, False)):
        engine = _fight(_compiled("weather", talents, dc=dc))
        foe = engine.state.actors[AN]
        foe.maximum_hp = foe.current_hp = TOUGH
        _cast(engine, "Heaven Breaks")
        roll = _events(engine, "DAMAGE_ROLLED")[-1].payload
        assert roll["expression"].startswith("10d10")
        assert TOUGH - foe.current_hp == (roll["total"] if stunned else roll["total"] // 2)
        assert ("stunned" in _names(foe)) is stunned
        assert "Heaven Breaks the Banner" not in _offered(engine)  # once per long rest


# ---------------------------------------------------------------- Wrestling
GRAPPLE_ONLY = {"Heaven-Lifting Throw": "TAL_WRESTLING_HEAVEN_LIFTING_THROW", "Mountain-Crashing Suplex": "TAL_WRESTLING_MOUNTAIN_CRASHING_SUPLEX",
                "Pin": "TAL_WRESTLING_PIN_2", "Ground Game": "TAL_WRESTLING_GROUND_GAME"}


@pytest.mark.parametrize("name", sorted(GRAPPLE_ONLY))
def test_grapple_techniques_are_offered_only_against_a_creature_grappled_by_you(name):
    # "Target: One creature Grappled by you" (Throw, Suplex, Pin) / "grappling" (Ground Game): they were offered against any foe.
    engine = _fight(_compiled("wrestling", (GRAPPLE_ONLY[name],)))
    assert name not in _offered(engine)
    _grapple(engine)
    if name == 'Ground Game':
        # "When you begin your turn grappling one creature": establishing the
        # grapple during this turn is insufficient. Start the next real turn.
        assert name not in _offered(engine)
        engine.end_turn()
        while engine.state.current_actor_id != ME:
            engine.end_turn()
    assert name in _offered(engine)


def test_ground_game_is_a_bonus_action_save_that_knocks_a_grappled_creature_prone():
    # "use a Bonus Action to force that creature to make a Strength or Dexterity saving throw, choosing which. Failed Save: Become
    # Prone. Successful Save: Remain standing." It was a turn-start Reaction that laid Prone with no saving throw at all.
    bundle = _compiled("wrestling", ("TAL_WRESTLING_GROUND_GAME",))
    assert "Ground Game" not in [r["name"] for r in bundle["typed_reactions"]]
    for bonus, prone in ((-40, True), (40, False)):
        # A Wrestling talent saves against the Wrestling Save DC (8 + Strength + Proficiency Bonus, "Wrestling Save DC and Escape DC";
        # rider lane C13), not technique_save_dc: the foe's own save bonus decides the outcome here.
        engine = _fight(_compiled("wrestling", ("TAL_WRESTLING_GROUND_GAME",)))
        _grapple(engine)
        engine.end_turn()
        while engine.state.current_actor_id != ME:
            engine.end_turn()
        engine.state.actors[AN].saving_throws.update({"STR": bonus, "DEX": bonus})
        _cast(engine, "Ground Game")
        assert ("prone" in _names(engine.state.actors[AN])) is prone


def test_slip_and_strike_deals_its_weapon_damage():
    # "when one creature fails to Grapple you, make one weapon attack ... against it as a Reaction": the attack was typed with no damage.
    engine = _fight(_compiled("wrestling", ("TAL_WRESTLING_SLIP_AND_STRIKE",)))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.armor_class = -50  # every roll but a natural 1 hits
    before = foe.current_hp
    typed_reactions.on_grapple_outcome(engine, foe, me, grabbed=False)
    assert foe.current_hp < before


def test_court_of_the_closed_distance_gives_advantage_not_free_movement():
    # Its movement line ("when one creature within reach misses you, move 5 feet toward it") is a triggered rider; typed as a plain
    # movement effect it granted 5 feet of movement every time the talent was used.
    engine = _fight(_compiled("wrestling", ("TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE",)))
    me = engine.state.actors[ME]
    feet = me.movement_remaining_ft
    _cast(engine, "Court of the Closed Distance")
    assert me.movement_remaining_ft == feet and not _events(engine, "MOVEMENT_GRANTED")
    assert "save_against" in _names(me)  # the Advantage half still applies


def test_grandstanding_slam_and_hard_whip_do_not_ride_every_technique():
    # Grandstanding Slam / Hard Whip are Slams applied through Apply a Slam, not upgrades of every technique: they added a
    # "+ Grandstanding Slam" copy of each Wrestling action and a second 10-foot forced movement to every Throw.
    talents = ("TAL_WRESTLING_CHOKE_HOLD", "TAL_WRESTLING_GRANDSTANDING_SLAM", "TAL_WRESTLING_HEAVEN_LIFTING_THROW",
               "TAL_WRESTLING_HARD_WHIP", "TAL_WRESTLING_PIN_2")
    bundle = _compiled("wrestling", talents)
    assert not [r["display_name"] for r in bundle["action_catalog"] if "Grandstanding" in r["display_name"]]
    throw = _row(bundle, "Heaven-Lifting Throw")
    assert [e["distance_ft"] for e in throw["parameters"]["typed"]["effects"] if e["type"] == "forced_movement"] == [60]
    assert [list(c) for c in _row(bundle, "Apply a Slam: Choke Hold")["costs"]] == [["resource:core.martial_focus", 1]]


@pytest.mark.parametrize("name,talent", [("Pin", "TAL_WRESTLING_PIN_2"), ("Impale", "TAL_WRESTLING_IMPALE"),
                                         ("The Hold Heaven Could Not Escape", "TAL_WRESTLING_THE_HOLD_HEAVEN_COULD_NOT_ESCAPE")])
def test_strength_or_dexterity_saves_use_the_creatures_better_save(name, talent):
    # Twin Tie-Up now needs two recipients; the equivalent committed-table
    # regression is test_a2_wrestling.test_twin_each_target_uses_its_chosen_save.
    # "Strength or Dexterity saving throw, choosing which": typed Strength-only, so a nimble foe was pinned by its weak save.
    engine = _fight(_compiled("wrestling", (talent,), dc=15))
    foe = engine.state.actors[AN]
    foe.saving_throws = {**foe.saving_throws, "STR": -30, "DEX": 30}
    _grapple(engine)
    _cast(engine, name)
    save = _events(engine, "SAVE_ROLLED")[0].payload
    assert save["reason"].endswith(":DEX") and save["success"]
    assert "restrained" not in _names(foe)


# --------------------------------------------------------------------- Yang
@pytest.mark.parametrize("talent,prefix", [("TAL_YANG_NOON_REVEALS_THE_HIDDEN_WORK", "Noon Reveals"),
                                           ("tianxia.talent.yang.yang_domain_court_of_unfinished_noon", "Yang Domain")])
def test_noon_and_domain_zones_neither_blind_nor_mark_the_enemy(talent, prefix):
    # The lines about enemies' Invisibility and Rising Marks are limits and triggers, not effects laid on every enemy when the zone opens:
    # the foe was made Invisible and Marked, and the zone carried mark triggers.
    bundle = _compiled("yang", (talent,))
    spec = _row(bundle, prefix)["parameters"]["typed"]["zone_spec"]
    assert spec["triggers"] == [] and spec["obscured"] is None
    engine = _fight(bundle)
    _cast(engine, prefix)
    assert _conds(engine.state.actors[AN]) == []


def test_no_seal_holds_the_sun_is_one_effect_free_action_that_denies_no_reactions():
    # Every outcome ends or damages a Barrier or seal; none of it is a creature's Reactions or Hit Points. It split into two options
    # and denied the foe its Reactions.
    bundle = _compiled("yang", ("TAL_YANG_NO_SEAL_HOLDS_THE_SUN",))
    rows = [r for r in bundle["action_catalog"] if r["display_name"].startswith("No Seal")]
    assert len(rows) == 1 and rows[0]["parameters"].get("inert")
    engine = _fight(bundle)
    _cast(engine, "No Seal")
    assert _conds(engine.state.actors[AN]) == []


def test_ten_thousand_motions_is_not_an_obscuring_zone():
    # "heavily obscured" is only a Rising Mark trigger in its text; the area itself is not obscured and nothing spends a mark at turn start.
    bundle = _compiled("yang", ("TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON",))
    spec = _row(bundle, "Ten-Thousand Motions")["parameters"]["typed"]["zone_spec"]
    assert spec["obscured"] is None and spec["triggers"] == []
    assert not spec["visual"].get("obscured")


def test_twofold_rising_never_marks_the_foe_by_itself():
    # It changes how Kindle the Rising / Rising Thread is used ("against two different willing targets"); typed as a mark it marked the foe.
    # AUTO136: AUTO35 automated both creature modes, so the ability is no longer inert -- it asks for two
    # different willing allies/self. What still has to hold is the printed rule: it never marks the foe itself.
    bundle = _compiled("yang", ("TAL_YANG_TWOFOLD_RISING",))
    assert not _row(bundle, "Twofold Rising")["parameters"].get("inert")
    engine = _fight(bundle)
    _cast(engine, "Twofold Rising")
    assert _conds(engine.state.actors[AN]) == []


@pytest.mark.parametrize("cl,dice", [(1, 1), (11, 2), (17, 3)])
def test_kindle_the_wounded_breath_aims_at_an_ally_and_heals_by_level(cl, dice):
    # "Choose one creature within range ... The target gains a Kindled Mark and regains 1d8 + Key Ability modifier. At CL 11 ... 2d8 ...
    # At CL 17 ... 3d8." The mark named the enemy as the target (so the ability could only be aimed at an enemy), the healing never scaled,
    # and the mark never expired.
    bundle = _compiled("yang", ("TAL_YANG_KINDLE_THE_WOUNDED_BREATH",), cl=cl)
    # AUTO136: the printed word is "Choose one creature within range", so AUTO35 widened the target to
    # ANY_CREATURE (with a living-target gate) rather than leaving it ally/self only.
    assert _row(bundle, "Kindle the Wounded")["target_kind"] == "ANY_CREATURE"
    engine = _fight(bundle, ally=True)
    foe, ally = engine.state.actors[AN], engine.state.actors[ALLY]
    ally.current_hp = 10
    _cast(engine, "Kindle the Wounded", target=ALLY)
    roll = _events(engine, "DAMAGE_ROLLED")[-1].payload
    assert roll["expression"].startswith(f"{dice}d8")
    assert ally.current_hp == 10 + roll["total"]
    assert (_kindled(), "END_OF_MARKER_NEXT_TURN") in _conds(ally)
    assert _conds(foe) == []


def test_life_refuses_closure_holds_the_ally_at_one_hit_point():
    # "The target gains a Kindled Mark and drops to 1 Hit Point instead of 0. Until the end of the target's next turn: Speed +10 ...":
    # typed as healing 1 (the ally still died: 5 + 1 Hit Points against a 30-point hit), with a Speed bonus that never ended.
    engine = _fight(_compiled("yang", ("TAL_YANG_LIFE_REFUSES_CLOSURE",)), ally=True)
    foe, ally = engine.state.actors[AN], engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4  # 5 Hit Points, held at 1
    assert (_kindled(), "END_OF_MARKER_NEXT_TURN") in _conds(ally)
    speed = [m for m in ally.modifiers.values() if m.target_field == "speed_ft"]
    assert [m.value for m in speed] == [10] and all(m.expires_on for m in speed)
    assert _conds(foe) == []


def test_dawn_commands_the_fallen_breath_holds_the_caster_or_the_ally_at_one_hit_point():
    # "The target drops to 1 Hit Point instead of dying and gains a Kindled Mark ... Until the end of the target's next turn ...":
    # healing 1 instead of a hold, and a "target" mark that landed on the attacker whenever the caster was the one dying.
    bundle = _compiled("yang", ("TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH",))
    engine = _fight(bundle, ally=True)
    foe, ally = engine.state.actors[AN], engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    # MGR-T15 1D1: the printed text is "gains a Kindled Mark that lasts for 1 minute", so the mark
    # now carries a clock expiry instead of never ending. The first-hit exception rides beside it.
    marks = [row for row in _conds(ally) if row[0] == _kindled()]
    from combat.ext import effect_durations
    assert marks and marks[0][1] == effect_durations.round_token(engine, 10)  # one minute = ten rounds
    assert any(row[0] == "yang_completion_exception" for row in _conds(ally))
    assert _conds(foe) == []
    assert [m.value for m in ally.modifiers.values() if m.target_field == "speed_ft"] == [20]
    engine = _fight(bundle, ally=True)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.current_hp = 5
    assert _hit(engine, me) == 4
    assert _conds(foe) == []


# ---------------------------------------------------------------- Authority
REVIEWED = ("TAL_WEATHER_FOUR_SEASON_REVERSAL", "TAL_WEATHER_HEAVEN_BREAKS_THE_BANNER", "TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE",
            "TAL_WRESTLING_GRANDSTANDING_SLAM", "TAL_WRESTLING_GROUND_GAME", "TAL_WRESTLING_HARD_WHIP", "TAL_WRESTLING_HEAVEN_LIFTING_THROW",
            "TAL_WRESTLING_IMPALE", "TAL_WRESTLING_MOUNTAIN_CRASHING_SUPLEX", "TAL_WRESTLING_PIN_2", "TAL_WRESTLING_SLIP_AND_STRIKE",
            "TAL_WRESTLING_THE_HOLD_HEAVEN_COULD_NOT_ESCAPE", "TAL_WRESTLING_TWIN_TIE_UP", "TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH",
            "TAL_YANG_KINDLE_THE_WOUNDED_BREATH", "TAL_YANG_LIFE_REFUSES_CLOSURE", "TAL_YANG_NOON_REVEALS_THE_HIDDEN_WORK",
            "TAL_YANG_NO_SEAL_HOLDS_THE_SUN", "TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON", "TAL_YANG_TWOFOLD_RISING",
            "tianxia.talent.yang.yang_domain_court_of_unfinished_noon")


def test_every_corrected_mechanic_still_carries_its_review():
    # A review entry is bound to the rules text's hash: if the owner edits a corrected talent's text, the builder stops applying its entry
    # and the old typing returns without a word. This names it.
    assert [k for k in REVIEWED if _AUTH[k]["typing_status"] != "reviewed_final"] == []
