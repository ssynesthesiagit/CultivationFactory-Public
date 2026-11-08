"""Lane OCF8 (owner 2026-10-04: "we are still lacking automation on various attacks. Sword Beyond Hand looks to be not
automated"): the Sword sphere's core rules that reached the fight log only as "GM should resolve" reminders, plus the
OCF8f1 review fixes (healing replacement, Training eligibility and scope, drawn-sword gating, concentration expiry,
regeneration suppression) and the OCF8r1f1 review fixes after them (the suppression's scope -- a regeneration feature
the creature pays for is still regeneration -- and the refusal query's purity, both covered below).

Rules text (owner's Sphere Compendium, authority/typed_mechanics/rules_text.json):

  SWORD_BASE_SWORD_TRAINING    "if already proficient with all three, gain +2 to attack rolls made with approved Sword
                               weapons. This bonus does not stack with another Sword-sphere feature granting the same
                               benefit."
  TAL_SWORD_IRON_SWORD_BODY    "While wielding a Sword: use Constitution for Sword attack and damage rolls if higher;
                               use Constitution as your Sword key ability; ... gain +1 AC."
  TAL_SWORD_LIFE_SEVERING_SWORD "Until the start of your next turn: reduce healing received by the target by your
                               Proficiency Bonus; the target cannot gain Temporary HP. If the target bears your Sword
                               Intent, choose one additional effect: halve healing received instead; impose Disadvantage
                               on its next Concentration saving throw; prevent ordinary regeneration until the start of
                               your next turn."
  SWORD_BASE_SWORD_BEYOND_HAND "Make a ranged Cultivation Attack. Hit: Deal Slashing or Force damage equal to the listed
                               dice + your Path key ability modifier and apply Sword Intent ... Choose the damage type
                               when making the attack."

Owners: plug-in combat/ext/sword_core.py, combat/rules/feature_blocks.d/sword.json, the Sword riders cleared in
authority/typed_mechanics/reviewed_final.d/review_sw-spirit_companions.json, and combat/ext/regeneration.py (the shared
suppression of ordinary regeneration).

On the typing the authority carried before this lane every one of these was a GM reminder: the +2 and the Constitution
swap were `attack_modifier`/`damage_modifier` rows with no block, so combat/typed_executor.block_rider printed their
evidence; Sword Beyond Hand also repeated its own printed attack, Cultivation Level table and damage-type choice. The
"with"/"without" pairs below are what fail without this lane.
"""

import json
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

from combat.factory_compiler import compile_character
from combat.ext.regeneration import RECORD as REGEN_RECORD
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_auto_lane1 as L1

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ocf8"
IMMORTAL = "actor:factory.ocf8_immortal"
SWORD_SPHERE = "tianxia.sphere.sword"
SWORD_BASES = ("SWORD_BASE_SWORD_BEYOND_HAND", "SWORD_BASE_SWORD_IN_HAND", "SWORD_BASE_SWORD_PRACTICE",
               "SWORD_BASE_SWORD_TRAINING")
WITHOUT_TRAINING = tuple(base for base in SWORD_BASES if base != "SWORD_BASE_SWORD_TRAINING")
TRAINING, IRON_BODY, LIFE_SEVERING = "SWORD_BASE_SWORD_TRAINING", "TAL_SWORD_IRON_SWORD_BODY", "TAL_SWORD_LIFE_SEVERING_SWORD"
IMMORTAL_BODY = "tianxia.path.body_refining.feature.immortal_body"
BEYOND_HAND = "Sword Beyond Hand"
BEYOND_HAND_ID = "SWORD_BASE_SWORD_BEYOND_HAND"
LIFE_SEVERING_STRIKE = BEYOND_HAND + " + Life-Severing Sword"
HALVE_HEALING, CON_DISADVANTAGE, NO_REGENERATION = "halve_healing", "con_disadvantage", "no_regeneration"
JIAN, DAO = "tianxia.mortal.weapon.jian", "tianxia.mortal.weapon.dao"
DUAN_JIAN = "tianxia.mortal.weapon.duan_jian"  # the printed shortsword
GREATSWORD = "tianxia.mortal.weapon.zhan_ma_dao"  # the printed greatsword
MARROW = "tianxia.subpath.body.bone_monarch.feature.marrow_regeneration"
STAMINA = "resource:core.stamina"


# ------------------------------------------------------------------------------------------------------- harness
def _sheet(talents, *, con=18, str_=8, key="STR", cl=10, weapon=JIAN, bases=SWORD_BASES, kit=None):
    """A Sword fighter: the Sword base abilities, the named talents, and one weapon in hand."""
    sheet = L1._sheet(BEYOND_HAND_ID, cl=cl)
    sheet["identity"].update({"path": "Body Refining", "key_ability": key})
    sheet["spheres_and_talents"] = {"sphere_record_ids": [SWORD_SPHERE], "learned_talent_record_ids": list(talents),
                                    "automatic_sphere_component_record_ids": list(bases)}
    sheet["path_and_subpath"] = {"path_record_ids": ["tianxia.path.body_refining"]}
    sheet["ability_scores_and_statistics"]["primary_resource"] = {"name": "Stamina", "maximum": 30}
    sheet["ability_scores_and_statistics"]["abilities"] = [
        {"ability": name, "score": score, "modifier": (score - 10) // 2}
        for name, score in (("STR", str_), ("DEX", 12), ("CON", con), ("INT", 10), ("WIS", 10), ("CHA", 10))]
    sheet["equipment"] = kit or [{"starting_kit": {"items": [{"item_id": weapon, "name": weapon, "quantity": 1}]}}]
    return sheet


def _bundle(talents=(), actor_id=ME, **kw):
    return compile_character(_sheet(talents, **kw), actor_id=actor_id)


def _affirmed(talents=(TRAINING,), **kw):
    """A bundle whose BUILD affirms Sword Training's printed "if already proficient with all three": the one data flag
    combat/rules/feature_blocks.d/sword.json exposes for that precondition (off by default, because nothing in this
    system records a proficiency the fighter had before the training grant)."""
    bundle = _bundle(list(talents), **kw)
    for row in bundle.get("typed_passives") or []:
        if row.get("block") == "sword" and row.get("kind") == "training":
            row["already_proficient"] = True
    return bundle


def _immortal_bundle():
    """The sparring partner that really regenerates: Body Refining's Immortal Body, "at the start of each of your turns
    ... regain 20 Hit Points" (the h52 fixture's Ning Kai owns it)."""
    sheet = _sheet([], cl=20, weapon=JIAN)
    sheet["path_and_subpath"] = {"path_feature_record_ids": [IMMORTAL_BODY]}
    sheet["spheres_and_talents"] = {}
    return compile_character(sheet, actor_id=IMMORTAL)


def _fight(bundle, *, partner=None, seed="OCF8"):
    bundles = (bundle,) if partner is None else (bundle, partner)
    actors = {ME: "team:a", AN: "team:b"} if partner is None else {ME: "team:a", IMMORTAL: "team:b"}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": list(actors),
                                                 "team_by_actor": actors,
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                        (AN if partner is None else IMMORTAL): {"x": 4, "y": 6}}})
    from tests.hunt24_support import finish_direct_setup

    finish_direct_setup(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 500
    engine.state.actors[AN if partner is None else IMMORTAL].armor_class = -50  # every printed Sword attack hits
    _ready(engine)
    return engine


def _ready(engine):
    """The fighter's next Action, for a second press in the same turn. Returns the engine."""
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available = me.bonus_action_available = me.reaction_available = True
    return engine


def _foe(engine, partner=None):
    return engine.state.actors[AN if partner is None else IMMORTAL]


def _use(engine, name):
    matches = [c for c in engine.legal_candidates() if c.display_name == name]
    assert matches, f"{name!r} is not legal; legal: {_names(engine)}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{before}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids or (), destination=candidate.destination))
    return engine.events[before:]


def _grip(engine, word):
    """Press the fighter's Draw/Stow button for its Jian."""
    return _use(engine, next(name for name in _names(engine) if name.startswith(f"{word} Jian")))


def _turn_start(engine, actor_id):
    """The engine's own turn start for one creature (this is what resolves the START_OF_*_NEXT_TURN expiries)."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return engine.state.actors[actor_id]


def _heal(engine, subject, amount, source=None):
    """Heal through the shared typed healing path every heal in this system uses (combat/typed_executor.block_healing)."""
    from combat import typed_executor as te
    from combat.ext.states import context

    actor = engine.state.actors[ME]
    source = source or next(aid for aid, a in engine.action_catalog.items()
                            if a.owner_id == ME and a.display_name == BEYOND_HAND)
    ctx = context(engine, actor, source, [subject], {"pb": 4})
    te.run_effects(ctx, [{"type": "healing", "applies_to": "target", "flat": int(amount),
                          "evidence": f"regain {amount} Hit Points"}])


def _names(engine):
    return sorted({c.display_name for c in engine.legal_candidates()})


def _payload(events, event_type):
    return next(e.payload for e in events if e.event_type == event_type)


def _said(events):
    return " ".join(str((e.payload or {}).get("rider") or "") for e in events if e.event_type == "GM_RIDER")


def _conditions(actor):
    return {c.condition_id: (c.data or {}) for c in actor.conditions.values()}


def _pill_text(engine, holder):
    """What the player's sheet reads for one creature's regeneration suppression: combat/status_text.py's own pure query
    of the ``status_description`` hook (the review's finding 2 replaced the log line with this)."""
    from combat import ext

    for row in holder.conditions.values():
        if row.condition_id == REGEN_RECORD:
            described = ext.query("status_description", engine, holder, {"condition_id": row.condition_id},
                                  dict(row.data or {}))
            return " ".join(str(entry.get("text") or "") for entry in described)
    return ""


def _answer(picks):
    """A reaction provider that takes the named option of every Sword Life-Severing choice it is asked."""
    def provider(request):
        for key, pick in picks.items():
            if key in str(request.get("checkpoint") or ""):
                options = list(request.get("legal_option_ids") or ())
                chosen = pick(options) if callable(pick) else pick
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                        reaction_source_id=request["reaction_source_id"], selection="USE",
                                        option_ids=tuple(chosen)), None
        return _decline(request)

    return provider


def _decline(request):
    """A printed choice that must be made: take its first option, which is also what an AI fighter takes."""
    options = list(request.get("legal_option_ids") or ())
    if options:
        return (ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                 reaction_source_id=request["reaction_source_id"], selection="USE",
                                 option_ids=(options[0],)), None)
    return (ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                             reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None)


def _watch(keys, seen):
    """A provider that records every choice asked for one of ``keys`` and takes its first option."""
    def provider(request):
        for key in keys:
            if key in str(request.get("checkpoint") or ""):
                trigger = request.get("choice_trigger") or {}
                seen.setdefault(key, []).append({"options": list(request.get("legal_option_ids") or ()),
                                                 "labels": dict(trigger.get("labels") or {}),
                                                 "prompt": str(trigger.get("prompt") or "")})
        return _decline(request)

    return provider


def _ac(engine):
    """The Armor Class the table actually uses against this creature (base plus every standing bonus)."""
    from combat.display_values import effective_defenses

    return int(effective_defenses(engine, engine.state.actors[ME])["armor_class"])


def _compiled(bundle, prefix=BEYOND_HAND):
    return next(a for a in bundle["action_catalog"]
                if a["owner_id"] == ME and a["display_name"].startswith(prefix))["parameters"]["typed"]


def _modifier(events):
    return int(_payload(events, "ATTACK_ROLLED")["modifier"])


def _damage_modifier(events):
    return int(_payload(events, "DAMAGE_ROLLED")["modifier"])


def _sword_in_hand(engine):
    return next(name for name in _names(engine) if "Sword in Hand" in name)


# ------------------------------------------------------------------------------------- Sword Training's +2 to the attack roll
def test_sword_training_pays_two_only_when_the_build_records_early_proficiency():
    """"if already proficient with all three": Sword Training grants exactly that proficiency, so owning the row does not
    establish the precondition. The +2 is paid only when the compiled build affirms it, and the default build does not."""
    affirmed, default, without = _fight(_affirmed()), _fight(_bundle([TRAINING])), _fight(_bundle([], bases=WITHOUT_TRAINING))
    hand = _sword_in_hand(affirmed)
    assert hand == _sword_in_hand(without) == _sword_in_hand(default)
    assert _modifier(_use(affirmed, hand)) == _modifier(_use(_ready(without), hand)) + 2
    assert _modifier(_use(_ready(default), hand)) == _modifier(_use(_ready(without), hand))


def test_the_training_bonus_never_reaches_a_weaponless_sword_attack():
    """"+2 to attack rolls made with approved Sword weapons": Sword Beyond Hand's wave of Sword Qi carries no weapon, so it
    earns no +2 even from a build that affirms the precondition. Each button is measured against the same button without
    Sword Training, so the two weapons' own numbers cannot make this pass for the wrong reason."""
    for name, expected in ((_sword_in_hand(_fight(_affirmed())), 2), (BEYOND_HAND, 0)):
        affirmed = _fight(_affirmed())
        plain = _fight(_bundle([], bases=WITHOUT_TRAINING))
        assert name in _names(affirmed) and name in _names(plain), name
        assert _modifier(_use(affirmed, name)) - _modifier(_use(plain, name)) == expected, name


def test_the_training_bonus_stays_off_for_another_proficiency_group():
    """"approved Sword weapons": a Dao is a Saber-profile weapon in the same hands, so on the very same button it earns
    neither the +2 to the attack roll nor Iron Sword Body's Constitution swap on the damage roll."""
    for weapon, approved in ((JIAN, True), (DAO, False)):
        fighter = _fight(_affirmed([TRAINING, IRON_BODY], weapon=weapon))
        plain = _fight(_bundle([], bases=WITHOUT_TRAINING, weapon=weapon))
        hand = _sword_in_hand(fighter)
        assert hand == _sword_in_hand(plain)
        swap = _swap(fighter, hand)
        assert _modifier(_use(fighter, hand)) - _modifier(_use(plain, hand)) == (2 + swap if approved else 0), weapon
        printed = _damage_modifier(_use(_ready(plain), hand))
        assert _damage_modifier(_use(_ready(fighter), hand)) == printed + (swap if approved else 0), weapon


def test_sword_training_bonus_pays_once_only():
    """The printed "This bonus does not stack with another Sword-sphere feature granting the same benefit": one row,
    one +2, however many Sword features the character owns. Both fighters' builds affirm the precondition, so the only
    difference left between them is Iron Sword Body's Constitution swap."""
    everything = _fight(_affirmed([TRAINING, IRON_BODY, LIFE_SEVERING]))
    only_training = _fight(_affirmed([TRAINING]))
    hand = _sword_in_hand(everything)
    assert _modifier(_use(everything, hand)) - _modifier(_use(only_training, hand)) == _swap(everything, hand)


# ---------------------------------------------------------------------------- Sword Training's printed proficiency grant
def _qi_sword(weapon, *, training):
    """A Qi Cultivation Sword learner (its Path trains simple weapons only, so nothing but Sword Training itself can
    make it proficient with a sword) carrying exactly one weapon: the compiled attack bonus then shows the printed
    grant on its own."""
    sheet = L1._sheet(BEYOND_HAND_ID, cl=10)
    sheet["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"]}
    sheet["spheres_and_talents"] = {"sphere_record_ids": [SWORD_SPHERE], "learned_talent_record_ids": [],
                                    "automatic_sphere_component_record_ids": [TRAINING] if training else []}
    sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon, "name": weapon, "quantity": 1}]}}]
    return compile_character(sheet, actor_id=ME)


def _weapon_attack_bonus(bundle, item):
    """The compiled to-hit number of one carried weapon's base attack (proficiency is delivered there)."""
    row = next(row for row in bundle["action_catalog"]
               if ".weapon." in str(row["source_definition_id"])
               and str(row["source_definition_id"]).rsplit(".weapon.", 1)[-1] == item.rsplit(".", 1)[-1]
               and not str(row["source_definition_id"]).endswith(".pickup"))
    return int(row["parameters"]["typed"]["numbers"]["attack_bonus"])


def test_sword_training_grants_proficiency_with_its_printed_swords():
    """"gain proficiency with shortswords, longswords, and greatswords": the training grant pays exactly the
    Proficiency Bonus (4 on this sheet) on each printed category's kit weapon -- measured against the same sheet
    compiled without the row -- and pays nothing on a weapon the printed list does not cover (the saber Dao). The
    printed greatsword (Zhan Ma Dao) is the same grant group's third member, asserted through the same producer; its
    kit row awaits a treasure-weapon authority rebuild (the pinned chassis list predates this lane)."""
    pb = 4  # this sheet's identity proficiency_bonus (test_auto_lane1._sheet)
    for item in (JIAN, DUAN_JIAN):
        assert _weapon_attack_bonus(_qi_sword(item, training=True), item) \
            == _weapon_attack_bonus(_qi_sword(item, training=False), item) + pb, item
    assert _weapon_attack_bonus(_qi_sword(DAO, training=True), DAO) \
        == _weapon_attack_bonus(_qi_sword(DAO, training=False), DAO)
    from combat.factory_compiler import _weapon_proficiency

    sheet = {"spheres_and_talents": {}}
    greatsword = [{"item_id": GREATSWORD}]
    assert _weapon_proficiency(sheet, [TRAINING], greatsword) == [True]  # the printed grant's group covers it
    assert _weapon_proficiency(sheet, [], greatsword) == [False]  # and nothing pays without the row


# ------------------------------------------------------------------------------------- Iron Sword Body's Constitution swap
def _swap(engine, attack):
    """How much higher Iron Sword Body's Constitution is than the modifier this attack's own printed rolls use (the
    weapon's own ability, or the Path key ability for a weaponless Sword technique)."""
    from combat.ability_checks import ability_modifier

    typed = engine.action_catalog[next(aid for aid, a in engine.action_catalog.items() if a.display_name == attack)] \
        .parameters["typed"]
    printed = int((typed.get("weapon") or {}).get("ability_modifier") or typed["numbers"]["key_mod"])
    return int(ability_modifier(engine.state.actors[ME], "CON")) - printed


def test_iron_sword_body_uses_constitution_for_sword_rolls_when_higher():
    """"While wielding a Sword: use Constitution for Sword attack and damage rolls if higher": both were GM lines, so a
    Sword fighter with a higher Constitution rolled its attack and its damage with the lower printed ability."""
    body = _fight(_bundle([TRAINING, IRON_BODY]))
    plain = _fight(_bundle([TRAINING]))
    swap = _swap(body, BEYOND_HAND)
    assert swap > 0, swap
    body_events = _use(body, BEYOND_HAND)
    plain_events = _use(plain, BEYOND_HAND)
    assert _damage_modifier(body_events) == _damage_modifier(plain_events) + swap


def test_iron_sword_body_swap_is_inert_without_the_feature():
    body = _fight(_bundle([TRAINING]))
    attack = BEYOND_HAND
    events = _use(body, attack)
    numbers = body.action_catalog[[s for s, a in body.action_catalog.items() if a.display_name == attack][0]] \
        .parameters["typed"]["numbers"]
    assert _damage_modifier(events) == int(numbers["key_mod"])
    assert _ac(body) == _ac(_fight(_bundle([], bases=WITHOUT_TRAINING)))


def test_iron_sword_body_adds_one_armor_class_while_a_sword_is_held():
    """"gain +1 AC" is an always-on passive, so it belongs on the Armor Class rather than on one action."""
    assert _ac(_fight(_bundle([TRAINING, IRON_BODY]))) == _ac(_fight(_bundle([TRAINING]))) + 1
    assert _ac(_fight(_bundle([TRAINING, IRON_BODY], weapon=DAO))) == _ac(_fight(_bundle([TRAINING], weapon=DAO)))


def test_iron_sword_body_ends_while_its_sword_is_stowed():
    """"While wielding a Sword" needs the Sword in hand. Reading possession instead (combat/ext/weapon_hits'
    available_weapons) kept the printed +1 AC after the only Sword was stowed."""
    fighter = _fight(_bundle([IRON_BODY]))
    plain = _fight(_bundle([], bases=WITHOUT_TRAINING))
    assert _ac(fighter) == _ac(plain) + 1
    _grip(fighter, "Stow")
    assert _ac(fighter) == _ac(plain)
    _grip(fighter, "Draw")
    assert _ac(fighter) == _ac(plain) + 1


def test_a_stowed_sword_does_not_grant_the_constitution_swap():
    """"While wielding a Sword" also covers the swap: Sword Beyond Hand is a legal button with empty hands, so without the
    drawn-Sword test the fighter kept rolling its Sword attack with Constitution after stowing its only Sword."""
    fighter = _fight(_bundle([IRON_BODY]))
    numbers = _compiled(_bundle([IRON_BODY]))["numbers"]
    printed = int(numbers["key_mod"])
    swap = _swap(fighter, BEYOND_HAND)
    assert swap > 0, swap
    assert _damage_modifier(_use(fighter, BEYOND_HAND)) == printed + swap
    _grip(fighter, "Stow")
    assert _damage_modifier(_use(_ready(fighter), BEYOND_HAND)) == printed


def test_iron_sword_body_needs_a_sword_in_hand_not_merely_in_the_pack():
    """A spare weapon left in the pack (drawn by the loadout, but a Saber, not an approved Sword weapon) grants nothing:
    the printed bonus names wielding a Sword, not carrying one."""
    kit = [{"starting_kit": {"items": [{"item_id": JIAN, "name": JIAN, "quantity": 1},
                                      {"item_id": DAO, "name": DAO, "quantity": 1}]}}]
    fighter = _fight(_bundle([IRON_BODY], kit=kit))
    plain = _fight(_bundle([], bases=WITHOUT_TRAINING, kit=kit))
    assert _ac(fighter) == _ac(plain) + 1
    _grip(fighter, "Stow")
    assert _ac(fighter) == _ac(plain)
    assert _damage_modifier(_use(_ready(fighter), BEYOND_HAND)) == int(_compiled(_bundle([IRON_BODY], kit=kit))["numbers"]["key_mod"])


# ------------------------------------------------------------------------------------- Life-Severing Sword on a Sword Intent target
def test_another_choice_leaves_the_printed_reduction_in_place():
    """"reduce healing received by the target by your Proficiency Bonus; the target cannot gain Temporary HP". Choosing one
    of the other two clauses replaces nothing, so the talent's own reduction stands and a 20-point heal is 16."""
    engine = _fight(_bundle([TRAINING, LIFE_SEVERING]))
    engine.set_reaction_provider(_answer({"sword_life_severing": [CON_DISADVANTAGE]}))
    _use(engine, LIFE_SEVERING_STRIKE)
    foe = _foe(engine)
    healing = [m for m in foe.modifiers.values() if m.target_field == "healing_reduction"]
    assert healing and str(healing[0].value).endswith(":4"), [m.value for m in healing]   # your Proficiency Bonus
    assert "condition:typed.no_temp_hp" in _conditions(foe), _conditions(foe)
    foe.current_hp = 100
    _heal(engine, foe, 20)
    assert foe.current_hp == 116


def test_halved_healing_replaces_that_reduction():
    """"halve healing received instead": the reduction this very strike applied is replaced, not applied on top of it, so at
    Proficiency Bonus 4 a 20-point heal is 10. Measured on the Hit Points, not on the modifier left behind."""
    engine = _fight(_bundle([LIFE_SEVERING]))
    engine.set_reaction_provider(_answer({"sword_life_severing": [HALVE_HEALING]}))
    _use(engine, LIFE_SEVERING_STRIKE)
    foe = _foe(engine)
    assert [m.value for m in foe.modifiers.values() if m.target_field == "healing_reduction"] == ["half"]
    foe.current_hp = 100
    _heal(engine, foe, 20)
    assert foe.current_hp == 110


def test_halved_healing_keeps_another_creatures_reduction():
    """Only this activation's own reduction is replaced: a second creature's reduction on the same target still applies,
    and the halving is applied to what is left of the healing."""
    engine = _fight(_bundle([LIFE_SEVERING]))
    engine.set_reaction_provider(_answer({"sword_life_severing": [HALVE_HEALING]}))
    foe = _foe(engine)
    engine._add_modifier(foe, "passive:another_fighter_wound", "healing_reduction", "ADD", "minus:1", "ALWAYS",
                         expires_on="UNTIL_REMOVED")
    _use(engine, LIFE_SEVERING_STRIKE)
    foe.current_hp = 100
    _heal(engine, foe, 20)
    assert foe.current_hp == 109  # (20 - 1) halved, the swordsman's own Proficiency Bonus reduction replaced


def test_life_severing_sword_asks_for_the_extra_effect_on_an_intent_target():
    """"If the target bears your Sword Intent, choose one additional effect": the one printed clause with no typed row,
    which used to reach the fight log not at all."""
    engine = _fight(_bundle([TRAINING, LIFE_SEVERING]))
    engine.set_reaction_provider(_answer({"sword_life_severing": [CON_DISADVANTAGE]}))
    _use(engine, LIFE_SEVERING_STRIKE)
    assert _conditions(_foe(engine)).get("condition:typed.concentration_mode")


def test_life_severing_sword_offers_its_three_printed_extra_effects():
    """The player is asked, and each option is named in plain words with what it does, to which creature, and how long."""
    engine = _fight(_bundle([TRAINING, LIFE_SEVERING]))
    seen = {}
    engine.set_reaction_provider(_watch(("sword_life_severing",), seen))
    _use(engine, LIFE_SEVERING_STRIKE)
    asked = seen["sword_life_severing"][0]
    assert len(asked["options"]) == 3, asked

    for option in asked["options"]:
        text = asked["labels"][option]
        assert "your next turn" in text, text      # how long, in the printed words
        assert "creature" in text or "healing" in text, text
    # the regeneration option names the regeneration features it stops, so nothing that pays for regenerating (Marrow
    # Regeneration spends 2 Stamina and its Bonus Action) is left believing it still works
    assert "Marrow Regeneration" in asked["labels"][NO_REGENERATION], asked["labels"][NO_REGENERATION]
    # the prompt names the ability, the strike and the creature, and explains the mark in plain words
    assert "Life-Severing Sword" in asked["prompt"] and "Sword strike" in asked["prompt"]
    assert _foe(engine).display_name in asked["prompt"]


def _concentration_clause():
    """A Sword fighter whose chosen extra effect is the printed Concentration disadvantage, and the creature it landed on."""
    engine = _fight(_bundle([TRAINING, LIFE_SEVERING]))
    engine.set_reaction_provider(_answer({"sword_life_severing": [CON_DISADVANTAGE]}))
    _use(engine, LIFE_SEVERING_STRIKE)
    return engine, _foe(engine)


def test_the_concentration_clause_waits_for_its_users_next_turn():
    """"impose Disadvantage on its next Concentration saving throw ... until the start of your next turn": the clause used
    to expire at the start of the TARGET's next turn, so it was gone before the later attacks in that round could force
    the save. When the victim's turn comes first in initiative it must still be there, and that save uses it up."""
    from combat import concentration

    engine, foe = _concentration_clause()
    held = next(row for row in foe.conditions.values() if row.condition_id == "condition:typed.concentration_mode")
    assert held.expires_on == "START_OF_SOURCE_NEXT_TURN", held.expires_on
    assert held.data["rule"]["next"] is True, held.data
    _turn_start(engine, AN)
    assert "condition:typed.concentration_mode" in _conditions(foe), _conditions(foe)
    assert concentration.save_mode(engine, foe) == "DISADVANTAGE"   # that Concentration save is at a Disadvantage
    assert concentration.save_mode(engine, foe) is None              # and the printed "next" uses it up


def test_the_concentration_clause_ends_at_the_start_of_the_swordsmans_own_next_turn():
    """The other initiative order: when the swordsman's own turn comes round again first, the clause is gone -- the
    printed duration is its next turn, not the victim's."""
    engine, foe = _concentration_clause()
    _turn_start(engine, ME)
    assert "condition:typed.concentration_mode" not in _conditions(foe), _conditions(foe)


def test_the_regeneration_clause_stops_a_real_regeneration():
    """"prevent ordinary regeneration until the start of your next turn": this used to say the clause in the log and change
    nothing, while Body Refining's Immortal Regeneration ("at the start of each of your turns ... regain 20 Hit Points")
    went on healing 20 at the next turn start. Choosing one of the other two clauses leaves that regeneration alone."""
    for clause, blocked in ((NO_REGENERATION, True), (CON_DISADVANTAGE, False)):
        engine = _fight(_bundle([LIFE_SEVERING]), partner=_immortal_bundle())
        engine.set_reaction_provider(_answer({"sword_life_severing": [clause]}))
        _use(engine, LIFE_SEVERING_STRIKE)
        regenerator = _foe(engine, partner=True)
        regenerator.current_hp = 300
        if blocked:
            held = next(row for row in regenerator.conditions.values()
                        if row.condition_id == "condition:typed.regeneration_suppressed")
            assert held.expires_on == "START_OF_SOURCE_NEXT_TURN", held.expires_on
        else:
            assert "condition:typed.regeneration_suppressed" not in _conditions(regenerator)
        _turn_start(engine, IMMORTAL)
        # 20 restored, less the printed Proficiency Bonus reduction this very talent applied (nothing at all when blocked)
        assert regenerator.current_hp == (300 if blocked else 316), (clause, regenerator.current_hp)
        # the refusal is a pure query, so nothing is written when it answers: the condition pill is what tells the player
        # why no Hit Points came back
        assert ("cannot regain Hit Points from regeneration" in _pill_text(engine, regenerator)) == blocked, \
            _conditions(regenerator)
        assert not [event for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"
                    and "regenerat" in str((event.payload or {}).get("log") or "").lower()]


def test_the_regeneration_refusal_is_a_pure_query_that_answers_the_same_way_twice():
    """Review finding 2: ``effect_allowed`` is a documented pure query ("handlers must be pure queries",
    combat/ext/__init__.py). Asking it whether a regeneration healing may resolve must not append an event, must not
    change the fight, and must give the same answer however often it is asked -- through the engine's own dispatch as
    well as by calling the hook."""
    from combat import ext
    from combat.ext import regeneration
    from combat.ext.states import context

    engine = _fight(_bundle([LIFE_SEVERING]), partner=_immortal_bundle())
    engine.set_reaction_provider(_answer({"sword_life_severing": [NO_REGENERATION]}))
    _use(engine, LIFE_SEVERING_STRIKE)
    regenerator = _foe(engine, partner=True)
    source = next(aid for aid, a in engine.action_catalog.items()
                  if a.owner_id == ME and a.display_name == BEYOND_HAND)
    healing = {"type": "healing", "applies_to": "target", "regeneration": True, "flat": 20}
    ctx = context(engine, engine.state.actors[ME], source, [regenerator], {"pb": 4})
    events, state = len(engine.events), engine.state.model_dump(mode="json")
    assert regeneration.regeneration_refused(ctx, healing) is False
    assert regeneration.regeneration_refused(ctx, healing) is False
    assert ext.run_strict("effect_allowed", ctx, healing) == [False]
    # rows this module does not own answer nothing, and change nothing either
    assert regeneration.regeneration_refused(ctx, {**healing, "regeneration": False}) is None
    assert regeneration.regeneration_refused(ctx, {"type": "damage", "applies_to": "target", "regeneration": True}) is None
    assert len(engine.events) == events, [e.event_type for e in engine.events[events:]]
    assert engine.state.model_dump(mode="json") == state


def test_a_paid_regeneration_still_pays_and_still_loses_only_its_healing():
    """Review finding 1: Marrow Regeneration is a Bonus Action that spends 2 Stamina, so it is a regeneration the
    creature pays for. Under the printed suppression its healing is refused -- but the activation it is: the Stamina and
    the Bonus Action are spent, and the benefit printed after the healing (end one Bleeding) still happens. Without the
    suppression the same press heals and costs exactly the same."""
    engine, fighter, events = _marrow_activation(suppressed=True)
    assert fighter.resources.get(STAMINA) == 28, fighter.resources      # the printed 2 Stamina was paid
    assert fighter.bonus_action_available is False                       # the printed Bonus Action was spent
    assert fighter.current_hp == 40, fighter.current_hp                  # and the healing it bought was refused
    assert not [event for event in events if event.event_type == "HEALING_APPLIED"], events[-3:]
    assert "cannot regain Hit Points from regeneration" in _pill_text(engine, fighter)
    assert not any(c.condition_id == "condition:typed.bleeding" for c in fighter.conditions.values())

    engine, fighter, events = _marrow_activation(suppressed=False)
    assert fighter.resources.get(STAMINA) == 28 and fighter.bonus_action_available is False
    assert fighter.current_hp > 40 and [event for event in events if event.event_type == "HEALING_APPLIED"]
    assert not any(c.condition_id == "condition:typed.bleeding" for c in fighter.conditions.values())


def _marrow_activation(*, suppressed):
    """A Bone Monarch's real Marrow Regeneration Bonus Action, bleeding, with or without Life-Severing Sword's printed
    suppression already on it. Returns the engine, its user and the events that press produced."""
    from combat import typed_executor as te
    from combat.ext.states import context

    engine = _fight(_marrow_bundle())
    fighter = engine.state.actors[ME]
    fighter.current_hp = 40
    engine._apply_condition(fighter, "condition:typed.bleeding", "test:bleed", AN, expires_on="UNTIL_REMOVED")
    if suppressed:
        # the same row combat/ext/sword_core.py delivers for the printed clause, so the pill is the printed wording
        press = next(a for a in engine.action_catalog.values() if a.display_name == "Marrow Regeneration")
        te.run_effects(context(engine, fighter, press.source_definition_id, [fighter], {}).with_source(
            "passive:TAL_SWORD_LIFE_SEVERING_SWORD"),
            [{"type": "suppress_regeneration", "applies_to": "self", "name": "Life-Severing Sword",
              "evidence": "it cannot benefit from ordinary regeneration until the start of your next turn",
              "expires_on": "START_OF_SOURCE_NEXT_TURN"}])
    engine.set_reaction_provider(_answer({"marrow_regeneration": ["bleeding"]}))
    return engine, fighter, _use(engine, "Marrow Regeneration")


def _marrow_bundle():
    """A Body Refining Bone Monarch owning Marrow Regeneration, the printed regeneration feature whose use costs
    something: a Bonus Action and 2 Stamina."""
    sheet = L1._sheet(MARROW, cl=10)
    sheet["identity"].update({"path": "Body Refining", "key_ability": "STR"})
    sheet["ability_scores_and_statistics"]["primary_resource"] = {"name": "Stamina", "maximum": 30}
    return compile_character(sheet, actor_id=ME)


def test_life_severing_sword_extra_effect_is_asked_once_per_turn():
    """The printed Use Limit is once per turn: a second Sword strike in the same turn does not ask again."""
    engine = _fight(_bundle([TRAINING, LIFE_SEVERING]))
    asked = {}
    engine.set_reaction_provider(_watch(("sword_life_severing",), asked))
    _use(engine, LIFE_SEVERING_STRIKE)
    _ready(engine)
    _use(engine, LIFE_SEVERING_STRIKE)
    assert len(asked["sword_life_severing"]) == 1, asked


def test_life_severing_sword_is_inert_without_the_talent():
    engine = _fight(_bundle([TRAINING]))
    _use(engine, BEYOND_HAND)
    conditions = _conditions(_foe(engine))
    assert "condition:typed.no_temp_hp" not in conditions
    assert "condition:typed.regeneration_suppressed" not in conditions


# ------------------------------------------------------------------------------------- Sword Beyond Hand repeats nothing
def test_sword_beyond_hand_raises_no_gm_reminder_for_a_line_the_table_runs():
    """Every one of the four reminders the owner saw named a line this attack already performs."""
    engine = _fight(_bundle([TRAINING, IRON_BODY, LIFE_SEVERING]))
    said = _said(_use(engine, _sword_attack(engine)))
    for printed in ("approved Sword weapons", "Constitution for Sword", "Make a ranged Cultivation Attack",
                    "Choose the damage type", "Cultivation Level"):
        assert printed not in said, said


def test_sword_beyond_hand_still_makes_its_printed_ranged_cultivation_attack():
    """The cleared lines are only cleared because the table does them: one attack at 60 feet, Cultivation Level dice,
    Slashing or Force, and Sword Intent on the target."""
    engine = _fight(_bundle([TRAINING, LIFE_SEVERING]))
    attack = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name.startswith(BEYOND_HAND))
    typed = attack.parameters["typed"]
    row = next(e for e in typed["effects"] if e["type"] == "attack")
    assert row["attack_kind"] == "cultivation_ranged" and attack.range_ft == 60
    assert row["on_hit"][0]["dice_by_cl"] == [[1, 4, 1, 10], [5, 10, 2, 10], [11, 16, 3, 10], [17, 20, 4, 10]]
    events = _use(engine, LIFE_SEVERING_STRIKE)
    assert _payload(events, "ATTACK_ROLLED")["target_ac"] == -50
    assert _payload(events, "DAMAGE_ROLLED")["expression"].startswith("2d10"), _payload(events, "DAMAGE_ROLLED")
    assert _payload(events, "DAMAGE_COMMITTED")["damage_type"] in ("SLASHING", "FORCE")
    assert any("sword_intent" in str(e.payload.get("condition_id")) for e in events if e.event_type == "CONDITION_APPLIED")


def _sword_attack(engine):
    """The Sword Beyond Hand button (the Life-Severing Sword form of it when that talent is owned)."""
    for name in (LIFE_SEVERING_STRIKE, BEYOND_HAND):
        if name in _names(engine):
            return name
    return next(name for name in _names(engine) if name.startswith(BEYOND_HAND))


def test_another_fighter_without_sword_keeps_its_own_rows():
    """Checklist 3: a character outside the Sword sphere is unchanged, so a fight saved before this lane replays as it did."""
    bundle = compile_character(L1._sheet("TAL_ALCHEMY_CALMING_HEART_PILL"), actor_id=ME)
    assert not [row for row in bundle.get("typed_passives") or [] if row.get("block") == "sword"]


@pytest.mark.parametrize("talent,kind", [(TRAINING, "training"), (IRON_BODY, "iron_body"),
                                         (LIFE_SEVERING, "life_severing")])
def test_each_owned_sword_feature_compiles_its_own_row(talent, kind):
    bundle = _bundle([talent])
    rows = {row["kind"]: row for row in bundle.get("typed_passives") or [] if row.get("block") == "sword"}
    assert kind in rows, rows
    assert rows[kind]["feature_id"] == talent
    assert (rows[kind]["keeps_compiling"] is talent_is_life_severing(talent))
    assert rows[kind].get("already_proficient") is False   # the printed precondition is not met by owning the row


def talent_is_life_severing(talent):
    """Life-Severing Sword keeps its own compiled modifier rows; the two passive rows do not compile a second copy."""
    return talent == LIFE_SEVERING


# --------------------------------------------------------------------- the same rules through the real table
def _table_sheet(tmp_path, project="44444444", *, talents=(TRAINING, LIFE_SEVERING), attack_bonus=100, hp=60,
                 spheres=(SWORD_SPHERE,), bases=SWORD_BASES, path_features=(), cl=10):
    """A portable Sword fighter the shipped table can install, built exactly like the direct-engine sheet above. With
    ``spheres=()`` and ``path_features=(IMMORTAL_BODY,)`` the same builder makes the regeneration test's partner."""
    import zipfile

    from tests.h1_support import sheet as base_sheet

    document = base_sheet([BEYOND_HAND_ID], cl=cl, primary="Stamina", key="STR", score=18)
    document["identity"]["update"] = None
    document["identity"].pop("update")
    document["identity"]["display_name"] = "Sword fighter" if spheres else "Regenerating mender"
    document["identity"]["path"] = "Body Refining"
    document["path_and_subpath"] = ({"path_record_ids": ["tianxia.path.body_refining"]} if not path_features
                                    else {"path_feature_record_ids": list(path_features)})
    if spheres:
        document["spheres_and_talents"] = {"sphere_record_ids": list(spheres),
                                            "learned_talent_record_ids": list(talents),
                                            "automatic_sphere_component_record_ids": list(bases)}
    else:
        document.pop("spheres_and_talents", None)
    document["ability_scores_and_statistics"]["technique_attack_bonus"] = attack_bonus
    document["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
    document["ability_scores_and_statistics"]["abilities"] = [
        {"ability": name, "score": score, "modifier": (score - 10) // 2}
        for name, score in (("STR", 18), ("DEX", 12), ("CON", 18), ("INT", 10), ("WIS", 10), ("CHA", 10))]
    document["equipment"] = [{"starting_kit": {"items": [{"item_id": JIAN, "name": JIAN, "quantity": 1}]}}]
    folder = tmp_path / "portable_characters" / project
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    return project


def _yard(combat, tmp_path, map_id):
    """A small yard: the two sides start 20 feet apart, so a 60-foot Sword Beyond Hand is in range from turn one."""
    combat.tabletop_maps.save({"map_id": map_id, "display_name": "Sword Yard",
                               "width_squares": 8, "height_squares": 8,
                               "starts": {"team1": [[3, 3]], "team2": [[7, 3]]}})
    return f"battlefield:map.{map_id}"


def _press(table, mid, menu, state, label=None, candidate=None, want=None, asked=None):
    """Press one button by label (None = end turn) and answer anything the table asks while it resolves. ``want`` picks the
    offered option whose label contains it (the printed clause this test chooses); the first option otherwise, which is
    also what an AI fighter takes. ``asked`` collects every prompt that was answered. Returns the committed response."""
    if candidate is None and label is None:
        candidate = menu["end_turn"]
    elif candidate is None:
        group = next(g for g in menu["actions"] if g["label"] == label)
        candidate = group["options"][0]["candidate_id"]
    before = state["last_sequence"]
    answers = []
    while True:
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], before, answers)
        if result["status"] != "REACTION_REQUIRED":
            return result
        prompt = result["reaction"]
        if asked is not None:
            asked.append(prompt)
        options = (prompt.get("choice") or {}).get("options") or []
        picked = next((row for row in options if want and want in str(row.get("label") or "")), None) or (options[0] if options else None)
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [picked["id"]] if picked else []})


def _done(state):
    """Whether this table state is the end of the fight (a finished match has no menu and refuses further decisions)."""
    return bool((state.get("match") or {}).get("state", {}).get("terminal_result")
                or not (state.get("menu") or {}).get("decision_id"))


def _sword_option(menu, prefix=BEYOND_HAND, target=None):
    """One Sword Beyond Hand option of this menu -- label and candidate -- aimed at ``target`` when it is named, or None."""
    group = next((g for g in menu.get("actions") or [] if str(g["label"]).startswith(prefix)), None)
    if group is None:
        return None
    option = next((row for row in group["options"] if target and target in (row.get("target_ids") or ())), None) \
        or next((row for row in group["options"] if row.get("target_ids")), group["options"][0])
    return str(group["label"]), option["candidate_id"]


def _auto(table, mid, state):
    """Step the fight on while the other side plays itself, tolerating the table refreshing underneath."""
    for _ in range(3):
        try:
            table.auto_step(mid, after=state["last_sequence"])
            return
        except Exception as exc:  # noqa: BLE001 - the table moved on; read it again
            if "STALE" not in type(exc).__name__.upper() and "409" not in str(exc):
                raise
            state = table.state(mid)


def _configure_sword_strike(combat, table, mid, state, target=None, *, enabled=True):
    """Use 25.x's persistent Life-Severing controls, then its owning base attack.

    Settings are real table commits; the player choice and saved-state assertions
    below still exercise the same printed effect, cost and once-per-turn limit.
    """
    from combat.ext.attack_modifiers import chosen

    if _sword_option(state.get("menu") or {}, BEYOND_HAND, target) is None:
        return state, None
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    parent = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == actor.entity_id and a.display_name == BEYOND_HAND)
    settings = chosen(actor, parent, LIFE_SEVERING)
    updates = []
    if bool(settings["on"]) != enabled:
        updates.append(("on", "toggle"))
    if enabled:
        updates.extend((field, "0") for field in ("option", "payment") if settings[field] != "0")
    for field, value in updates:
        engine = combat._load_session(mid).engine
        source = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.owner_id == actor.entity_id and (a.parameters.get("attack_modifier_setting") or {}) == {
                          "family": parent, "modifier": LIFE_SEVERING, "name": "Life-Severing Sword",
                          "field": field, "value": value})
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == source)
        assert _press(table, mid, state["menu"], state, candidate=cid)["status"] == "COMMITTED"
        state = table.state(mid)
    return state, _sword_option(state["menu"], BEYOND_HAND, target)


def test_the_table_never_asks_the_gm_about_a_sword_line_it_runs(tmp_path):
    """The owner's report was a line in the player-facing fight log, so this presses the button at a real table and
    reads the feed the player reads."""
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop import ButtonStore

    project = _table_sheet(tmp_path)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(project, {"mode": "ask"}, set())
    combat = CombatService(ROOT, tmp_path)
    fighter = FACTORY_ACTOR_PREFIX + project
    mid = combat.create_factory_match(project_ids=[project], opponent_actor_ids=["an_eui_early_book1_cl5"],
                                      control_modes={fighter: "MANUAL"}, match_seed="OCF8-TABLE")["match_id"]
    table = TabletopService(combat, tmp_path)
    pressed = 0
    for _ in range(40):
        state = table.state(mid)
        if (state.get("match") or {}).get("state", {}).get("terminal_result"):
            break
        menu = state.get("menu") or {}
        if not menu.get("manual"):
            _auto(table, mid, state)
            continue
        group = next((g for g in menu.get("actions") or [] if g["label"].startswith(BEYOND_HAND)), None)
        if group is None:  # the setup turn, or a turn with nothing worth pressing
            _press(table, mid, menu, state, None, next((o["candidate_id"] for g in menu.get("actions") or []
                                                       if g["label"] == "Finish fight setup"
                                                       for o in g["options"]), None))
            continue
        option = next(o for o in group["options"] if o["target_ids"])
        _press(table, mid, menu, state, None, option["candidate_id"])
        pressed += 1
    rows = table.events(mid, 0, engine=combat._load_session(mid).engine)["events"]
    said = " ".join(str(row.get("summary") or "") for row in rows)
    assert pressed, f"Sword Beyond Hand was never offered at the table: {said[:400]}"
    for printed in ("approved Sword weapons", "Constitution for Sword", "Make a ranged Cultivation Attack",
                    "Choose the damage type", "Cultivation Level"):
        assert printed not in said, said
    assert "Sword Beyond Hand" in said, said


@pytest.mark.parametrize("extra", ["No regeneration", "Halved healing"])
def test_the_table_asks_the_player_and_the_choice_survives_a_commit_and_reload(tmp_path, extra):
    """Checklist 7 and 9 at the service level: the extra effect is asked on the real table, what it puts on the creature is
    still there after the fight is committed and read back from disk, and the printed once-per-turn limit is remembered
    across that reload (the melee form is a different button with the other economy, so it is still pressable)."""
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop import ButtonStore

    project = _table_sheet(tmp_path, hp=400)
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(project, {"mode": "ask"}, set())
    combat = CombatService(ROOT, tmp_path)
    fighter = FACTORY_ACTOR_PREFIX + project
    mid = combat.create_factory_match(project_ids=[project], opponent_actor_ids=["an_eui_early_book1_cl5"],
                                      control_modes={fighter: "MANUAL"}, match_seed="OCF8-CHOICE")["match_id"]
    table = TabletopService(combat, tmp_path)
    asked, struck = [], False
    for _ in range(40):
        state = table.state(mid)
        if _done(state):
            break
        menu = state.get("menu") or {}
        if not menu.get("manual"):
            _auto(table, mid, state)
            continue
        state, found = _configure_sword_strike(combat, table, mid, state)
        menu = state.get("menu") or {}
        if found is None:
            _press(table, mid, menu, state, None, next((o["candidate_id"] for g in menu.get("actions") or []
                                                       if g["label"] == "Finish fight setup"
                                                       for o in g["options"]), None))
            continue
        _press(table, mid, menu, state, None, found[1], want=extra, asked=asked)
        struck = True
        break
    assert struck, "the real table never offered Sword Beyond Hand + Life-Severing Sword"
    assert asked, "the table never asked the player to choose the extra effect"

    engine = combat._load_session(mid).engine
    foe = next(actor for actor in engine.state.actors.values() if actor.team_id != engine.state.actors[fighter].team_id)
    chosen = _conditions(foe)
    if extra == "No regeneration":
        assert "condition:typed.regeneration_suppressed" in chosen, chosen
    else:
        assert [m.value for m in foe.modifiers.values() if m.target_field == "healing_reduction"] == ["half"]
        assert "condition:typed.regeneration_suppressed" not in chosen
    assert "condition:typed.no_temp_hp" in chosen, chosen
    from combat.ext.sword_core import PAID_HIT_KEY
    assert PAID_HIT_KEY not in engine.state.actors[fighter].turn_flags

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    again = reloaded.engine.state.actors[foe.entity_id]
    assert {row.condition_id: (row.data or {}) for row in again.conditions.values()} == chosen
    assert again.maximum_hp == foe.maximum_hp and again.current_hp == foe.current_hp
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")

    # the printed once-per-turn limit is remembered in the saved fight too: the reloaded fighter still carries the
    # turn's mark of the choice (the once-per-turn behaviour itself is test_life_severing_sword_extra_effect_is_asked_once_per_turn)
    from combat.ext.sword_core import TURN_KEY

    remembered = reloaded.engine.state.actors[fighter].turn_flags.get(TURN_KEY)
    assert remembered and ":" in str(remembered), reloaded.engine.state.actors[fighter].turn_flags


def test_a_regenerating_foe_loses_only_its_regeneration(tmp_path):
    """The printed clause at the service level, against a creature that really regenerates: Immortal Body's "at the start
    of each of your turns ... regain 20 Hit Points" gives back 20 at one turn start and nothing at the next, after
    Life-Severing Sword's printed choice, through real TabletopService commits."""
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop import ButtonStore

    project, mender = _table_sheet(tmp_path, "44444444", hp=400), _table_sheet(tmp_path, "55555555", hp=400,
                                                                             spheres=(), path_features=(IMMORTAL_BODY,),
                                                                             cl=20)
    for pid in (project, mender):
        ButtonStore(tmp_path / "tabletop_buttons").save_reactions(pid, {"mode": "ask"}, set())
    combat = CombatService(ROOT, tmp_path)
    swordsman, regenerator = FACTORY_ACTOR_PREFIX + project, FACTORY_ACTOR_PREFIX + mender
    mid = combat.create_factory_match(project_ids=[project], opponent_actor_ids=[regenerator],
                                      control_modes={swordsman: "MANUAL", regenerator: "LOCAL_AUTO"},
                                      arena_id=_yard(combat, tmp_path, "ocf8f1-regeneration"),
                                      match_seed="OCF8F1-REGEN", maximum_rounds=12)["match_id"]
    table = TabletopService(combat, tmp_path)

    def regenerator_turned(events, after=0):
        return any(event.event_type == "TURN_STARTED" and event.actor_id == regenerator and event.sequence > after
                   for event in events)

    chosen_at, plain_at = None, None
    for _ in range(200):
        state = table.state(mid)
        if _done(state):
            break
        menu = state.get("menu") or {}
        events = combat._load_session(mid).engine.events
        if chosen_at is not None and regenerator_turned(events, chosen_at):
            break                                   # its next turn start has come and gone
        if not menu.get("manual"):
            _auto(table, mid, state)
            continue
        if chosen_at is not None:                   # the choice is made; let the next turn start happen
            _press(table, mid, menu, state)
            continue
        state, found = _configure_sword_strike(combat, table, mid, state, regenerator,
                                              enabled=plain_at is not None)
        menu = state.get("menu") or {}
        if found is None:
            _press(table, mid, menu, state, None, next((o["candidate_id"] for g in menu.get("actions") or []
                                                       if g["label"] == "Finish fight setup"
                                                       for o in g["options"]), None))
            continue
        if plain_at is None:  # the plain blade first, so the regeneration is seen working before anything suppresses it
            unpaid_prompts = []
            _press(table, mid, menu, state, None, found[1], asked=unpaid_prompts)
            # Since e67ceeb8, Sword Qi Wave's printed damage-type choice is legitimate;
            # only Life-Severing Sword's extra-effect prompt must be absent here.
            life_severing_prompts = [prompt for prompt in unpaid_prompts
                                     if "Life-Severing Sword" in str(prompt)]
            assert not life_severing_prompts, (
                "a disabled, unpaid talent must not ask for its extra effect")
            assert "condition:typed.regeneration_suppressed" not in _conditions(
                combat._load_session(mid).engine.state.actors[regenerator])
            plain_at = len(events)
            continue
        _press(table, mid, menu, state, None, found[1], want="No regeneration")
        chosen_at = len(combat._load_session(mid).engine.events)
    assert chosen_at is not None, "the real table never reached a Sword strike with Life-Severing Sword"

    events = combat._load_session(mid).engine.events
    healed = [event for event in events if event.event_type == "HEALING_APPLIED"
              and event.source_definition_id.endswith("feature.immortal_body")]
    assert healed, "Immortal Regeneration never ran at all, so the suppression proves nothing"
    assert {event.actor_id for event in healed} == {regenerator}
    assert max(event.sequence for event in healed) < chosen_at, "the regeneration ran after the printed choice"
    assert regenerator_turned(events, chosen_at), "the regenerator never took another turn"
    assert not [event for event in healed if event.sequence > chosen_at], "it regenerated after the printed choice"

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.verify()["status"] == "PASS"
    assert "condition:typed.regeneration_suppressed" in _conditions(reloaded.engine.state.actors[regenerator])
    # the condition pill, not a log line, is what the player reads to find out why nothing was restored (the refusal
    # query is pure), and it survives the commit and reload
    assert "cannot regain Hit Points from regeneration" in _pill_text(reloaded.engine, reloaded.engine.state.actors[regenerator])


def test_the_ai_swordsman_never_asks_the_human_and_still_advances(tmp_path):
    """Checklist 9, the AI direction: the extra effect is the swordsman's own decision, so on a table where the swordsman
    is played by the AI and the human holds the other creature, the human is never asked to answer it -- the AI's turns
    step on by themselves and the fight advances. (The AI's own scoring never picks this clause: it deals no extra
    damage, so over these rounds it never pressed it. What this proves is that its turns never stop and question the
    human; test_life_severing_sword_ai_takes_the_first_printed_option_without_a_provider covers the decision itself.)"""
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    from combat.tabletop import ButtonStore

    project, mender = _table_sheet(tmp_path, "44444444", hp=400), _table_sheet(tmp_path, "55555555", hp=400,
                                                                                 spheres=(), path_features=(IMMORTAL_BODY,),
                                                                                 cl=20)
    for pid in (project, mender):
        ButtonStore(tmp_path / "tabletop_buttons").save_reactions(pid, {"mode": "ask"}, set())
    combat = CombatService(ROOT, tmp_path)
    swordsman, regenerator = FACTORY_ACTOR_PREFIX + project, FACTORY_ACTOR_PREFIX + mender
    mid = combat.create_factory_match(project_ids=[project], opponent_actor_ids=[regenerator],
                                      control_modes={swordsman: "LOCAL_AUTO", regenerator: "MANUAL"},
                                      arena_id=_yard(combat, tmp_path, "ocf8f1-ai"), match_seed="OCF8F1-AI",
                                      maximum_rounds=12)["match_id"]
    table = TabletopService(combat, tmp_path)
    asked, rounds = [], set()
    for _ in range(80):
        state = table.state(mid)
        if _done(state):
            break
        menu = state.get("menu") or {}
        rounds.add(combat._load_session(mid).engine.state.round_number)
        if menu.get("manual"):
            result = _press(table, mid, menu, state, None, None, asked=asked)
            assert result["status"] != "REACTION_REQUIRED"
        else:
            _auto(table, mid, state)
    assert max(rounds) >= 3, f"the AI's turns did not carry the fight forward (reached round {max(rounds)})"
    assert asked == [], f"the human was asked to answer an AI swordsman's decision: {asked}"
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()["status"] == "PASS"


def test_life_severing_sword_ai_takes_the_first_printed_option_without_a_provider():
    """An AI fighter (no provider answering, exactly as the controller leaves it) decides for itself and the printed clause
    lands: nothing waits for a player, and the once-per-turn mark is still written."""
    engine = _fight(_bundle([LIFE_SEVERING]))          # no reaction provider at all
    _use(engine, LIFE_SEVERING_STRIKE)
    foe = _foe(engine)
    assert [m.value for m in foe.modifiers.values() if m.target_field == "healing_reduction"] == ["half"]
    from combat.ext.sword_core import TURN_KEY

    assert engine.state.actors[ME].turn_flags.get(TURN_KEY)
