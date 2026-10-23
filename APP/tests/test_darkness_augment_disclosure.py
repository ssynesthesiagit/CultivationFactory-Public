"""What a free augment toggle is labelled, and what Obfuscation says for its 1 CP (owner MMX66, DeepSeek DS7 #2-#3).

Two player-facing promises were broken at once by the same area of the code:

  * An augment toggle is a free setting (combat/factory_compiler.py builds it with EconomyKind.NONE), but the fight
    menu row carried no cost at all, and static/tabletop/tabletop.js drew the fight button's cost tag straight from
    the row's kind.  A toggle that costs nothing therefore read "Bonus" in the fight, contradicting the sheet button
    beside it, which already said "free" (that map was keyed on button.economy and already had FREE).  The cost now
    travels on the row itself -- TabletopService._menu_descriptions copies the compiled definition's own economy onto
    every menu row, and costTag() reads it -- so a free setting reads "Free" and a real Bonus Action still reads
    "Bonus".  Display only: no candidate kind, id or hash is touched, so saved fights replay as they always did.
  * Obfuscation charges its printed 1 CP, and the table has no scrying or divination for the printed effect to
    resolve -- so the point bought silence.  Other unmodelled rows say so; this one did not.

These fight for real: a character sheet is compiled and its rows cast on a real map, and the menu is the one the
browser draws, so a failure here is the failure an owner sees at the table, not a unit-level detail.
"""

import json
import subprocess
from pathlib import Path

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, CandidateKind
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.nightshade"
QI = "resource:core.qi"
DARK_SPHERE = "tianxia.sphere.dark"


def _sheet(*talents: str) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": [DARK_SPHERE], "learned_talent_record_ids": list(talents)}}


def _fight(*talents: str) -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX66", typed_bundles=(compile_character(_sheet(*talents), actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _row(engine: Gate4ControllerEngine, name: str):
    return next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name)


def _cast(engine: Gate4ControllerEngine, name: str, at=(10, 6)) -> None:
    candidate = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name
                     and c.destination is not None and (c.destination.x, c.destination.y) == at)
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _toggle(engine: Gate4ControllerEngine, name: str) -> None:
    candidate = _row(engine, name)
    engine.execute_intent(ActionIntent(intent_id="toggle", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))


def _rider_texts(engine: Gate4ControllerEngine) -> list[str]:
    return [str((event.payload or {}).get("rider") or "") for event in engine.events if event.event_type == "GM_RIDER"]


# ------------------------------------------------------------------------------------- a free toggle is not a Bonus Action
def _menu(tmp_path, *talents) -> dict:
    """The fight menu exactly as a player's browser receives it: a real service, a real compiled fight, a real
    state answer -- not the engine's candidates seen from the side."""
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        [compile_character(_sheet(*talents), actor_id=ME, reaction_plan={"ask": False}),
         compile_character(_sheet(), actor_id=AN)], [ME, AN], {ME: "team:a", AN: "team:b"},
        {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [AN],
        control_modes={ME: "MANUAL", AN: "MANUAL"}, match_seed="MMX66",
        display_name="MMX66 free toggle", maximum_rounds=5)["match_id"]
    return TabletopService(combat, tmp_path).state(mid)["menu"]


def _menu_row(engine: Gate4ControllerEngine, name: str) -> dict:
    """One fight menu row, assembled the way TabletopService assembles it: the kind from the real candidate, the
    cost from the same compiled definition the character sheet was built from."""
    candidate = _row(engine, name)
    return {"label": name, "kind": str(candidate.kind),
            "economy": str(engine.action_catalog[candidate.source_definition_id].economy)}


def _cost_tags(rows: list[dict]) -> dict[str, str]:
    """What the shipped button says for these rows: the real costTag() from static/tabletop/tabletop.js, run over
    real rows, so this is the label an owner reads rather than a restatement of it."""
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    start = source.index("function costTag(")
    program = (source[start:source.index("\n}", start) + 2]
               + f"\nconsole.log(JSON.stringify({json.dumps(rows)}.map(row => [row.label, costTag(row)])));")
    out = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    return dict(json.loads(out.stdout))


def test_a_free_toggle_carries_its_own_cost_to_the_fight_menu(tmp_path):
    """The bug as an owner sees it: the fight's menu row for a free setting carried no cost at all, so the
    button had nothing but the candidate kind to read and said "Bonus"."""
    menu = _menu(tmp_path, "DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION", "TAL_DARK_GREATER_DARKNESS")
    groups = {group["label"]: group for group in menu["actions"]}
    for label in ("Augment Darkness: Obfuscation", "Augment Darkness: Greater Darkness",
                  "Augment Darkness: no augments (clears all of them)"):
        assert groups[label]["economy"] == "NONE", f"{label} does not carry its own cost: {groups[label]}"


def test_a_real_action_still_carries_its_own_cost(tmp_path):
    """The cost is each row's own, read from the definition: an Action is still an Action."""
    menu = _menu(tmp_path, "DARK_BASE_DARKNESS")
    assert next(group for group in menu["actions"] if group["label"] == "Darkness")["economy"] == "ACTION"


def test_the_fight_button_reads_the_rows_own_cost():
    """The shipped button over real rows: a free setting reads "Free", a real Bonus Action still reads "Bonus",
    an Action still "Action", and a row with no compiled economy (Hold) still reads "Hold"."""
    toggles = _fight("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION", "TAL_DARK_ROLLING_BLACKOUT")
    rows = [_menu_row(toggles, "Augment Darkness: Obfuscation"), _menu_row(toggles, "Darkness + Obfuscation")]
    _cast(toggles, "Darkness")
    rows.append(_menu_row(toggles, "Rolling Blackout: move Darkness"))
    rows.append({"label": "Hold position", "kind": "HOLD_POSITION"})  # no compiled definition: the kind is all it has
    assert _cost_tags(rows) == {
        "Augment Darkness: Obfuscation": "Free",
        "Darkness + Obfuscation": "Action",
        "Rolling Blackout: move Darkness": "Bonus",
        "Hold position": "Hold",
    }


def test_the_fix_moved_no_candidate_identity():
    """Display only.  A saved fight replays from the candidate ids and kinds it was saved with, so a free toggle
    keeps exactly the kind it always had, and only what the button says about it changes."""
    engine = _fight("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")
    candidate = _row(engine, "Augment Darkness: Obfuscation")
    assert candidate.kind == CandidateKind.BONUS_ACTION  # unchanged since 65cf60c9: candidate ids and hashes are untouched


def test_toggling_an_augment_costs_no_action_of_any_kind():
    """Confirming "Free" is honest: the toggle leaves the action, bonus action and reaction untouched."""
    engine = _fight("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")
    me = engine.state.actors[ME]
    before = (me.action_available, me.bonus_action_available, me.reaction_available, me.resources[QI])
    _toggle(engine, "Augment Darkness: Obfuscation")
    assert (me.action_available, me.bonus_action_available, me.reaction_available, me.resources[QI]) == before


# ------------------------------------------------------------------------------------- Obfuscation says what the point bought
def test_obfuscation_says_what_the_charge_bought():
    """The 1 CP is printed, so it is still charged -- but the log now states the effect and that it is not the
    table's to resolve, rather than taking the point in silence."""
    engine = _fight("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")
    me = engine.state.actors[ME]
    qi = me.resources[QI]
    _cast(engine, "Darkness + Obfuscation")
    assert me.resources[QI] == qi - 1  # the printed 1 CP is still charged
    obfuscation = [text for text in _rider_texts(engine) if "Obfuscation" in text]
    assert len(obfuscation) == 1, f"expected one plain line about Obfuscation, got {obfuscation}"
    said = obfuscation[0]
    assert "scrying or divination" in said  # what it does
    assert "between fights" in said  # when and where it applies
    assert "between you and the GM" in said  # who resolves it


def test_a_darkness_without_obfuscation_says_nothing_about_it():
    """The disclosure belongs to the augment, not to Darkness itself: a plain Darkness must not mention it."""
    engine = _fight("DARK_BASE_DARKNESS", "TAL_DARK_GREATER_DARKNESS")
    _cast(engine, "Darkness + Greater Darkness")
    assert not [text for text in _rider_texts(engine) if "Obfuscation" in text]


def test_a_character_who_does_not_own_obfuscation_never_hears_about_it():
    """Inert for everyone else: the plug-in returns before speaking if the augment is not in play."""
    engine = _fight("DARK_BASE_DARKNESS", "TAL_DARK_GREATER_DARKNESS")
    _cast(engine, "Darkness + Greater Darkness")
    assert not [text for text in _rider_texts(engine) if "scrying" in text]
    assert not any("Obfuscation" in str((zone.trigger_profile or {}).get("augments") or "")
                   for zone in zones.typed_zones(engine))


def test_the_printed_cost_of_each_augment_is_still_exactly_its_own_share():
    """The disclosure must not disturb the economy: Greater Darkness costs its printed 1 CP and says nothing about
    Obfuscation, and the stacked compiled row still carries the printed 1 + 1 = 2 CP."""
    engine = _fight("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION", "TAL_DARK_GREATER_DARKNESS")
    me = engine.state.actors[ME]
    qi = me.resources[QI]
    _cast(engine, "Darkness + Greater Darkness")
    assert me.resources[QI] == qi - 1
    assert not [text for text in _rider_texts(engine) if "Obfuscation" in text]
    stacked = next(row for row in compile_character(
        _sheet("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION", "TAL_DARK_GREATER_DARKNESS"), actor_id=ME)["action_catalog"]
        if row["display_name"] == "Darkness + Greater Darkness + Obfuscation")
    assert stacked["costs"] == [[QI, 2]]  # Greater (1 CP) + Obfuscation (1 CP), as printed
