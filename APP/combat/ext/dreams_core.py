"""The Dreams sphere's core rules (rider lane C5, owner 2026-09-30: "i want everything we can automated"): Drowsy, Dream Sleep and
the Dream Seed, from the Sphere Compendium's CORE DREAMS RULES and BASE SPHERE ABILITIES. The catalog keeps Dream Seed only as its
rules paragraph (a passive), so the planting action is built here for every Dreams cultivator.

Effect types (inert unless an ability's own typed row names them):
  drowsy          {"duration" | "expires_on"}: "A Drowsy creature: cannot take Reactions; has Speed reduced by 10 feet; has Disadvantage
                  on its next Wisdom (Perception) check or Concentration saving throw before the condition ends." One Drowsy at a
                  time (a new one replaces it); the Concentration part is the engine's "next Concentration save" Disadvantage.
                  A sphere that prints its own "While Drowsy" list configures this one condition with it and changes nothing
                  else: "rule" (merged over DROWSY_RULE, so it can also restate the player-facing "_rule" text), "speed_delta",
                  "label" (the condition pill), and "while_drowsy" -- the extra conditions the list asks for, an empty list for a
                  sphere that grants none (Flowers' Soporific Pollen: Speed -10, no Reactions, Disadvantage on Wisdom (Perception)
                  checks, and no Concentration penalty). Those consequences are applied with the Drowsy's own expiry, so they end
                  with the Drowsy rather than with the caster's next turn, and each is recorded on the Drowsy instance that granted it
                  (condition data "consequences": the instance ids it made, strings only). A Drowsy that replaces another takes its
                  consequences with it, so replacing the Dreams list with Pollen's ends the Concentration penalty it granted, while a
                  penalty some other source granted is none of this Drowsy's business and stays.
  plant_dream_seed  the "Dream Seed" mark: 1 hour on a willing (same side) or sleeping creature, else until the start of your next
                  turn; one of your Seeds per creature (a new one replaces it).
  dream_seed      the Dream Seed action: a willing or sleeping creature is planted at once; an awake unwilling one makes a Wisdom
                  save, a failure plants the Seed and (Drowsy Thought, learned by every Dreams cultivator) makes it Drowsy.
  seed_or_drowsy  marker: the ability is offered only against a creature bearing your Dream Seed or currently Drowsy (Sleep,
                  Nightmare Glimpse).
  dream_passage   marker: a teleport lands only inside a Dreamscape you made or your Dreams Domain (Waking Dream Passage).
Condition "dream_sleep" (a typed condition row with this module's rule): Unconscious and Prone; it ends when the sleeper takes
damage (event hook).
Condition rule key (shared, any condition's rule may carry it): "target_within_ft": n -- "cannot willingly target creatures more
than n feet away" (Dream Prison, Dream That Swallows the Waking World), read by candidate_allowed.
Hooks: candidate_allowed; save (allies inside a Dreamscape shaped by Lucid Veil or Symbolic Shelter have Advantage on saves against
the conditions those talents name); event (Dream Sleep ends on damage); attack_damage (Dream-Sovereign Incarnation's 6d10 Dream
Needle); turn_start_choice (Dream-Sovereign Incarnation plants a Seed at the start of each of your turns); compile_actions (every
Dreams cultivator: "Dream Seed" and "Dream Seed: willing creature").
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from . import effect, hook

DREAMS = "tianxia.sphere.dreams"
SEED = "Dream Seed"
DROWSY = "condition:typed.drowsy"
SLEEP = "condition:typed.dream_sleep"
NEEDLE = "TAL_DREAM_DREAM_NEEDLE"
SOVEREIGN = "condition:typed.stance.dream_sovereign_incarnation"
DOMAINS = ("TAL_DREAM_COURT_HALF_WAKING_MOON", "tianxia.talent.dreams.world_of_dreams")  # the Dreams Domains
# "Allies inside the Dreamscape gain: Advantage on saving throws against ..." (the Dreamscape talents, by the names the zone records)
SHELTERS = {"Lucid Veil": {"charmed", "frightened", "dream_sleep"}, "Symbolic Shelter": {"frightened", "dream_sleep"}}
DROWSY_RULE = {"no_reactions": True, "_rule": "Drowsy (Dreams core rules): cannot take Reactions; Speed reduced by 10 feet; Disadvantage on its "
               "next Wisdom (Perception) check or Concentration saving throw before the condition ends."}
DROWSY_SPEED = -10
DROWSY_LABEL = "Drowsy: no Reactions, Speed -10 feet, Disadvantage on its next Perception check or Concentration save"
# The Dreams core list's one extra consequence ("its next Concentration saving throw"), applied as the engine's own condition.
DROWSY_WHILE = ({"type": "disadvantage", "applies_to": "target", "on": "its next Concentration saving throw",
                 "evidence": "Drowsy: Disadvantage on its next Concentration saving throw"},)
SLEEP_RULE = {"no_actions": True, "no_reactions": True, "speed_zero": True, "attacked_with": "ADVANTAGE", "save_mode": {"STR": "AUTO_FAIL", "DEX": "AUTO_FAIL"},
              "_rule": "Dream Sleep (Dreams core rules): Unconscious; it awakens if it takes damage."}


def _subjects(ctx: Any) -> list[Any]:
    return [s for s in (ctx.targets or ([ctx.target] if ctx.target is not None else [])) if s is not None and s.active]


def _remove(engine: Any, holder: Any, condition_id: str, source: str, *, owner: str | None = None) -> None:
    for iid, condition in list(holder.conditions.items()):
        if condition.condition_id == condition_id and (owner is None or condition.source_actor_id == owner):
            holder.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(holder.entity_id,),
                                 payload={"condition_id": condition_id, "instance_id": iid})


def _tracked(holder: Any, instance_id: str) -> list[str]:
    """The consequences the Drowsy at this instance put on its creature (see the drowsy effect)."""
    condition = holder.conditions.get(instance_id)
    rows = ((condition.data or {}).get("consequences") or []) if condition is not None else []
    return [str(row) for row in rows if isinstance(row, str)]


def _drop_consequences(engine: Any, holder: Any, source: str, instance_id: str) -> None:
    """Take off what the Drowsy at this instance granted besides the condition itself: those things belong to that
    Drowsy, so a Drowsy that no longer holds them has to take them with it."""
    for row_id in _tracked(holder, instance_id):
        child = holder.conditions.pop(row_id, None)
        if child is not None:
            engine._append_event("CONDITION_REMOVED", source, actor_id=child.source_actor_id, target_ids=(holder.entity_id,),
                                 payload={"condition_id": child.condition_id, "instance_id": row_id, "reason": "DROWSY_REPLACED"})
        modifier = holder.modifiers.pop(row_id, None)
        if modifier is not None:
            engine._append_event("MODIFIER_REMOVED", source, actor_id=modifier.source_actor_id, target_ids=(holder.entity_id,),
                                 payload={"modifier_id": row_id, "reason": "DROWSY_REPLACED"})


def _end_drowsy(engine: Any, holder: Any, source: str) -> None:
    """One Drowsy at a time: a new one replaces what it replaces, together with the consequences that belonged to the
    old one (its "While Drowsy" list, e.g. the Dreams list's Disadvantage on its next Concentration saving throw). A
    penalty this Drowsy never granted is not touched, so another source's own Concentration penalty stays."""
    for iid, condition in list(holder.conditions.items()):
        if condition.condition_id != DROWSY:
            continue
        _drop_consequences(engine, holder, source, iid)
        holder.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", source, actor_id=condition.source_actor_id, target_ids=(holder.entity_id,),
                             payload={"condition_id": DROWSY, "instance_id": iid, "reason": "DROWSY_REPLACED"})


@effect("drowsy")
def drowsy(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import condition_immune, effect_expiry, run_effects, stated_expiry

    for subject in _subjects(ctx):
        if condition_immune(ctx.engine, subject, "drowsy"):
            continue
        _end_drowsy(ctx.engine, subject, ctx.source)
        spec = {**eff, "applies_to": "target"}
        expires = effect_expiry(ctx, spec, subject, condition=True)
        rows = eff.get("while_drowsy")
        rows = [row for row in (DROWSY_WHILE if rows is None else rows) if isinstance(row, dict)]
        before = set(subject.conditions)
        ctx.engine._apply_condition(subject, DROWSY, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                    data={"rule": {**DROWSY_RULE, **dict(eff.get("rule") or {})},
                                          "speed_delta": int(eff.get("speed_delta", DROWSY_SPEED)),
                                          "label": str(eff.get("label") or DROWSY_LABEL)})
        mine = next((iid for iid in sorted(set(subject.conditions) - before)
                     if subject.conditions[iid].condition_id == DROWSY), None)
        if mine is None:
            continue  # the engine refused the condition, so nothing is Drowsy and no "While Drowsy" list is granted
        # "While Drowsy:" holds for as long as the Drowsy does, so those rows carry the Drowsy's own expiry: the name the
        # drowsy row states, else the one its own words name ("until the start of its next turn"), which keeps them on the
        # affected creature instead of the caster.
        carried = {k: v for k, v in eff.items() if k in ("duration", "expires_on")}
        if not carried.get("expires_on"):
            carried["expires_on"] = str(stated_expiry(ctx, spec, subject, condition=True) or "")
        held_modifiers = set(subject.modifiers)
        run_effects(replace(ctx, targets=[subject], target=subject), [{**carried, **row} for row in rows])
        # Whatever those rows made belongs to this Drowsy, so it is recorded on it and ends with it: a Drowsy that
        # replaces this one takes these consequences with it. Instance ids only, so a saved fight keeps them.
        consequences = sorted((set(subject.conditions) - before) - {mine}) + sorted(set(subject.modifiers) - held_modifiers)
        if consequences:
            subject.conditions[mine].data = {**subject.conditions[mine].data, "consequences": consequences}


def asleep(creature: Any) -> bool:
    return any(c.condition_id in (SLEEP, "condition:typed.unconscious") for c in creature.conditions.values())


@effect("plant_dream_seed")
def plant_dream_seed(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import block_mark

    for subject in _subjects(ctx):
        long = subject.team_id == ctx.actor.team_id or asleep(subject)
        duration = {"kind": "hours", "amount": 1} if long else {"kind": "until_start_of_your_next_turn"}
        block_mark(replace(ctx, targets=[subject], target=subject), {"type": "mark", "mark": SEED, "applies_to": "target", "duration": duration,
                                                                     "evidence": str(eff.get("evidence") or "plant Dream Seed")})


@effect("dream_seed")
def dream_seed(ctx: Any, eff: dict[str, Any]) -> None:
    """"Willing or Sleeping Creature: Apply Dream Seed automatically. The Dream Seed lasts for 1 hour. Awake Unwilling Creature: The
    target makes a Wisdom saving throw. Failed Save: Apply Dream Seed until the start of your next turn" and Drowsy Thought's "it also
    becomes Drowsy until the start of your next turn"."""
    from ..typed_executor import run_effects

    for subject in _subjects(ctx):
        one = replace(ctx, targets=[subject], target=subject)
        if subject.team_id == ctx.actor.team_id or asleep(subject):
            plant_dream_seed(one, eff)
            continue
        run_effects(one, [{"type": "save", "ability": "wis", "applies_to": "target", "evidence": "The target makes a Wisdom saving throw.",
                           "on_fail": [{"type": "plant_dream_seed", "evidence": "Failed Save: Apply Dream Seed until the start of your next turn."},
                                       {"type": "drowsy", "duration": "until_start_of_your_next_turn",
                                        "evidence": "Drowsy Thought: it also becomes Drowsy until the start of your next turn."}],
                           "on_success": []}])


@effect("seed_or_drowsy")
def seed_or_drowsy(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker read by candidate_allowed."""


@effect("dream_passage")
def dream_passage(ctx: Any, eff: dict[str, Any]) -> None:
    """Marker read by candidate_allowed."""


def _typed(action: Any) -> dict[str, Any]:
    return ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}


def _has(typed: dict[str, Any], name: str) -> bool:
    return any(isinstance(row, dict) and row.get("type") == name for row in typed.get("effects") or [])


def _bears_seed(owner: Any, creature: Any) -> bool:
    from ..typed_executor import mark_condition_id

    return any(c.condition_id == mark_condition_id(SEED, owner.entity_id) for c in creature.conditions.values())


def _dream_zone(engine: Any, owner: Any, spot: Any) -> bool:
    for zone in engine.state.zones.values():
        if not zone.active or zone.owner_id != owner.entity_id or not any(cell.x == spot.x and cell.y == spot.y for cell in zone.affected_cells):
            continue
        typed = _typed(engine.action_catalog.get(zone.source_definition_id))
        if (zone.trigger_profile or {}).get("name") == "Dreamscape" or str(typed.get("source") or typed.get("option_of") or "") in DOMAINS:
            return True
    return False


@hook("candidate_allowed")
def dreams_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from ..typed_executor import condition_rules

    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", None) or ()]
    reach = min([int(row["target_within_ft"]) for row in condition_rules(actor) if row.get("target_within_ft")] or [0])
    if reach and any(t is not None and t.entity_id != actor.entity_id and engine._distance_actor_to_actor(actor, t) > reach for t in targets):
        return False  # "cannot willingly target creatures more than 10 feet away"
    typed = _typed(action)
    if not typed or typed.get("sphere") != DREAMS:
        return None
    if _has(typed, "seed_or_drowsy") and not (targets and all(t is not None and (_bears_seed(actor, t) or any(c.condition_id == DROWSY for c in t.conditions.values()))
                                                             for t in targets)):
        return False
    if _has(typed, "dream_passage") and getattr(candidate, "destination", None) is not None:
        return _dream_zone(engine, actor, candidate.destination)
    return None


@hook("save")
def sheltered(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Lucid Veil / Symbolic Shelter: "Allies inside the Dreamscape gain: Advantage on saving throws against ..." (the zone records the
    talents shaping it)."""
    against = {str(name).lower() for name in named or ()}
    if not against:
        return None
    for zone in ctx.engine.state.zones.values():
        owner = ctx.engine.state.actors.get(zone.owner_id or "")
        profile = zone.trigger_profile or {}
        if not zone.active or owner is None or owner.team_id != subject.team_id or profile.get("name") != "Dreamscape":
            continue
        if not any(cell.x == subject.position.x and cell.y == subject.position.y for cell in zone.affected_cells):
            continue
        if any(against & SHELTERS.get(str(talent), set()) for talent in profile.get("talents") or []):
            return {"modes": ["ADVANTAGE"]}
    return None


@hook("event")
def sleeper_wakes(engine: Any, event_type: str, kwargs: Any) -> None:
    """Dream Sleep: "awakens if it takes damage unless the talent says otherwise"."""
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = (kwargs or {}).get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    for target_id in (kwargs or {}).get("target_ids") or ():
        sleeper = engine.state.actors.get(target_id)
        if sleeper is not None and any(c.condition_id == SLEEP for c in sleeper.conditions.values()):
            _remove(engine, sleeper, SLEEP, str((kwargs or {}).get("source_definition_id") or "dream_sleep"))


@hook("attack_damage")
def sovereign_needle(ctx: Any, dice: Any) -> Any:
    """Dream-Sovereign Incarnation: "Dream Needle damage becomes 6d10" while it lasts."""
    if dice is None or ctx.typed.get("source") != NEEDLE or not any(c.condition_id == SOVEREIGN for c in ctx.actor.conditions.values()):
        return None
    from ..gate2_runtime_models import DiceSpec

    return DiceSpec(count=6, sides=10, modifier=int(getattr(dice, "modifier", 0) or 0))


@hook("turn_start_choice")
def sovereign_seed(engine: Any, actor: Any) -> None:
    """Dream-Sovereign Incarnation: "plant Dream Seed on one visible creature within 60 feet at the start of each of your turns without
    spending an Action" (asked of a player; the AI picks the nearest foe)."""
    stance = next((c for c in actor.conditions.values() if c.condition_id == SOVEREIGN), None)
    if stance is None or not actor.active or stance.source_definition_id not in engine.action_catalog:
        return
    from .. import zones

    near = sorted((c for c in engine.state.actors.values() if c.active and c.entity_id != actor.entity_id and engine._distance_actor_to_actor(actor, c) <= 60
                   and not zones.hidden_from(engine, actor, c)),
                  key=lambda c: (c.team_id == actor.team_id, engine._distance_actor_to_actor(actor, c), c.entity_id))
    if not near:
        return
    from ..typed_executor import Context
    from .needle import CHOICE, ask, checkpoint_id

    ids = [c.entity_id for c in near]
    picked = ask(engine, None, checkpoint_id(engine, "DREAM_SOVEREIGN_SEED", actor.entity_id), actor, CHOICE + "dream_sovereign_seed", ids,
                 labels={c.entity_id: f"Plant a Dream Seed on {c.display_name}" for c in near}, allow_decline=True, name="Dream-Sovereign Incarnation",
                 prompt="Dream-Sovereign Incarnation: plant a Dream Seed on one visible creature within 60 feet?")
    if not picked:
        return
    chosen = engine.state.actors[picked[0]]
    action = engine.action_catalog[stance.source_definition_id]
    plant_dream_seed(Context(engine, actor, action, None, copy.deepcopy(_typed(action)), [chosen], chosen, {}), {"evidence": "Dream-Sovereign Incarnation"})


@hook("compile_actions")
def dream_seed_actions(info: dict[str, Any]) -> list[Any] | None:
    if DREAMS not in (info.get("spheres") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    def action(key: str, name: str, kind: str, description: str) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{key}", display_name=name, owner_id=info["actor_id"], economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind=kind, range_ft=60,
            parameters={"typed": {"effects": [{"type": "dream_seed", "evidence": "Plant a symbolic impression in one creature's subconscious."}],
                                  "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": "DREAMS_BASE_DREAM_SEED", "sphere": DREAMS},
                        "expected_damage": 0, "description": description})

    return [action("dream_seed", "Dream Seed", "HOSTILE_ENTITY",
                   "Dream Seed (60 feet): an awake unwilling creature makes a Wisdom save; on a failure your Dream Seed lasts until the start of your "
                   "next turn and it is Drowsy (Drowsy Thought). A sleeping creature takes the Seed for 1 hour, no save."),
            action("dream_seed_willing", "Dream Seed: willing creature", "ALLY_OR_SELF",
                   "Dream Seed on a willing creature (you or an ally within 60 feet), no save; it lasts 1 hour.")]
