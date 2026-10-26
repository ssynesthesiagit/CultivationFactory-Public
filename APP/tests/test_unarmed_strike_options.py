"""The generic Unarmed Strike options: Grapple, Shove: Push 5 ft and Shove: Prone.

2024 rules, quoted by the compiler itself (combat/factory_compiler.py ``_unarmed_options``): on the Attack
action a Grapple or Shove *replaces one of your attacks* and resolves on the target's Strength or Dexterity
save of its choice against DC 8 + your Strength modifier + Proficiency Bonus, against a creature at most one
size larger. On a failure it is Grappled, pushed 5 feet, or knocked Prone; on a success nothing happens. The
maneuver makes no attack roll of its own.

The attacks that follow it in that same Attack action are your *remaining attacks*, and they are delivered the
way the rest of your attacks are: with the melee weapon in your hand when you hold one, otherwise as an
Unarmed Strike. The Attack action lets you mix a weapon attack, an Unarmed Strike, a Grapple and a Shove, one
per attack, so those follow-ups keep the template's complete delivery -- its to-hit, its dice, its damage
ability and its mastery -- rather than an unrelated number. Only the save is the option's own.

These tests drive the real table (candidate preview, commit, reload from disk) and pin that delivery, the
number of remaining attacks, the save, the size limit, the three outcomes, the help text a player reads, and a
talent that shoves while its owner carries a weapon -- one that is genuinely *active*, which for Mounted Maneuvers
means its owner is actually riding the steed whose Strength answers the save.
"""
import pytest
from combat.ability_checks import ability_modifier
from combat.action_text import describe_action
from combat.ext import mounts
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import h1_support
from tests.h1_support import ROOT
from tests.hunt12_support import FOE, ME, candidate, hit_dice, reload, send
from tests.test_lock2_persistence import act

# A dao in hand: this fighter is not trained with a martial blade, so the blade's own to-hit is Strength only
# (+4) and deliberately different from the unarmed bonus (+8). Every other number is the default synthetic
# sheet: all abilities +4, PB +4, so a Shove's save DC is 8 + 4 + 4 = 16.
DAO = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}
STR_MOD, PB, UNARMED, SAVE_DC = 4, 4, 8, 16
DAO_TO_HIT, DAO_DAMAGE = 4, {"count": 1, "sides": 10, "modifier": 4}
# Unarmed damage is fixed at 1 + Strength; its unused dice placeholder carries no bonus.
UNARMED_DAMAGE = {"count": 1, "sides": 2, "modifier": 0}
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"
# "Driving Heel" (Iron Fist talent): "when a creature fails the saving throw against your Unarmed Strike's
# Grapple or Shove option ... increase the push distance by 5 feet" -- a talent that changes the Grapple itself.
DRIVING_HEEL = "TAL_IRON_FIST_DRIVING_HEEL"
# "Mounted Maneuvers" (Beastmastery talent) is a reviewed modifier on the Shove itself. Its owner keeps the dao
# as the delivery template, so it is a talent that shoves with a weapon in hand.
MOUNTED = "TAL_BEASTMASTERY_MOUNTED_MANEUVERS"
# ...but the talent only means anything to a rider who is actually in the saddle: its rule is "When you Shove while
# mounted, use the mount's Strength modifier" (combat/ext/mounts.py ``mounted_shove_dc`` returns early with no
# mount). The Rider Package rides a warhorse from the first turn (combat/rules/summons.json "mount_default"), a
# Large beast with Strength 18.
WARHORSE = "warhorse"
MOUNT = f"{ME}.summon.mount.{WARHORSE}.1"
MOUNT_STR_MOD = 4
# A second Beastmastery talent, so the control fighter below owns the same Rider Package and rides the same steed
# but *not* Mounted Maneuvers: the mount on its own must not move the save DC.
RIDER_TALENT = "TAL_BEASTMASTERY_SKIRMISH_RIDER"
# The rider tested against: Strength 10, so its own +0 cannot be mistaken for the warhorse's +4. It is still not
# trained with a dao, so the blade's to-hit is its Strength alone and the dao's damage carries the same +0.
RIDER_STR_SCORE, RIDER_STR_MOD = 10, 0
# This fighter's ordinary Attack action: three attacks, plus one more from Extra Attack. A Grapple or Shove spends
# exactly one of them, so three are left to deliver.
ORDINARY_ATTACKS = 4
DAO_ATTACK = "Dao (Saber / Broadsword) attack"
OPTIONS = ["Grapple", "Shove: Push 5 ft", "Shove: Prone"]


def _abilities(score, *, dex=None, str_score=None):
    """The synthetic sheet's six abilities. ``dex``/``str_score`` override one of them, so a test can tell this
    character's own Strength modifier from the mount's."""
    overrides = {"DEX": dex, "STR": str_score}
    out = []
    for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        value = overrides.get(ability) or score
        out.append({"ability": ability, "score": value, "modifier": (value - 10) // 2})
    return out


def fight(tmp_path, *, mids=(), foe_mids=(), kit=None, dex=None, cl=18, seed="UNARMED-OPT",
          mount=None, str_score=None):
    """A real Factory fight: ME (manual owner) next to FOE, both committed through the table.

    ``mount`` puts ME in the saddle from the first turn, and ``str_score`` sets ME's own Strength, which is what
    lets a test tell the rider's Strength modifier from the mount's."""
    me = h1_support.sheet(list(mids), cl=cl, dc=100, primary="Stamina", score=18, kit=kit)
    me["ability_scores_and_statistics"]["abilities"] = _abilities(18, str_score=str_score)
    foe = h1_support.sheet(list(foe_mids), cl=cl, primary="Stamina", score=18)
    foe["ability_scores_and_statistics"]["abilities"] = _abilities(18, dex=dex)
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundles = [compile_character(me, actor_id=ME, reaction_plan={"ask": True},
                                 summon_plan={"mount": mount} if mount else None),
               compile_character(foe, actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed=seed,
        display_name="Unarmed Strike options regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def action(combat, mid, name):
    engine = combat._load_session(mid).engine
    return engine.action_catalog[next(a for a in engine.state.actors[ME].action_ids
                                      if engine.action_catalog[a].display_name == name)]


def typed(combat, mid, name):
    return action(combat, mid, name).parameters["typed"]


def rolls(engine, source, event_type):
    return [e for e in engine.events if e.source_definition_id == source and e.event_type == event_type]


def remaining(typed_row):
    return next((e for e in typed_row["effects"] if e.get("type") == "attack"), None)


def attacks_in(typed_row):
    """How many attacks an action makes, counted from *its own* attack effects. This is the independent source for
    "the Attack action's count": a maneuver's remaining attacks are read against it, never against the maneuver's
    own compiled effect, which would happily agree with a compiler that emitted one attack too many."""
    return sum(int(e.get("count") or 1) for e in typed_row["effects"] if e.get("type") == "attack")


@pytest.mark.parametrize("name", OPTIONS)
def test_the_attacks_after_a_shove_keep_the_held_weapon_delivery(tmp_path, name):
    """The attacks that follow a Shove/Grapple in the same Attack action are the character's own remaining
    attacks, so they keep that weapon's complete delivery: its to-hit, its dice, its damage ability. They are
    never a weapon's damage rolled at some unrelated bonus (or a bonus taken from a weapon the damage does not
    come from)."""
    combat, _, mid = fight(tmp_path, mids=[EXTRA_ATTACK], kit=DAO)
    row = typed(combat, mid, name)
    attack = remaining(row)
    assert attack is not None, f"{name} has no remaining attacks to deliver"
    assert attack["attack_kind"] == "weapon"
    assert row["numbers"]["attack_bonus"] == DAO_TO_HIT, f"{name} to-hit {row['numbers']['attack_bonus']} is not the dao's {DAO_TO_HIT}"
    assert row["weapon"]["damage"] == DAO_DAMAGE
    assert row["weapon"]["damage_type"] == "SLASHING"
    assert row["weapon"]["ability"] == "STR"
    # The blade's own attack is untouched: this is the option's delivery, not a nerf to the weapon.
    assert typed(combat, mid, "Dao (Saber / Broadsword) attack")["numbers"]["attack_bonus"] == DAO_TO_HIT


@pytest.mark.parametrize("name", OPTIONS)
def test_an_unarmed_character_still_shoves_and_strikes_unarmed(tmp_path, name):
    """With no melee weapon in hand the template is the Unarmed Strike (1 + Strength, Strength + PB), so the
    follow-up attacks are genuinely unarmed -- the fix is not a blanket 'always Strength + PB'."""
    combat, _, mid = fight(tmp_path, mids=[EXTRA_ATTACK])
    row = typed(combat, mid, name)
    attack = remaining(row)
    assert attack["attack_kind"] == "unarmed"
    assert row["numbers"]["attack_bonus"] == UNARMED == PB + STR_MOD
    assert row["weapon"]["damage"] == UNARMED_DAMAGE
    assert row["weapon"]["fixed_damage"] == 1 + STR_MOD


def test_remaining_unarmed_attacks_commit_fixed_strength_damage_and_replay(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, mids=[EXTRA_ATTACK])
    chosen = candidate(combat, mid, lambda c: c.display_name == "Grapple" and tuple(c.target_ids) == (FOE,))
    before = combat._load_session(mid).engine.state.actors[FOE].current_hp
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    committed = rolls(engine, chosen.source_definition_id, "DAMAGE_COMMITTED")
    assert [event.payload["hp_damage"] for event in committed] == [1 + STR_MOD] * (ORDINARY_ATTACKS - 1)
    assert engine.state.actors[FOE].current_hp == before - (1 + STR_MOD) * (ORDINARY_ATTACKS - 1)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_the_attacks_after_a_shove_are_rolled_exactly_as_many_as_the_attack_action_leaves(tmp_path, monkeypatch):
    """The option replaces one attack, so the shove is committed and the rolls that follow are exactly the
    Attack action's remaining attacks, rolled with the weapon's own to-hit.

    The count is settled *before* anything is committed and never read back out of the maneuver's own compiled
    effect: this fighter's ordinary Attack action makes four attacks, the Shove spends one of them, and the three
    that are left are the three that are rolled. A compiler that emitted a fourth follow-up attack would have
    satisfied an expectation read from its own output, and would fail here instead."""
    combat, table, mid = fight(tmp_path, mids=[EXTRA_ATTACK], kit=DAO)
    ordinary = attacks_in(typed(combat, mid, DAO_ATTACK))
    assert ordinary == ORDINARY_ATTACKS, f"the Attack action makes {ordinary} attacks, not {ORDINARY_ATTACKS}"
    expected = ORDINARY_ATTACKS - 1
    row = typed(combat, mid, "Shove: Prone")
    assert attacks_in(row) == expected, "a Shove spends exactly one of the Attack action's attacks, and delivers the rest"
    assert row["numbers"]["attack_bonus"] == DAO_TO_HIT
    shove = candidate(combat, mid, lambda c: c.display_name == "Shove: Prone" and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, shove)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    attacked = rolls(engine, shove.source_definition_id, "ATTACK_ROLLED")
    assert len(attacked) == expected, f"expected {expected} remaining attacks, rolled {len(attacked)}"
    assert {e.payload["modifier"] for e in attacked} == {DAO_TO_HIT}
    assert {e.payload["expression"] for e in attacked} == {f"1d20+{DAO_TO_HIT}"}
    # The damage that lands is the dao's own, read back from the same committed action: the to-hit and the
    # damage come from the same weapon (a Strength to-hit on a dao would be the mixed delivery this pins).
    assert {e.payload["expression"] for e in rolls(engine, shove.source_definition_id, "DAMAGE_ROLLED")} == {"1d10+4"}
    assert {e.payload["damage_type"] for e in rolls(engine, shove.source_definition_id, "DAMAGE_COMMITTED")} == {"SLASHING"}


def test_a_shove_makes_no_attack_roll_of_its_own(tmp_path, monkeypatch):
    """A Shove/Grapple resolves on the target's save, so it contributes no attack roll -- only the remaining
    attacks of the same Attack action do."""
    combat, table, mid = fight(tmp_path, kit=DAO)  # one attack: the shove uses all of it
    shove = candidate(combat, mid, lambda c: c.display_name == "Shove: Prone" and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, shove)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert rolls(engine, shove.source_definition_id, "SAVE_ROLLED")
    assert not rolls(engine, shove.source_definition_id, "ATTACK_ROLLED"), "a Shove replaces its attack; it makes none of its own"


@pytest.mark.parametrize("name", OPTIONS)
def test_the_target_saves_against_eight_plus_strength_plus_proficiency(tmp_path, monkeypatch, name):
    """DC 8 + Strength + PB, and the target picks Strength or Dexterity (a failed roll here)."""
    combat, table, mid = fight(tmp_path, kit=DAO)
    chosen = candidate(combat, mid, lambda c: c.display_name == name and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    saved = rolls(engine, chosen.source_definition_id, "SAVE_ROLLED")
    assert len(saved) == 1
    assert saved[0].payload["dc"] == SAVE_DC == 8 + STR_MOD + PB


def test_the_target_chooses_its_own_better_strength_or_dexterity_save(tmp_path, monkeypatch):
    """The target uses its better of the two ("its choice"); a Dexterity-foiled fighter is saved with Dexterity."""
    combat, table, mid = fight(tmp_path, kit=DAO, dex=20)  # FOE Dex +5 vs Str +4
    shove = candidate(combat, mid, lambda c: c.display_name == "Shove: Prone" and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, shove)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    saved = rolls(engine, shove.source_definition_id, "SAVE_ROLLED")
    assert saved[0].payload["reason"].endswith(":DEX")
    assert saved[0].actor_id == FOE


@pytest.mark.parametrize("name,condition", [("Shove: Prone", "prone"), ("Grapple", "grappled")])
def test_a_failed_save_prones_or_grapples_the_target(tmp_path, monkeypatch, name, condition):
    combat, table, mid = fight(tmp_path, kit=DAO)
    chosen = candidate(combat, mid, lambda c: c.display_name == name and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == f"condition:typed.{condition}" for c in engine.state.actors[FOE].conditions.values())


def test_a_failed_save_pushes_the_target_five_feet_away(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, kit=DAO)
    shove = candidate(combat, mid, lambda c: c.display_name == "Shove: Push 5 ft" and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, shove)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) == 10


def test_a_talent_that_changes_the_grapple_still_applies(tmp_path, monkeypatch):
    """Iron Fist's "Driving Heel" fires when the target fails the Grapple's save and pushes it 5 feet further,
    so a grappled target ends up 10 feet away -- out of the grappler's reach, which drops the hold."""
    combat, table, mid = fight(tmp_path, mids=[DRIVING_HEEL])
    grapple = candidate(combat, mid, lambda c: c.display_name == "Grapple" and tuple(c.target_ids) == (FOE,))
    on_fail = next(e for e in typed(combat, mid, "Grapple")["effects"] if e.get("type") == "save")["on_fail"]
    assert [row["type"] for row in on_fail][:2] == ["condition", "forced_movement"], "the talent's extra push is missing"
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, grapple)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert rolls(engine, grapple.source_definition_id, "SAVE_ROLLED")[0].payload["dc"] == SAVE_DC
    applied = [e for e in engine.events if e.event_type == "CONDITION_APPLIED"
               and e.payload.get("condition_id") == "condition:typed.grappled"]
    assert applied, "the failed save did not grapple the target"
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) == 10  # 5 ft, plus the talent's 5
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == "condition:typed.grappled"
               and e.payload.get("reason") == "OUT_OF_REACH" for e in engine.events)


def _committed_shove(tmp_path, monkeypatch, mids, *, mount=None, str_score=None, name="Shove: Prone", seed="SHAVE"):
    """Build the fight, commit ``name`` through the real table, reload it from disk, and report both what the
    maneuver was compiled to and what it actually rolled. Every number below is read off the reloaded fight."""
    combat, table, mid = fight(tmp_path, mids=mids, mount=mount, str_score=str_score, kit=DAO, seed=seed)
    row = typed(combat, mid, name)
    chosen = candidate(combat, mid, lambda c: c.display_name == name and tuple(c.target_ids) == (FOE,))
    hit_dice(monkeypatch, save_roll=3)
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    source = chosen.source_definition_id
    return {"engine": engine, "row": row,
            "save_dc": rolls(engine, source, "SAVE_ROLLED")[0].payload["dc"],
            "attacks": rolls(engine, source, "ATTACK_ROLLED"),
            "damage": rolls(engine, source, "DAMAGE_ROLLED"),
            "hurt": rolls(engine, source, "DAMAGE_COMMITTED"),
            "prone": any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[FOE].conditions.values())}


def test_a_mounted_talent_that_shoves_with_a_weapon_uses_the_mounts_strength_and_keeps_that_weapon(tmp_path, monkeypatch):
    """Mounted Maneuvers: "When you Shove while mounted, use the mount's Strength modifier." The talent is only live
    on a real riding bond -- its hook returns early with no mount -- so this fighter owns it *and* rides the
    warhorse, and holds a dao besides. The save is then the mount's to answer (8 + PB + the warhorse's +4, not the
    rider's +0), while the attacks that follow the shove stay the dao's own: committed through the real table, then
    read back after a reload from disk.

    The control fighter owns a different Beastmastery talent -- same Rider Package, same steed, same numbers, no
    Mounted Maneuvers -- and its shove is answered at the rider's own Strength. The mount alone therefore does not
    move the DC, and the difference above is the talent's doing."""
    rider = _committed_shove(tmp_path, monkeypatch, [EXTRA_ATTACK, MOUNTED], mount=WARHORSE,
                             str_score=RIDER_STR_SCORE, seed="SHAVE-RIDER")
    engine, horse = rider["engine"], rider["engine"].state.actors[MOUNT]
    assert mounts.mount_of(engine, engine.state.actors[ME]) is horse, \
        "Mounted Maneuvers is inert off the saddle: this fighter has to actually be riding for the talent to mean anything"
    assert ability_modifier(horse, "STR") == MOUNT_STR_MOD != ability_modifier(engine.state.actors[ME], "STR"), \
        "the mount's Strength must differ from the rider's, or the substitution proves nothing"
    # The option is still compiled with the rider's own DC; the mount's Strength is applied when the save is made.
    assert rider["row"]["numbers"]["save_dc"] == 8 + PB + RIDER_STR_MOD
    assert rider["save_dc"] == 8 + PB + MOUNT_STR_MOD, "the mount's Strength modifier must answer the Shove's save"
    assert rider["prone"], "the failed save must still knock the target Prone"
    # The talent changed the save, not the delivery: the attacks that follow the shove are still the dao's own.
    assert len(rider["attacks"]) == ORDINARY_ATTACKS - 1
    assert {e.payload["expression"] for e in rider["attacks"]} == {f"1d20+{RIDER_STR_MOD}"}, \
        "the dao's own to-hit, not the rider's unarmed bonus"
    assert {e.payload["expression"] for e in rider["damage"]} == {f"1d10+{RIDER_STR_MOD}"}, \
        "the dao's own damage, dealt by the same weapon the save came from"
    assert {e.payload["damage_type"] for e in rider["hurt"]} == {"SLASHING"}

    control = _committed_shove(tmp_path, monkeypatch, [EXTRA_ATTACK, RIDER_TALENT], mount=WARHORSE,
                               str_score=RIDER_STR_SCORE, seed="SHAVE-CONTROL")
    assert mounts.mount_of(control["engine"], control["engine"].state.actors[ME]) is control["engine"].state.actors[MOUNT], \
        "the control must ride the same steed, or it is not a control"
    assert control["save_dc"] == 8 + PB + RIDER_STR_MOD, \
        "without Mounted Maneuvers the mount leaves the Shove's DC alone"


def test_a_creature_more_than_one_size_larger_is_never_even_attempted(tmp_path):
    """2024: "at most one size larger than you" -- a bigger target makes no save at all, so it is never moved."""
    from combat import typed_executor
    from combat.gate2_runtime_models import Position

    combat, _, mid = fight(tmp_path, kit=DAO)
    engine = combat._load_session(mid).engine
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    shove = action(combat, mid, "Shove: Push 5 ft")
    attempt = next(effect for effect in shove.parameters["typed"]["effects"] if effect["type"] == "save")
    assert attempt["max_size_larger"] == 1
    plain = typed_executor.Context(engine, me, shove, None, shove.parameters["typed"], [foe], foe, {})
    typed_executor.block_save(plain, attempt)
    assert any(e.event_type == "SAVE_ROLLED" for e in engine.events)  # Medium vs Medium: the save happens
    before = foe.position
    engine.actor_footprints[FOE] = engine._footprint(foe).model_copy(update={
        "width_cells": 3, "height_cells": 3,
        "occupied_relative_cells": tuple(Position(x=x, y=y) for x in range(3) for y in range(3))})
    saves = len([e for e in engine.events if e.event_type == "SAVE_ROLLED"])
    huge = typed_executor.Context(engine, me, shove, None, shove.parameters["typed"], [foe], foe, {})
    typed_executor.block_save(huge, attempt)
    assert len([e for e in engine.events if e.event_type == "SAVE_ROLLED"]) == saves  # Huge vs Medium: no attempt
    assert foe.position == before


def test_the_help_text_names_the_delivery_the_character_actually_has(tmp_path):
    """A player who knows only basic D&D reads what the button promises. The follow-ups must not be called
    'unarmed' while the row deals weapon damage, and must not advertise the unarmed bonus on a weapon attack."""
    combat, _, mid = fight(tmp_path, mids=[EXTRA_ATTACK], kit=DAO)
    row = typed(combat, mid, "Shove: Prone")
    count = int(remaining(row)["count"])
    text = describe_action(action(combat, mid, "Shove: Prone").model_dump(mode="json"))
    assert f"Then make {count} remaining attack{'s' if count != 1 else ''} with the weapon in your hand" in text
    assert f"roll 1d20+{DAO_TO_HIT} against the target's Armor Class" in text
    assert "Each hit deals 1d10+4 slashing" in text
    assert "unarmed" not in text.split("Then make")[1], "a dao attack is not an unarmed attack"


def test_the_help_text_calls_the_follow_ups_unarmed_when_no_weapon_is_in_hand(tmp_path):
    """The same sentence, read the way an unarmed fighter actually receives it."""
    combat, _, mid = fight(tmp_path, mids=[EXTRA_ATTACK])
    row = typed(combat, mid, "Grapple")
    count = int(remaining(row)["count"])
    text = describe_action(action(combat, mid, "Grapple").model_dump(mode="json"))
    assert f"Then make {count} remaining unarmed attack{'s' if count != 1 else ''}" in text
    assert f"roll 1d20+{UNARMED} against the target's Armor Class" in text
    assert "Strength or Dexterity save, DC 16" in text
