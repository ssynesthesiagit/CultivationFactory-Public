"""The Flowers sphere's unique talents (owner 2026-10-05, AUTO86: "automate everything" -- the printed text of
TAL_FLOWERS_* and tianxia.talent.flowers.* in authority/typed_mechanics/rules_text.json, read against the owner's Sphere
Compendium. Spheres 5e and D&D 5.5e were not needed: each line below is the owner's own words.)

The Blossom talents and the Fragrance shapes are already the table's own (combat/ext/blossom.py places a Blossom and
combat/zones.py shapes a Fragrance, which is why "Choose one Fragrance talent you know and apply it" and the Lingering
Fragrance augment are button presses, not GM lines). What is left here is the printed wording the compiler has no shape
for, each one a *choice the owner of the talent* makes:

  Petal Dart        "Choose the damage type when attacking." -- Slashing or Poison. The engine's own fallback picks the
                    type that lands hardest (typed_executor.choose_damage_type, the owner's 2026-09-26 ruling); here the
                    owning player is asked, once per strike, and an AI owner answers for itself.
  Fragrant Mirage   "gain Advantage on Dexterity (Stealth) checks while Lightly Obscured" (the table's own Stealth
                    Advantage condition, which does not read the obscurity); "opportunity attacks against you have
                    Disadvantage"; "the first Petal Dart you make each turn has Advantage while you stand inside one of
                    your Fragrances." Advantage on the first Petal Dart of the turn, only while the caster stands in one of
                    the Fragrance areas it made and only while its own Mirage is up; the printed Opportunity-Attack
                    Disadvantage answered for the incoming reaction attack. Both answers are read from this character's own
                    rows: a fighter who does not know the talent, or whose Mirage has ended, gets neither.

Hooks: attack_damage_type_choice, attack_mode. Both are documented in combat/ext/__init__.py, both return None for a
character that owns neither talent, and neither writes state outside the owner (the "first each turn" readings are the
owner's own turn flags, integers, so a saved fight replays them).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

PETAL_DART = "TAL_FLOWERS_PETAL_DART"
FRAGRANT_MIRAGE = "TAL_FLOWERS_FRAGRANT_MIRAGE"
FRAGRANCE = "Fragrance"
DAMAGE_TYPE_CHOICE = "petal_dart_damage_type"
MIRAGE_TURN_FLAG = "flowers_fragrant_mirage"


@effect("damage_recipient_effects")
def damage_recipient_effects(ctx: Any, row: dict[str, Any]) -> None:
    """Opt-in defensive follow-ups for the actual protected self/ally.

    Generic bystander reactions snapshot ``protects``; the self-damage path
    protects the reactor. Nested rows use ordinary explicit target semantics,
    rather than searching for another ally. No unstamped saved row changes.
    """
    from dataclasses import replace
    from ..typed_executor import run_effects

    subject = ctx.engine.state.actors.get(ctx.typed.get("protects") or ctx.actor.entity_id)
    if subject is None:
        return
    inner = replace(ctx, target=subject, targets=[subject], typed={**ctx.typed, "protects": subject.entity_id})
    run_effects(inner, row.get("effects") or [])


@hook("attack_mode")
def beguiling_perfume_allies(ctx: Any, target: Any) -> str | None:
    """Only attacks against the charmer's allies, while the attacker sees it.

    The reviewed condition snapshots the opt-in marker; old saved rows are
    unchanged. The ordinary Charmed recipient gate protects the charmer itself.
    """
    if target is None:
        return None
    from ..target_knowledge import can_see

    for condition in ctx.actor.conditions.values():
        if condition.condition_id != "condition:typed.charmed" or (condition.data or {}).get("suppressed") or (condition.data or {}).get("flowers_beguiling") != 1:
            continue
        charmer = ctx.engine.state.actors.get(condition.source_actor_id)
        if charmer is not None and target.entity_id != charmer.entity_id and target.team_id == charmer.team_id and can_see(ctx.engine, ctx.actor, charmer):
            return "DISADVANTAGE"
    return None


@effect("flowers_repeat_frightened")
def calming_repeat(ctx: Any, row: dict[str, Any]) -> None:
    """The recipient may repeat exactly one of its original Frightened saves.

    No extra ally/range search: the saved area trigger already selected the
    creature starting its turn inside. A hostile creature may also consent.
    """
    from .repeat_saves import repeatable, save_of
    from .needle import CHOICE, ask, checkpoint_id

    subject = ctx.target
    if subject is None:
        return
    available = repeatable(subject, ("frightened",))
    if not available:
        return
    options = {iid: condition for iid, condition in available}
    picked = ask(ctx.engine, ctx.intent,
                 checkpoint_id(ctx.engine, "calming_repeat", ctx.source, subject.entity_id),
                 subject, CHOICE + "flowers:calming_repeat", list(options), allow_decline=True,
                 labels={iid: f"Frightened: {save_of(c)['ability']} save, DC {save_of(c)['dc']}" for iid, c in available},
                 target_id=subject.entity_id, name="Calming Perfume",
                 prompt=f"Calming Perfume: {subject.display_name} starts its turn inside the Fragrance and may repeat one saving throw against Frightened, or decline.")
    if not picked:
        return
    iid = picked[0]
    condition = options[iid]
    save = save_of(condition)
    roll = ctx.engine._roll_save(subject, str(save['ability']).upper(), int(save['dc']), ctx.source,
                                roll_context={"source_actor_id": condition.source_actor_id, "named": ["frightened"]})
    if roll is not None and roll.total >= int(save['dc']) and iid in subject.conditions:
        subject.conditions.pop(iid)
        ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=subject.entity_id,
                                target_ids=(subject.entity_id,), payload={"condition_id": condition.condition_id,
                                "instance_id": iid, "repeat_save": True})


def _owns(engine: Any, actor: Any, feature_id: str) -> bool:
    """Whether *this* actor's own catalog carries the talent (its display names are the printed ones). Scoped to the actor's
    own actions: the catalog holds every fighter's bundles, so an unscoped read would hand one fighter's talent to another."""
    if actor is None:
        return False
    for action in (engine.action_catalog or {}).values():
        if str(getattr(action, "owner_id", "") or "") != actor.entity_id:
            continue
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        if str(typed.get("source") or "") == feature_id or str(typed.get("option_of") or "") == feature_id:
            return True
        if str(getattr(action, "source_definition_id", "")).endswith(feature_id):
            return True
    return False


def _wears_own_mirage(engine: Any, actor: Any) -> bool:
    """"For the duration:" -- the printed effect is the condition the Bonus Action put on the caster, so it lasts exactly as
    long as the creature's own Fragrant Mirage (until Concentration ends). An engine bookkeeping row of the same ability (the
    Concentration deadline) carries no rule and is not the printed effect."""
    for condition in (actor.conditions or {}).values():
        if str(condition.source_definition_id or "").split(".")[-1] != FRAGRANT_MIRAGE:
            continue
        if condition.source_actor_id != actor.entity_id or not (condition.data or {}).get("rule"):
            continue
        if (condition.data or {}).get("hidden"):
            continue
        return True
    return False


def _petal_dart_of(engine: Any, source: str) -> bool:
    """The strike comes from this character's own Petal Dart action (not a borrowed weapon or another talent)."""
    action = (engine.action_catalog or {}).get(source)
    if action is None:
        return False
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return str(typed.get("source") or "") == PETAL_DART or str(typed.get("option_of") or "") == PETAL_DART


def _inside_own_fragrance(engine: Any, actor: Any) -> bool:
    from .. import zones

    for zone in zones.typed_zones(engine):
        if zone.owner_id != actor.entity_id:
            continue
        if str((zone.trigger_profile or {}).get("name") or "") != FRAGRANCE:
            continue
        if engine._footprint_intersects(actor, zone.affected_cells):
            return True
    return False


@hook("attack_damage_type_choice")
def petal_dart_damage_type(ctx: Any, attack: dict[str, Any], target: Any, kinds: list[str], attack_index: int) -> str | None:
    """Petal Dart: "Choose the damage type when attacking." Asked of the owner of the talent -- a player-controlled
    caster on their turn or an AI creature's -- for each strike, naming the attack and the creature it is made against.
    An AI owner, or a fight nobody answers, keeps the type that lands hardest. Inert unless this character's own attack
    is its Petal Dart and the strike really offers a choice."""
    if target is None or len(kinds) < 2 or not _petal_dart_of(ctx.engine, ctx.source):
        return None
    from ..typed_executor import choose_damage_type
    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    best = choose_damage_type(ctx, list(kinds), [target])
    count = int(attack.get("count") or 1)
    which = f" (attack {attack_index} of {count})" if count > 1 else ""
    picked = ask(engine, ctx.intent, checkpoint_id(engine, DAMAGE_TYPE_CHOICE, actor.entity_id, target.entity_id, attack_index),
                 actor, CHOICE + "flowers:" + DAMAGE_TYPE_CHOICE, list(kinds), labels={kind: f"{kind.title()} damage" for kind in kinds},
                 preferred=[best], target_id=target.entity_id, name="Petal Dart", feature_id=PETAL_DART,
                 prompt=f"Petal Dart: choose the damage type of your {ctx.action.display_name}{which} against {target.display_name}. "
                        f"The dice and your bonus stay the same; only the type changes, which matters against Resistance.",
                 prompt_context=action_context(engine, actor, ctx.source, target))
    return picked[0] if picked else None


@hook("attack_mode")
def fragrant_mirage_first_dart(ctx: Any, target: Any) -> str | None:
    """Fragrant Mirage: "the first Petal Dart you make each turn has Advantage while you stand inside one of your
    Fragrances." Three readings, all required: the caster owns the talent, its own Mirage is up right now ("for the
    duration"), and this is the first Petal Dart of the turn (the flag records the round in which it resolved, wherever the
    caster stood -- a first Dart from outside the Fragrance still spends it). Inert for everyone else and for every other
    attack."""
    engine, actor = ctx.engine, ctx.actor
    if target is None or not _petal_dart_of(engine, ctx.source) or not _owns(engine, actor, FRAGRANT_MIRAGE):
        return None
    if actor.turn_flags.get(MIRAGE_TURN_FLAG) == engine.state.round_number:
        return None
    actor.turn_flags[MIRAGE_TURN_FLAG] = int(engine.state.round_number)
    if not _wears_own_mirage(engine, actor) or not _inside_own_fragrance(engine, actor):
        return None
    return "ADVANTAGE"


@hook("attack_mode")
def fragrant_mirage_opportunity(ctx: Any, target: Any) -> str | None:
    """Fragrant Mirage: "opportunity attacks against you have Disadvantage." The printed row itself lands as a
    Disadvantage the attack never reads (it names no roll the engine rolls), so the roll is answered here instead: every
    Opportunity Attack made against a creature wearing this talent's own condition is made with Disadvantage. Inert for
    anyone else and for every other attack."""
    if target is None:
        return None
    if not (ctx.typed or {}).get("opportunity_of") and "opportunity" not in str(ctx.source):
        return None
    return "DISADVANTAGE" if any(str(own.source_definition_id or "").split(".")[-1] == FRAGRANT_MIRAGE
                                  and own.source_actor_id == target.entity_id and not (own.data or {}).get("hidden")
                                  for own in target.conditions.values()) else None
