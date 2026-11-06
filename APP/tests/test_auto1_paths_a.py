"""Automation lane AUTO1 (round 24, 2026-10-04): Body Refining Path and Subpath features, the first Path
alphabetically, whose printed combat effects the table still left to the GM.

Every test compiles a real character owning the feature and runs the engine; each fails on the typing this lane
replaced. Rows: combat/rules/feature_blocks.d/auto1_paths_a.json. Typed text:
authority/typed_mechanics/reviewed_final.d/subpaths.json (Sword Saint Incarnation's Critical Hit range) and
riders_c7.json (Thousand-Hand Incarnation's extra Reaction).
"""

from __future__ import annotations

import json

import pytest

from combat import ext
from combat.gate2_runtime_models import ActionIntent

from tests import test_riders_c7 as C7

KENSEI = "tianxia.subpath.body.kensei.feature."
SWORD_SAINT = KENSEI + "sword_saint_incarnation"
MANDALA = "tianxia.subpath.body.hundred_hand_battle_mandala.feature."
CIRCLE = MANDALA + "circle_of_uncounted_arms"
THOUSAND = MANDALA + "thousand_hand_incarnation"
BLADE = "tianxia.mortal.weapon.dao"
HAFTED = "tianxia.mortal.weapon.chui"  # a hammer: Hafted, so outside the printed "Blade" group
STAMINA = "resource:core.stamina"
TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"


def force_d20(engine, natural, *, actor_id=None, reason=None):
    """Every d20 rolled from now on (by ``actor_id``, for a reason starting with ``reason``) shows ``natural``."""
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original

    def d20(**kwargs):
        wanted = natural if (actor_id in (None, kwargs.get("actor_id"))
                             and (reason is None or str(kwargs.get("reason") or "").startswith(reason))) else None
        while True:
            roll = original(**kwargs)
            if wanted is None or int(roll.natural_result) == wanted:
                return roll

    engine.roller.d20 = d20


def crit_events(events, actor_id=C7.ME):
    return [e.payload for e in events if e.event_type == "ATTACK_CRITICAL_RESOLVED" and e.actor_id == actor_id]


def damage_rolls(events, actor_id=C7.ME):
    return [e.payload for e in events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == actor_id]


def kensei_incarnated(*, items=()):
    """A CL20 Kensei with Sword Saint Incarnation used and its hands free to attack."""
    engine, me, foe = C7._kensei(["sword_saint_incarnation"], picks={"sword_saint": ["Speed -10"]}, items=items)
    foe.armor_class = 1  # the attack lands whatever it rolls
    C7.turn(engine, C7.ME)
    C7.use(engine, "Sword Saint Incarnation")
    me.action_available = True
    return engine, me, foe


def end_incarnation(engine, me):
    for condition in list(me.conditions.values()):
        if condition.condition_id.endswith("sword_saint_incarnation"):
            engine._remove_condition(me, condition.condition_id, condition.source_definition_id)


# ============================================ Sword Saint Incarnation: "Your critical-hit range becomes 19-20."
def test_sword_saint_incarnation_makes_a_natural_19_one_critical_hit():
    """The printed 19-20 range lands as ONE critical hit resolved before the damage roll, not a second packet."""
    engine, me, foe = kensei_incarnated()
    assert me.resources[STAMINA] == 60 - 7  # the printed 7-Stamina cost, unchanged
    force_d20(engine, 19, actor_id=C7.ME, reason="ATTACK")
    before = len(engine.events)
    C7.use(engine, C7.unarmed(engine), target=C7.FOE)
    answer = engine.events[before:]
    resolved = crit_events(answer)
    rolled = damage_rolls(answer)
    assert resolved and rolled
    assert all(p["critical_threshold"] == 19 and p["critical"] is True for p in resolved)
    assert all(p.get("critical") is True for p in rolled)  # every strike of the sequence takes the 19
    # ONE packet per critical attack: the printed 19 is a wider range, never a second damage roll.
    for payload in rolled:
        commits = [e for e in answer if e.event_type == "DAMAGE_COMMITTED"
                   and (e.payload or {}).get("rolled_or_pending_damage") == payload["total"]]
        assert len(commits) == 1


def test_sword_saint_incarnation_keeps_the_ordinary_20_only_range_before_it_lands():
    engine, me, foe = C7._kensei(["sword_saint_incarnation"], picks={"sword_saint": ["Speed -10"]})
    foe.armor_class = 1
    force_d20(engine, 19, actor_id=C7.ME, reason="ATTACK")
    before = len(engine.events)
    C7.use(engine, C7.unarmed(engine), target=C7.FOE)
    answer = engine.events[before:]
    assert crit_events(answer) == []
    assert damage_rolls(answer) and all(not p.get("critical") for p in damage_rolls(answer))


def test_sword_saint_incarnation_critical_range_ends_with_the_state():
    """The printed range lasts only as long as the incarnation; other characters are never affected."""
    engine, me, foe = kensei_incarnated()
    end_incarnation(engine, me)
    force_d20(engine, 19, actor_id=C7.ME, reason="ATTACK")
    before = len(engine.events)
    C7.use(engine, C7.unarmed(engine), target=C7.FOE)
    answer = engine.events[before:]
    assert crit_events(answer) == []
    assert damage_rolls(answer) and all(not p.get("critical") for p in damage_rolls(answer))


def test_sword_saint_incarnation_defers_a_blade_without_recorded_integration():
    """Carrying a Blade is not a recorded integration choice; its range stays with the GM."""
    engine, me, foe = kensei_incarnated(items=(BLADE,))
    blade = next(a.display_name for a in engine.action_catalog.values()
                 if a.owner_id == C7.ME and a.display_name.startswith("Dao (Saber / Broadsword) attack"))
    force_d20(engine, 19, actor_id=C7.ME, reason="ATTACK")
    before = len(engine.events)
    C7.use(engine, blade, target=C7.FOE)
    answer = engine.events[before:]
    assert crit_events(answer) == []
    assert damage_rolls(answer) and all(not p.get("critical") for p in damage_rolls(answer))


def test_sword_saint_incarnation_does_not_widen_a_weapon_outside_the_blade_group():
    """A club is not a Blade, so it keeps the ordinary 20-only range."""
    engine, me, foe = kensei_incarnated(items=(HAFTED,))
    club = next(a.display_name for a in engine.action_catalog.values()
                if a.owner_id == C7.ME and a.display_name.startswith("Chui (Hammer) attack"))
    force_d20(engine, 19, actor_id=C7.ME, reason="ATTACK")
    before = len(engine.events)
    C7.use(engine, club, target=C7.FOE)
    answer = engine.events[before:]
    assert crit_events(answer) == []
    assert damage_rolls(answer) and all(not p.get("critical") for p in damage_rolls(answer))


def test_sword_saint_incarnation_row_is_state_scoped_to_its_own_feature():
    engine, me, foe = kensei_incarnated()
    row = next(r for r in engine.typed_passive_rows[C7.ME] if r.get("feature_id") == SWORD_SAINT)
    assert (row["block"], row["lowest"], row["while_state"], row["weapons"]) == (
        "critical_range", 19, "sword_saint_incarnation", "unarmed_or_blade")


def test_sword_saint_incarnation_no_longer_asks_the_gm_for_a_19():
    """The printed effect is resolved by the table, so the fight stops printing it as a GM-only line."""
    assert C7.riders(SWORD_SAINT) == []


def test_sword_saint_incarnation_has_no_obsolete_combat_reminder():
    """Flight, passage and recorded integrated attacks use native consumers."""
    engine = C7.fight(C7.bundle([SWORD_SAINT], cl=20), foe=C7._typed_foe())
    button = next(a for a in engine.action_catalog.values()
                  if a.owner_id == C7.ME and a.display_name == "Sword Saint Incarnation")
    riders = (button.parameters.get("typed") or {}).get("riders") or []
    assert riders == C7.riders(SWORD_SAINT)


@pytest.mark.parametrize("feature", [TEMPERED, "tianxia.path.body_refining.feature.indomitable_body",
                                     "tianxia.path.body_refining.feature.meridian_reinforcement"])
def test_the_printed_procedure_lines_a_path_feature_enforces_are_marked_as_covered(feature):
    """Checklist 6/10: the rows name which printed lines the table resolves, so they cannot come back as GM lines."""
    from combat.typed_reactions import rules as block_rules

    block = (block_rules().get("features") or {})[feature]
    covers = block.get("covers") or []
    from combat.rule_help import printed_rule_text
    from tests.prose_fingerprints import assert_prose_fingerprint

    assert block.get("block") and covers, (feature, block)
    assert_prose_fingerprint("covers:" + feature, covers)
    assert_prose_fingerprint("printed:" + feature, printed_rule_text(feature))


# ======================== Thousand-Hand Incarnation: "Gain one additional Reaction each round ..."
def mandala_incarnated():
    engine = C7.fight(C7.bundle([CIRCLE, THOUSAND], cl=20), foe=C7._typed_foe())
    me, foe = engine.state.actors[C7.ME], engine.state.actors[C7.FOE]
    foe.armor_class = 1
    C7.answers(engine)
    C7.turn(engine, C7.ME)
    C7.use(engine, "Thousand-Hand Incarnation")
    return engine, me, foe


def test_thousand_hand_incarnation_grants_one_extra_reaction_for_circle_of_uncounted_arms():
    from combat.ext.reaction_economy import covers

    engine, me, foe = mandala_incarnated()
    rows = [r for r in engine.typed_passive_rows[C7.ME]
            if r.get("block") == "reaction_economy" and r.get("feature_id") == THOUSAND]
    assert len(rows) == 1
    grant = rows[0]
    assert grant["grant"] == "extra" and grant["while_state"] == "thousand_hand_incarnation"
    assert covers(grant, {"feature_id": CIRCLE, "block": "generic"}) is True
    assert covers(grant, {"feature_id": "opportunity_attack", "block": "opportunity"}) is False


def test_thousand_hand_incarnation_reaction_grant_is_inert_without_the_state():
    """Checklist 3: the plug-in row is inert for anyone who does not own the incarnation."""
    engine = C7.fight(C7.bundle([CIRCLE], cl=20), foe=C7._typed_foe())
    assert not [r for r in engine.typed_passive_rows[C7.ME] if r.get("block") == "reaction_economy"]


def test_thousand_hand_incarnation_no_longer_says_its_extra_reaction_is_the_gms():
    """Pin the exact remaining Circle-use rider, not merely its count."""
    from combat.factory_compiler import TYPED_AUTHORITY

    record = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"][THOUSAND]
    from tests.prose_fingerprints import assert_prose_fingerprint

    assert record["coverage"] == "CORE_WITH_RIDERS" and len(record["riders"]) == 1
    assert_prose_fingerprint("riders:" + THOUSAND, record["riders"])
    engine, _me, _foe = mandala_incarnated()
    rows = [r for r in engine.typed_passive_rows[C7.ME] if r.get("block") == "reaction_economy"]
    assert len(rows) == 1 and rows[0]["grant"] == "extra"


@pytest.mark.parametrize("feature,block", [(SWORD_SAINT, "critical_range"), (THOUSAND, "reaction_economy")])
def test_scope_features_carry_their_own_block_row(feature, block):
    from combat.typed_reactions import rules as block_rules

    assert (block_rules().get("features") or {})[feature]["block"] == block

# ============================ Tempered Response: "Choose one Defensive Discipline" (a build-time choice)
ABILITY = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
           "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}


def disciplined(feature, ability, *, cl=1):
    """Fight the Path feature and record the printed Defensive Discipline through its own button."""
    engine = C7.fight(C7.bundle([feature], cl=cl), foe=C7._typed_foe())
    # C7.fight artificially starts the owner twice; this selector is first-turn setup.
    engine.state.actors[C7.ME].turns_started = 1
    C7.answers(engine)
    label = next(a.display_name for a in engine.action_catalog.values()
                 if a.owner_id == C7.ME and a.display_name.startswith(feature.rsplit(".", 1)[-1].replace("_", " ").title())
                 and ABILITY[ability] in a.display_name)
    C7.use(engine, label)
    return engine, engine.state.actors[C7.ME], engine.state.actors[C7.FOE]


def test_a_character_without_a_discipline_gets_no_buttons():
    engine = C7.fight(C7.bundle([], cl=5), foe=C7._typed_foe())
    assert not [a for a in engine.action_catalog.values()
                if a.owner_id == C7.ME and "Response" in a.display_name and "Defensive" not in a.display_name
                and a.display_name.startswith(("Tempered", "Cultivated", "Soulward"))]


def _service_discipline(tmp_path, feature, ability, seed):
    """Record the build choice by an accepted table action, then cold load it."""
    from tests.h48_table_support import OWNER, fixture, candidate, assert_reload_verify_replay
    from combat.gate5_service import CombatService

    combat, table, match_id, _send, _commit = fixture(tmp_path, [], seed=seed, path_features=[feature])
    _commit(candidate(table, match_id, ABILITY[ability]))
    assert_reload_verify_replay(combat, match_id, tmp_path)
    engine = CombatService(combat.source_root, tmp_path)._load_session(match_id).engine
    me = engine.state.actors[OWNER]
    row = next(r for r in engine.typed_reaction_rows[OWNER] if r.get("feature_id") == feature)
    return engine, me, row


class _Roll:
    """The engine's save roll shape, as a stand-in for a failed roll the table has already made."""

    def __init__(self, total, natural_result):
        self.total, self.natural_result = total, natural_result

    def model_copy(self, update):
        return _Roll(update.get("total", self.total), self.natural_result)

    @property
    def modifier(self):
        return self.total


# ------------------------------------------------------------------------------- Meridian Reinforcement (CL7, Body Refining)
# Row: combat/rules/feature_blocks.d/auto1_paths_a.json; plug-in: combat/ext/meridian_reinforcement.py
MERIDIAN = "tianxia.path.body_refining.feature.meridian_reinforcement"


def _meridian_fight(*, features=(MERIDIAN,), dc=5, condition="condition:typed.poisoned", stamina=60, **kw):
    """A live engine on a yard whose owner owns ``features`` and is Poisoned by a failed save of Difficulty Class ``dc``."""
    engine = C7.fight(C7.bundle(list(features), **kw), **kw.pop("fight", {}))
    me = engine.state.actors[C7.ME]
    me.resources[C7.STAMINA] = stamina
    engine._apply_condition(me, condition, "test:poison", C7.foe_id(engine), expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CON", "dc": dc},
                                  "repeat_save": {"ability": "CON", "dc": dc, "when": "start"}})
    # A turn_end hook runs inside the TURN_ENDED event, so the ask has an intent to travel on.
    engine._active_intent = ActionIntent(intent_id="auto1-meridian", decision_id="d", candidate_id="c",
                                         state_version=0, actor_id=C7.ME)
    C7.answers(engine)
    return engine, me


def _poisoned(actor, condition="condition:typed.poisoned"):
    return any(c.condition_id == condition for c in actor.conditions.values())


def test_meridian_reinforcement_repeats_the_poisoned_save_at_the_end_of_your_turn():
    """The printed "at the end of your turn ... spend 1 Stamina to repeat the original saving throw"."""
    engine, me = _meridian_fight(dc=1)
    assert _poisoned(me)
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 59  # 1 Stamina, the printed cost
    assert not _poisoned(me)  # the repeated save beat DC 1, so the Poisoned condition ends
    saves = [r for r in engine.rolls if str(r.reason).startswith("SAVE") and str(r.expression).endswith("+2")]
    assert any(int(r.total) >= 1 for r in saves), [str(r.reason) for r in engine.rolls]


def test_meridian_reinforcement_keeps_you_poisoned_when_the_repeated_save_fails():
    engine, me = _meridian_fight(dc=99)
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 59 and _poisoned(me)


def test_meridian_reinforcement_is_offered_once_per_round():
    engine, me = _meridian_fight(dc=99)
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 59
    engine._system_start_turn()
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 59, "the printed 'once per round' limit"
    engine.state.round_number = int(engine.state.round_number) + 1
    engine._system_start_turn()
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 58


def test_meridian_reinforcement_asks_before_spending_and_the_fighter_may_decline():
    from combat.gate2_runtime_models import ReactionDecision

    engine, me = _meridian_fight(dc=1)

    def provider(request):
        if request.get("extension_choice") is None:
            return None, None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine.set_reaction_provider(provider)
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 60 and _poisoned(me), "a declined repeat costs nothing"


def test_meridian_reinforcement_does_nothing_without_the_feature():
    engine, me = _meridian_fight(features=(), dc=1)
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 60 and _poisoned(me)
    assert not any(row.get("block") == "meridian_reinforcement"
                   for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(C7.ME, []))


def test_meridian_reinforcement_does_nothing_to_a_condition_with_no_save_behind_it():
    engine, me = _meridian_fight(dc=1)
    engine._remove_condition(me, "condition:typed.poisoned", "test:clear")
    engine._apply_condition(me, "condition:typed.poisoned", "test:natural", C7.foe_id(engine), expires_on="UNTIL_REMOVED")
    ext.run("turn_end", engine, me)
    assert me.resources[C7.STAMINA] == 60 and _poisoned(me), "the printed text asks to REPEAT the original throw"


def test_meridian_reinforcement_never_ends_the_printed_excluded_conditions():
    """The printed exclusion of Exhaustion from 0 Cultivation Points, Hidden Injuries and the rest."""
    engine, me = _meridian_fight(features=(), dc=1)
    for name in ("condition:typed.exhaustion", "condition:typed.hidden_injury", "condition:typed.tribulation_scar"):
        engine._apply_condition(me, name, "test:source", C7.foe_id(engine), expires_on="UNTIL_REMOVED",
                                data={"origin_save": {"ability": "CON", "dc": 1}})
    engine._apply_condition(me, "condition:typed.poisoned", "test:poison", C7.foe_id(engine), expires_on="UNTIL_REMOVED",
                            data={"origin_save": {"ability": "CON", "dc": 99},
                                  "repeat_save": {"ability": "CON", "dc": 99, "when": "start"}})
    engine.typed_passive_rows[C7.ME] = [{"feature_id": MERIDIAN, "block": "meridian_reinforcement",
                                         "resource_id": C7.STAMINA, "cost": 1,
                                         "conditions": ["poisoned"], "against": ["poisoned"]}]
    ext.run("turn_end", engine, me)
    for name in ("condition:typed.exhaustion", "condition:typed.hidden_injury", "condition:typed.tribulation_scar"):
        assert any(c.condition_id == name for c in me.conditions.values()), name
    assert _poisoned(me)  # DC 99 beat nothing: the only readable condition was the Poisoned one


def test_meridian_reinforcement_rolls_with_advantage_against_being_poisoned():
    from combat import typed_executor

    engine, me = _meridian_fight(dc=1)
    ctx = typed_executor.Context(engine, me, engine.action_catalog.get("unarmed_strike") or next(iter(engine.action_catalog.values())),
                                 None, {"effects": [], "numbers": {}}, [], me, {})
    assert ext.run("save", ctx, me, "CON", {"poisoned"}) == [{"bonus": 0, "modes": ["ADVANTAGE"]}]
    assert ext.run("save", ctx, me, "CON", {"frightened"}) == [], "only the printed conditions"


def test_meridian_reinforcement_still_leaves_the_printed_exclusion_line_to_the_gm():
    """The exclusion list is not claimed as covered: the plug-in only reads its own printed conditions."""
    from combat.typed_reactions import rules as block_rules

    covers = (block_rules().get("features") or {})[MERIDIAN].get("covers") or []
    assert "Meridian Reinforcement cannot remove or suppress Exhaustion gained from reaching 0 Cultivation Points" \
        not in " ".join(covers)


# ------------------------------------------------------------------- Extra Attack: "This increases to three attacks at CL11 and four attacks at CL17."
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"


@pytest.mark.parametrize("cl,attacks", [(1, 2), (10, 2), (11, 3), (16, 3), (17, 4), (20, 4)])
def test_extra_attack_grants_the_printed_number_of_attacks_by_class_level(cl, attacks):
    """The printed CL11 and CL17 increase is resolved by the table (combat/typed_reactions.py:extra_attack)."""
    from combat.typed_reactions import compile_blocks

    compiled = compile_blocks([EXTRA_ATTACK], pb=6, key_mod=3, saves={}, resource_ids={"stamina": C7.STAMINA}, cl=cl)
    row = next(r for r in compiled["passives"] if r.get("block") == "extra_attack")
    assert row["attacks"] == attacks, (cl, row)

    engine = C7.fight(C7.bundle([EXTRA_ATTACK], cl=cl, items=("dao",)), foe=C7._typed_foe())
    assert [r for r in engine.typed_passive_rows[C7.ME] if r.get("block") == "extra_attack"][0]["attacks"] == attacks


def test_extra_attack_names_its_printed_increase_as_a_covered_line():
    from combat.typed_reactions import rules as block_rules

    block = (block_rules().get("features") or {})[EXTRA_ATTACK]
    covers = block.get("covers") or []
    assert block.get("block") == "extra_attack", block
    from combat.rule_help import printed_rule_text
    from tests.prose_fingerprints import assert_prose_fingerprint

    assert_prose_fingerprint("covers:" + EXTRA_ATTACK, covers)
    assert_prose_fingerprint("printed:" + EXTRA_ATTACK, printed_rule_text(EXTRA_ATTACK))
