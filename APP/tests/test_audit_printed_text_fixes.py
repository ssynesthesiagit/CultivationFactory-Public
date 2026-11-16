"""AUDIT3 printed-text data fixes: the confirmed typed-data mismatches now carry the printed value.

Each test names the printed rule it holds the data to, so a regression says which
printed sentence the typed record has stopped matching.

Three levels are used, and the difference matters:

* **Executed** -- a character owning the ability is put in a real duel
  (``tests.h1_support.duel``), the dice are scripted, and the ability is taken
  from the menu.  This is the level the two claims that are about *behaviour*
  are held to: that Myriad-Venom Sovereign actually spends its 10 Qi and is
  refused when the Qi is short, and that Sword Array Field actually rolls 3d8
  below CL17 and 4d8 at CL17.  A cost that is stored but never charged, or a
  CL table the executor ignores, fails here.
* **Compiled action** -- ``combat.factory_compiler.compile_character`` output is
  inspected.  Used for the header fields (range, area), which are what the
  table measures a target with.
* **Record data** -- used only for rows the compiler does not turn into an
  action (a passive, a modifier with nothing typed to add, a talent the
  character builder treats as out of scope).  Those rows are listed in
  ``NOT_COMPILED_TO_AN_ACTION`` with the reason, so a test here is never read
  as a claim that the engine pays or rolls it.

``test_every_row_this_file_claims_is_classified`` keeps the lists honest: every
record id the live regression tests name must be classified exactly once, and no
classification may outlive the test that justified it.  The lists are never read
by that scan, and a negative control deletes a regression in memory to prove it.
The two action/data lists are also checked against what the compiler really does.

Rows 1 (Song of the Forgotten Name's GM-chosen save), 4 (Brace the Heavens'
two separate 1 Qi sub-costs) and 12 (Twin Sword Refinement's per-hit CL
scaling) are deliberately absent: forcing them into this data charged or rolled
the wrong thing.  ``DEFERRED_NEEDS_ENGINE_SUPPORT`` names them and why, and
``test_deferred_row_is_left_at_the_record_the_model_pass_wrote`` pins what they
must not become.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from character_creation.constructed_arts.forging_authority import realm_for_cl
from combat.factory_compiler import RESOURCE_IDS, compile_character
from factory_authoring.typed_mechanics import dice_for_cl
from tests.h1_support import ME, duel, give, ready, script, sheet, use

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))
OVERRIDES = ROOT / "authority/typed_mechanics/reviewed_final.d"

QI = "tianxia.subpath.qi"
GREATBOW = f"{QI}.star_piercing_greatbow_cultivator.feature"
VENOM = f"{QI}.venomous_poison_cultivator.feature"
SWORDS = f"{QI}.ten_thousand_sword_array_cultivator.feature"
TEA = f"{QI}.tea_sage_cultivator.feature"
STORM = f"{QI}.storm_soul_cultivator.feature"
YINYANG = f"{QI}.yin_yang_cultivator.feature"

# Rows this lane holds to the printed text that DO compile to an action, and are
# therefore checked on the compiled action (the level a bug report is written at).
COMPILES_TO_AN_ACTION = {
    f"{VENOM}.myriad_venom_sovereign",
    f"{VENOM}.venomous_incarnation",
    "tianxia.talent.ink.world_as_canvas",
    f"{SWORDS}.sword_array_field",
}

# Why a row is only checkable as data: what the compiler does with it, observed
# by compiling a character that owns it (factory_compiler diagnostics).
NOT_COMPILED_TO_AN_ACTION = {
    f"{GREATBOW}.celestial_firing_platform": "compiled as a generic reaction (creature_d20), so it has no "
                                             "action a Qi cost could be charged to",
    f"{STORM}.lightning_reflexes": "skipped as a passive (no action economy, no modifier)",
    f"{TEA}.grandmaster_infusion": "skipped as a passive; its printed 'Touch, or 30 feet' range is a "
                                   "conditional the compiler cannot reduce to a number, so the stored text "
                                   "is correct but no targeting changes",
    f"{YINYANG}.balanced_flow": "compiled as a modifier with 'nothing typed to add'",
    "tianxia.talent.alchemy.heaven_defying_pill": "out of scope for a bare character sheet; the refinement "
                                                  "CP is cost text, shown and not enforced",
    "tianxia.talent.alchemy.resurrection_pill": "same as Heaven-Defying Pill",
    "tianxia.talent.destruction.ruin_tempered_armament": "skipped as a passive, so there is no attack the "
                                                         "printed bonus damage would be added to; the CL "
                                                         "table is stored and asserted as data",
}

# Rows the audit flagged that the data already gets right.  Listed so they are
# not mistaken for a deferred row, and so the realm-vs-CL question stays closed.
FALSE_POSITIVE_ROWS = {
    "tianxia.talent.disease.contaminated_wound": "the printed Realm stages and the stored CL key are the "
                                                 "same axis (a realm IS a function of CL), so the record is "
                                                 "already correct; see the parametrized case below",
}

# AUDIT3 rows this lane deliberately does not hold to the printed text, because
# the schema/engine cannot express them without charging or rolling the wrong
# thing.  See MMX5.report.md ("Review fixes (MMX25)").
DEFERRED_NEEDS_ENGINE_SUPPORT = {
    "tianxia.talent.music.song_of": "the print assigns the save choice to the GM; the '_OR_' pattern picks "
                                    "the target's better save, an unauthorized substitution",
    f"{GREATBOW}.brace_the_heavens": "two independently payable 1 Qi sub-costs (Greatbow Conduction's "
                                     "additional cost and Fix the Star's on-hit cost) on one bonus action",
    f"{SWORDS}.twin_sword_refinement": "the second attack's CL table on a payload shared by both attacks",
}


def _record(record_id: str) -> dict:
    return AUTHORITY["mechanics"][record_id]


def _compiled(record_id: str, *, cl: int = 17) -> dict:
    """The action a character owning ``record_id`` actually gets, or a failure explaining why not.

    This is the level the bug was reported at: what the engine hands the player.
    """
    doc = sheet([record_id], cl=cl, primary="Stamina")
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundle = compile_character(doc, actor_id="actor:test.audit_printed_text_fixes")
    actions = [action for action in (bundle.get("action_catalog") or [])
               if record_id in json.dumps(action, default=str)]
    assert actions, (
        f"{record_id} compiled to no action at CL{cl}, so it cannot be checked at the action level. "
        f"Diagnostics: {json.dumps(bundle.get('diagnostics'), default=str)}. "
        f"If this is expected, move the row to NOT_COMPILED_TO_AN_ACTION with its reason."
    )
    return actions[0]


def _typed(action: dict) -> dict:
    return (action.get("parameters") or {}).get("typed") or {}


def _walk_rows(rows: list) -> list[dict]:
    """Every nested effect row, so a check does not depend on list depth."""
    found: list[dict] = []
    for row in rows or []:
        if isinstance(row, dict):
            found.append(row)
            for value in row.values():
                if isinstance(value, list):
                    found.extend(_walk_rows(value))
    return found


# ------------------------------------------------------- execution: a real duel, real dice


def _button(engine, ability_name: str):
    """The menu button the engine offers for ``ability_name``, or None.

    The engine appends the aimed-at square to the label ("Sword Array Field at
    6,6"), so the button is matched on the ability's printed name and the
    candidate's own destination is handed back to the engine.
    """
    return next((c for c in engine.legal_candidates()
                 if c.actor_id == ME and c.display_name.startswith(ability_name)), None)


def _at_table(record_id: str, *, cl: int, qi: int, seed: str = "AUDIT3"):
    """``record_id``'s owner standing at the table with exactly ``qi`` Qi, turn open."""
    engine = duel([record_id], cl=cl, primary="Qi", seed=seed)
    give(engine, ME, qi=qi)
    ready(engine)
    return engine


def _rolls(events) -> list[dict]:
    return [e.payload for e in events if e.event_type == "DAMAGE_ROLLED"]


def test_myriad_venom_sovereign_spends_ten_qi_when_it_is_actually_used():
    """"**Cost:** 10 Qi" -- the Qi has to leave the pool, not just sit in the record.

    The ability is taken from a real duel menu, so this fails if the compiled
    cost is dropped, if the resource is wired to the wrong pool, or if the
    engine stops charging the action at all.
    """
    record_id = f"{VENOM}.myriad_venom_sovereign"
    engine = _at_table(record_id, cl=10, qi=10)
    button = _button(engine, "Myriad-Venom Sovereign")
    assert button is not None, "with 10 Qi the ability should be offered on the menu"

    events = use(engine, button.display_name)

    assert engine.state.actors[ME].resources[RESOURCE_IDS["qi"]] == 0
    assert [(e.payload.get("resource_id"), e.payload.get("amount")) for e in events
            if e.event_type == "RESOURCE_SPENT"] == [
                (RESOURCE_IDS["qi"], 10), (f"resource:uses.{button.source_definition_id}", 1)]
    assert not engine.state.actors[ME].action_available, "using the action should spend the action itself"


def test_myriad_venom_sovereign_is_refused_when_the_ten_qi_are_not_there():
    """The same cost, seen from the other side: one Qi short, the action is not playable.

    This is the half of the claim that a stored-cost assertion cannot see --
    a cost the engine records but does not enforce would still let the player
    cast it for free.
    """
    record_id = f"{VENOM}.myriad_venom_sovereign"
    engine = _at_table(record_id, cl=10, qi=9)

    assert _button(engine, "Myriad-Venom Sovereign") is None, (
        "at 9 Qi the ability must not be offered; the printed cost is 10 Qi"
    )
    assert engine.state.actors[ME].resources[RESOURCE_IDS["qi"]] == 9
    assert engine.state.actors[ME].action_available, "being unable to pay must not burn the turn's action"


@pytest.mark.parametrize("cl, dice_expression, damage", [
    (10, "3d8+0", 24),
    (16, "3d8+0", 24),
    (17, "4d8+0", 32),
])
def test_sword_array_field_rolls_3d8_below_cl17_and_4d8_at_cl17(cl: int, dice_expression: str, damage: int):
    """"**Failed Save:** `3d8` ... Damage becomes `4d8` at CL17." -- the dice the engine actually rolls.

    The save is forced to fail (a scripted 1 against DC 16) and every damage
    die is scripted to 8, so 3d8 lands 24 and 4d8 lands 32.  The asserted
    ``expression`` is the engine's own dice string, so this fails if the CL
    table stops reaching the roller -- not merely if the record changes.
    """
    record_id = f"{SWORDS}.sword_array_field"
    engine = _at_table(record_id, cl=cl, qi=5)
    button = _button(engine, "Sword Array Field")
    assert button is not None, f"the 5 Qi action should be offered at CL{cl}"

    # d20 = 1 (a failed save), then one scripted 8 per damage die.
    script(engine, [1, *([8] * (4 if cl >= 17 else 3))])
    events = use(engine, button.display_name)

    saves = [e.payload for e in events if e.event_type == "SAVE_ROLLED"]
    assert [s["success"] for s in saves] == [False], f"the save was meant to fail, got {saves}"
    assert [r["expression"] for r in _rolls(events)] == [dice_expression]
    assert [e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED"] == [damage]


# ------------------------------------------------------- the costs that were never charged


def test_printed_qi_cost_is_charged_on_the_compiled_action():
    """"**Cost:** 10 Qi" -- the ability was free in the engine because the record dropped the cost.

    Checked on the compiled action, i.e. the cost the player is actually asked
    to pay, not only on the stored record.
    """
    record_id, qi = f"{VENOM}.myriad_venom_sovereign", 10
    assert record_id in COMPILES_TO_AN_ACTION
    assert _record(record_id)["cost"] == [[{"resource": "qi", "amount": qi, "amount_formula": None}]]
    charged = [amount for resource, amount in _compiled(record_id)["costs"]
               if resource == RESOURCE_IDS["qi"]]
    assert charged == [qi], f"expected the compiled action to charge {qi} Qi, got {charged}"


@pytest.mark.parametrize(
    "record_id, qi",
    [
        (f"{TEA}.grandmaster_infusion", 0),   # free passive; its named Actions cost 5 Qi
        (f"{STORM}.lightning_reflexes", 0),   # free passive; Flash Between Heartbeats costs 2 Qi
        (f"{YINYANG}.balanced_flow", 0),      # free passive; Restorative Palm costs 2 Qi
        (f"{GREATBOW}.celestial_firing_platform", 3),  # "**Cost:** 3 Qi"
    ],
)
def test_printed_qi_cost_is_stored_for_rows_the_compiler_does_not_activate(record_id: str, qi: int):
    """"**Cost:** N Qi" is in the record, for the rows that are not activatable actions.

    These are listed in NOT_COMPILED_TO_AN_ACTION with the reason; this test
    holds the stored value to the print and deliberately does NOT claim the
    engine charges it.
    """
    assert record_id in NOT_COMPILED_TO_AN_ACTION, (
        f"{record_id} now compiles to an action, so its cost must be asserted on that action "
        f"instead (test_printed_qi_cost_is_charged_on_the_compiled_action)."
    )
    expected = [[{"resource": "qi", "amount": qi, "amount_formula": None}]] if qi else []
    assert _record(record_id)["cost"] == expected


# ------------------------------------------------------- the header fields the model pass dropped


def test_myriad_venom_sovereign_measure_is_the_printed_range_and_area():
    """"**Range:** 120 feet", "**Area:** 40-foot-radius, 40-foot-high cylinder" -- on the compiled action."""
    action = _compiled(f"{VENOM}.myriad_venom_sovereign")
    assert action["range_ft"] == 120
    assert action["radius_ft"] == 40
    area = _typed(action)["area"]
    assert area["shape"] == "cylinder" and area["size_ft"] == 40


def test_venomous_incarnation_is_aimed_at_the_printed_thirty_feet():
    """"**Range:** 30 feet" -- the compiled action's reach, not just the stored field."""
    assert _compiled(f"{VENOM}.venomous_incarnation")["range_ft"] == 30


def test_world_as_canvas_area_is_the_printed_sixty_foot_sphere():
    """"Area: 60-foot-radius sphere." -- not the 20-foot Binding zone, which is its own effect.

    The compiled action's radius is what the table measures the area with, and
    the Binding Script zone keeps its own printed 20 feet.
    """
    action = _compiled("tianxia.talent.ink.world_as_canvas")
    assert action["radius_ft"] == 60
    area = _typed(action)["area"]
    assert area["shape"] == "sphere" and area["size_ft"] == 60
    zone = next(row for row in _walk_rows(_typed(action)["effects"])
                if row.get("type") == "zone" and row.get("distance_ft") == 20)
    assert zone["distance_ft"] == 20


def test_grandmaster_infusion_keeps_its_printed_conditional_range_as_text():
    """"**Range:** Touch, or 30 feet through your Tea Domain Armament".

    Stored as text because the reach depends on a condition the compiler cannot
    evaluate.  This asserts the printed range is preserved, NOT that targeting
    implements it -- the row is a passive (NOT_COMPILED_TO_AN_ACTION).
    """
    reach = _record(f"{TEA}.grandmaster_infusion")["range"]
    assert reach["kind"] == "special" and reach["feet"] is None
    assert "30 feet" in reach["text"] and "Touch" in reach["text"]


# ------------------------------------------------------- the CL tables the model pass dropped


def test_ruin_tempered_armament_bonus_damage_grows_with_cl():
    """"CL 1-4: +1d6 ... CL 5-10: +2d6, CL 11-16: +3d6, CL 17+: +4d6 damage"."""
    effect = _record("tianxia.talent.destruction.ruin_tempered_armament")["effects"][0]
    assert [(low, high, count) for low, high, count, _sides in effect["dice_by_cl"]] == [
        (1, 4, 1), (5, 10, 2), (11, 16, 3), (17, 20, 4)]
    assert all(sides == 6 for *_row, sides in effect["dice_by_cl"])
    for cl, expected in ((2, 1), (7, 2), (14, 3), (19, 4)):
        assert dice_for_cl(effect["dice_by_cl"], cl)["count"] == expected


def test_sword_array_field_damage_becomes_four_d8_at_cl17():
    """"**Failed Save:** `3d8` ... Damage becomes `4d8` at CL17." -- resolved on the compiled action.

    The compiled action carries the table; ``dice_for_cl`` is the resolver the
    executor uses, so this is the damage the two CLs actually produce.
    """
    damage = next(row for row in _walk_rows(_typed(_compiled(f"{SWORDS}.sword_array_field", cl=17))["effects"])
                  if row.get("type") == "damage")
    assert damage["dice_by_cl"] == [[1, 16, 3, 8], [17, 20, 4, 8]]
    assert dice_for_cl(damage["dice_by_cl"], 10) == {"count": 3, "sides": 8}
    assert dice_for_cl(damage["dice_by_cl"], 17) == {"count": 4, "sides": 8}


# ------------------------------------------------------- the refinement CP the cost dropped


@pytest.mark.parametrize(
    "record_id, cp",
    [("tianxia.talent.alchemy.heaven_defying_pill", 20), ("tianxia.talent.alchemy.resurrection_pill", 25)],
)
def test_pill_cost_keeps_the_printed_refinement_cp(record_id: str, cp: int):
    """"Refinement Cost: N CP paid across the refinement" -- the number must not be dropped.

    Cost text, not a charge: the print pays it across a 30-day refinement, not
    on activation, so it is shown and not enforced.
    """
    parts = _record(record_id)["cost"][0]
    assert all(part["resource"] == "text" for part in parts)
    assert f"{cp} CP" in " ".join(str(part.get("text", "")) for part in parts)


# ------------------------------------------------------- the row the audit called a Realm table


@pytest.mark.parametrize("cl, realm, count", [
    (4, "Mortal", 1), (9, "Foundation", 1), (10, "Core Formation", 2), (14, "Core Formation", 2),
    (15, "Nascent Soul", 3), (20, "Immortal", 3),
])
def test_contaminated_wound_scaling_follows_the_printed_realm_stages(cl: int, realm: str, count: int):
    """increases to 2d6 at Core Formation and 3d6 at Nascent Soul" -- the table is keyed on CL, which is
    the axis the realm comes from, so the two readings cannot disagree."""
    effect = _record("tianxia.talent.disease.contaminated_wound")["modifier"]["effects"][0]
    assert realm_for_cl(cl) == realm
    assert dice_for_cl(effect["dice_by_cl"], cl)["count"] == count


# ------------------------------------------------------- the rows this lane deliberately defers

# "This field is not typed at all" -- the honest base value for a CL table the
# model pass never wrote.  Kept distinct from a field typed as null, because
# those are two different claims about the record.
_NOT_TYPED = object()

# What each deferred row must still contain, pinned to the values the model pass
# wrote at the base commit.  These are the exact fields that made the forced
# fixes unsafe, so a record cannot come back marked "unchecked" while carrying
# the payload this lane rejected.  Dotted path -> the value it must have.
DEFERRED_BASELINE = {
    "tianxia.talent.music.song_of": {
        # must stay a plain Wisdom save: "WIS_OR_CHA" is the one this lane tried
        # and backed out, because the print hands the choice to the GM.
        "effects.0.ability": "wis",
    },
    f"{GREATBOW}.brace_the_heavens": {
        # the printed feature carries two separate 1 Qi sub-costs; one blanket
        # cost on the shared bonus action would charge the free stance.
        "cost": [],
    },
    f"{SWORDS}.twin_sword_refinement": {
        # the second attack's table; on this shared payload it also raised the
        # first attack, which the print does not say.
        "effects.0.on_hit.0.dice_by_cl": _NOT_TYPED,
        "effects.0.count": 2,
    },
}


def _at(record: dict, path: str):
    """The value at a dotted path like ``effects.0.on_hit.0.dice_by_cl``.

    Returns ``_NOT_TYPED`` for an absent key, so "the model never typed this"
    cannot be quietly read as "this is null".
    """
    value = record
    for step in path.split("."):
        if isinstance(value, list):
            value = value[int(step)]
        elif isinstance(value, dict):
            if step not in value:
                return _NOT_TYPED
            value = value[step]
        else:
            return _NOT_TYPED
    return value


def _show(value) -> str:
    return "not typed at all" if value is _NOT_TYPED else repr(value)


def _override_registrations() -> dict[str, list[str]]:
    """Which ``reviewed_final.d`` files register each record, by record id.

    The attribution for a reviewed record lives in the override file, not in the
    built authority, so this is the only place a deferral can actually be
    enforced against.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(OVERRIDES.glob("*.json")):
        mechanics = json.loads(path.read_text(encoding="utf-8")).get("mechanics") or {}
        for record_id in mechanics:
            found.setdefault(record_id, []).append(path.name)
    return found


def test_the_deferral_check_reads_this_lanes_own_overrides():
    """A negative guard only counts if the files it reads really carry this lane's work.

    Without this, every assertion in
    ``test_deferred_row_is_left_at_the_record_the_model_pass_wrote`` would pass
    just as happily if the whole override directory were empty.
    """
    assert "audit_printed_text_fixes.json" in _override_registrations().get(
        f"{VENOM}.myriad_venom_sovereign", []), (
        "the override directory no longer shows this lane's own rows, so the deferral "
        "check below cannot see an override even if one is added"
    )


@pytest.mark.parametrize("record_id", sorted(DEFERRED_NEEDS_ENGINE_SUPPORT))
def test_deferred_row_is_left_at_the_record_the_model_pass_wrote(record_id: str):
    """A deferred row must carry neither this lane's override nor an unsafe payload.

    Holding the data back is only honest while the record really is untouched:
    the engine still reads the model's version, so nothing here silently charges
    or rolls a rule the print does not describe.  Three separate things have to
    hold -- no override file registers the row, the built record is not marked
    reviewed, and the fields this lane got wrong are still at their base values.
    When an owner/engine change makes the row representable, this test is the
    thing to delete.
    """
    registrations = _override_registrations()
    assert record_id not in registrations, (
        f"{record_id} is registered in reviewed_final.d/{registrations[record_id]}, so it IS carrying an "
        f"override; either it is no longer deferred or DEFERRED_NEEDS_ENGINE_SUPPORT is stale. "
        f"{DEFERRED_NEEDS_ENGINE_SUPPORT[record_id]}"
    )
    record = _record(record_id)
    assert record.get("typing_status") != "reviewed_final", (
        f"{record_id} is marked reviewed_final, so it IS carrying an override; either it is no longer "
        f"deferred or DEFERRED_NEEDS_ENGINE_SUPPORT is stale. {DEFERRED_NEEDS_ENGINE_SUPPORT[record_id]}"
    )
    for path, expected in DEFERRED_BASELINE[record_id].items():
        actual = _at(record, path)
        assert actual is expected or actual == expected, (
            f"{record_id} no longer has {path} at the base value ({_show(expected)}) -- found "
            f"{_show(actual)}. Restoring a rejected mapping silently: "
            f"{DEFERRED_NEEDS_ENGINE_SUPPORT[record_id]}"
        )


# The four classification lists.  They are the *claims* under test, so the scanner
# below must never read them: a list that named its own rows could keep a
# classification alive after the test that justified it had been deleted.
CLASSIFICATION_LISTS = (
    "COMPILES_TO_AN_ACTION",
    "NOT_COMPILED_TO_AN_ACTION",
    "DEFERRED_NEEDS_ENGINE_SUPPORT",
    "FALSE_POSITIVE_ROWS",
)

# The subpath prefixes the f-strings above are written against (``f"{VENOM}.some_talent"``).
PREFIXES = ("QI", "VENOM", "SWORDS", "GREATBOW", "TEA", "STORM", "YINYANG")


def _this_file_tree() -> ast.Module:
    return ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=str(Path(__file__)))


def _record_ids_in(nodes) -> set[str]:
    """Authority record ids written as string literals, whole or as an f-string tail.

    Both spellings this file uses are resolved: the whole id
    (``"tianxia.talent.ink.world_as_canvas"``) and the tail of a prefixed
    f-string (``f"{VENOM}.myriad_venom_sovereign"``), which is joined onto each
    prefix the file defines.  Anything that is not a known record is dropped.
    """
    found: set[str] = set()
    for node in nodes:
        for leaf in ast.walk(node):
            if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
                found.add(leaf.value)
            elif isinstance(leaf, ast.JoinedStr):
                for part in leaf.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        tail = part.value.strip()[1:]
                        if part.value.strip().startswith(".") and tail \
                                and all(character.isalnum() or character == "_" for character in tail):
                            found |= {f"{globals()[prefix]}.{tail}" for prefix in PREFIXES}
    return {name for name in found if name in AUTHORITY["mechanics"]}


def _rows_the_live_tests_name(tree: ast.Module) -> set[str]:
    """The authority records this file's *regressions* name -- in both directions.

    Only the bodies of live test functions are read, plus any module-level table
    that a test still uses as its data (``DEFERRED_BASELINE`` is the deferral
    test's data, not a classification).  The four classification lists are skipped
    entirely, so a row that nothing asserts on any more is no longer counted as
    named, and ``test_the_classification_check_would_notice_a_deleted_regression``
    proves it by deleting a regression from this tree in memory.
    """
    live = [node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    names: set[str] = set()
    used_by_tests: set[str] = set()
    for function in live:
        names |= _record_ids_in(ast.walk(function))
        used_by_tests |= {leaf.id for leaf in ast.walk(function) if isinstance(leaf, ast.Name)}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id not in CLASSIFICATION_LISTS \
                and target.id in used_by_tests:
            names |= _record_ids_in(ast.walk(node))
    return names


def _compiles_to_an_action(record_id: str, *, cl: int = 17) -> bool:
    """Does a character owning ``record_id`` get an action out of the compiler?"""
    doc = sheet([record_id], cl=cl, primary="Stamina")
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundle = compile_character(doc, actor_id="actor:test.audit_printed_text_fixes")
    return any(record_id in json.dumps(action, default=str)
               for action in (bundle.get("action_catalog") or []))


def test_every_row_this_file_claims_is_classified():
    """No row is asserted on without saying which level it is asserted at.

    The lists are compared against the rows the file's live regression tests
    actually name, in both directions, so a case added without a classification
    fails and a classification left behind by a deleted case fails too.  The
    second direction only holds because the scan skips the four lists
    themselves; ``test_the_classification_check_would_notice_a_deleted_regression``
    is the negative control that keeps that honest.  This is what caught
    Ruin-Tempered Armament, which was asserted as data while sitting in neither
    list.
    """
    classified = {
        "COMPILES_TO_AN_ACTION": set(COMPILES_TO_AN_ACTION),
        "NOT_COMPILED_TO_AN_ACTION": set(NOT_COMPILED_TO_AN_ACTION),
        "DEFERRED_NEEDS_ENGINE_SUPPORT": set(DEFERRED_NEEDS_ENGINE_SUPPORT),
        "FALSE_POSITIVE_ROWS": set(FALSE_POSITIVE_ROWS),
    }
    for name, rows in classified.items():
        assert rows, f"{name} should stay listed"
    overlap = {
        left: rows & classified[right]
        for left, rows in classified.items() for right in classified if left < right
        if rows & classified[right]
    }
    assert not overlap, f"a row is classified more than once: {overlap}"
    reasons = {**NOT_COMPILED_TO_AN_ACTION, **DEFERRED_NEEDS_ENGINE_SUPPORT, **FALSE_POSITIVE_ROWS}
    for name in ("NOT_COMPILED_TO_AN_ACTION", "DEFERRED_NEEDS_ENGINE_SUPPORT", "FALSE_POSITIVE_ROWS"):
        assert all(reasons[row].strip() for row in classified[name]), \
            f"every row in {name} needs a reason"

    named = _rows_the_live_tests_name(_this_file_tree())
    unclassified = named - set().union(*classified.values())
    assert not unclassified, (
        f"these rows are asserted on in this file but classified nowhere: {sorted(unclassified)}. "
        f"Add each to COMPILES_TO_AN_ACTION, NOT_COMPILED_TO_AN_ACTION, DEFERRED_NEEDS_ENGINE_SUPPORT "
        f"or FALSE_POSITIVE_ROWS."
    )
    unmentioned = set().union(*classified.values()) - named
    assert not unmentioned, (
        f"these rows are classified but no regression in this file names them any more: {sorted(unmentioned)}. "
        f"Delete the classification with the test, or restore the test."
    )


def test_the_classification_check_would_notice_a_deleted_regression():
    """Negative control: drop a regression in memory and the check must react.

    The check above is only a guard against a stale classification if the scan
    stops reading the classification lists.  This removes the Ruin-Tempered
    Armament damage regression from a copy of the file's own syntax tree and
    asserts the row stops being named, so a future regression that lets the
    lists vouch for themselves fails here instead of passing quietly.

    The affected row is worked out from the trees rather than written out as a
    literal, because a literal here would be one more place naming it and would
    hide the very effect this is checking for.
    """
    tree = _this_file_tree()
    victim = "test_ruin_tempered_armament_bonus_damage_grows_with_cl"
    assert any(isinstance(node, ast.FunctionDef) and node.name == victim for node in tree.body), (
        f"the control needs {victim} to still exist in this file; point it at a real regression"
    )
    trimmed = ast.Module(
        body=[node for node in tree.body
              if not (isinstance(node, ast.FunctionDef) and node.name == victim)],
        type_ignores=tree.type_ignores,
    )

    named_before = _rows_the_live_tests_name(tree)
    named_after = _rows_the_live_tests_name(trimmed)
    classified = set().union(COMPILES_TO_AN_ACTION, NOT_COMPILED_TO_AN_ACTION,
                             DEFERRED_NEEDS_ENGINE_SUPPORT, FALSE_POSITIVE_ROWS)
    lost = named_before - named_after
    orphaned = classified - named_after

    assert lost, f"deleting {victim} changed nothing the scan names, so it is not a usable control"
    assert orphaned, (
        f"deleting {victim} left every classification still named, so the scan is reading the "
        f"classification lists and cannot see a deleted regression"
    )
    assert orphaned == lost & classified, (
        f"the classifications left behind should be exactly the deleted test's classified rows: "
        f"orphaned {sorted(orphaned)}, newly unnamed {sorted(lost)}"
    )


@pytest.mark.parametrize("record_id", sorted(COMPILES_TO_AN_ACTION))
def test_a_row_listed_as_an_action_really_compiles_to_one(record_id: str):
    """The action-level list has to match the compiler, not just the lane's memory."""
    assert _compiles_to_an_action(record_id), (
        f"{record_id} is listed in COMPILES_TO_AN_ACTION but compiles to no action; "
        f"move it to NOT_COMPILED_TO_AN_ACTION with the reason, and lower the tests that "
        f"claim the engine pays or rolls it."
    )


@pytest.mark.parametrize("record_id", sorted(NOT_COMPILED_TO_AN_ACTION))
def test_a_row_listed_as_data_really_does_not_compile_to_an_action(record_id: str):
    """The data-only list has to match the compiler too, in the other direction."""
    assert not _compiles_to_an_action(record_id), (
        f"{record_id} is listed in NOT_COMPILED_TO_AN_ACTION but now compiles to an action; "
        f"its tests should be moved to the action or execution level."
    )
