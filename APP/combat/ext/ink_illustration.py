"""Painted Beast form benefits; ownership and selections travel in the fight.

Only explicit ink_illustration owner rows opt in. A new summon resets its base
statistics before applying the selected distinct benefits, so re-summoning
cannot stack them. Combat bonuses use the ordinary attack/save/flight hooks.
Horse passenger capacity, Spider climbing and Hound tracking need separate
movement/check support; selecting them never silently grants those mechanics.
"""
from dataclasses import replace
from typing import Any

from . import hook

FORMS = {
    "tiger": "Tiger: Ink Fang deals 3d6 + the writer's key ability modifier",
    "crane": "Crane: Fly Speed 50 feet; Hover",
    "serpent": "Serpent: an Ink Fang hit forces a Constitution save; failure poisons until the writer's next turn",
    "spider": "Spider: an Ink Fang hit forces a Strength save; failure sets Speed to 0 until the writer's next turn (Climb Speed 40 feet is manual)",
    "horse": "Horse: Speed 60 feet (carrying two Medium creatures or one Large creature is manual)",
    "tortoise": "Tortoise: +3 AC; Speed 20 feet",
    "hound": "Hound: Advantage on tracking and detecting hidden targets (manual checks)",
}


@hook("compile_block")
def compile_illustration(block, spec, row, numbers):
    if block != "ink_illustration":
        return None
    return [{**row, "kind": spec["kind"], "numbers": {key: int(numbers[key]) for key in ("pb", "cl", "key_mod")}}]


@hook("summon_appeared")
def illustrate(engine, owner, beast, source):
    from .. import maximum_hp
    from .needle import ask, checkpoint_id
    rows = [r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(owner.entity_id, [])
            if r.get("block") == "ink_illustration"]
    record = beast.summon or {}
    if record.get("group") != "painted_beast" or not rows:
        return
    kinds = {r["kind"] for r in rows}
    numbers = rows[0]["numbers"]
    count = int("training" in kinds) + int("adept" in kinds)
    forms = ask(engine, None, checkpoint_id(engine, "ink_forms", beast.entity_id), owner,
        "choice:needle.ink_forms", list(FORMS), labels=FORMS, minimum=count, maximum=count,
        preferred=["tiger", "tortoise"], name="Living Illustration", target_id=beast.entity_id,
        prompt=f"Living Illustration: {owner.display_name} creates {beast.display_name}; choose {count} different form benefit(s). They last while this Painted Beast remains; no extra cost.")
    # Integers and strings only, retained through commit and reload. Use native
    # evented adjustments: base AC/Speed writes have no reducer event.
    action_numbers = ((engine.action_catalog[source].parameters or {}).get("typed") or {}).get("numbers") or {}
    record.update(ink_forms=",".join(forms), ink_dc=int(action_numbers.get("save_dc") or 8 + numbers["pb"] + numbers["key_mod"]))
    ac_bonus = (2 if "adept" in kinds else 0) + (3 if "tortoise" in forms else 0)
    if ac_bonus:
        engine._add_modifier(beast, source, "armor_class", "ADD", ac_bonus, "ALL_ATTACKS", expires_on="CONCENTRATION_END")
    speed = 20 if "tortoise" in forms else 60 if "horse" in forms else beast.speed_ft
    if speed != beast.speed_ft:
        engine._add_modifier(beast, source, "speed_ft", "ADD", speed - beast.speed_ft, "ALL_MOVEMENT", expires_on="CONCENTRATION_END")
    hp_key = "ink_illustration_adept"
    if hp_key in beast.maximum_hp_adjustments:
        maximum_hp.change(engine, beast, hp_key, 0, source, owner.entity_id, label="Previous Painted Beast's Adept bonus ends")
    if "adept" in kinds:
        amount = 2 * int(numbers["cl"])
        maximum_hp.change(engine, beast, hp_key, amount, source, owner.entity_id,
                          label="Living Illustration Adept", current_delta=amount)
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=owner.entity_id, target_ids=(beast.entity_id,),
        payload={"text": "Living Illustration: " + "; ".join(FORMS[f] for f in forms),
                 "armor_class": beast.armor_class + engine._ac_modifier(beast), "hit_points": beast.maximum_hp, "speed_ft": engine._effective_speed(beast)})


def forms_of(actor):
    """Persisted forms of this Painted Beast, empty for every other creature."""
    record = actor.summon or {}
    return set(str(record.get("ink_forms") or "").split(",")) if record.get("group") == "painted_beast" else set()


@hook("attack_damage")
def tiger_damage(ctx, dice):
    if "tiger" not in forms_of(ctx.actor) or dice is None or ".attack" not in ctx.source and not ctx.source.endswith("opportunity_attack"):
        return None
    return dice.model_copy(update={"count": 3, "sides": 6})


@hook("flight")
def crane_flight(engine, actor):
    if "crane" in forms_of(actor) and actor.active:
        return {"fly_speed_ft": 50, "flight_hover": 1}
    return None


@hook("after_hit")
def fang_rider(ctx, target, kind):
    from .. import typed_executor as te
    from .effect_durations import token
    forms = forms_of(ctx.actor)
    owner = ctx.engine.state.actors.get((ctx.actor.summon or {}).get("owner"))
    if not owner or not target.active or not forms.intersection({"serpent", "spider"}):
        return
    if ".attack" not in ctx.source and not ctx.source.endswith("opportunity_attack"):
        return
    sub = replace(ctx, actor=owner, target=target, targets=[target],
                  typed={**ctx.typed, "numbers": {**ctx.numbers, "save_dc": ctx.actor.summon["ink_dc"]}})
    for form, ability, result in (("serpent", "CON", {"type": "condition", "condition": "poisoned"}),
                                  ("spider", "STR", {"type": "speed", "becomes": 0})):
        if form in forms:
            # Speed modifiers are filed under the current turn actor, not
            # sub.actor. Name the writer's next turn explicitly for Spider.
            expires = (token("start", owner.entity_id, int(owner.turns_started) + 1)
                       if form == "spider" else "START_OF_SOURCE_NEXT_TURN")
            te.block_save(sub, {"type": "save", "ability": ability, "on_success": [],
                "on_fail": [{**result, "applies_to": "target", "expires_on": expires}]})
