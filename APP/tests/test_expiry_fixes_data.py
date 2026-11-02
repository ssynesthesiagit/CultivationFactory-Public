"""Expiry review (fix/expiry-clock).  ~30 rows typed with the bare ``until_end_of_turn`` -- which the engine can only read as a
guess ("this turn" for a buff on the user's side, "the affected creature's next turn" for a foe) -- were read against the printed
words and given the expiry those words state: "until the end of *your* next turn" (the user's turn: END_OF_SOURCE_TURN_AT),
"its next turn" (the affected creature's), "the start of your next turn", or "the rest of the turn" (END_OF_CURRENT_TURN).  The
rows live in authority/typed_mechanics/reviewed_final.d/expiry_fixes.json (a few in the files that already reviewed the same
talent); the builder skips an override whose printed text has changed since, so the first tests here guard against a silently
dropped fix, and the rest cast three of the talents for real."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

APP = Path(__file__).resolve().parents[1]
OVERRIDES = APP / "authority/typed_mechanics/reviewed_final.d"
FIXES = OVERRIDES / "expiry_fixes.json"

SRC, HOLDER, START = "until_end_of_your_next_turn", "until_end_of_next_turn", "until_start_of_next_turn"
THIS = "END_OF_CURRENT_TURN"

# (mechanic, field, path to the row inside it, what the row must say): a duration kind, or the explicit expires_on THIS.
ROWS = [
    ("TAL_AIR_EMPTY_LUNG_EDICT", "effects", (0, "on_fail", 0), SRC),
    ("TAL_AIR_EMPTY_LUNG_EDICT", "effects", (0, "on_fail", 1), SRC),
    ("TAL_AIR_EMPTY_LUNG_EDICT", "effects", (0, "on_fail", 2), SRC),  # Silenced: was typed "its next turn"
    ("TAL_DAEMONIC_CULTIVATION_BLACK_SUN_OVER_THE_DANTIAN", "effects", (0, "on_fail", 1), SRC),
    # Approved creature selection now precedes Bell's save; its failed-save
    # misalignment still ends with the caster's next turn.
    ("TAL_METAL_BELL_OF_SHATTERED_WEAPONS", "effects", (1, "on_fail", 1), SRC),
    # on_hit[0] is the 8d8 Piercing damage the sw-lightning review added ("Hit: the target takes 8d8 Piercing damage and must make a
    # Constitution saving throw"); the save whose Failure runs "until the end of your next turn" is the row after it
    ("TAL_METAL_HEAVEN_PIERCING_NAIL", "effects", (2, "on_hit", 1, "on_fail", 0, "options", 3, "effects", 0), SRC),
    ("TAL_WATER_ABYSSAL_PRESSURE_SEAL", "effects", (0, "on_fail", 0), SRC),
    ("TAL_WATER_ABYSSAL_PRESSURE_SEAL", "effects", (0, "on_fail", 1), SRC),
    ("TAL_WRESTLING_THE_HOLD_HEAVEN_COULD_NOT_ESCAPE", "effects", (0, "on_fail", 0), SRC),
    ("TAL_WRESTLING_THE_HOLD_HEAVEN_COULD_NOT_ESCAPE", "effects", (0, "on_fail", 1), SRC),
    ("TAL_WRESTLING_THE_HOLD_HEAVEN_COULD_NOT_ESCAPE", "effects", (0, "on_fail", 2), SRC),
    # Three Sovereign Venoms' Nerve/Marrow rows are no longer typed options: rider lane C7 moved the whole feature (all three Venoms,
    # asked, one per creature) into combat/ext/hundred_venom.py, which applies every Venom row until the end of the user's next turn;
    # tests/test_riders_c7.py::test_a_new_sovereign_venom_replaces_the_old_one checks that expiry on the table.
    ("tianxia.subpath.qi.sound_cultivator.feature.requiem_of_the_heavens", "options", (0, "effects", 1, "on_fail", 2), SRC),  # stun: typed under the Psychic option
    ("tianxia.subpath.qi.sound_cultivator.feature.shattering_note", "effects", (0, "on_fail", 3), SRC),  # qi5_clear_concentration sits at 2
    ("tianxia.talent.jester.the_whole_court_laughs", "effects", (0, "on_fail", 0), SRC),
    ("tianxia.talent.jester.the_whole_court_laughs", "effects", (0, "on_fail", 1), SRC),  # Flustered: was typed "its next turn"
    ("tianxia.talent.lightning.when_potential_becomes_judgment", "options", (1, "effects", 0), SRC),
    ("tianxia.talent.lightning.when_potential_becomes_judgment", "options", (1, "effects", 1), SRC),
    ("tianxia.talent.metal.ten_thousand_metal_sovereign_edict", "options", (3, "effects", 0, "on_fail", 0), HOLDER),
    ("tianxia.talent.metal.ten_thousand_metal_sovereign_edict", "options", (4, "effects", 0), SRC),
    ("tianxia.talent.music.heartstring_severing_prelude", "effects", (0, "on_fail", 0), SRC),
    ("tianxia.talent.puppetry.joint_catching_needle", "modifier", ("effects", 0), SRC),
    ("tianxia.talent.imbuement.the_edict_that_names_the_world_again", "options", (3, "effects", 0), SRC),
    ("tianxia.tradition.spirit.heartbinder.feature.heart_s_rebuke", "modifier", ("effects", 0), HOLDER),
    # Beast King's Technique moved to combat/ext/beast_aspects.py (rider lane C7); Wolf's Advantage still ends with the ally's next
    # turn: tests/test_riders_c7.py::test_beast_kings_wolf_gives_an_ally_advantage_until_the_end_of_that_allys_next_turn
    ("tianxia.tradition.spirit.echo_step_disciple.feature.three_step_soul_execution", "effects", (0, "final_save", "on_fail", 2), SRC),  # C8: the save rides the plug-in row
    ("TAL_SWORD_SWORD_DRAWING_STANCE", "modifier", ("effects", 0), START),
    # "until the end of the turn" / "for the remainder of the turn": bounded to the turn, whoever holds it
    ("TAL_MAGMA_FURNACE_STEP", "effects", (2,), THIS),
    ("TAL_MAGMA_FURNACE_STEP", "effects", (0,), THIS),  # "Speed increases by 10 feet": once (the parser's second copy of it is gone)
    ("TAL_YIN_YIN_SINKING_STEP", "effects", (1,), THIS),
    ("foundation.dragon_wind_vessel_v0_2E.dragon_marrow_drive", "modifier", ("effects", 1), THIS),
    # Tread the Empty Sky's row was a misread attack (the feature makes none; its "no Opportunity Attacks from creatures 10 feet
    # below you" needs altitude); rider lane C7 removed it and left the feature to the GM until the table has flight.
    # "Make one Sabers Cultivation Attack ... On hit, it takes 6d8 slashing damage and its movement is reduced by 20 feet until the end
    # of the turn": the sw-sabers review moved the reduction from a top-level row (which also slowed on a miss) into the attack's on_hit
    ("tianxia.talent.sabers.kingfisher_beheads_the_retreat", "effects", (0, "on_hit", 1), THIS),
    ("tianxia.subpath.qi.formation_breaking_halberd_cultivator.feature.break_the_rank", "effects", (0, "on_success", 0), THIS),
    ("tianxia.talent.chains.chain_counter", "options", (3, "effects", 0, "on_fail", 0), THIS),
]


@lru_cache(maxsize=None)
def _mechanics() -> dict:
    return json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]


def _row(key: str, field: str, path: tuple):
    node = _mechanics()[key][field]
    for part in path:
        node = node[part]
    return node


def _id(row) -> str:
    key, field, path, _ = row
    return f"{key.rsplit('.', 1)[-1]}:{field}" + "".join(f"[{part}]" for part in path)


@pytest.mark.parametrize("key, field, path, expected", ROWS, ids=[_id(row) for row in ROWS])
def test_the_row_states_the_expiry_its_printed_words_do(key, field, path, expected):
    row = _row(key, field, path)
    if expected == THIS:
        assert row.get("expires_on") == THIS
        return
    duration = row.get("duration")
    kind = duration.get("kind") if isinstance(duration, dict) else duration
    assert kind == expected, f"{key}: {row.get('evidence')!r} is typed {kind!r}"


def _without_derived(value):
    """The build derives a forced movement's direction from its words (typed_structure.derive_forced_movement_directions)."""
    if isinstance(value, dict):
        return {key: _without_derived(item) for key, item in value.items() if key != "direction"}
    if isinstance(value, list):
        return [_without_derived(item) for item in value]
    return value


def test_every_expiry_override_reached_the_built_authority():
    """The builder skips a reviewed override whose source text has changed (or whose key is gone) with only a warning on stderr,
    and the built file is what runs: each field the override supplies must be, whole, in the authority."""
    doc = json.loads(FIXES.read_text(encoding="utf-8"))
    assert doc["mechanics"]
    for key, override in doc["mechanics"].items():
        for field, value in override.items():
            if field in ("text_sha256", "reviewed_by"):
                continue
            if value is None:  # a full-record review (sw-spirit_companions: Sword Drawing Stance) states the nulls; the builder drops the field
                assert field not in _mechanics()[key], f"{key}.{field} is null in the override but was built in"
                continue
            assert _without_derived(_mechanics()[key][field]) == _without_derived(value), f"{key}.{field} was not built in (rebuild, or the printed text changed)"
        assert _mechanics()[key]["typing_status"] == "reviewed_final"


def test_the_expiry_review_is_the_only_review_of_its_mechanics():
    """A mechanic reviewed in two files gets the later file's (the builder warns 'reviewed twice'); this file's keys must have
    one owner, or the fixes would silently lose to (or shadow) another review's."""
    mine = set(json.loads(FIXES.read_text(encoding="utf-8"))["mechanics"])
    for path in sorted(OVERRIDES.glob("*.json")):
        if path != FIXES:
            assert not mine & set(json.loads(path.read_text(encoding="utf-8"))["mechanics"]), path.name


# ---- three of the talents, cast for real ------------------------------------------------------------------------------------

FAILS = 30  # the foe's saving throw (a d20 and a small modifier) against this DC never succeeds


@lru_cache(maxsize=None)
def _compiled(sphere: str, talent: str) -> dict:
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": FAILS}
    return compile_character({**SHEET, "equipment": [], "ability_scores_and_statistics": stats,
                              "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": [talent]}}, actor_id=ME)


def _cast(sphere: str, talent: str, name: str, foe_save_bonus: int | None = None):
    engine = _engine(copy.deepcopy(_compiled(sphere, talent)), foe_at=(4, 6))
    if foe_save_bonus is not None:  # a talent whose DC is not technique_save_dc (Wrestling Save DC: 8 + Strength + Proficiency Bonus)
        engine.state.actors[AN].saving_throws.update({ability: foe_save_bonus for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")})
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine


def _held(foe) -> dict:
    """What the foe carries, by name, with the expiry each has."""
    held = {c.condition_id.removeprefix("condition:typed."): c.expires_on for c in foe.conditions.values()}
    held.update({m.target_field: m.expires_on for m in foe.modifiers.values() if m.expires_on})
    return held


def _end_turn(engine) -> None:
    engine.end_turn()


def test_empty_lung_edict_lasts_to_the_end_of_the_casters_next_turn_not_the_foes():
    """'Until the end of your next turn, the target cannot take Reactions, has Disadvantage on attack rolls and is Silenced':
    typed as the bare until_end_of_turn, a foe lost all three when ITS next turn ended -- one turn (a whole round for the
    creature that acts first) short of what is printed."""
    engine = _cast("tianxia.sphere.air", "TAL_AIR_EMPTY_LUNG_EDICT", "Empty-Lung Edict")
    caster, foe = engine.state.actors[ME], engine.state.actors[AN]
    goal = f"END_OF_SOURCE_TURN_AT:{caster.turns_started + 1}"
    # The "once per long rest per target" record (a fight-long mark, rider lane C9 2026-09-30) is not one of the three effects.
    assert {k: v for k, v in _held(foe).items() if not k.startswith("mark.")} == {"reaction_denied": goal, "silenced": goal, "attack_mode": goal}
    while engine.state.current_actor_id != ME or caster.turns_started < 2:  # through the foe's turn, into the caster's next
        _end_turn(engine)
        assert _held(foe), "gone before the end of the caster's next turn"
    assert engine.state.current_actor_id == ME and caster.turns_started == 2
    _end_turn(engine)  # the end of the caster's next turn
    assert not [name for name in _held(foe) if name in ("reaction_denied", "silenced", "attack_mode")]


def test_the_hold_heaven_could_not_escape_grapples_until_the_end_of_the_casters_next_turn():
    engine = _cast("tianxia.sphere.wrestling", "TAL_WRESTLING_THE_HOLD_HEAVEN_COULD_NOT_ESCAPE", "The Hold Heaven Could Not Escape",
                   foe_save_bonus=-40)
    caster, foe = engine.state.actors[ME], engine.state.actors[AN]
    goal = f"END_OF_SOURCE_TURN_AT:{caster.turns_started + 1}"
    held = _held(foe)
    assert held["grappled"] == goal and held["restrained"] == goal


def test_furnace_step_is_this_turns_only():
    """'Until the end of your turn: Speed increases by 10 feet ... do not provoke opportunity attacks from one creature of your
    choice'.  The creature it names was barred from opportunity attacks until ITS next turn ended (a foe's bare
    until_end_of_turn), and the parser's second copy of the Speed bonus, which names no duration at all, stayed on the caster
    for the rest of the fight -- one more +10 Speed for every use."""
    engine = _cast("tianxia.sphere.magma", "TAL_MAGMA_FURNACE_STEP", "Furnace Step")
    caster, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert _held(foe) == {"no_opportunity_attacks": THIS}
    speed = lambda: [m.expires_on for m in caster.modifiers.values() if m.target_field == "speed_ft"]  # noqa: E731
    assert speed() and set(speed()) == {THIS}
    _end_turn(engine)  # the caster's turn is over
    assert "no_opportunity_attacks" not in _held(foe)
    assert speed() == []
