"""Automation lane 3 of 3 (owner 2026-09-29: "i want everything we can automated"): abilities that carried only GM text (coverage
RIDERS_ONLY) now run through the engine.  Each test compiles a real character with the ability and uses it in a fight, and each
fails on the typing the authority carried before (overrides: authority/typed_mechanics/reviewed_final.d/auto_lane3.json; plug-ins:
combat/ext/repeat_saves.py ...).  Saves are forced with the sheet's technique DC (50: the foe fails, -40: it succeeds).
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
H = importlib.import_module("test_review_sw-athletics")  # the shared harness: _bundle, _engine, _use, ...
ME, AN, FAIL, PASS = H.ME, H.AN, H.FAIL, H.PASS
APP = Path(__file__).resolve().parents[1]

NO_KIT = {"starting_kit": {"items": []}}
SOUND, DREAMS = "tianxia.sphere.sound", "tianxia.sphere.dreams"
BELL, NIGHTMARE = "TAL_SOUND_BELL_OF_CLARITY", "TAL_DREAM_NIGHTMARE_GLIMPSE"


def _bell_engine():
    return H._engine(H._bundle(SOUND, [BELL], NO_KIT, cl=10))


def _frighten(engine, dc, ability="WIS", data_key="origin_save"):
    me = H._me(engine)
    engine._apply_condition(me, "condition:typed.frightened", "test:fear", AN, expires_on="UNTIL_REMOVED",
                            data={data_key: {"ability": ability, "dc": dc}})
    return me


# ------------------------------------------------------------------------------------------------------------ Sound


def test_bell_of_clarity_repeats_the_save_that_imposed_frightened():
    """"Each target may immediately repeat one saving throw against Charmed, Frightened, Deafened ... On a success, the effect
    ends": it was GM text only (no action effect)."""
    engine = _bell_engine()
    me = _frighten(engine, PASS)
    events = H._use(engine, "Bell of Clarity", target=ME)
    assert "typed.frightened" not in H._conditions(me)
    assert H._payloads(events, "SAVE_ROLLED")
    assert any(p.get("bell_of_clarity") for p in H._payloads(events, "CONDITION_REMOVED"))


def test_bell_of_clarity_failed_repeat_keeps_the_condition():
    engine = _bell_engine()
    me = _frighten(engine, FAIL)
    events = H._use(engine, "Bell of Clarity", target=ME)
    assert H._payloads(events, "SAVE_ROLLED") and "typed.frightened" in H._conditions(me)


def test_bell_of_clarity_needs_a_saving_throw_to_repeat():
    """A Frightened with no save behind it has nothing to repeat, and the bell is not offered when nobody can use it."""
    engine = _bell_engine()
    assert "Bell of Clarity" not in H._legal(engine)
    me = H._me(engine)
    engine._apply_condition(me, "condition:typed.frightened", "test:fear", AN, expires_on="UNTIL_REMOVED")
    assert "Bell of Clarity" not in H._legal(engine)
    _frighten(engine, PASS)
    assert "Bell of Clarity" in H._legal(engine)


def test_a_condition_a_failed_save_imposes_remembers_its_save():
    """block_save hands the save it rolled to block_condition: the bell repeats that ability and DC."""
    engine = H._engine(H._bundle(DREAMS, [NIGHTMARE], NO_KIT, cl=10, dc=FAIL))
    # "Choose one creature bearing your Dream Seed or currently Drowsy" (rider lane C5)
    engine._apply_condition(H._foe(engine), "condition:typed.mark.dream_seed." + ME, "test:seed", ME, expires_on="UNTIL_REMOVED")
    H._use(engine, "Nightmare Glimpse")
    frightened = [c for c in H._foe(engine).conditions.values() if c.condition_id == "condition:typed.frightened"]
    assert frightened and frightened[0].data["origin_save"] == {"ability": "WIS", "dc": FAIL}


# --------------------------------------------------------------------------------------------------------- Berserker

BERSERKER, SAVAGE = "tianxia.sphere.berserker", "TAL_BERSERKER_SAVAGE"
FOCUS = "resource:core.martial_focus"
FU = "Fu (Short Axe) attack"


def _melee(bundle, *, foe_hp, foe_at=(4, 6)):
    """ME against a weak foe (AN, foe_hp) and a second one (FOE) that keeps the fight going after the first falls."""
    engine = H.Gate4ControllerEngine(H.ROOT, match_seed="LANE3", typed_bundles=(bundle, H.compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=H.FOE)),
                                     roster_setup={"primary_actor_ids": [ME, AN, H.FOE], "team_by_actor": {ME: "team:a", AN: "team:b", H.FOE: "team:b"},
                                                   "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}, H.FOE: {"x": 8, "y": 9}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = H._foe(engine)
    foe.armor_class = -50
    foe.maximum_hp = max(foe_hp, foe.maximum_hp)
    foe.current_hp = foe_hp
    H._ready(engine)
    return engine


def _savage_engine(*, foe_hp=1):
    engine = _melee(H._bundle(BERSERKER, [SAVAGE], H.AXE_KIT, cl=10), foe_hp=foe_hp)
    H._me(engine).resources[FOCUS] = 0  # spent
    return engine


SAVAGE_BONUS = "Savage: Regain Martial Focus"


def _savage_kill(*, foe_hp=1, focus=0, level=None):
    engine = _savage_engine(foe_hp=foe_hp)
    H._me(engine).resources[FOCUS] = focus
    if level is not None:
        engine.typed_bundle_documents = (*engine.typed_bundle_documents, {"actor_id": AN, "cl": level})
    H._use(engine, FU)
    return engine


def test_savage_offers_focus_after_a_melee_kill():
    """"When you reduce an eligible creature to 0 HP with a melee or thrown weapon attack, use a Bonus Action to regain Martial
    Focus": a bare Bonus Action that regained nothing, always on offer, stood in for it."""
    engine = _savage_engine()
    assert "Savage" not in H._legal(engine) and SAVAGE_BONUS not in H._legal(engine)  # nothing killed yet
    H._use(engine, FU)
    assert not H._foe(engine).active
    assert SAVAGE_BONUS in H._legal(engine)
    H._use(engine, SAVAGE_BONUS, target=None)
    assert H._me(engine).resources[FOCUS] == 1


def test_savage_needs_a_kill_missing_focus_and_an_eligible_creature():
    assert SAVAGE_BONUS in H._legal(_savage_kill())  # the baseline that the cases below take away from
    hit_only = _savage_kill(foe_hp=500)
    assert H._foe(hit_only).active and SAVAGE_BONUS not in H._legal(hit_only)  # no kill
    assert SAVAGE_BONUS not in H._legal(_savage_kill(focus=1))  # already holds Martial Focus
    # "CR at least half your CL": a creature of known level 2 is under 5 (half of CL 10), one of level 5 is not.
    assert SAVAGE_BONUS not in H._legal(_savage_kill(level=2))
    assert SAVAGE_BONUS in H._legal(_savage_kill(level=5))


# ---------------------------------------------------------------------------------------------------------------- Music

MUSIC, ECHOING_STEP = "tianxia.sphere.music", "tianxia.talent.music.echoing_step"


def test_echoing_step_ignores_difficult_terrain_and_stops_one_creatures_opportunity_attack():
    """"Until the end of your turn: ignore nonmagical difficult terrain; do not provoke Opportunity Attacks from one creature":
    a bare Bonus Action that did neither stood in for it."""
    from combat import ext, motion, typed_reactions

    engine = _melee(H._bundle(MUSIC, [ECHOING_STEP], NO_KIT, cl=10), foe_hp=500, foe_at=(19, 13))  # the compiled foe is the nearer
    me, near, far = H._me(engine), engine.state.actors[H.FOE], engine.state.actors[AN]
    assert not motion.ignores_difficult(engine, me) and typed_reactions.wants_opportunity_attack(engine, near, me)
    H._use(engine, "Echoing Step", target=None)
    assert motion.ignores_difficult(engine, me)
    assert not typed_reactions.wants_opportunity_attack(engine, near, me)  # it makes no Opportunity Attack against the mover ...
    assert not ext.any_false("opportunity_allowed", engine, far, me)  # ... but only that one creature is spared
    engine.state.current_actor_id = AN  # the turn ends: nothing carries over
    assert not motion.ignores_difficult(engine, me) and typed_reactions.wants_opportunity_attack(engine, near, me)


# ----------------------------------------------------------------------------------------------------------- Hidden Eye

EYE, GAZE, EYE_BASE = "tianxia.sphere.the_hidden_eye", "TAL_THE_HIDDEN_EYE_INIMICAL_GAZE", "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"
ANALYZED = "typed.analyzed_by"


def _gaze_engine(*, foe_at=(4, 6), cl=10):
    engine = _melee(H._bundle(EYE, [GAZE], NO_KIT, cl=cl), foe_hp=500, foe_at=foe_at)
    H._me(engine).resources[FOCUS] = 1
    return engine


def _gaze(engine, *, bonus):
    me = H._me(engine)
    for bundle in engine.typed_bundle_documents:
        if bundle.get("actor_id") == me.entity_id:
            bundle.setdefault("skills", {}).update({"Investigation": bonus, "Perception": bonus})
    return H._use(engine, "Inimical Gaze", target=None)


def test_inimical_gaze_analyzes_every_enemy_in_range_with_one_roll():
    """"Make one Analyze check ... compare the result against the Analyze DC of each creature within your Analyze range. On each
    success ... it becomes Analyzed by you": Inimical Gaze had no effect (GM text only)."""
    engine = _gaze_engine(foe_at=(6, 6))
    assert "Inimical Gaze" in H._legal(engine)
    events = _gaze(engine, bonus=100)
    checks = H._payloads(events, "CHECK_ROLLED")
    assert len(checks) == 2 and all(check["success"] for check in checks)  # one against each enemy in range ...
    assert len({check["actor"]["total"] for check in checks}) == 1  # ... from a single roll
    assert ANALYZED in H._conditions(H._foe(engine)) and ANALYZED in H._conditions(engine.state.actors[AN])
    assert H._me(engine).resources[FOCUS] == 0  # "Expend Martial Focus"


def _place(engine, actor_id, x, y):
    actor = engine.state.actors[actor_id]
    actor.position = actor.position.__class__(x=x, y=y)


def test_inimical_gaze_fails_against_a_dc_the_roll_misses_and_skips_what_is_out_of_range():
    engine = _gaze_engine(foe_at=(6, 6))
    events = _gaze(engine, bonus=-100)
    assert [check["success"] for check in H._payloads(events, "CHECK_ROLLED")] == [False, False]
    assert ANALYZED not in H._conditions(H._foe(engine)) and ANALYZED not in H._conditions(engine.state.actors[AN])
    far = _gaze_engine(foe_at=(6, 6))
    _place(far, AN, 19, 6)  # 80 feet away: beyond the 60-foot Analyze range
    events = _gaze(far, bonus=100)
    assert len(H._payloads(events, "CHECK_ROLLED")) == 1 and ANALYZED in H._conditions(far.state.actors[H.FOE])
    assert ANALYZED not in H._conditions(far.state.actors[AN])


def test_inimical_gaze_is_not_offered_with_no_enemy_to_look_at():
    engine = _gaze_engine(foe_at=(19, 6))
    _place(engine, H.FOE, 19, 12)
    assert "Inimical Gaze" not in H._legal(engine)


# --------------------------------------------------------------------------------------------------------------- Wrestling

WRESTLING, TACKLE = "tianxia.sphere.wrestling", "TAL_WRESTLING_TACKLE"


def test_tackle_is_a_bonus_action_grapple_after_the_dash_action():
    """"When taking the Dash action as your Action, use a Bonus Action before the end of the turn to attempt to Grapple one
    creature within reach": Tackle had no effect (a rider only)."""
    engine = H._engine(H._bundle(WRESTLING, [TACKLE], NO_KIT, cl=10))
    foe = H._foe(engine)
    foe.saving_throws["STR"] = foe.saving_throws["DEX"] = -100  # the Grapple attempt cannot be saved against
    assert "Tackle: Grapple" not in H._legal(engine)  # no Dash yet
    H._use(engine, "Dash", target=None)
    assert "Tackle: Grapple" in H._legal(engine)
    events = H._use(engine, "Tackle: Grapple")
    assert "typed.grappled" in H._conditions(foe)
    assert H._payloads(events, "SAVE_ROLLED")
    assert "Tackle: Grapple" not in H._legal(engine)  # the Bonus Action is spent


def test_tackle_is_not_offered_to_a_fighter_without_it():
    engine = H._engine(H._bundle(WRESTLING, [], NO_KIT, cl=10))
    H._use(engine, "Dash", target=None)
    assert "Tackle: Grapple" not in H._legal(engine)


# ------------------------------------------------------------------------------------------------------------ Foundations


def test_oath_skin_frame_and_ash_returning_meridian_are_no_longer_skipped_passives():
    """Both print a maximum-HP increase that the sheet's hit points already carry from creation
    (non_sphere_authority/foundation_mechanics.py); the compiler listed them as skipped (unautomated) passives all the same."""
    from tests.test_auto_paths import _bundle as foundation_bundle

    def skipped(foundation_id, resource):
        foundation = {"foundation_id": foundation_id, "stage": "Awakened",
                      "resource": {"name": resource, "resource_id": f"foundation.resource.{foundation_id}", "maximum": 1, "current": 0}}
        return foundation_bundle(foundation)["diagnostics"]["skipped"].get("passive", [])

    assert "Oath-Skin Frame" not in skipped("iron_oath_skin_v0_2B", "Oath Mark")
    assert "Ash-Returning Meridian" not in skipped("red_lotus_ash_returning_v0_2B", "Funeral Ash")


# --------------------------------------------------------------------------------------------------------------- Subpaths

NINE_NEEDLES = "tianxia.subpath.qi.meridian_physician.feature.heaven_returning_nine_needles"
NEEDLES = "Heaven-Returning Nine Needles"


def _needles_engine():
    from tests.test_zones import SHEET  # a Qi Cultivator: the Nine Needles cost 8 Qi

    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": 18},
             "path_and_subpath": {"path_feature_record_ids": [NINE_NEEDLES]}}
    return H._engine(H.compile_character(sheet, actor_id=ME))


def test_nine_needles_return_the_living_heals_half_and_ends_the_named_conditions():
    """"Regains Hit Points equal to half its Hit Point maximum. Regains Cultivation Points equal to twice your Proficiency Bonus.
    Ends Charmed, Frightened, Poisoned ... Bleeding ... paralysis. Stands without spending movement": the action did nothing
    (GM text only)."""
    engine = _needles_engine()
    me = H._me(engine)
    pool = "resource:core.qi"
    me.current_hp = 10
    me.resources[pool] = 20
    for name in ("frightened", "poisoned", "prone", "bleeding"):
        engine._apply_condition(me, f"condition:typed.{name}", "test:hurt", AN, expires_on="UNTIL_REMOVED")
    engine._apply_condition(me, "condition:typed.blinded", "test:hurt", AN, expires_on="UNTIL_REMOVED")  # not on the list
    events = H._use(engine, NEEDLES, target=ME)
    assert me.current_hp == 10 + me.maximum_hp // 2
    assert H._payloads(events, "HEALING_APPLIED")[0]["offered"] == me.maximum_hp // 2
    assert H._conditions(me) == {"typed.blinded"}
    pb = int(next(c for c in engine.action_catalog.values() if c.display_name == NEEDLES).parameters["typed"]["numbers"]["pb"])
    assert me.resources[pool] == 20 - 8 + 2 * pb  # the 8 Qi paid, twice PB gained



# ----------------------------------------------------------------------------------------------- Abilities labelled as such


def test_labelled_abilities_are_recorded_as_not_fight_mechanics():
    """Diagnosis remains information and Quick-Draw Arsenal remains a table matter, each labelled with its reason.
    Funeral Candle Shelter now runs through wax_candle.py's life_state death handler (riders/c11, 2bcff05c,
    merge 6f7355d5; approving C11r4.review.md). Its Shelter the Dying effect is applied rather than skipped;
    Shelter the Departing Trace remains the GM's. test_riders_c11 exercises the death handler and its cost.

    Physician's Pulse left this list with AUTO80: the printed text is an Action ("Action Type: Action, Range: Touch,
    Cost: 1 CP") that examines one willing creature, and the table now reads that creature's own conditions and
    reports the printed ailments it can see (combat/ext/blood_diagnosis.py), so it is a fight Action instead of a
    skill the GM plays. Its own entry in feature_status.d/auto_lane3.json now says exactly what the table can and
    cannot see; tests/test_auto80_blood.py presses the button and reads the reported line."""
    def skipped(sphere, talent):
        return H._bundle(sphere, [talent], NO_KIT)["diagnostics"]["skipped"]

    candle_skipped = skipped("tianxia.sphere.wax", "TAL_WAX_FUNERAL_CANDLE_SHELTER")
    assert all("Funeral Candle Shelter" not in names for names in candle_skipped.values())
    assert "Quick-Draw Arsenal" in skipped("tianxia.sphere.barrage", "TAL_BARRAGE_QUICK_DRAW_ARSENAL")["table"]  # no draw Action here


def test_physicians_pulse_is_no_longer_labelled_a_non_fight_mechanic():
    """The companion to the test above: the Blood sphere's examination is an Action the table runs."""
    skipped = H._bundle("tianxia.sphere.blood", ["tianxia.talent.blood.physician_s_pulse"], NO_KIT)["diagnostics"]["skipped"]
    assert "Physician’s Pulse" not in skipped["outside"]
    status = json.loads((APP / "combat/rules/feature_status.d/auto_lane3.json").read_text(encoding="utf-8"))["features"]
    why = status["tianxia.talent.blood.physician_s_pulse"]["why"]
    assert "reports ordinary bleeding" in why and "removes nothing" in why


def test_echoing_step_is_no_longer_labelled_a_table_matter():
    """It was labelled "table" (no typed effect for it) in feature_status.d/wenxue.json; it is automated now, so it is not skipped."""
    skipped = H._bundle(MUSIC, [ECHOING_STEP], NO_KIT)["diagnostics"]["skipped"]
    assert "Echoing Step" not in skipped["table"]
