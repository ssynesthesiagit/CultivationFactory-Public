"""The Piercing Needle's typing-only GM riders (needle-riders-1, 2026-10-21).

Each printed clause runs through the real fight or the real character compiler, and each test fails on the authority
and plug-ins the branch replaced:

  Arm Strike   "A creature without a suitable limb is immune to this Exploit."
  Chest Strike "A creature without a vulnerable chest, core, or comparable center of breath is immune to Chest Strike."
  Leg Slash    "A creature without a vulnerable limb, joint, or comparable means of movement is immune to Leg Slash."
  Read Foe     "Gain proficiency in Insight. If you already have proficiency in Insight, gain Expertise instead."
  The One      "Object, Barrier, or Structure: the target takes additional damage equal to eighteen rolls of the
  Opening       attack's normal damage die, ignoring ordinary damage thresholds and ordinary Resistance."
  Beneath
  Heaven

Vacuum Slice stays a GM rider: one shared attack roll compared with each creature's AC needs a shared-d20 attack seam
that combat/gate2_engine._resolve_attack_spec does not offer (the same missing seam Nine Palaces Killing Array waits
on), so no test here pretends otherwise.

The physiology labels are the persisted creature record (an explicit printed trait), never inferred from a name.
"""

from pathlib import Path

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests import h1_support as H
from tests import r1i_service_support as R
from tests.test_carry import KIT
from tests.test_needle import FOE1, _bears, _land_exploit

ROOT = Path(__file__).resolve().parents[1]


def _labels(actor_id, **traits):
    """Add explicit printed physiology labels to one compiled actor, then re-seal the bundle."""
    def transform(bundles):
        bundle = next(item for item in bundles if item["actor_id"] == actor_id)
        template = bundle["actor_template"]
        template["creature_types"] = list(template.get("creature_types") or ()) + [
            f"physiology:{name}:{int(value)}" for name, value in traits.items()]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return transform


def _failing_constitution(actor_id):
    """Make the foe's Constitution save fail whatever the seed rolls, so the ordinary path is not dice-luck."""
    def transform(bundles):
        bundle = next(item for item in bundles if item["actor_id"] == actor_id)
        bundle["actor_template"]["saving_throws"] = {
            **(bundle["actor_template"].get("saving_throws") or {}), "CON": -100}
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return transform


def _both(*transforms):
    def run(bundles):
        for transform in transforms:
            if transform is not None:
                transform(bundles)
    return run


def _use_exploit(tmp_path, talent, seed, *, transform=None):
    """The table's owner hits a foe with the dagger and the sole known Exploit is accepted through the real menu."""
    combat, table, mid, _send, commit = R.fixture(
        tmp_path, [talent], seed=seed, owner_kit={"starting_kit": KIT}, owner_dc=50,
        foe_ac=4, foe_score=6, allies=["actor:factory.r1i-second"], bundle_transform=transform)
    commit(R.candidate(table, mid, "Bi Shou (Dagger) attack", R.FOE))
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    return session.engine


def _logs(engine, source=None):
    return [event.payload.get("log") for event in engine.events
            if event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("log")
            and (source is None or str(event.source_definition_id) == source)]


# ================================================================================================================ physiology
def test_a_forbidden_trait_refuses_only_a_record_that_says_it_is_absent():
    """An unstated anatomy stays unknown: only an explicit printed 'no' makes a creature immune."""
    from combat.ext import physiology

    engine, _me, foe = _land_exploit("TAL_FENCING_CHEST_STRIKE")
    assert physiology.eligible(foe, {"forbids_physiology": {"any": ["vulnerable_core"]}}), "an unstated record is immune"
    foe.creature_types = (*foe.creature_types, "physiology:vulnerable_core:0")
    assert not physiology.eligible(foe, {"forbids_physiology": {"any": ["vulnerable_core"]}})
    assert physiology.eligible(foe, {"forbids_physiology": {"any": ["vulnerable_limbs"]}}), "another trait is not touched"


# ================================================================================================================ Arm Strike
def test_arm_strike_passes_over_a_creature_that_has_no_limb_to_strike():
    engine, _me, foe = _land_exploit(
        "TAL_FENCING_ARM_STRIKE", prepare=lambda e: setattr(
            e.state.actors[FOE1], "creature_types",
            (*e.state.actors[FOE1].creature_types, "physiology:manipulating_limbs:0")))
    assert not _bears(foe, "needle_arm_strike")
    # The table is told why, by the exploit's own source (the sentence itself is owner prose).
    assert _logs(engine, "passive:TAL_FENCING_ARM_STRIKE"), _logs(engine)


def test_arm_strike_still_lands_on_an_ordinary_creature():
    engine, _me, foe = _land_exploit("TAL_FENCING_ARM_STRIKE")
    assert _bears(foe, "needle_arm_strike")


# ================================================================================================================ Chest Strike
def test_chest_strike_never_poisons_a_creature_without_a_vulnerable_core(tmp_path):
    engine = _use_exploit(tmp_path, "TAL_FENCING_CHEST_STRIKE", "RIDERS1-CHEST-IMMUNE",
                          transform=_labels(R.FOE, vulnerable_core=False))
    foe = engine.state.actors[R.FOE]
    assert not [c for c in foe.conditions.values() if c.condition_id == "condition:typed.poisoned"]
    assert not [e for e in engine.events if e.event_type == "SAVE_ROLLED"], "an immune target is not asked to save"
    assert _logs(engine, "passive:TAL_FENCING_CHEST_STRIKE"), _logs(engine)


def test_chest_strike_still_poisons_an_ordinary_creature_after_reload(tmp_path):
    engine = _use_exploit(tmp_path, "TAL_FENCING_CHEST_STRIKE", "RIDERS1-CHEST-ORDINARY",
                          transform=_failing_constitution(R.FOE))
    foe = engine.state.actors[R.FOE]
    assert [c.condition_id for c in foe.conditions.values() if c.condition_id == "condition:typed.poisoned"]
    assert [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.payload.get("success") is False]


# ================================================================================================================ Leg Slash
def test_leg_slash_leaves_a_creature_without_vulnerable_limbs_at_full_speed(tmp_path):
    engine = _use_exploit(tmp_path, "TAL_FENCING_LEG_SLASH", "RIDERS1-LEG-IMMUNE",
                          transform=_labels(R.FOE, vulnerable_limbs=False))
    foe = engine.state.actors[R.FOE]
    assert engine._effective_speed(foe) == foe.speed_ft
    assert _logs(engine, "passive:TAL_FENCING_LEG_SLASH"), _logs(engine)


def test_leg_slash_halves_an_ordinary_creatures_speeds_after_reload(tmp_path):
    engine = _use_exploit(tmp_path, "TAL_FENCING_LEG_SLASH", "RIDERS1-LEG-ORDINARY")
    foe = engine.state.actors[R.FOE]
    assert engine._effective_speed(foe) == foe.speed_ft // 2


# ================================================================================================================ Read Foe
def _skills(talents, *, sheet=None):
    document = sheet or H.sheet(talents, cl=10)
    bundle = compile_character(document, actor_id=H.ME)
    return bundle.get("skills") or {}, bundle.get("skill_proficiency") or {}


def test_read_foe_grants_insight_proficiency_and_a_second_copy_expertise():
    assert _skills(["TAL_FENCING_READ_FOE"]) == ({"Insight": 6}, {"Insight": 1})
    assert _skills(["TAL_FENCING_READ_FOE", "TAL_FENCING_READ_FOE"]) == ({"Insight": 10}, {"Insight": 2})


def test_read_foe_gives_expertise_to_a_character_who_already_has_insight():
    document = H.sheet(["TAL_FENCING_READ_FOE"], cl=10)
    document["ability_scores_and_statistics"]["skills"] = [
        {"skill": "Insight", "bonus": 6, "proficiency": "proficient", "proficiency_multiplier": 1}]
    assert _skills(["TAL_FENCING_READ_FOE"], sheet=document) == ({"Insight": 10}, {"Insight": 2})


def test_read_foe_never_moves_an_existing_expertise_and_the_skill_reaches_a_check():
    document = H.sheet(["TAL_FENCING_READ_FOE", "TAL_FENCING_READ_FOE"], cl=10)
    document["ability_scores_and_statistics"]["skills"] = [
        {"skill": "Insight", "bonus": 10, "proficiency": "expertise", "proficiency_multiplier": 2}]
    assert _skills(["TAL_FENCING_READ_FOE", "TAL_FENCING_READ_FOE"], sheet=document) == (
        {"Insight": 10}, {"Insight": 2})
    from combat.ability_checks import skill_bonus

    engine = H.duel(["TAL_FENCING_READ_FOE"])
    assert skill_bonus(engine, engine.state.actors[H.ME], "Insight", 99) == 6
    engine = H.duel(["TAL_FENCING_READ_FOE", "TAL_FENCING_READ_FOE"])
    assert skill_bonus(engine, engine.state.actors[H.ME], "Insight", 99) == 10


# ================================================ The One Opening Beneath Heaven (at an object)
def _crate(arena):
    arena["map_objects"] = [{"id": 1, "kind": "crate", "x": 4, "y": 5, "hp": 999, "ac": 1, "unattended": True}]


def test_the_one_opening_at_an_object_deals_normal_damage_plus_eighteen_rolls(tmp_path):
    combat, table, mid, _send, commit = R.fixture(
        tmp_path, ["TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN", "TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"],
        seed="RIDERS1-OPENING", owner_kit={"starting_kit": KIT}, owner_dc=50, foe_ac=1, foe_score=6, arena_edit=_crate)
    name = "Bi Shou (Dagger) attack: The One Opening Beneath Heaven (at an object)"
    commit(R.candidate(table, mid, name, "object:map.1"))
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    engine = session.engine
    rolls = {str(roll.reason): roll for roll in engine.rolls}
    attack = next(roll for reason, roll in rolls.items() if reason.startswith("ATTACK:") and "#one_opening_object" in reason)
    main = next(roll for reason, roll in rolls.items() if reason.startswith("DAMAGE:") and "#one_opening_object" in reason)
    extra = next(roll for reason, roll in rolls.items() if reason.startswith("DAMAGE:needle_one_opening_object"))
    assert attack.mode == "ADVANTAGE"
    assert extra.expression == "18d4+0", extra.expression
    assert 999 - engine.state.objects["object:map.1"].current_hp == int(main.total) + int(extra.total)
    hit = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.target_ids == ("object:map.1",))
    assert hit.payload["provisional_hit"] is True and hit.payload["mode"] == "ADVANTAGE"


def test_the_one_opening_at_an_object_ignores_ordinary_threshold_and_resistance(tmp_path):
    def armoured(arena):
        arena["map_objects"] = [{"id": 1, "kind": "crate", "x": 4, "y": 5, "hp": 999, "ac": 1,
                                 "unattended": True, "threshold": 1000, "resist": ["piercing"]}]

    combat, table, mid, _send, commit = R.fixture(
        tmp_path, ["TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN", "TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"],
        seed="RIDERS1-OPENING-THRESHOLD", owner_kit={"starting_kit": KIT}, owner_dc=50, foe_ac=1, foe_score=6,
        arena_edit=armoured)
    name = "Bi Shou (Dagger) attack: The One Opening Beneath Heaven (at an object)"
    commit(R.candidate(table, mid, name, "object:map.1"))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    damage = sum(int(roll.total) for roll in engine.rolls if str(roll.reason).startswith("DAMAGE:") and "object:1" in str(roll.reason))
    assert damage >= 19, "the Damage Threshold and Resistance must not zero this damage"
    assert 999 - engine.state.objects["object:map.1"].current_hp == damage
