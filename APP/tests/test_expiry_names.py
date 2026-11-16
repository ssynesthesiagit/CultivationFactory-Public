"""Expiry names nothing removes (hunt 2, bugs 1-3, 2026-09-28).

A condition or modifier carries an ``expires_on`` name, and only the engine's checkpoint sweeps (combat/gate2_engine.py
``_expire_for_checkpoint`` / ``_expire_typed_for_checkpoint``), combat/ext/effect_durations.py's turn / slot names and the
few event-driven names (a mark's turn, Concentration, "consumed") ever take one off. A name none of them knows lasts the rest
of the fight: Forged Severe Hindrance's END_OF_TARGET_NEXT_TURN was a stun-lock and Ignore Resistance's END_OF_SOURCE_TURN a
permanent loss of the target's Resistance (tests/test_forged_expiry.py).

Bug 3: START_OF_TARGET_NEXT_TURN is a name the engine does remove, but at the start of the applier's next turn or the holder's,
whichever comes first -- put on during the holder's own turn (a zone that fires as its turn starts, a Reaction) it ended with
the applier's turn. combat/typed_executor.py ``stated_expiry`` now names the holder's next turn exactly.

The guard at the end scans the combat code and the reviewed data for every expiry name and fails on one that is not in KNOWN,
and shows for each engine-timed name that the engine really removes it when it says.
"""

import ast
import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from combat import forged, typed_executor
from combat.ext import blacksmith_rebuke, effect_durations
from combat.factory_compiler import TYPED_AUTHORITY
from combat.gate2_runtime_content import AN
from tests.test_auto_docket import ME
from tests.test_effect_durations import _conditions, _ctx, _end_turn, _fight, _modifiers
from tests.test_forged_expiry import PRIMARY_ID, _attack_primary, _technique

APP = Path(__file__).resolve().parents[1]
MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
SOOT = MECH["ASH_TAL_SOOT_IN_LUNGS"]["effects"][0]  # Failed Save: Smothered; Successful Save: cannot take Reactions -- both "until the start of its next turn"


# ------------------------------------------------------------------ bug 3: START_OF_TARGET_NEXT_TURN
def _no_opportunity(actor):
    return [c for c in actor.conditions.values() if c.condition_id == blacksmith_rebuke.NO_OPPORTUNITY]


def test_until_the_start_of_the_targets_next_turn_names_the_targets_turn():
    engine, me, foe = _fight("TOKENS-NAMED")
    ctx = _ctx(engine, me, foe)
    effect = {"expires_on": "START_OF_TARGET_NEXT_TURN"}
    want = effect_durations.token("start", AN, foe.turns_started + 1)
    assert typed_executor.stated_expiry(ctx, effect, foe, condition=True) == want
    assert typed_executor.effect_expiry(ctx, effect, foe, condition=True) == want
    assert typed_executor.stated_expiry(ctx, {"expires_on": "START_OF_SOURCE_NEXT_TURN"}, foe) == "START_OF_SOURCE_NEXT_TURN"  # the rest are untouched
    assert typed_executor.stated_expiry(ctx, {"expires_on": "UNTIL_REMOVED"}, foe) == "UNTIL_REMOVED"


@pytest.mark.parametrize("branch, name", [("on_fail", "smothered"), ("on_success", "reaction_denied")])
def test_soot_in_lungs_lasts_to_the_start_of_the_targets_next_turn_when_it_lands_on_its_own_turn(branch, name):
    engine, me, foe = _fight("TOKENS-SOOT")
    assert _end_turn(engine) == AN  # the zone's save comes as the creature's own turn starts
    typed_executor.run_effects(_ctx(engine, me, foe), SOOT[branch])
    assert _conditions(foe, name)
    assert _end_turn(engine) == ME
    assert _conditions(foe, name), "ended with the applier's turn, before the start of the creature's own next turn"
    assert _end_turn(engine) == AN
    assert not _conditions(foe, name)


def test_soot_in_lungs_from_the_appliers_own_turn_still_ends_as_the_targets_turn_starts():
    engine, me, foe = _fight("TOKENS-SOOT-OWN")
    typed_executor.run_effects(_ctx(engine, me, foe), SOOT["on_fail"])
    assert _conditions(foe, "smothered")
    assert _end_turn(engine) == AN
    assert not _conditions(foe, "smothered")


def test_hammer_rebukes_no_opportunity_attacks_lasts_to_the_start_of_the_targets_next_turn():
    engine, me, foe = _fight("TOKENS-REBUKE")
    assert _end_turn(engine) == AN  # a Reaction: it answers on the attacker's own turn
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "hammer_rebuke_no_oa"}])
    assert _no_opportunity(foe)
    assert _end_turn(engine) == ME
    assert _no_opportunity(foe), "ended with the blacksmith's turn, before the start of the creature's own next turn"
    assert _end_turn(engine) == AN
    assert not _no_opportunity(foe)


def _put_rebukes_modifiers(engine, me, foe):
    for _key, _label, effects in blacksmith_rebuke.OPTIONS:
        if effects != [{"type": "hammer_rebuke_no_oa"}]:
            typed_executor.run_effects(_ctx(engine, me, foe), effects)  # Disadvantage on its next attack; Speed -10 feet
    assert _modifiers(foe, "attack_mode") and _modifiers(foe, "speed_ft")


def test_a_modifier_put_on_the_targets_own_turn_lasts_to_the_start_of_its_next_turn():
    # (A modifier is filed under whoever's turn it is, so the engine's own name was already right for it; the mapping keeps that.)
    engine, me, foe = _fight("TOKENS-MODIFIER-OWN")
    assert _end_turn(engine) == AN
    _put_rebukes_modifiers(engine, me, foe)
    assert _end_turn(engine) == ME
    assert _modifiers(foe, "speed_ft")
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft")


def test_a_modifier_put_on_the_appliers_turn_ends_as_the_targets_turn_starts():
    engine, me, foe = _fight("TOKENS-MODIFIER-APPLIER")
    _put_rebukes_modifiers(engine, me, foe)
    assert _end_turn(engine) == AN
    assert not _modifiers(foe, "speed_ft")


# ------------------------------------------------------------------ the guard
# The expiry names the live combat code and the reviewed data may carry, each with what takes it off. A name outside this set
# lasts the rest of the fight (hunt 2). To add one: teach something to remove it, show that in ``ENGINE_LIVES`` below (or in the
# tests of the module that removes it), then list it here.
ENGINE_NAMES = {  # combat/gate2_engine.py, swept at the turn checkpoints
    "START_OF_SELF_NEXT_TURN",    # _expire_for_checkpoint: the start of the source's next turn *or* the holder's, whichever is first
    "START_OF_TARGET_NEXT_TURN",  # the same sweep; typed_executor.stated_expiry rewrites it to the holder's own turn (bug 3)
    "END_OF_CURRENT_TURN",        # the end of the turn it was put on
    "START_OF_SOURCE_NEXT_TURN",  # _expire_typed_for_checkpoint: the start of the applier's next turn
    "END_OF_HOLDER_NEXT_TURN",    # ... the end of the affected creature's turn
    "STAND_UP",                   # ... Prone: it stands at the start of its turn (tests/test_factory_combat_compiler.py)
}
CLOCK_NAMES = {  # the name, then ":<n>" / ":<who>:<n>" / ":<round>:<slot>"
    "END_OF_SOURCE_TURN_AT",      # gate2_engine _expire_typed_for_checkpoint: the end of the applier's nth turn
    "START_OF_TURN_AT", "END_OF_TURN_AT", "START_OF_SLOT_AT",  # combat/ext/effect_durations.py (START_OF_SLOT_AT: tests/test_expiry_clock.py)
}
EVENT_NAMES = {"UNTIL_REMOVED", "CONSUMED", "CONCENTRATION_END"}  # what they wait for takes them off: the fight's end, the roll, Concentration
MARK_NAMES = {"START_OF_MARKER_NEXT_TURN", "END_OF_MARKER_NEXT_TURN"}  # typed_executor.expire_marks
# Never removed, and harmless: Meridian Regulation's penalty suppression (character_runtime_adapter.py) is keyed to the id of the
# condition instance it suppresses, so once that instance is gone the leftover modifier matches nothing.
INERT_NAMES = {"SOURCE_EFFECT_END"}
KNOWN = ENGINE_NAMES | EVENT_NAMES | MARK_NAMES | INERT_NAMES
# Strings of an expiry name's shape that are not expiry names: turn checkpoints, a reaction checkpoint, event types.
NOT_EXPIRY = {"START_OF_TURN", "END_OF_TURN", "LEAVE_REACH", "CONCENTRATION_STARTED", "CONCENTRATION_ENDED"}
# The generic expiry vocabulary excludes the stock characters' engine-specific
# expiry names and descriptive reconciliation metadata. Those runtime paths have
# their own mechanics tests; admitting their tokens here would weaken this guard
# for newly compiled characters and extensions.
STOCK_RUNTIME_AND_METADATA = {
    "combat/gate2_engine.py", "combat/gate2_runtime_content.py",
    "combat/gate2_reconciliation.py", "combat/gate2a.py", "combat/gate2_defaults.py",
}
SHAPE = re.compile(r"^(?:(?:START|END)_OF_[A-Z0-9_]+|UNTIL_[A-Z0-9_]+|LEAVE_[A-Z0-9_]+|CONSUMED[A-Z0-9_]*|CONCENTRATION_[A-Z0-9_]+|STAND_UP)(?::.*)?$")

# Read-only labels/reconciliation metadata in these modules, not admitted
# expiry tokens. Explicit expires_on writes and comparisons still scan below;
# JSON storage remains subject to the unchanged KNOWN guard.
READ_ONLY_CLOCK_METADATA = {
    "combat/ext/spatial_absence.py": {
        "CONCENTRATION_ENDED_DURING_APPLICATION",  # CONDITION_REMOVED reason
        "END_OF_SOURCE_NEXT_TURN", "END_OF_TARGET_NEXT_TURN", "END_OF_TARGET_TURN",  # _timing labels
    },
    "combat/flight_decision.py": {"END_OF_TARGET_NEXT_TURN_OR_CONSUMED"},  # legacy forecast input only
}


def unknown(name):
    return name not in KNOWN and name not in NOT_EXPIRY and name.partition(":")[0] not in CLOCK_NAMES


def _leaves(node):
    """The strings a value can be outright: itself, a branch of a conditional, an item of a list of choices, the fixed parts of an
    f-string -- not a call's arguments or a subscript's key, which only *make* a name."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            yield node.value
    elif isinstance(node, ast.IfExp):
        yield from _leaves(node.body)
        yield from _leaves(node.orelse)
    elif isinstance(node, (ast.BoolOp, ast.JoinedStr)):
        for value in node.values:
            yield from _leaves(value)
    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for value in node.elts:
            yield from _leaves(value)


def _names_in_python(source, *, metadata_names=()):
    """Every string with an expiry name's shape, and any string put where an expiry goes: ``expires_on=...``, ``{"expires_on": ...}``,
    ``x.expires_on = ...`` and ``x.expires_on == ... / in (...)``."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and SHAPE.match(node.value) and node.value not in metadata_names):
            names.add(node.value)
        put_at = []
        if isinstance(node, ast.keyword) and node.arg == "expires_on":
            put_at.append(node.value)
        elif isinstance(node, ast.Dict):
            put_at += [value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant) and key.value == "expires_on"]
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute) and node.left.attr == "expires_on":
            put_at += node.comparators
        elif isinstance(node, ast.Assign):
            put_at += [node.value for t in node.targets if getattr(t, "attr", getattr(t, "id", None)) == "expires_on"]
        for value in put_at:
            names.update(s for s in _leaves(value) if re.search(r"[A-Za-z]", s))
    return names


def _names_in_json(value, key=None):
    if isinstance(value, dict):
        return set().union(set(), *(_names_in_json(v, k) for k, v in value.items()))
    if isinstance(value, list):
        return set().union(set(), *(_names_in_json(v, key) for v in value))
    return {value} if isinstance(value, str) and (SHAPE.match(value) or (key == "expires_on" and value.strip())) else set()


@pytest.mark.parametrize("name", sorted(set().union(*READ_ONLY_CLOCK_METADATA.values())))
@pytest.mark.parametrize("put", ["apply(expires_on={value})", "x.expires_on = {value}", "row = {{'expires_on': {value}}}"])
def test_read_only_clock_metadata_never_admits_a_stored_expiry(name, put):
    value = repr(name)
    assert name not in _names_in_python("legacy_label = " + value, metadata_names={name})
    assert name in _names_in_python(put.format(value=value), metadata_names={name})
    assert name in _names_in_json({"expires_on": name}) and unknown(name)


@lru_cache(maxsize=1)
def _python_names():
    found = {}
    for path in sorted((APP / "combat").rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel not in STOCK_RUNTIME_AND_METADATA:
            found[rel] = sorted(n for n in _names_in_python(path.read_text(encoding="utf-8"),
                metadata_names=READ_ONLY_CLOCK_METADATA.get(rel, ())) if unknown(n))
    return {rel: names for rel, names in found.items() if names}


@lru_cache(maxsize=1)
def _data_names():
    files = [APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json",
             *(p for p in sorted((APP / "authority/typed_mechanics").rglob("*.json")) if p.name != "rules_text.json"),  # (the printed rules: prose)
             *sorted((APP / "combat/rules").glob("*.json")), *sorted((APP / "combat_gate4").rglob("*.json")),
             *sorted((APP / "non_sphere_authority").rglob("*.json"))]
    found = {p.relative_to(APP).as_posix(): sorted(n for n in _names_in_json(json.loads(p.read_bytes())) if unknown(n)) for p in files}
    return {rel: names for rel, names in found.items() if names}


_HOW_TO_FIX = ("An expiry name nothing removes lasts the rest of the fight. Use one of KNOWN (tests/test_expiry_names.py), or teach the engine "
               "or combat/ext/effect_durations.py to remove the new one and list it there with its proof.")


def test_no_combat_code_names_an_expiry_nothing_removes():
    assert not _python_names(), f"{_python_names()}\n{_HOW_TO_FIX}"


def test_no_reviewed_data_names_an_expiry_nothing_removes():
    assert not _data_names(), f"{_data_names()}\n{_HOW_TO_FIX}"


def test_the_rules_duration_table_names_only_expiries_something_removes():
    table = typed_executor.rules()["durations"]  # (kind -> name; null for the kinds the round clock or the ability names instead)
    assert table and not [f"{kind} -> {name}" for kind, name in table.items() if name and unknown(name)]


def test_the_scan_finds_a_name_nothing_removes():
    source = ('def f(engine, target):\n'
              '    engine._apply_condition(target, "x", "y", "z", expires_on="END_OF_TARGET_NEXT_TURN")\n'
              '    modifier = {"expires_on": "END_OF_SOURCE_TURN", "flat": -2}\n'
              '    return target.expires_on == "SOMETIME"\n')
    assert {n for n in _names_in_python(source) if unknown(n)} == {"END_OF_TARGET_NEXT_TURN", "END_OF_SOURCE_TURN", "SOMETIME"}
    data = {"effects": [{"expires_on": "END_OF_TARGET_NEXT_TURN"}, {"expires_on": "at dawn"}, {"duration": "UNTIL_LONG_REST"}, {"expires_on": None}]}
    assert {n for n in _names_in_json(data) if unknown(n)} == {"END_OF_TARGET_NEXT_TURN", "at dawn", "UNTIL_LONG_REST"}
    for name in ("START_OF_SOURCE_NEXT_TURN", "END_OF_SOURCE_TURN_AT:3", "START_OF_TURN_AT:actor:2", "START_OF_SLOT_AT:4:1", "START_OF_TURN"):
        assert not unknown(name)


# What the engine does with each name it times: put on AN by ME during ME's first turn, it survives this many of the following
# ``end_turn()`` calls (the first hands the turn to AN, the second to ME, ...) and is gone after the next one.
PROBE = typed_executor.CONDITION_PREFIX + "expiry_probe"
ENGINE_LIVES = [
    ("END_OF_CURRENT_TURN", 0),                # ME's turn ends
    ("START_OF_SELF_NEXT_TURN", 0),           # these two end at the start of the source's next turn or the holder's: AN's comes first
    ("START_OF_TARGET_NEXT_TURN", 0),
    ("START_OF_SOURCE_NEXT_TURN", 1),         # ME's next turn starts after the whole of AN's
    ("END_OF_HOLDER_NEXT_TURN", 1),           # AN's turn ends
    ("END_OF_SOURCE_TURN_AT:{me_next}", 2),   # ME's next turn ends
    ("START_OF_TURN_AT:{an}:{an_next}", 0),   # AN's next turn starts
    ("END_OF_TURN_AT:{an}:{an_next}", 1),     # ... and ends
]


def _probe(actor):
    return [c for c in actor.conditions.values() if c.condition_id == PROBE]


@pytest.mark.parametrize("name, survives", ENGINE_LIVES)
def test_every_engine_name_ends_when_it_says(name, survives):
    engine, me, foe = _fight("TOKENS-LIVES")
    name = name.format(an=AN, me_next=me.turns_started + 1, an_next=foe.turns_started + 1)
    assert not unknown(name)
    engine._apply_condition(foe, PROBE, "test.probe", me.entity_id, expires_on=name, data={})
    for _ in range(survives):
        _end_turn(engine)
        assert _probe(foe), f"{name} ended early"
    _end_turn(engine)
    assert not _probe(foe), f"{name} was not removed when it says"


def test_every_engine_timed_name_has_its_proof():
    proved = {name.partition(":")[0] for name, _ in ENGINE_LIVES}
    assert proved == (ENGINE_NAMES - {"STAND_UP"}) | (CLOCK_NAMES - {"START_OF_SLOT_AT"})  # (those two have their own tests, named above)


def test_a_name_nothing_removes_lasts_the_rest_of_the_fight():
    engine, me, foe = _fight("TOKENS-NOBODY")
    name = "END_OF_NOBODYS_TURN"  # what END_OF_TARGET_NEXT_TURN and END_OF_SOURCE_TURN were: a name that sounds like a turn
    assert unknown(name)
    engine._apply_condition(foe, PROBE, "test.probe", me.entity_id, expires_on=name, data={})
    for _ in range(8):
        _end_turn(engine)
    assert _probe(foe)


# Every Forged Technique Augment (with each of its choices) puts on only names something removes, whatever the owner's table says.
def _augment_choices():
    for augment, rule in forged.rules()["augments"].items():
        choices = rule.get("choices")
        for choice in (list(choices) if choices else [None]):
            yield augment, choice


@pytest.mark.parametrize("augment, choice", list(_augment_choices()))
def test_every_forged_augment_puts_on_only_names_something_removes(augment, choice):
    engine, me, foe = _fight("TOKENS-FORGED")
    foe.saving_throws.update({ability: -100 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")})  # it fails every save
    mechanic = forged.mechanic_for(_technique("projection", augment, **({augment: choice} if choice else {})), {PRIMARY_ID: _attack_primary()})
    held = [x for actor in (me, foe) for x in (*actor.conditions.values(), *actor.modifiers.values())]  # (kept alive: ids stay theirs)
    typed_executor.run_effects(_ctx(engine, me, foe), (mechanic or {}).get("augment_effects") or [])
    put_on = [x for actor in (me, foe) for x in (*actor.conditions.values(), *actor.modifiers.values()) if not any(x is old for old in held)]
    assert not [(x, x.expires_on) for x in put_on if not x.expires_on or unknown(x.expires_on)]
    if augment in ("minor_hindrance", "major_condition", "severe_hindrance"):
        assert put_on, "the check saw nothing put on"
