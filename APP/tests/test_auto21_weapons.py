"""AUTO21 (automation lane, Weapons Sphere): the printed effect happens at the table.

Every test drives a real Factory character through CombatService/TabletopService (tests/h1_support.sheet builds
the sheet, tests/hunt12_support.reload reads the committed fight back), scripts only the dice it is about, and
answers the printed prompts a player would answer. The abilities live in combat/ext/weapons_sphere.py; their
feature rows are combat/rules/feature_blocks.d/auto21_weapons.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import armour
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script

ME = "actor:factory.auto21"
ALLY = "actor:factory.auto21_ally"
FOE = "actor:gate2.sparring.opponent"
FOCUS = "resource:core.martial_focus"

BREAK_GUARD = "tianxia.talent.weapons.break_the_guard"
IRON = "tianxia.talent.weapons.iron_against_iron"
SOFT = "tianxia.talent.weapons.soft_weapon_discipline"
DRILL = "tianxia.talent.weapons.formation_weapon_drill"

DAGGER = "tianxia.mortal.weapon.bi_shou"
WHIP = "tianxia.mortal.weapon.jie_bian"        # "Reach 10, Flexible, Finesse, Special Method"
SPEAR = "tianxia.mortal.weapon.qiang"          # "Reach, Two-Handed" (a Long weapon)
BLADE = "tianxia.mortal.weapon.guandao_yanyuedao"   # "Smash": a weapon that may use Breaking Method (it does not push)
AXE = "tianxia.mortal.weapon.fu"              # "Light, Thrown, Armor-Breaking": a one-handed Breaking weapon
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"   # "you may make two attacks instead of one"
SHIELD = "tianxia.mortal.armor.shield"
DAGGER_ATTACK = "(Dagger) attack"             # the dagger's own attack, not its Drop or Stow
PALM = "TAL_BRUTE_MOUNTAIN_MOVING_PALM"        # an enemy's push, resolved as a Strength or Dexterity save
PARRY_AND_RIPOSTE = "TAL_FENCING_PARRY_AND_RIPOSTE"   # "a creature hits you with a melee attack": the target
                                                      # takes that damage to nothing and answers with its own strike

ITEM_DOWN = "condition:typed.weapons_item_disrupted"
PULLED_BACK = "condition:typed.weapons_pulled_back"


def kit(*item_ids):
    names = {DAGGER: "Bi Shou (Dagger)", WHIP: "Jie Bian (Chain Whip)", SPEAR: "Qiang (Spear)",
             BLADE: "Guandao / Yanyuedao (Reclining Moon Blade)", AXE: "Fu (Short Axe)", SHIELD: "Shield"}
    return {"starting_kit": {"items": [{"item_id": i, "name": names.get(i, i.rsplit(".", 1)[-1]), "quantity": 1} for i in item_ids]}}


def _shield_trained(document, items):
    """Give the fixture the book's Shield training when its kit really holds a Shield.

    The printed Shield rule (SHIELD_BASE_SHIELD_TRAINING) grants its +2 Armor Class only to a wielder with Shield
    training, so a fighter who carries a Shield but owns no training is not a shielded fighter. These tests need the
    +2 to be really in Armor Class; the known grant is the book's mundane "You gain shield proficiency" row, which the
    compiler reads as ``proficiencies.armor``. Only kits that hold a Shield are touched.
    """
    if SHIELD in items:
        proficiency = document.setdefault("proficiencies", {})
        armor = [str(value) for value in proficiency.get("armor") or ()]
        if "shield" not in [value.lower() for value in armor]:
            proficiency["armor"] = [*armor, "shield"]
    return document


def fight(tmp_path, *, mids=(BREAK_GUARD,), me_kit=(DAGGER,), foe_mids=(), foe_kit=(DAGGER, SHIELD), ally_mids=(),
          ally_kit=(DAGGER,), ally_at=(3, 7), foe_at=(4, 6), seed="AUTO21", modes=None):
    """ME owns ``mids`` and swings ``me_kit``; FOE is a shielded fighter with a weapon of its own."""
    bundles = [compile_character(_shield_trained(sheet(list(mids), cl=10, dc=16, primary="Stamina", kit=kit(*me_kit)), me_kit),
                                 actor_id=ME, reaction_plan={"ask": True})]
    foe = _shield_trained(sheet(list(foe_mids), cl=10, dc=16, primary="Stamina", kit=kit(*foe_kit)), foe_kit)
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
    bundles.append(compile_character(foe, actor_id=FOE, reaction_plan={"ask": True}))
    actors = [ME, FOE]
    teams = {ME: "team:factory", FOE: "team:opponents"}
    spots = {ME: {"x": 3, "y": 6}, FOE: {"x": foe_at[0], "y": foe_at[1]}}
    if ally_mids or ally_kit:
        ally = _shield_trained(sheet(list(ally_mids), cl=10, dc=16, primary="Stamina", kit=kit(*ally_kit)), ally_kit)
        ally["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        bundles.append(compile_character(ally, actor_id=ALLY, reaction_plan={"ask": True}))
        actors.append(ALLY)
        teams[ALLY] = "team:factory"
        spots[ALLY] = {"x": ally_at[0], "y": ally_at[1]}
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, actors, teams, spots, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
                                      [ME], [FOE], control_modes=modes or {actor: "MANUAL" for actor in actors},
                                      match_seed=seed, display_name="AUTO21 weapons", maximum_rounds=20)["match_id"]
    table.state(mid)  # settle initiative before any script is queued
    return combat, table, mid


def reload(tmp_path, mid):
    """The committed fight read back through CombatService, with its replay check (tests/hunt12_support.reload)."""
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def ask(table, mid, chosen, answers=("USE",), choice=None, prompts_out=None):
    """Commit one action, answering every prompt with the given selection (default: the first option).

    ``choice`` picks one named option wherever a prompt offers it (Shifting Grip Scripture's three grips).
    """
    state = table.state(mid)
    menu = state["menu"]
    chosen = menu["end_turn"] if chosen == "end" else chosen
    sent, prompts = [], []
    for _ in range(30):
        result = table.act(mid, chosen, menu["decision_id"], menu["state_version"], state["last_sequence"], sent)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            if prompts_out is not None:
                prompts_out.extend(prompts)
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": answers[min(len(sent), len(answers) - 1)]}
        if prompt.get("choice"):
            options = [row["id"] for row in prompt["choice"]["options"]]
            answer["option_ids"] = [choice if choice in options else options[0]]
        sent.append(answer)
    raise AssertionError("repeated prompt without a commit")


def to_turn(table, mid, actor, choice=None, seen=None):
    """Advance to ``actor``'s turn, answering any start-of-turn menu with ``choice`` (a grip)."""
    for _ in range(20):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        ask(table, mid, "end", choice=choice, prompts_out=seen)
    raise AssertionError("turn never reached " + actor)


def draw(combat, table, mid, who):
    """Take the starting weapon in hand (a heavier weapon is not held at the start of a fight)."""
    engine = combat._load_session(mid).engine
    for candidate in engine.legal_candidates():
        action = engine.action_catalog.get(candidate.source_definition_id)
        if str(getattr(action, "display_name", "")).startswith("Draw "):
            return ask(table, mid, candidate.candidate_id)
    raise AssertionError("no Draw action")


def attack_on(combat, mid, who, *, ranged=None, word="attack"):
    engine = combat._load_session(mid).engine
    for candidate in engine.legal_candidates():
        if tuple(candidate.target_ids) != (who,) or candidate.kind.value in ("MOVE", "END_TURN"):
            continue
        action = engine.action_catalog.get(candidate.source_definition_id)
        name = str(getattr(action, "display_name", "")).lower()
        if word not in name or "+" in name or ":" in name:
            continue  # the plain attack, not a weapon method or a maneuver
        if ranged is not None and (int(getattr(action, "range_ft", 0) or 0) > 5) is not ranged:
            continue
        return candidate.candidate_id
    raise AssertionError(f"no {word} on {who}")


def named(combat, mid, actor_id, word, *, at=None):
    """The candidate id of an action whose display name contains ``word``, aimed at the square ``at`` when given."""
    engine = combat._load_session(mid).engine
    for candidate in engine.legal_candidates():
        if candidate.actor_id != actor_id or candidate.kind.value in ("MOVE", "END_TURN"):
            continue
        action = engine.action_catalog.get(candidate.source_definition_id)
        if word.lower() not in str(getattr(action, "display_name", "")).lower():
            continue
        spot = getattr(candidate, "destination", None)
        if at is not None and (spot is None or (spot.x, spot.y) != at):
            continue
        return candidate.candidate_id
    raise AssertionError(f"no {word} for {actor_id}" + (f" at {at}" if at else ""))


def force_naturals(monkeypatch, *, who, attack=15, save=3):
    """Force ``who``'s attack rolls to ``attack``, every saving throw to ``save``, and the damage dice to 1."""
    pristine = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine, actor, *args, **kwargs):
        if getattr(actor, "entity_id", None) == who:
            script(engine, [attack, *([1] * 40)])
        return pristine(engine, actor, *args, **kwargs)

    def roll_save(engine, actor, *args, **kwargs):
        if getattr(actor, "entity_id", None) != who:
            script(engine, [save, *([1] * 20)])
        return pristine_save(engine, actor, *args, **kwargs)

    pristine_save = Gate4ControllerEngine._roll_save
    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)
    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)
    return pristine


def force_rolls(monkeypatch, *, attack=(ME,), attack_value=15, save=(FOE,), save_value=3):
    """Script the attack rolls of ``attack`` and the saving throws of ``save``; everyone else rolls as the fight does.

    Used where two fights are compared attack-roll for attack-roll, so neither side's own rolls move with the seed.
    """
    pristine_attack = Gate4ControllerEngine._resolve_attack_spec
    pristine_save = Gate4ControllerEngine._roll_save

    def resolve(engine, actor, *args, **kwargs):
        if getattr(actor, "entity_id", None) in attack:
            script(engine, [attack_value, *([1] * 40)])
        return pristine_attack(engine, actor, *args, **kwargs)

    def roll_save(engine, actor, *args, **kwargs):
        if getattr(actor, "entity_id", None) in save:
            script(engine, [save_value, *([1] * 20)])
        return pristine_save(engine, actor, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)
    monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)


def events(tmp_path, mid, event_type, actor_id=None):
    engine = reload(tmp_path, mid)
    return [event for event in engine.events if event.event_type == event_type
            and (actor_id is None or event.actor_id == actor_id)]


def lowered_armor_class(tmp_path, mid, who):
    """How much Armor Class this creature is currently losing to a printed reduction (a negative modifier)."""
    engine = reload(tmp_path, mid)
    return sum(int(m.value) for m in engine.state.actors[who].modifiers.values()
               if m.target_field == "armor_class" and m.operation == "ADD" and int(m.value) < 0)


def conditions(tmp_path, mid, who):
    """The creature's conditions by condition id (fight state keys each instance separately)."""
    engine = reload(tmp_path, mid)
    return {held.condition_id: held for held in engine.state.actors[who].conditions.values()}


def negate_the_second_attack(monkeypatch):
    """Defend one action's second attack down to nothing and leave its first attack alone.

    Registered as the engine's own general ``final_damage`` seam, so this is a defended packet that ends at 0 and
    not a different kind of attack: whatever reads "the hit dealt damage" must read 0 for that attack alone.
    """
    from combat import ext

    ext.effects()

    def second_attack_only(engine, target, amount, damage_type, source_id, source_actor_id, intent):
        packet = engine.damage_context()
        return {"amount": 0} if packet is not None and int(packet.attack_index) == 2 else None

    monkeypatch.setitem(ext._HOOKS, "final_damage", [second_attack_only])


def damage_gate(monkeypatch):
    """A switch that defends every damage packet to nothing while it is on, as an immunity would.

    Registered as the engine's own general ``final_damage`` seam, so this is a defended packet that ends at 0 and not
    a different kind of attack. The switch is returned so a fight can be played normally and defended from one moment
    on: the provider is bound when the fight starts, so it is installed before the fight and turned on later.
    """
    from combat import ext

    ext.effects()
    switch = {"on": False}
    monkeypatch.setitem(ext._HOOKS, "final_damage", [lambda *args: {"amount": 0} if switch["on"] else None])
    return switch


def late_rider_damage(monkeypatch, amount=4):
    """Attach a damage rider to every landed hit of an attack, committed after that hit's own offer.

    Registered on the engine's general ``attack_resolved`` seam, which runs after this hit's own ``after_hit``
    observer has already been asked and answered and before the next hit of the same action, so the packet it
    deals is genuinely this hit's own damage that arrives too late for the offer already put to the player. It is
    added to the seam rather than replacing it, so every other ability's handler still runs.

    It fires on every landed hit rather than once: a printed choice makes the table re-resolve the action from its
    checkpoint, and a rider that only fired the first time would be missing from the resolution that is kept.
    """
    from combat import ext
    from combat.typed_executor import run_effects

    ext.effects()

    def rider(ctx, target, hit, effect):
        if not hit:
            return
        run_effects(ctx, [{"type": "damage", "flat": int(amount), "damage_types": ["slashing"], "applies_to": "target",
                          "evidence": "test fixture: a rider of this hit, committed after the offer"}])

    monkeypatch.setitem(ext._HOOKS, "attack_resolved", [*(ext._HOOKS.get("attack_resolved") or []), rider])


def nested_counterattack(monkeypatch):
    """Make the target answer with a melee strike of its own in the middle of one hit, between the Weapon Method
    that hit paid for and the point where a printed trigger reads the method back.

    Registered on the engine's general ``damage_dealt`` seam, so the reply lands on the second committed packet of
    the hit -- the hit's own damage first, then the Weapon Method's -- which is the window a reaction attack
    resolving inside the damage really occupies, and the window that must not cost this hit its own record. The
    reply is a real attack (the target's own weapon, through combat.ext.needle.parry_riposte) and it is committed
    to the fight, so the fight file shows it.

    The packet count is reset on ``attack_result`` because a printed choice (which item did the hit land on) makes
    the table re-resolve the action from its checkpoint; without the reset the reply would be made once, rolled
    back with that checkpoint, and never made again. Both seams are added to rather than replacing them, so every
    other ability's handler still runs.
    """
    from combat import ext
    from combat.ext.needle import parry_riposte

    ext.effects()
    state = {"packets": 0}

    def new_hit(ctx, target, hit, critical):
        if ctx.actor.entity_id == ME:
            state["packets"] = 0

    def after_the_method(ctx, target, amount):
        state["packets"] += 1
        if state["packets"] != 2:
            return   # the second committed packet of this hit is the Weapon Method's own damage
        parry_riposte(ctx.engine, ctx.engine.state.actors[FOE], ctx.actor, [PARRY_AND_RIPOSTE])

    monkeypatch.setitem(ext._HOOKS, "attack_result", [*(ext._HOOKS.get("attack_result") or []), new_hit])
    monkeypatch.setitem(ext._HOOKS, "damage_dealt", [*(ext._HOOKS.get("damage_dealt") or []), after_the_method])
    return state


def negate_all_damage(monkeypatch):
    """Make every damage packet resolve to nothing, as an immunity or a total reduction would.

    Registered as the engine's own general ``final_damage`` seam, so this is a defended packet that ends at 0 and
    not a different kind of attack: whatever reads "the hit dealt damage" must read 0 here.
    """
    from combat import ext

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "final_damage", [lambda *args: {"amount": 0}])


def ac(tmp_path, mid, who):
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[who]
    return int(actor.armor_class) + int(engine._ac_modifier(actor))


# ======================================================================== Break the Guard
def test_break_the_guard_spends_focus_breaks_the_guard_and_the_target_loses_two_armor_class(tmp_path, monkeypatch):
    """"you may expend Martial Focus to use Breaking Method ... the target must make a Strength saving throw. On a
    failure, reduce one such defensive bonus by 2 until the start of your next turn." """
    combat, table, mid = fight(tmp_path)
    before = ac(tmp_path, mid, FOE)
    assert before >= 16, f"the fixture needs FOE's Shield bonus to be in its Armor Class, not {before}"
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False))

    offered = [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)]
    assert offered, f"the printed Guard offer was never put to the player: {[p.get('prompt') for p in prompts]}"
    assert "1 Martial Focus" in json.dumps(offered[0]), "the printed cost was not named at the prompt"
    assert "Proficiency Bonus" in json.dumps(offered[0]), "the prompt did not say what Breaking Method adds"
    assert "Strength saving throw" in json.dumps(offered[0]), "the prompt did not name the target's save"

    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources.get(FOCUS, 0) == 0, "the printed Martial Focus was not spent"
    damage = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED" and event.actor_id == ME]
    assert damage, "the hit dealt no damage at all"
    saves = [event for event in engine.events if event.event_type == "SAVE_ROLLED" and event.actor_id == FOE]
    assert saves and saves[0].payload.get("reason", "").endswith(":STR"), "the target never made the printed Strength save"
    assert saves[0].payload.get("success") is False, "the scripted low save did not fail"
    assert lowered_armor_class(tmp_path, mid, FOE) == -2, "the failed save took nothing off its guard"
    assert ac(tmp_path, mid, FOE) == before - 2, "the guard was not 2 lower"
    held = reload(tmp_path, mid).state.actors[FOE].modifiers
    assert any(m.expires_on for m in held.values() if m.target_field == "armor_class" and m.value < 0), \
        "the reduction has no expiry of its own"


def test_broken_guard_survives_a_table_commit_and_reload(tmp_path, monkeypatch):
    """Persistence: the reduced Armor Class is fight state the next table session must read back."""
    combat, table, mid = fight(tmp_path)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert ac(tmp_path, mid, FOE) < 16, "the guard was never broken, so there is nothing to reload"
    engine = reload(tmp_path, mid)
    reductions = [m for m in engine.state.actors[FOE].modifiers.values()
                  if m.target_field == "armor_class" and m.operation == "ADD" and int(m.value) < 0]
    assert reductions and reductions[0].expires_on, "the reduction is not saved fight state with an expiry"
    assert ac(tmp_path, mid, FOE) == 14, "the reloaded fight no longer reads the reduced Armor Class"


def test_break_the_guard_is_inert_against_a_creature_with_no_defensive_bonus(tmp_path, monkeypatch):
    """A creature keeping no Shield, parry or guard stance has no defensive bonus to break: nothing is asked."""
    combat, table, mid = fight(tmp_path, foe_kit=(DAGGER,))
    assert ac(tmp_path, mid, FOE) < 16, "the fixture's FOE still has a defensive bonus"
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert not [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)], \
        "the guard was offered against a creature that has none"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, "a creature with no guard lost Armor Class anyway"
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, "Martial Focus was spent for nothing"


def test_a_second_hit_of_a_two_hit_breaking_attack_rattles_nothing(tmp_path, monkeypatch):
    """"When you use Breaking Method": a Weapon Method is one per turn, so on a two-hit attack the second hit never
    used one. Iron Against Iron must read what this hit executed, not what the attack offered."""
    combat, table, mid = fight(tmp_path, mids=(IRON, EXTRA_ATTACK), me_kit=(BLADE,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    rolled = [event for event in events(tmp_path, mid, "ATTACK_ROLLED", ME)
              if event.source_definition_id.endswith("#method_breaking")]
    assert len(rolled) == 2, f"the fixture did not make a two-hit Breaking attack: {len(rolled)} rolls"
    offered = [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)]
    assert len(offered) == 1, \
        f"the item was asked about {len(offered)} times; only the hit that actually used Breaking Method may ask"
    rattled = [held for held in reload(tmp_path, mid).state.actors[FOE].conditions.values()
               if held.condition_id == ITEM_DOWN]
    assert len(rattled) == 1, f"the second hit rattled an item as well: {len(rattled)}"


def test_the_breaking_hit_keeps_its_own_method_record_while_the_target_answers_with_its_own_attack(tmp_path, monkeypatch):
    """A Weapon Method that ran on this hit is this hit's fact, and a reaction attack resolving between the method
    and the point where that method is read back must not take it away.

    Break the Guard is the printed use that matters here: it runs from ``after_hit``, builds its own Context for the
    paid rider rather than reusing the hit's, and so is the one path where the method could be recorded outside the
    hit. FOE answers the landed hit with a melee strike of its own, which resolves after the method's damage and
    before ``after_hit_effects`` asks Iron Against Iron which item the hit landed on. That reply is a strike in its
    own right and starts its own record, but it cannot end this one: the holder must still be asked, because the hit
    really did break its guard with Breaking Method.
    """
    nested_counterattack(monkeypatch)
    combat, table, mid = fight(tmp_path, mids=(IRON, BREAK_GUARD))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False), answers=("USE", "USE"))

    engine = reload(tmp_path, mid)
    order = list(engine.events)

    def where(event_type, actor_id, source_ends=None):
        return [index for index, event in enumerate(order) if event.event_type == event_type
                and event.actor_id == actor_id
                and (source_ends is None or event.source_definition_id.endswith(source_ends))]

    committed = where("DAMAGE_COMMITTED", ME)
    answered = where("ATTACK_ROLLED", FOE)
    iron = where("PASSIVE_TRIGGERED", ME, IRON)
    assert len(committed) == 2, \
        f"the fixture did not deal the hit's damage and then the paid method's: {committed}"
    assert answered, "the fixture never answered with a counterattack of its own, so it proves nothing"
    assert iron, f"Iron Against Iron never ran, so there is nothing to prove: {where('PASSIVE_TRIGGERED', ME)}"
    assert committed[0] < answered[0] < iron[0], \
        (f"the counterattack did not land between the method's damage ({committed}) and Iron's read ({iron}); "
         f"the reply is at {answered}")

    offered = [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)]
    assert offered, \
        f"the reaction attack's own strike erased the Breaking hit's record: {[p.get('prompt') for p in prompts]}"
    assert ITEM_DOWN in conditions(tmp_path, mid, FOE), \
        "the holder's item was left sound although its guard was broken by Breaking Method"


def test_the_item_choice_promises_no_penalty_for_an_item_that_makes_no_attacks(tmp_path, monkeypatch):
    """Item 13: the prompt must not tell the player their attacks will be 2 lower with a shield."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,), foe_kit=(DAGGER, SHIELD))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    offered = [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)]
    assert offered, f"the printed item choice was never asked: {[p.get('prompt') for p in prompts]}"
    text = json.dumps(offered[0])
    assert "A shield makes no attacks" in text, \
        f"the prompt does not say what rattling a shield does: {text}"
    assert "attacks made with it are 2 lower" in text, f"the printed penalty is not described: {text}"


# ======================================================================== Iron Against Iron
def test_iron_against_iron_makes_that_items_attacks_two_lower(tmp_path, monkeypatch):
    """"When you use Breaking Method against a weapon, shield, or object held by a creature, the holder makes a Strength
    saving throw. On a failure ... attacks made with that item suffer a -2 penalty" until the start of your next turn."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    assert [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)], \
        f"the printed item choice was never asked: {[p.get('prompt') for p in prompts]}"
    held = conditions(tmp_path, mid, FOE).get(ITEM_DOWN)
    assert held is not None, "the failed save left the item sound"
    assert str((held.data or {}).get("item")) == DAGGER, f"the rattled item is not the weapon FOE carries: {held.data}"
    assert int((held.data or {}).get("amount") or 0) == 2

    # The printed penalty, read off the roll FOE's own weapon attack now makes, against an otherwise identical
    # fight whose holder was never attacked. The control lives in its own directory: two fights sharing one
    # data root would trip the immutable-file hash check.
    rattled = swing(tmp_path, table, mid)
    control_root = tmp_path / "control"
    control_root.mkdir()
    control_combat, control_table, control_mid = fight(control_root, mids=())
    control = swing(control_root, control_table, control_mid)
    assert rattled["modifier"] == control["modifier"] - 2, \
        f"a rattled weapon rolled {rattled['modifier']} against an unrattled {control['modifier']}"


def swing(tmp_path, table, mid):
    """FOE swings its own weapon at ME and returns the recorded attack roll's payload."""
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(table.combat, mid, ME, ranged=False))
    rolled = [event for event in events(tmp_path, mid, "ATTACK_ROLLED", FOE)]
    assert rolled, "the weapon never attacked"
    return rolled[-1].payload


def swing_with(tmp_path, table, mid, word):
    """FOE attacks ME with the weapon whose own name ``word`` appears in, and returns that attack roll's payload."""
    to_turn(table, mid, FOE)
    ask(table, mid, named(table.combat, mid, FOE, word))
    rolled = [event for event in events(tmp_path, mid, "ATTACK_ROLLED", FOE)]
    assert rolled, f"no attack was made with {word}"
    return rolled[-1].payload


def test_a_rattled_weapon_is_not_penalised_for_another_weapon(tmp_path, monkeypatch):
    """The penalty is on that item, not on the holder: FOE disarms nothing here, it simply swings its own weapon
    again, so the second swing must still be 2 lower while a second, unrattled item is untouched."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    engine = reload(tmp_path, mid)
    from combat.ext.weapons_sphere import disrupted_item_attack

    class Ctx:
        typed = {"weapon": {"implement_id": DAGGER}}

    assert disrupted_item_attack(Ctx(), engine.state.actors[FOE]) == -2
    Ctx.typed = {"weapon": {"implement_id": AXE}}
    assert disrupted_item_attack(Ctx(), engine.state.actors[FOE]) is None, "an unrattled weapon was penalised too"


def test_iron_against_iron_against_a_shield_rattles_it_without_inventing_a_penalty(tmp_path, monkeypatch):
    """"attacks made with that item suffer a -2 penalty": a shield makes no attacks, so its rattle is recorded and
    takes nothing away. The table does not substitute a benefit the printed rule never gave it either."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,), foe_kit=(SHIELD,))
    before = ac(tmp_path, mid, FOE)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    saves = events(tmp_path, mid, "SAVE_ROLLED", FOE)
    assert saves and saves[-1].payload.get("success") is False, "the holder never made the printed Strength save"
    held = conditions(tmp_path, mid, FOE).get(ITEM_DOWN)
    assert held is not None, "the failed save left the shield sound"
    assert str((held.data or {}).get("item")) == "shield", f"the wrong item was rattled: {held.data}"
    assert int((held.data or {}).get("amount") or 0) == 0, "a shield was credited with an attack penalty"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, \
        "a rattled shield lost Armor Class: the printed -2 is on attacks made with the item, and a shield makes none"
    assert ac(tmp_path, mid, FOE) == before, "the fighter's Armor Class changed when a shield was rattled"


def test_iron_against_iron_leaves_an_item_it_cannot_reach_alone(tmp_path, monkeypatch):
    """Nothing to break, nothing asked: a barehanded target is not offered a weapon to rattle."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,), foe_kit=())
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    assert not [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)]
    assert ITEM_DOWN not in conditions(tmp_path, mid, FOE)
    assert lowered_armor_class(tmp_path, mid, FOE) == 0


def test_iron_against_iron_is_inert_on_an_ordinary_hit(tmp_path, monkeypatch):
    """The printed trigger is "When you use Breaking Method": a plain weapon attack uses no Weapon Method, so the
    holder is asked nothing, nothing is rattled and the fighter's one Martial Focus is still in hand."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE))
    assert not [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)], \
        f"an ordinary hit offered to rattle an item: {[p.get('reaction') for p in prompts]}"
    assert ITEM_DOWN not in conditions(tmp_path, mid, FOE)
    assert lowered_armor_class(tmp_path, mid, FOE) == 0
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, "Martial Focus was spent for nothing"


def test_a_holder_who_saves_keeps_its_item_sound(tmp_path, monkeypatch):
    """"the holder makes a Strength saving throw. On a failure, the item is rattled": a save that succeeds leaves the
    weapon and the shield exactly as they were."""
    for foe_kit in ((DAGGER,), (SHIELD,)):
        root = tmp_path / ("dagger" if foe_kit == (DAGGER,) else "shield")
        root.mkdir()
        combat, table, mid = fight(root, mids=(IRON,), me_kit=(BLADE,), foe_kit=foe_kit, seed="AUTO21-save")
        force_naturals(monkeypatch, who=ME, attack=15, save=20)   # every other creature's save comes up high
        to_turn(table, mid, ME)
        ask(table, mid, named(combat, mid, ME, "+ Breaking"))
        saves = events(root, mid, "SAVE_ROLLED", FOE)
        assert saves and saves[-1].payload.get("success") is True, "the scripted high save did not succeed"
        assert ITEM_DOWN not in conditions(root, mid, FOE), f"an item was rattled despite the save: {foe_kit}"
        assert lowered_armor_class(root, mid, FOE) == 0, "a shield lost Armor Class despite the save"


def test_break_the_guard_is_not_offered_on_a_hit_that_deals_no_damage(tmp_path, monkeypatch):
    """"If the hit deals damage": a packet that defenses bring to nothing took no hit points off, so there is no
    guard to break and nothing to charge. The engine's committed-damage notification is what decides this."""
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD,))
    negate_all_damage(monkeypatch)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    rolled = [event for event in events(tmp_path, mid, "DAMAGE_ROLLED", ME)]
    assert rolled, "the attack never rolled any damage, so the fixture proves nothing"
    assert not [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)], \
        f"a hit that dealt no damage still offered to break a guard: {[p.get('prompt') for p in prompts]}"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, "a guard was broken by a hit that dealt no damage"
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, "Martial Focus was spent for nothing"


def test_break_the_guard_judges_each_hit_of_one_attack_on_its_own_damage(tmp_path, monkeypatch):
    """With Extra Attack both hits share one action and one attack-roll record, so a later hit must not inherit an
    earlier hit's damage, and declining one hit's offer must not settle the next one."""
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD, EXTRA_ATTACK))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False), answers=("DECLINE",))
    offered = [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)]
    assert len(offered) == 2, \
        f"both hits dealt damage, so each must be offered its own: {len(offered)}"
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, \
        "declining both offers still spent Martial Focus"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, "a guard was broken without an accepted offer"
    # The second hit was offered after the first was declined: a decline settles that hit, not the attack action.


def test_a_hit_that_deals_no_damage_is_not_offered_an_earlier_strike_s_damage(tmp_path, monkeypatch):
    """What the printed "if the hit deals damage" asks about is the hit in front of the player, and nothing else.

    One action, two hits, and the fighter's Weapon Method allowance is untouched throughout, so Break the Guard is
    eligible for both hits and only the damage each hit committed can tell them apart. The first hit takes damage off
    the guarded fighter, and then a rider of that same hit deals its own damage too late for the offer already put
    to the player. The second hit is defended down to nothing.

    The first hit's late damage must therefore never answer the second hit: a record left behind from an earlier
    packet would read that damage and offer (and pay) Break the Guard for a hit that took no hit points off anything.
    """
    late_rider_damage(monkeypatch)         # a rider of the first hit, committed after its own offer was answered
    negate_the_second_attack(monkeypatch)  # the second hit of this action is defended down to nothing
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD, EXTRA_ATTACK))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)

    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False), answers=("DECLINE", "DECLINE"))
    engine = reload(tmp_path, mid)
    order = list(engine.events)
    hits = [index for index, event in enumerate(order) if event.event_type == "ATTACK_ROLLED" and event.actor_id == ME]
    damage = [(index, event) for index, event in enumerate(order) if event.event_type == "DAMAGE_COMMITTED"
              and FOE in event.target_ids and event.actor_id == ME]
    assert len(hits) == 2, f"the fixture did not make a two-hit attack: {len(hits)} hits"
    assert damage, "neither hit rolled any damage, so the fixture proves nothing"
    assert not [event for event in engine.events if event.event_type == "DAMAGE_COMMITTED"
                and ME in event.target_ids and event.actor_id == FOE], \
        "the guarded fighter struck back, so the fixture proves nothing"

    # The first hit really committed damage (its own packet plus the late rider's) and the second committed none.
    first_hit = [event for index, event in damage if index < hits[1]]
    second_hit = [event for index, event in damage if index > hits[1]]
    assert any(int((event.payload or {}).get("hp_damage") or 0) > 0 for event in first_hit), \
        f"the first hit took nothing off the guarded fighter: {first_hit}"
    assert all(int((event.payload or {}).get("hp_damage") or 0) == 0 for event in second_hit), \
        f"the defended second hit still committed damage, so it is not the fixture this test claims: {second_hit}"

    # Both hits were eligible: the fighter still held its Martial Focus and the target still kept a guard.
    assert engine.state.actors[ME].resources.get(FOCUS, 0) == 1, "Martial Focus was spent on a declining offer"
    assert armour.shield_bonus_earning(engine, engine.state.actors[FOE]) > 0, \
        "the fixture's FOE no longer keeps a defensive bonus, so the second hit was never eligible"

    offered = [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)]
    assert len(offered) == 1, \
        f"a hit that dealt no damage was offered a guard to break: {len(offered)} offers"
    assert not [event for event in engine.events if event.event_type == "SAVE_ROLLED" and event.actor_id == FOE], \
        "a Strength saving throw was asked for a hit that dealt no damage"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, "a guard was broken by a hit that dealt no damage"


# ======================================================================== Soft Weapon Discipline
def test_soft_weapon_discipline_pulls_the_weapon_back_and_the_next_opportunity_attack_has_disadvantage(tmp_path, monkeypatch):
    """"When you miss with a Flexible weapon attack, you may choose to pull the weapon back safely ... the next
    opportunity attack against you has Disadvantage"."""
    combat, table, mid = fight(tmp_path, mids=(SOFT,), me_kit=(WHIP,))
    force_naturals(monkeypatch, who=ME, attack=1, save=3)   # a natural 1 misses
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE))   # the whip reaches 10 feet
    assert [prompt for prompt in prompts if "Soft Weapon Discipline" in json.dumps(prompt)], \
        f"the printed pull-back was never offered: {[p.get('prompt') for p in prompts]}"
    assert "Opportunity Attack" in json.dumps(prompts), "the prompt did not say what the pull-back buys"

    # ME then walks out of the foe's reach, which is what provokes an Opportunity Attack made against ME.
    to_turn(table, mid, ME)
    prompts = ask(table, mid, walk_out_of_reach(combat, mid, FOE, beyond_ft=10))
    assert [prompt for prompt in prompts if "Opportunity" in json.dumps(prompt)], \
        f"leaving the foe's reach provoked no Opportunity Attack: {[p.get('moment') for p in prompts]}"
    rolled = [event for event in events(tmp_path, mid, "ATTACK_ROLLED", FOE)
              if "opportunit" in str(event.payload.get("reason") or "").lower()]
    assert rolled, "the Opportunity Attack was never rolled"
    assert rolled[-1].payload.get("mode") == "DISADVANTAGE", \
        f"the pulled-back weapon gave no Disadvantage: {rolled[-1].payload}"
    assert PULLED_BACK not in conditions(tmp_path, mid, ME), "the printed Disadvantage was not spent by that attack"


def walk_out_of_reach(combat, mid, who, *, beyond_ft=10):
    """A move candidate that takes the mover past ``who``'s reach, so it provokes an Opportunity Attack."""
    engine = combat._load_session(mid).engine
    for candidate in engine.legal_candidates():
        spot = getattr(candidate, "destination", None)
        if candidate.kind.value != "MOVE" or spot is None:
            continue
        if engine.grid.distance_ft(engine.state.actors[who].position, spot) <= beyond_ft:
            continue
        return candidate.candidate_id
    raise AssertionError("no move leaves the reach")


def test_soft_weapon_discipline_is_inert_for_a_rigid_weapon(tmp_path, monkeypatch):
    """Nothing is offered after missing with a weapon that is not Flexible."""
    combat, table, mid = fight(tmp_path, mids=(SOFT,), me_kit=(DAGGER,))
    force_naturals(monkeypatch, who=ME, attack=1, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert not [prompt for prompt in prompts if "Soft Weapon Discipline" in json.dumps(prompt)]
    assert PULLED_BACK not in conditions(tmp_path, mid, ME)


# ======================================================================== Formation Weapon Drill
def test_formation_weapon_drill_is_left_to_the_table_and_grants_nothing_on_its_own(tmp_path, monkeypatch):
    """"allies within 5 feet of you gain Advantage on ... saving throws made to avoid being forcibly moved through
    your threatened area": the benefit is conditional on the movement passing through the owner's threatened area, and
    this table resolves being pushed as one save with no path, so it does not grant a printed protection whose
    trigger it cannot establish. The talent therefore has no compiled row and no hook."""
    combat, table, mid = fight(tmp_path, mids=(DRILL,), me_kit=(SPEAR,), foe_mids=(PALM,), foe_kit=(DAGGER, SHIELD))
    engine = reload(tmp_path, mid)
    mine = [row for row in engine.typed_passive_rows.get(ME, []) if row.get("block") == "weapons_talent"]
    assert mine == [], f"the drill still compiles a row for a talent this table does not resolve: {mine}"
    to_turn(table, mid, FOE)
    ask(table, mid, named(combat, mid, FOE, "Mountain-Moving Palm", at=(3, 7)))
    saves = [event for event in events(tmp_path, mid, "SAVE_ROLLED", ALLY)]
    assert saves, "the ally beside the drill never made the forced-movement save"
    assert saves[-1].payload.get("mode") != "ADVANTAGE", \
        f"an advantage was granted for movement this table cannot place: {saves[-1].payload}"


# ======================================================================== Weapon-Breaking Retort
RETORT = "tianxia.talent.weapons.weapon_breaking_retort"
VERSATILE = "tianxia.mortal.weapon.jian"   # "Finesse, Versatile 1d10, Balanced Edge Method"


def scripted_miss_and_retort(monkeypatch):
    """FOE's attack misses; ME's own retort attack, if it makes one, hits."""
    pristine = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine, actor, *args, **kwargs):
        if getattr(actor, "entity_id", None) == FOE:
            script(engine, [1, *([1] * 40)])       # the foe's attack misses
        elif getattr(actor, "entity_id", None) == ME:
            script(engine, [15, *([1] * 40)])      # the retort's own attack hits
        return pristine(engine, actor, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)


def test_the_weapon_breaking_retort_answers_the_miss_with_its_printed_normal_damage(tmp_path, monkeypatch):
    """"On a hit, deal normal damage": the Reaction, its price and that damage are the table's own, so a missed melee
    attack costs 1 Martial Focus and is answered by one weapon attack."""
    combat, table, mid = fight(tmp_path, mids=(RETORT,))
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, "the fixture starts with its Focus"
    scripted_miss_and_retort(monkeypatch)
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    rolls = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED" and event.actor_id == ME]
    assert rolls, "the retort's hit dealt no weapon damage at all"
    assert engine.state.actors[ME].resources.get(FOCUS, 0) == 0, "the printed Reaction cost was not paid"
    lost = 200 - engine.state.actors[FOE].current_hp
    printed = int(rolls[-1].payload.get("combined_total") or rolls[-1].payload.get("total") or 0)
    assert lost == printed, f"the retort's hit dealt {lost}, not the weapon's own {printed}"


def test_the_retort_does_not_guess_which_item_it_broke(tmp_path, monkeypatch):
    """"you make one weapon attack against the attacking weapon, shield, or limb ... If the target is a weapon or
    shield, apply Breaking Method": the printed attack is aimed at an item or a limb. This table cannot aim a weapon
    attack at a carried item or name a limb as its target, so carrying a weapon is not a reason to apply Breaking, and
    the retort's hit deals its normal damage only."""
    combat, table, mid = fight(tmp_path, mids=(RETORT,))
    scripted_miss_and_retort(monkeypatch)
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    rolls = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED" and event.actor_id == ME]
    assert rolls, "the retort's hit dealt no weapon damage at all"
    lost = 200 - engine.state.actors[FOE].current_hp
    printed = int(rolls[-1].payload.get("combined_total") or rolls[-1].payload.get("total") or 0)
    assert lost == printed, \
        f"a foe carrying a weapon took {lost} against the weapon's own {printed}: Breaking was applied on a guess"
    assert engine.state.actors[ME].turn_flags.get("weapon_method") is None, \
        "a Weapon Method ran even though the table cannot know what the retort struck"


def test_a_retort_is_not_mistaken_for_a_breaking_use_by_iron_against_iron(tmp_path, monkeypatch):
    """Iron Against Iron answers "when you use Breaking Method", and a retort that broke nothing used none: the
    holder's item is not rattled and no Iron question is put to the table."""
    combat, table, mid = fight(tmp_path, mids=(RETORT, IRON), seed="AUTO21-retort-iron")
    scripted_miss_and_retort(monkeypatch)
    to_turn(table, mid, FOE)
    prompts = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert not [prompt for prompt in prompts if "Iron Against Iron" in json.dumps(prompt)], \
        "a retort that applied no Breaking Method still rattled an item"
    assert ITEM_DOWN not in conditions(tmp_path, mid, FOE), "a retort that broke nothing still rattled an item"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0


def test_the_retort_leaves_a_bare_limbed_creature_normal_damage_only(tmp_path, monkeypatch):
    """A creature holding neither weapon nor shield is the clearest case of what the retort may not assume."""
    combat, table, mid = fight(tmp_path, mids=(RETORT,), foe_kit=())
    scripted_miss_and_retort(monkeypatch)
    to_turn(table, mid, FOE)
    ask(table, mid, named(combat, mid, FOE, "Unarmed Strike"))
    engine = reload(tmp_path, mid)
    rolls = [event for event in engine.events if event.event_type == "DAMAGE_ROLLED" and event.actor_id == ME]
    assert rolls, "the retort's hit dealt no weapon damage at all"
    lost = 200 - engine.state.actors[FOE].current_hp
    printed = int(rolls[-1].payload.get("combined_total") or rolls[-1].payload.get("total") or 0)
    assert lost == printed, f"a limb took {lost} against the weapon's own {printed}"
    assert engine.state.actors[ME].turn_flags.get("weapon_method") is None, \
        "the printed condition was ignored and a Weapon Method was still used"


# ======================================================================== the printed one-Weapon-Method-per-turn limit
def test_break_the_guard_is_not_offered_on_an_attack_that_already_uses_a_weapon_method(tmp_path, monkeypatch):
    """Break the Guard's paid use is a Weapon Method ("you may expend Martial Focus to use Breaking Method even if
    your weapon does not have a qualifying tag"), so an attack the fighter already gave a Weapon Method is not also
    offered one, and the next turn's plain attack is."""
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD, EXTRA_ATTACK), me_kit=(BLADE,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, named(combat, mid, ME, "+ Pressing"))     # two hits; the method costs no Martial Focus
    assert reload(tmp_path, mid).state.actors[ME].turn_flags.get("weapon_method") is True, \
        "the fighter's own Weapon Method was not recorded"
    assert not [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)], \
        f"a second Weapon Method was offered on the same Attack action: {[p.get('reaction') for p in prompts]}"
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, "Martial Focus was spent for nothing"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, "a guard was broken with no Weapon Method to pay for it"

    ask(table, mid, "end")
    to_turn(table, mid, ME)                                  # the next turn clears the spent mark
    prompts = ask(table, mid, attack_on(combat, mid, FOE))
    assert [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)], \
        "the limit outlived the turn it belongs to"
    assert lowered_armor_class(tmp_path, mid, FOE) == -2


def test_break_the_guard_is_not_offered_once_this_turns_weapon_method_is_spent(tmp_path, monkeypatch):
    """The same limit, read off the mark the shared Weapon Method execution leaves: this turn's one is spent, so
    the fighter's Opportunity Attack on the foe's own turn is offered no second one (and keeps its Martial Focus)."""
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD,), me_kit=(BLADE,), seed="AUTO21-limit")
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "+ Pressing"))     # the turn's one Weapon Method, free of Martial Focus
    ask(table, mid, "end")
    to_turn(table, mid, FOE)
    prompts = ask(table, mid, walk_out_of_reach(combat, mid, ME, beyond_ft=5))
    assert [prompt for prompt in prompts if "Opportunity" in json.dumps(prompt)], \
        f"leaving the fighter's reach provoked no Opportunity Attack: {[p.get('reaction') for p in prompts]}"
    assert not [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)], \
        "a second Weapon Method was offered after this turn's one was spent"
    assert reload(tmp_path, mid).state.actors[ME].resources.get(FOCUS, 0) == 1, "Martial Focus was spent for nothing"
    assert lowered_armor_class(tmp_path, mid, FOE) == 0, "a guard was broken with no Weapon Method to pay for it"


def test_the_broken_guard_is_mended_at_the_start_of_your_next_turn(tmp_path, monkeypatch):
    """"reduce one such defensive bonus by 2 until the start of your next turn": the reduction lasts the wielder's
    round and no longer."""
    combat, table, mid = fight(tmp_path)
    before = ac(tmp_path, mid, FOE)
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    assert ac(tmp_path, mid, FOE) == before - 2, "the guard was never broken, so there is nothing to expire"
    ask(table, mid, "end")
    to_turn(table, mid, ME)
    assert ac(tmp_path, mid, FOE) == before, "the broken guard outlived the start of the wielder's next turn"


def test_a_rattled_weapon_is_sound_again_at_the_start_of_your_next_turn(tmp_path, monkeypatch):
    """"Until the start of your next turn, attacks made with that item suffer a -2 penalty": the rattle lasts the
    wielder's round and no longer."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    assert ITEM_DOWN in conditions(tmp_path, mid, FOE), "the rattle never landed, so there is nothing to expire"
    ask(table, mid, "end")
    to_turn(table, mid, ME)
    assert ITEM_DOWN not in conditions(tmp_path, mid, FOE), "the rattle outlived the start of the wielder's next turn"


def test_a_rattled_weapon_does_not_follow_the_holder_to_another_weapon(tmp_path, monkeypatch):
    """The -2 is on that item. FOE carries two weapons and the hit named one of them, so the weapon it swings
    instead is rolled exactly as it is in a fight where nothing was ever rattled (the swap a Disarm makes you do)."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,), foe_kit=(DAGGER, AXE), seed="AUTO21-swap")
    force_rolls(monkeypatch, attack=(ME, FOE), save=(FOE,), save_value=3)
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    held = conditions(tmp_path, mid, FOE).get(ITEM_DOWN)
    assert held is not None, "the failed save left every item sound"
    assert str((held.data or {}).get("item")) == AXE, f"the wrong item was rattled: {held.data}"
    swapped = swing_with(tmp_path, table, mid, DAGGER_ATTACK)

    control_root = tmp_path / "control"
    control_root.mkdir()
    control_combat, control_table, control_mid = fight(control_root, mids=(), foe_kit=(DAGGER, AXE), seed="AUTO21-swap")
    force_rolls(monkeypatch, attack=(ME, FOE), save=(FOE,), save_value=3)
    control = swing_with(control_root, control_table, control_mid, DAGGER_ATTACK)
    assert swapped["modifier"] == control["modifier"], \
        f"the unrattled weapon rolled {swapped['modifier']} against an untouched {control['modifier']}"
    assert ITEM_DOWN in conditions(tmp_path, mid, FOE), "the rattle ended early, so the comparison proved nothing"


def test_a_holder_that_drops_its_rattled_weapon_is_not_penalised_barehanded(tmp_path, monkeypatch):
    """The penalty is on attacks made with that item: a holder that lets it go (a swap, a disarm, a choice) and fights
    bare-handed is not charged for it."""
    combat, table, mid = fight(tmp_path, mids=(IRON,), me_kit=(BLADE,), foe_kit=(AXE,), seed="AUTO21-drop")
    force_rolls(monkeypatch, attack=(ME, FOE), save=(FOE,), save_value=3)
    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "+ Breaking"))
    assert str((conditions(tmp_path, mid, FOE).get(ITEM_DOWN).data or {}).get("item")) == AXE

    to_turn(table, mid, FOE)
    ask(table, mid, named(combat, mid, FOE, "Drop fu"))
    bare = swing_with(tmp_path, table, mid, "Unarmed Strike")

    control_root = tmp_path / "control"
    control_root.mkdir()
    control_combat, control_table, control_mid = fight(control_root, mids=(), foe_kit=(), seed="AUTO21-drop")
    force_rolls(monkeypatch, attack=(ME, FOE), save=(FOE,), save_value=3)
    control = swing_with(control_root, control_table, control_mid, "Unarmed Strike")
    assert bare["modifier"] == control["modifier"], \
        f"a bare-handed fighter rolled {bare['modifier']} against an untouched {control['modifier']}"


def test_an_ai_fighter_answers_its_own_break_the_guard(tmp_path, monkeypatch):
    """Item 9: the printed offer is the fighter's own decision, so an AI fighter answers it by itself and never puts
    the question to a player (the player-owned half is every other Break the Guard test here)."""
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD,), modes={ME: "LOCAL_AUTO", FOE: "MANUAL"}, seed="AUTO21-ai")
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    before = ac(tmp_path, mid, FOE)
    to_turn(table, mid, ME)                     # the AI fighter's own turn, wherever the initiative put it
    engine = combat._load_session(mid).engine
    wanted = [candidate for candidate in engine.legal_candidates()
              if candidate.display_name.endswith("attack") and "+" not in candidate.display_name
              and tuple(candidate.target_ids) == (FOE,)]
    assert wanted, f"the AI fighter cannot attack: {[c.display_name for c in engine.legal_candidates()]}"

    original = combat.controller.choose_primary_action
    monkeypatch.setattr(combat.controller, "choose_primary_action",
                        lambda context: original(context.model_copy(update={"legal_candidates": tuple(
                            c for c in context.legal_candidates if c.candidate_id == wanted[0].candidate_id)})))
    result = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert result["status"] == "COMMITTED", \
        f"the AI fighter put its own question to the table: {result.get('reaction')}"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources.get(FOCUS, 0) == 0, "the AI fighter did not pay the printed price"
    assert lowered_armor_class(tmp_path, mid, FOE) == -2, "the AI fighter never used its own Break the Guard"
    assert ac(tmp_path, mid, FOE) == before - 2


# ======================================================================== Shifting Grip Scripture
GRIP = "condition:typed.weapons_shifting_grip"
GRIP_TALENT = "tianxia.talent.weapons.shifting_grip_scripture"


def grip_of(tmp_path, mid, who=ME):
    held = conditions(tmp_path, mid, who).get(GRIP)
    return str((held.data or {}).get("grip") or "") if held is not None else ""


def armed_candidates(combat, mid, who):
    """(candidate id, display name, implement id) of every melee attack the table currently offers against ``who``.

    Melee only, because the reach query asks about melee attacks alone: a thrown dagger has a range of its own and is
    offered from 20 feet whatever the fighter is holding.
    """
    from combat.attack_reach import melee

    engine = combat._load_session(mid).engine
    rows = []
    for candidate in engine.legal_candidates():
        if tuple(candidate.target_ids) != (who,) or candidate.kind.value in ("MOVE", "END_TURN"):
            continue
        action = engine.action_catalog.get(candidate.source_definition_id)
        typed = (getattr(action, "parameters", {}) or {}).get("typed") or {}
        weapon = typed.get("weapon") if isinstance(typed.get("weapon"), dict) else {}
        if melee(action):
            rows.append((candidate.candidate_id, str(getattr(action, "display_name", "")),
                         str(weapon.get("implement_id") or "")))
    return rows


def attack_with(combat, mid, who, implement_id):
    """The candidate id of the offered attack that delivers ``implement_id`` against ``who``."""
    for candidate_id, name, implement in armed_candidates(combat, mid, who):
        if implement == implement_id:
            return candidate_id
    raise AssertionError(f"no attack with {implement_id} on {who}: {armed_candidates(combat, mid, who)}")


def last_attack(tmp_path, mid, who=ME):
    rolled = [event for event in events(tmp_path, mid, "ATTACK_ROLLED", who)]
    assert rolled, "no attack was made"
    return rolled[-1].payload


def choose_grip(table, mid, option, *, who=ME, seen=None):
    """Advance to ``who``'s turn and answer its start-of-turn grip menu with ``option``.

    The menu is raised by the turn boundary itself, so it is answered on the way in.
    """
    to_turn(table, mid, who, choice=option, seen=seen)


def test_shifting_grip_scripture_offers_three_grips_and_guard_grip_raises_armor_class(tmp_path):
    """"Guard Grip. You gain +1 AC until the start of your next turn, but your speed is reduced by 5 feet"."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,))
    before = ac(tmp_path, mid, ME)
    seen = []
    choose_grip(table, mid, "guard", seen=seen)
    grip_prompts = [prompt for prompt in seen if "Shifting Grip" in json.dumps(prompt)]
    assert grip_prompts, "the grip was never put to the player"
    labels = json.dumps(grip_prompts[0])
    assert all(word in labels for word in ("Close Grip", "Long Grip", "Guard Grip")), \
        f"the printed three grips were not offered: {labels}"
    assert "Speed 5 feet lower" in labels and "1 more Armor Class" in labels, f"the printed numbers are missing: {labels}"
    assert grip_of(tmp_path, mid) == "guard", "the chosen grip was not recorded"
    assert ac(tmp_path, mid, ME) == before + 1, "Guard Grip's Armor Class did not apply"
    engine = reload(tmp_path, mid)
    from combat.ext.weapons_sphere import guard_grip_speed

    assert guard_grip_speed(engine, engine.state.actors[ME]) == -5, "Guard Grip's Speed reduction is missing"


def gripped_jian_action(engine):
    """The fighter's own jian attack: the action whose delivered item is the gripped weapon."""
    for action in engine.action_catalog.values():
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        weapon = typed.get("weapon") if isinstance(typed.get("weapon"), dict) else {}
        if (action.owner_id == ME and str(weapon.get("implement_id") or "") == VERSATILE
                and str(getattr(action, "display_name", "")).endswith("attack") and "+" not in action.display_name):
            return action
    raise AssertionError("the fighter has no plain jian attack")


def long_grip_frame(engine, action):
    """The frame the Disadvantage query is asked with: the holder, and the attack this weapon is making.

    The printed penalty belongs to the gripped weapon's own attacks, so the frame has to name which weapon is being
    swung; a frame with no attack in it is no attack at all and takes nothing from the grip.
    """
    return SimpleNamespace(engine=engine, actor=engine.state.actors[ME], action=action,
                           typed=action.parameters["typed"])


def test_shifting_grip_scripture_long_grip_reaches_five_further_and_gives_disadvantage(tmp_path):
    """"Long Grip. Increase reach by 5 feet until the start of your next turn, but attacks against adjacent
    creatures have Disadvantage"."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,))
    choose_grip(table, mid, "long")
    assert grip_of(tmp_path, mid) == "long"
    engine = reload(tmp_path, mid)
    from combat import attack_reach
    from combat.ext.weapons_sphere import long_grip_disadvantage

    action = gripped_jian_action(engine)
    assert attack_reach.maximum(engine, engine.state.actors[ME], action, base=5) == 10, \
        "Long Grip's extra reach is not in this attack's reach"
    frame = long_grip_frame(engine, action)
    near = engine.state.actors[FOE]
    assert long_grip_disadvantage(frame, near) == "DISADVANTAGE", "an adjacent creature does not attack with Disadvantage"
    far = near.model_copy(update={"position": near.position.model_copy(update={"x": near.position.x + 4})})
    assert long_grip_disadvantage(frame, far) is None, "a creature 20 feet away still suffers the penalty"


def test_shifting_grip_scripture_is_inert_for_a_weapon_with_no_handling_modes(tmp_path):
    """A dagger is not Versatile, Staff, Polearm, Flexible or Variable Reach: no grip is ever asked for."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(DAGGER,))
    seen = []
    to_turn(table, mid, ME, seen=seen)
    ask(table, mid, "end")
    assert not [prompt for prompt in seen if "Shifting Grip" in json.dumps(prompt)], "a dagger was given a grip"
    assert grip_of(tmp_path, mid) == ""


def test_a_grip_ends_when_its_weapon_is_put_away(tmp_path):
    """A grip is how one weapon is held: Guard Grip's Armor Class and Speed belong to that weapon, so putting it
    away ends them at once instead of leaving a bonus that follows nobody."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,))
    base = ac(tmp_path, mid, ME)
    choose_grip(table, mid, "guard")
    assert ac(tmp_path, mid, ME) == base + 1, "Guard Grip's Armor Class did not apply"

    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "Drop jian"))       # the gripped weapon goes to the ground
    assert grip_of(tmp_path, mid) == "guard", "the fixture dropped nothing: the grip is still recorded"
    assert ac(tmp_path, mid, ME) == base, \
        "Guard Grip's Armor Class outlived the weapon it was a way of holding"
    engine = reload(tmp_path, mid)
    from combat.ext.weapons_sphere import guard_grip_speed

    assert guard_grip_speed(engine, engine.state.actors[ME]) is None, \
        "Guard Grip's Speed reduction outlived the weapon it was a way of holding"


def test_a_long_grip_ends_when_its_weapon_is_put_away(tmp_path):
    """The same for Long Grip: the extra reach and the Disadvantage are that weapon's, not the fighter's."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,))
    choose_grip(table, mid, "long")
    engine = reload(tmp_path, mid)
    from combat import attack_reach
    from combat.ext.weapons_sphere import long_grip_disadvantage

    action = gripped_jian_action(engine)
    holder = engine.state.actors[ME]
    assert attack_reach.maximum(engine, holder, action, base=5) == 10, "Long Grip's extra reach never applied"
    assert long_grip_disadvantage(long_grip_frame(engine, action), engine.state.actors[FOE]) == "DISADVANTAGE"

    to_turn(table, mid, ME)
    ask(table, mid, named(combat, mid, ME, "Drop jian"))
    engine = reload(tmp_path, mid)
    holder = engine.state.actors[ME]
    assert attack_reach.maximum(engine, holder, action, base=5) == 5, \
        "Long Grip's extra reach outlived the weapon it was a way of holding"
    assert long_grip_disadvantage(long_grip_frame(engine, action), engine.state.actors[FOE]) is None, \
        "Long Grip's Disadvantage outlived the weapon it was a way of holding"


def test_the_grip_prompt_describes_what_the_holder_itself_loses(tmp_path):
    """Item 13: "attacks against adjacent creatures have Disadvantage" is the holder's own attacks, and the prompt
    must say so rather than promising that everyone attacking the holder is worse off. It also says which weapon the
    two numbers belong to, because that is how the grip is read at the table."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE,))
    seen = []
    to_turn(table, mid, ME, seen=seen)
    ask(table, mid, "end")
    prompts = [prompt for prompt in seen if "Shifting Grip" in json.dumps(prompt)]
    assert prompts, "the grip was never put to the player"
    text = json.dumps(prompts[0])
    assert "your own attacks with it against creatures next to you have Disadvantage" in text, \
        f"the prompt does not say whose attacks are worse: {text}"
    assert "gives attackers Disadvantage against you" not in text, \
        f"the prompt still claims the holder's attackers are penalised: {text}"


def test_long_grip_reaches_five_further_only_with_the_gripped_weapon(tmp_path):
    """"Long Grip. Increase reach by 5 feet": the 5 feet are the gripped weapon's own reach, because a grip is a way of
    holding one weapon. Standing 10 feet away, the fighter reaches the target with the gripped jian and with nothing
    else: the dagger in the other hand still reaches 5 feet and an unarmed strike still reaches 5 feet."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE, DAGGER), foe_at=(3, 8))
    engine = combat._load_session(mid).engine
    assert engine.grid.distance_ft(engine.state.actors[ME].position, engine.state.actors[FOE].position) == 10, \
        "the fixture did not stand the fighter 10 feet away"
    choose_grip(table, mid, "long")
    assert grip_of(tmp_path, mid) == "long"
    offered = armed_candidates(combat, mid, FOE)
    assert any(implement == VERSATILE for _, _, implement in offered), \
        f"the gripped weapon does not reach 10 feet, so the fixture proves nothing: {offered}"
    assert not [row for row in offered if row[2] == DAGGER], \
        f"the Long Grip's 5 extra feet were given to the dagger as well: {offered}"
    assert not [row for row in offered if not row[2] and "unarmed" in row[1].lower()], \
        f"the Long Grip's 5 extra feet were given to a bare-handed strike: {offered}"


def test_long_grip_penalises_only_the_gripped_weapon_s_own_attacks(tmp_path, monkeypatch):
    """"but attacks against adjacent creatures have Disadvantage": that penalty belongs to the gripped weapon's own
    attacks. The fighter striking with the other weapon, or barehanded, is not disadvantaged by how the jian is held,
    while the jian's own attack is."""
    combat, table, mid = fight(tmp_path, mids=(GRIP_TALENT,), me_kit=(VERSATILE, DAGGER))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    choose_grip(table, mid, "long")
    to_turn(table, mid, ME)
    ask(table, mid, attack_with(combat, mid, FOE, DAGGER))
    dagger_roll = last_attack(tmp_path, mid)
    assert dagger_roll.get("mode") != "DISADVANTAGE", \
        f"an attack with another weapon was made at Disadvantage by the jian's grip: {dagger_roll}"

    ask(table, mid, "end")                     # the turn's one action is spent; the grip lasts to the start of the next
    to_turn(table, mid, ME, choice="long")     # the grip lasts to the start of the next turn, so it is chosen again
    assert grip_of(tmp_path, mid) == "long"
    ask(table, mid, attack_with(combat, mid, FOE, VERSATILE))
    jian_roll = last_attack(tmp_path, mid)
    assert jian_roll.get("mode") == "DISADVANTAGE", \
        f"the gripped weapon's own attack against an adjacent creature was not made at Disadvantage: {jian_roll}"


def test_the_break_the_guard_prompt_names_a_damage_type_rather_than_a_list(tmp_path, monkeypatch):
    """Item 13: the prompt must read as a sentence for a player, not show a list's own punctuation."""
    combat, table, mid = fight(tmp_path, mids=(BREAK_GUARD,))
    force_naturals(monkeypatch, who=ME, attack=15, save=3)
    to_turn(table, mid, ME)
    prompts = ask(table, mid, attack_on(combat, mid, FOE, ranged=False))
    offered = [prompt for prompt in prompts if "Break the Guard" in json.dumps(prompt)]
    assert offered, "the printed Guard offer was never put to the player"
    text = json.dumps(offered[0])
    assert "add your Proficiency Bonus to the damage (" in text, \
        f"the prompt does not say what Breaking Method adds: {text}"
    name = text.split("the damage (")[1].split(")")[0]
    assert name and name.isalpha(), f"the damage type printed as {name!r} instead of a plain name"


# ======================================================================== one Breaking Method, from the owner's data
def test_breaking_method_is_built_from_the_owner_weapon_data():
    """There is one implementation of Breaking Method, in combat/ext/weapon_specials.json, and both the table's own
    use and the detector read it there. A second hand-written definition would drift from the compiler's button."""
    from combat.ext.weapon_methods import breaking_effects, damage_types_of, used_breaking

    source = json.loads((ROOT / "combat/rules/weapon_specials.json").read_text(encoding="utf-8"))
    owner = source["weapon_methods"]["Breaking"]["effects"]
    assert any("<weapon_damage_type>" in str(effect.get("damage_types")) for effect in owner), \
        f"the fixture's Breaking row no longer names the weapon's damage type: {owner}"

    built = breaking_effects(["SLASHING"])
    assert built and built[0]["damage_types"] == ["SLASHING"], \
        f"the row was not filled with the weapon's own damage type: {built}"
    assert used_breaking(built, ["SLASHING"]), "the detector does not recognise the row the owner wrote"
    assert not used_breaking(built, ["PIERCING"]), "Breaking was recognised for a weapon that deals no such damage"
    assert not used_breaking(built, []), "Breaking was recognised on a hit that dealt no weapon damage"

    # The compiler fills the same token for the weapon's "+ Breaking" button, so the two rows are one row.
    filled = json.loads(json.dumps(owner).replace("<weapon_damage_type>", "SLASHING"))
    assert used_breaking(filled, ["SLASHING"]), \
        "the detector does not recognise the row combat/factory_compiler.py builds for the weapon's own button"
    assert damage_types_of({"damage_types": ["slashing"]}) == ["SLASHING"]
