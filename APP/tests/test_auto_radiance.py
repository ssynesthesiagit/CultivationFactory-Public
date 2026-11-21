"""The Radiance sphere's Dawnmark loop (owner 2026-09-28, "automate every aspect before another playtest"; Wen
Xue, w4-radiance). Before this: no record ever applied a "Dawnmark" mark -- "apply your Dawnmark" (Radiance
Strike) and "become Dawnmarked" (Judgment Ray, Dawn-Cleansing Wave) were GM-only lines, so everything keyed on it
(Dawnlit Rebuke's reaction, Daybreak Seal's modifier, Dawnmark Scripture's duration/flare) never worked. Also
covers Consecrated Recovery's precondition bug (it granted free Temporary HP on every Radiance action, not just
the ones that end/suppress/grant a save against Charmed/Frightened/Poisoned/possession/corruption/disease/curse)
and Mercy of Morning's missing fourth option. combat/ext/radiance_dawnmark.py,
authority/typed_mechanics/reviewed_final.d/wenxue.json."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import CONDITION_PREFIX, bears_mark, mark_condition_id

from tests.test_auto_wenxue import BASE_SHEET, ME

ROOT = Path(__file__).resolve().parents[1]

RADIANCE_TALENTS = ["RADIANCE_BASE_STRIKE", "RADIANCE_TAL_JUDGMENT_RAY", "RADIANCE_TAL_DAWN_CLEANSING_WAVE",
                    "RADIANCE_TAL_DAWNLIT_REBUKE", "tianxia.talent.radiance.daybreak_seal",
                    "tianxia.talent.radiance.dawnmark_scripture", "tianxia.talent.radiance.consecrated_recovery",
                    "tianxia.talent.radiance.mercy_of_morning", "tianxia.talent.radiance.consecrated_boundary"]


def _bundle(talents=RADIANCE_TALENTS, extra_sphere_ids=()):
    sheet = {**BASE_SHEET,
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.radiance", *extra_sphere_ids],
                                     "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="RADIANCE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _use(engine, name, *, actor_id=ME, target=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=f"i{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids or ((target,) if target else ())))
    return candidate


def _ready(engine, actor_id=ME):
    engine.state.actors[actor_id].action_available = True
    engine.state.actors[actor_id].bonus_action_available = True
    engine.state.actors[actor_id].reaction_available = True
    engine.state.current_actor_id = actor_id


def _dawnmark(actor):
    condition_id = mark_condition_id("Dawnmark", ME)
    return next((c for c in actor.conditions.values() if c.condition_id == condition_id), None)


def test_radiance_strike_hits_apply_a_real_dawnmark_and_scale_damage_by_cl():
    bundle = _bundle(["RADIANCE_BASE_STRIKE"])
    strike = next(row for row in bundle["action_catalog"] if row["display_name"] == "Radiance Strike")
    on_hit = strike["parameters"]["typed"]["effects"][0]["on_hit"]
    damage = next(e for e in on_hit if e["type"] == "damage")
    assert damage["dice_by_cl"] == [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 20, 4, 8]]  # CL 10 sheet: 2d8, not a flat 1d8
    mark = next(e for e in on_hit if e["type"] == "mark")
    assert mark["mark"] == "Dawnmark" and mark["duration"]["kind"] == "until_start_of_your_next_turn"
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    for _ in range(8):
        _ready(engine)
        _use(engine, "Radiance Strike", target=AN)
        if _dawnmark(foe) is not None:
            break
    condition = _dawnmark(foe)
    assert condition is not None and condition.expires_on == "START_OF_MARKER_NEXT_TURN"


def test_dawnmark_scripture_extends_the_mark_to_the_end_of_her_next_turn_and_flares_reactions():
    bundle = _bundle()
    assert any(row["block"] == "radiance_dawnmark_scripture" for row in bundle["typed_passives"])
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    for _ in range(8):
        _ready(engine)
        _use(engine, "Radiance Strike", target=AN)
        if _dawnmark(foe) is not None:
            break
    condition = _dawnmark(foe)
    assert condition is not None
    # "Your Dawnmark lasts until the end of your next turn": Dawnmark Scripture upgrades the base
    # "until the start of your next turn" duration Radiance Strike alone would place.
    assert condition.expires_on == "END_OF_MARKER_NEXT_TURN"
    # "You may choose to make the mark flare ... cannot take Reactions until the start of its next turn":
    # AI / unattended engines prefer flaring through the transactional choice hook.
    engine.state.current_actor_id = AN
    from combat import ext
    ext.run_strict('turn_start_choice', engine, foe)
    assert any(c.condition_id == CONDITION_PREFIX + "reaction_denied" for c in foe.conditions.values())


def test_dawnlit_rebuke_only_reacts_to_a_creature_bearing_her_dawnmark():
    bundle = _bundle(["RADIANCE_BASE_STRIKE", "RADIANCE_TAL_DAWNLIT_REBUKE"])
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert not bears_mark(foe, ME, "Dawnmark")
    row = next(r for r in bundle["typed_reactions"] if r["name"] == "Dawnlit Rebuke")
    assert row.get("requires_mark") == "Dawnmark"  # parsed straight from the printed trigger text


def test_daybreak_seal_only_denies_temp_hp_against_a_marked_target():
    bundle = _bundle(["RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.daybreak_seal"])
    seal = next((row for row in bundle["action_catalog"] if row["display_name"] == "Radiance Strike + Daybreak Seal"), None)
    assert seal is not None
    on_hit = seal["parameters"]["typed"]["effects"][0]["on_hit"]
    gated = next(e for e in on_hit if e.get("type") == "if_marked")
    assert gated["mark"] == "Dawnmark" and gated["effects"][0]["type"] == "save"


def test_consecrated_recovery_no_longer_grants_temp_hp_on_every_radiance_action():
    bundle = _bundle(["RADIANCE_BASE_STRIKE", "tianxia.talent.radiance.consecrated_recovery"])
    strike = next(row for row in bundle["action_catalog"] if row["display_name"] == "Radiance Strike")
    on_hit = strike["parameters"]["typed"]["effects"][0]["on_hit"]
    assert not any(e.get("type") == "temp_hp" for e in on_hit)  # was: free 2xPB Temp HP on every hit, even a bare Radiance Strike
    modifier = next(row for row in bundle["modifiers"] if row["name"] == "Consecrated Recovery")
    assert "Radiance Strike" not in modifier["applied"]


def test_mercy_of_morning_offers_all_four_printed_options_including_stand_from_prone():
    bundle = _bundle(["tianxia.talent.radiance.mercy_of_morning"])
    names = {row["display_name"] for row in bundle["action_catalog"] if row["display_name"].startswith("Mercy of Morning")}
    assert names == {"Mercy of Morning: End Fear Response", "Mercy of Morning: Advantage vs Charm",
                     "Mercy of Morning: Stand from Prone", "Mercy of Morning: Move 5 Feet"}
    stand = next(row for row in bundle["action_catalog"] if row["display_name"] == "Mercy of Morning: Stand from Prone")
    effect = stand["parameters"]["typed"]["effects"][0]
    assert effect["type"] == "remove_condition" and effect["condition"] == "prone"
