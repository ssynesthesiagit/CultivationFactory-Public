"""Wax sphere: the printed lines that were only shown to the GM (riders lane 5, 2026-09-29).

Rules text (authority/typed_mechanics/rules_text.json, the owner's Wax entries) is the source; where it is silent this module
says which default it took.  Nothing here changes a saved fight's engine files: it is compile_actions / candidate_allowed /
event / after_save hooks and effects, all keyed off compiled rows.

* **Kindle Wax** (Bonus Action, 0 CP, range 60 ft) had no action at all.  "You burn one Wax form, Wax Seal, candle, or wax object
  you created within range.  The chosen wax is consumed."  A Wax Seal is the ``Wax Seal`` mark Press Seal leaves on a creature
  (authority override on TAL_WAX_PRESS_SEAL); a Wax form is one of the zones Mold Wax made (Soft Spread / Set Shape).  Candles and
  wax objects are not tracked as things in this engine (blocked: tracked candles/objects -- see docs), so they are not offered.
  Releases: Candleflare (Dex save, 1d6 + PB fire, half on a success) at one creature within 5 feet of the kindled wax; Release
  Seal (ally: PB temporary hit points, enemy: PB fire damage) on a sealed creature; Smoke Puff (a 5-foot-radius smoke, Lightly
  Obscured until the start of your next turn; Smoke Wick: 10 feet, Heavily Obscured until the start of your next turn, then Lightly
  Obscured until the end of your next turn).  Mark the Wick is a GM reading and stays one.
  Range is measured to the wax. Candleflare's creature may be another 5 feet away; smoke is centered on the consumed wax.
* **Searing Seal** (Wick, 1 CP): "When you kindle a Wax Seal on a hostile creature, you may spend 1 CP to make it sear" -- each
  hostile-sealed release also comes in a "+ Searing Seal" form: Con save, 2d8 fire and no Reactions until the start of its next
  turn, half and no Reaction loss on a success.
* **Hundred-Seal Conflagration** asks which owned seals to ignite, then up to three creatures bearing or adjacent to those seals.
  Only the selected seals are consumed. Player decisions use the shared bounded-choice transport.
* **Court of Ten Thousand Candles**: "The first time each round an enemy fails a saving throw against one of your Wax talents, you
  may place a Wax Seal on that enemy without spending additional CP" -- while the Court (its zone) stands and the enemy is in it, the
  its owner may decline the first qualifying opportunity each combat round.
* **Soft Spread's "knocked Prone there"** (Adhesive Pool): a zone moment ``prone`` fires for hostile creatures knocked Prone inside
  a zone (combat/zones.py ``_fire``), so a reviewed zone trigger can list ``"prone"`` in ``on``.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from . import effect, hook
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..typed_executor import bears_mark, mark_condition_id, run_effects

PRESS_SEAL = "TAL_WAX_PRESS_SEAL"
MOLD_WAX = "TAL_WAX_MOLD_WAX"
SEARING = "TAL_WAX_SEARING_SEAL"
SMOKE_WICK = "TAL_WAX_SMOKE_WICK"
HUNDRED = "TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"
COURT = "TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"
SEAL = "Wax Seal"
RANGE_FT = 60
PRONE = "condition:typed.prone"
COURT_ONCE = "Wax Court Seal Placed This Round"
SEAL_LINK = "condition:typed.wax_seal_link"


# ------------------------------------------------------------------------------------------------------- wax in the field
def _forms(engine: Any, owner_id: str) -> list[Any]:
    """The Wax forms ``owner_id`` made with Mold Wax that still stand."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.owner_id == owner_id and MOLD_WAX in str(zone.source_definition_id)]


def _form_distance(engine: Any, zone: Any, creature: Any) -> int:
    return min((engine._distance_actor_to_cell(creature, cell) for cell in zone.affected_cells), default=999)


def _wax_near(engine: Any, owner: Any, target: Any, reach: int = 5) -> list[tuple[str, Any]]:
    """Wax of ``owner`` within ``reach`` feet of ``target``, the target's own seal first: ("seal", bearer) / ("form", zone)."""
    found: list[tuple[str, Any]] = []
    if bears_mark(target, owner.entity_id, SEAL) and engine._distance_actor_to_actor(owner, target) <= RANGE_FT:
        found.append(("seal", target))
    for other in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id):
        if other is not target and other.active and bears_mark(other, owner.entity_id, SEAL) \
                and engine._distance_actor_to_actor(owner, other) <= RANGE_FT \
                and engine._distance_actor_to_actor(target, other) <= reach:
            found.append(("seal", other))
    for zone in _forms(engine, owner.entity_id):
        if _form_distance(engine, zone, target) <= reach and _form_distance(engine, zone, owner) <= RANGE_FT:
            found.append(("form", zone))
    return found


def consume_wax(ctx: Any, kind: str, thing: Any) -> None:
    """Consume one exact owned seal/form and eventfully clean its linked effects."""
    from .. import zones

    if kind == "seal":
        ctx.engine._remove_condition(thing, mark_condition_id(SEAL, ctx.actor.entity_id), ctx.source)
        clean_seal_links(ctx.engine, thing)
    elif thing.active:
        zones.remove(ctx.engine, thing, "KINDLED")


_consume = consume_wax  # retained spelling for existing callers in this module


def _owned_wax(engine: Any, owner: Any) -> list[tuple[str, Any]]:
    """All represented wax within Kindle range, without requiring a nearby creature."""
    seals = [("seal", actor) for actor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
             if actor.active and bears_mark(actor, owner.entity_id, SEAL)
             and engine._distance_actor_to_actor(owner, actor) <= RANGE_FT]
    return seals + [("form", zone) for zone in _forms(engine, owner.entity_id)
                    if _form_distance(engine, zone, owner) <= RANGE_FT]


def clean_seal_links(engine: Any, actor: Any) -> None:
    """Remove only modifiers linked to an ended seal, including other owners' independent links."""
    for link in list(actor.conditions.values()):
        if link.condition_id != SEAL_LINK or link.data.get("seal_id") in actor.conditions:
            continue
        modifier = actor.modifiers.get(link.data.get("modifier_id"))
        if modifier is not None and modifier.source_actor_id == link.source_actor_id \
                and modifier.source_definition_id == link.source_definition_id:
            del actor.modifiers[modifier.modifier_id]
            engine._append_event("MODIFIER_REMOVED", link.source_definition_id, actor_id=link.source_actor_id,
                                 target_ids=(actor.entity_id,), payload={"modifier_id": modifier.modifier_id, "reason": "SEAL_ENDED"})
        if actor.conditions.pop(link.instance_id, None) is not None:
            engine._append_event("CONDITION_REMOVED", link.source_definition_id, actor_id=link.source_actor_id,
                                 target_ids=(actor.entity_id,), payload={"condition_id": SEAL_LINK, "instance_id": link.instance_id})


@effect("wax_clinging_seal")
def clinging_seal(ctx: Any, eff: dict[str, Any]) -> None:
    """New Press Seal rows bind their speed modifier to their exact Wax Seal instance.

    Old saved rows have no link and retain their existing behavior. Link data is
    strings only; every creation/removal is evented for commit/reload and replay.
    """
    target = ctx.target
    if target is None:
        return
    if bears_mark(target, ctx.actor.entity_id, SEAL):
        _consume(ctx, "seal", target)
    before = set(target.modifiers)
    run_effects(ctx, copy.deepcopy(eff.get("effects") or []))
    held = next((c for c in target.conditions.values() if c.condition_id == mark_condition_id(SEAL, ctx.actor.entity_id)), None)
    if held is None:
        return
    for mid in set(target.modifiers) - before:
        modifier = target.modifiers[mid]
        if modifier.source_actor_id == ctx.actor.entity_id and modifier.source_definition_id == ctx.source:
            ctx.engine._apply_condition(target, SEAL_LINK, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"seal_id": held.instance_id, "modifier_id": mid})


@hook("event")
def seal_removed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "CONDITION_REMOVED":
        for actor in engine.state.actors.values():
            clean_seal_links(engine, actor)


# --------------------------------------------------------------------------------------------------------------- actions
def _fire(dice: dict[str, int] | None, formula: str = "pb") -> dict[str, Any]:
    return {"type": "damage", "applies_to": "target", "dice": dice, "flat": 0, "formula": formula, "damage_types": ["fire"]}


def _save(ability: str, on_fail: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "save", "ability": ability, "dc": "technique_save_dc", "applies_to": "target", "on_fail": on_fail,
            "on_success": [{"type": "half_damage"}]}


SEAR = [_save("con", [
    {"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "flat": 0, "formula": "none", "damage_types": ["fire"]},
    {"type": "condition", "applies_to": "target", "condition": "reaction_denied", "expires_on": "START_OF_TARGET_NEXT_TURN"}])]


def _aimed(*effects: dict[str, Any]) -> dict[str, Any]:
    return {"type": "wax_aimed", "effects": list(effects)}  # see the wax_aimed effect


def _smoke(wick: bool) -> list[dict[str, Any]]:
    radius = 10 if wick else 5
    if not wick:
        return [{"type": "wax_smoke", "terrain": "wax smoke", "radius_ft": radius, "edge": "start"}]
    return [{"type": "wax_smoke", "terrain": "dense wax smoke", "radius_ft": radius, "edge": "start"},
            {"type": "wax_smoke", "terrain": "wax smoke", "radius_ft": radius, "edge": "end"}]


@effect("wax_smoke")
def smoke_deadline(ctx: Any, eff: dict[str, Any]) -> None:
    """Smoke's next owner turn start/end, persisted as integer/string zone metadata."""
    from .. import zones

    before = set(ctx.engine.state.zones)
    run_effects(ctx, [{**eff, "type": "terrain_patch", "duration": None,
                      **({"center": ctx.damage_cache["_wax_center"]} if ctx.damage_cache.get("_wax_center") else {})}])
    for zone in zones.typed_zones(ctx.engine):
        if zone.zone_id in before:
            continue
        zone.trigger_profile.update(wax_smoke_edge=eff["edge"], wax_smoke_turn=int(ctx.actor.turns_started) + 1)
        ctx.engine._append_event("ZONE_CREATED", ctx.source, actor_id=ctx.actor.entity_id,
                                payload={"zone": zone.model_dump(mode="json")})


def expire_smoke(engine: Any, actor: Any, edge: str, *, nominal: bool = False) -> None:
    from .. import zones
    from .effect_durations import custom_turn_due

    for zone in zones.typed_zones(engine):
        if zone.owner_id == actor.entity_id and zone.trigger_profile.get("wax_smoke_edge") == edge \
                and custom_turn_due(actor, zone.trigger_profile["wax_smoke_turn"], zone.per_turn_triggered, "wax_smoke", nominal=nominal):
            zones.remove(engine, zone, "DURATION_ENDED")


@hook("turn_start")
def smoke_start(engine: Any, actor: Any) -> None:
    expire_smoke(engine, actor, "start")


@hook("turn_end")
def smoke_end(engine: Any, actor: Any) -> None:
    expire_smoke(engine, actor, "end")


@hook("nominal_slot_boundary")
def nominal_smoke(engine: Any, actor: Any, checkpoint: str) -> None:
    expire_smoke(engine, actor, "start" if checkpoint == "START_OF_TURN" else "end", nominal=True)


@hook("compile_actions")
def wax_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS

    owned = set(info["owned_ids"])
    if PRESS_SEAL not in owned:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    out: list[Any] = []

    def make(key: str, name: str, effects: list[dict[str, Any]], target: str, cost: int = 0, needs_seal: bool = False,
             economy: Any = EconomyKind.BONUS_ACTION, range_ft: int = RANGE_FT, **extra: Any) -> None:
        params: dict[str, Any] = {"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"},
                                            "riders": [], "source": "tianxia.sphere.wax"}, "expected_damage": 0, **extra}
        if needs_seal:
            params["target_requires_condition"] = mark_condition_id(SEAL, actor_id)
        pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.wax.{key}", display_name=name, owner_id=actor_id,
            economy=economy, resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
            costs=((pool, cost),) if cost else (), parameters=params))

    # Press Seal on a willing creature: "A willing creature ... is sealed automatically" (the printed action asks a foe's Dexterity save).
    make("press_seal_ally", "Seal a Willing Creature (Press Seal)", [{"type": "choose_willing", "target_only": True,
         "allow_hostile_target": True, "range_ft": 30,
         "effects": [{"type": "mark", "mark": SEAL, "applies_to": "target", "duration": {"kind": "one_minute"},
                     "evidence": "A willing creature ... is sealed automatically."}]}],
         "ALLY_OR_SELF", 1, economy=EconomyKind.ACTION, range_ft=30)
    kindle = {"type": "wax_kindle"}
    flare = [kindle, _save("dex", [_fire({"count": 1, "sides": 6})])]
    seal_enemy = [kindle, _fire(None)]
    seal_ally = [_aimed(kindle, {"type": "temp_hp", "applies_to": "target", "flat": 0, "formula": "pb"})]
    smoke = [kindle, *_smoke(SMOKE_WICK in owned)]
    smoke_ally = [_aimed(kindle, *_smoke(SMOKE_WICK in owned))]
    # The owner's printed Kindle Wax line, so no release button reaches the table saying nothing. Every one of
    # them costs a Bonus Action, burns one wax of yours within 60 feet and consumes it.
    KINDLE = ("Costs a Bonus Action. Burn one Wax form or Wax Seal that you created within 60 feet; the wax you choose is "
              "consumed and cannot be used again.")
    SEARING_NOTE = (" Spend 1 Cultivation Point as well: the target then makes a Constitution saving throw and takes 2d8 fire "
                    "damage, and cannot use Reactions until the start of its next turn (half damage and it keeps its "
                    "Reaction on a success).")
    CANDLEFLARE = KINDLE + (" One creature within 5 feet of the kindled wax makes a Dexterity saving throw and takes 1d6 fire "
                            "damage plus your Proficiency Bonus, or half as much on a success.")
    RELEASE_SEAL_ENEMY = KINDLE + (" The target must bear one of your Wax Seals and takes fire damage equal to your Proficiency "
                                   "Bonus, then the Seal is consumed.")
    RELEASE_SEAL_ALLY = KINDLE + (" The target must bear one of your Wax Seals and gains Temporary Hit Points equal to your "
                                  "Proficiency Bonus, then the Seal is consumed.")
    SMOKE_PUFF = KINDLE + (f" A {10 if SMOKE_WICK in owned else 5}-foot-radius sphere of smoke appears centred on the kindled wax: "
                           f"it is {'Heavily Obscured until the start of your next turn, then Lightly Obscured until the end of that turn' if SMOKE_WICK in owned else 'Lightly Obscured until the start of your next turn'}.")
    make("kindle.candleflare", "Kindle Wax: Candleflare", flare, "HOSTILE_ENTITY", range_ft=RANGE_FT + 5,
         description=CANDLEFLARE)
    make("kindle.candleflare_ally", "Kindle Wax: Candleflare (ally or self)", [_aimed(*flare)],
         "ALLY_OR_SELF", range_ft=RANGE_FT + 5, description=CANDLEFLARE)
    make("kindle.release_seal", "Kindle Wax: Release Seal", seal_enemy, "HOSTILE_ENTITY", needs_seal=True,
         description=RELEASE_SEAL_ENEMY)
    make("kindle.release_seal_ally", "Kindle Wax: Release Seal (ally)", seal_ally, "ALLY_OR_SELF", needs_seal=True,
         description=RELEASE_SEAL_ALLY)
    make("kindle.smoke_puff", "Kindle Wax: Smoke Puff", smoke, "HOSTILE_ENTITY", range_ft=RANGE_FT + 5,
         description=SMOKE_PUFF)
    make("kindle.smoke_puff_ally", "Kindle Wax: Smoke Puff (ally)", smoke_ally, "ALLY_OR_SELF", needs_seal=True,
         description=SMOKE_PUFF)
    make("kindle.smoke_puff_wax", "Kindle Wax: Smoke Puff (choose wax)",
         [_aimed({"type": "wax_kindle", "wax_first": True}, *_smoke(SMOKE_WICK in owned))], "SELF", description=SMOKE_PUFF)
    if SEARING in owned:
        make("kindle.candleflare_searing", "Kindle Wax: Candleflare + Searing Seal (1 CP)", [*flare, *SEAR], "HOSTILE_ENTITY", 1, True,
             description=CANDLEFLARE + SEARING_NOTE)
        make("kindle.release_seal_searing", "Kindle Wax: Release Seal + Searing Seal (1 CP)", [*seal_enemy, *SEAR], "HOSTILE_ENTITY", 1, True,
             description=RELEASE_SEAL_ENEMY + SEARING_NOTE)
        make("kindle.smoke_puff_searing", "Kindle Wax: Smoke Puff + Searing Seal (1 CP)", [*smoke, *SEAR], "HOSTILE_ENTITY", 1, True,
             description=SMOKE_PUFF + SEARING_NOTE)
    # compile_actions receives the original catalog, so its willing hook cannot
    # see actions supplied by this hook. Reuse its public opt-in path explicitly.
    from .willing_targets import willing_non_allies

    return out + (willing_non_allies({"actions": out}) or [])


@hook("candidate_allowed")
def wax_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Creature releases need nearby owned wax; wax-first Smoke Puff needs only
    owned wax in range. Hundred-Seal needs a creature bearing/beside a seal."""
    source = str(getattr(action, "source_definition_id", ""))
    if source.endswith(".wax.kindle.smoke_puff_wax"):
        return bool(_owned_wax(engine, actor))
    if ".wax.kindle." in source and ("candleflare" in source or not source.endswith("_ally")) \
            and "release_seal" not in source and "_searing" not in source:
        target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        return bool(target is not None and _wax_near(engine, actor, target))
    if source.endswith(f".{HUNDRED}"):
        target = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        return bool(target is not None and _seal_beside(engine, actor, target))
    return None


@hook("source_unavailable")
def wax_kindle_unavailable(engine: Any, actor: Any, action: Any) -> str | None:
    """The compact-menu header for a Kindle Wax release: no owned wax in Kindle range, so no creature can be near it."""
    source = str(getattr(action, "source_definition_id", ""))
    if ".wax.kindle." not in source or "release_seal" in source or "_searing" in source:
        return None
    if source.endswith(".wax.kindle.smoke_puff_wax") or _owned_wax(engine, actor):
        return None
    return "You have no wax within reach to kindle."


@effect("wax_aimed")
def wax_aimed(ctx: Any, eff: dict[str, Any]) -> None:
    """Run ``effects`` on the creature the ability was aimed at, the caster itself when an ally-or-self ability is aimed at its user
    (the executor leaves the target empty then, and a mark or a terrain patch has nobody to land on)."""
    who = ctx.target or (ctx.targets[0] if ctx.targets else ctx.actor)
    run_effects(replace(ctx, target=who, targets=[who]), [dict(row) for row in eff.get("effects") or []])


@effect("wax_kindle")
def wax_kindle(ctx: Any, eff: dict[str, Any]) -> None:
    """Consume the selected owned wax, optionally without a creature recipient."""
    wax_first = bool(eff.get("wax_first"))
    if ctx.target is None and not wax_first:
        return
    near = _owned_wax(ctx.engine, ctx.actor) if wax_first else _wax_near(ctx.engine, ctx.actor, ctx.target)
    if "release_seal" in ctx.source or ctx.source.endswith("_searing"):
        near = [(kind, thing) for kind, thing in near if kind == "seal" and thing is ctx.target]
    if not near:
        ctx.rider("Kindle Wax: no wax of yours is beside that creature.")
        return
    from .needle import ask, checkpoint_id

    options = {f"{kind}:{thing.entity_id if kind == 'seal' else thing.zone_id}": (kind, thing) for kind, thing in near}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "wax_kindle", ctx.source), ctx.actor,
                 "choice:needle.wax_kindle", list(options),
                 labels={key: f"Wax Seal on {thing.display_name}" if kind == "seal" else "Mold Wax form"
                         for key, (kind, thing) in options.items()},
                 name="Kindle Wax", feature_id=PRESS_SEAL,
                 prompt=f"{ctx.actor.display_name} uses {ctx.action.display_name}"
                        + ("" if wax_first else f" on {ctx.target.display_name}") + ": choose the wax to consume.")
    if chosen:
        kind, thing = options[chosen[0]]
        center = thing.position if kind == "seal" else thing.center
        ctx.damage_cache["_wax_center"] = {"x": int(center.x), "y": int(center.y)}
        _consume(ctx, kind, thing)


# ------------------------------------------------------------------------------------------- Hundred-Seal Conflagration
def _seal_beside(engine: Any, owner: Any, creature: Any) -> bool:
    """A creature bearing one of the owner's seals, or standing beside one (within 5 feet), within range of the owner."""
    return any(kind == "seal" and engine._distance_actor_to_actor(owner, seal) <= RANGE_FT
               for kind, seal in _wax_near(engine, owner, creature))


@effect("wax_hundred_seals")
def wax_hundred_seals(ctx: Any, eff: dict[str, Any]) -> None:
    """Choose owned seals in range and up to three creatures beside those exact seals."""
    from .needle import ask, checkpoint_id

    engine, me = ctx.engine, ctx.actor
    seals = [actor for actor in engine.state.actors.values()
             if actor.active and bears_mark(actor, me.entity_id, SEAL) and engine._distance_actor_to_actor(me, actor) <= RANGE_FT]
    from .. import stealth
    from . import ai_controlled
    if ai_controlled(engine, me):
        seals = [actor for actor in seals if actor.team_id != me.team_id and stealth.sees(engine, me, actor)]
    selected = ask(engine, ctx.intent, checkpoint_id(engine, "wax_ignite", ctx.source), me,
                   "choice:needle.wax_ignite", [a.entity_id for a in seals], minimum=0, maximum=len(seals),
                   allow_decline=True, preferred=[a.entity_id for a in seals],
                   labels={a.entity_id: f"Wax Seal on {a.display_name}" for a in seals}, name="Hundred-Seal Conflagration",
                   feature_id=HUNDRED, target_id=getattr(ctx.target, "entity_id", None),
                   prompt=f"{me.display_name} uses Hundred-Seal Conflagration: choose which Wax Seals to ignite.")
    seals = [a for a in seals if a.entity_id in selected]
    if not seals:
        return
    available = sorted((a for a in engine.state.actors.values() if a.active and
                        any(engine._distance_actor_to_actor(a, seal) <= 5 for seal in seals)),
                       key=lambda a: (a is not ctx.target, a.team_id == me.team_id, a.entity_id))
    selected = ask(engine, ctx.intent, checkpoint_id(engine, "wax_burst_targets", ctx.source), me,
                   "choice:needle.wax_burst_targets", [a.entity_id for a in available], minimum=0, maximum=3,
                   allow_decline=True, preferred=[a.entity_id for a in available if a.team_id != me.team_id][:3],
                   automatic_options=[a.entity_id for a in available if a.team_id != me.team_id and stealth.sees(engine, me, a)],
                   labels={a.entity_id: a.display_name for a in available}, name="Hundred-Seal Conflagration", feature_id=HUNDRED,
                   prompt=f"{me.display_name} uses Hundred-Seal Conflagration: choose up to three creatures beside the selected seals.")
    chosen = [a for a in available if a.entity_id in selected]
    for creature in chosen:
        # A carried seal occupies its bearer's square: the map has no direction
        # away from that same square. Do not substitute the caster as an anchor.
        nearest = min(seals, key=lambda seal: (engine._distance_actor_to_actor(creature, seal), seal.entity_id), default=None)
        anchor = nearest.position
        effects = copy.deepcopy(eff.get("effects") or [])
        if nearest is creature:
            for row in effects:
                if row.get("type") == "save":
                    row["on_fail"] = [{"type": "rider", "evidence": "Hundred-Seal Conflagration: GM chooses the 10-foot push direction away from a seal carried on this creature."}
                                      if part.get("type") == "forced_movement" else part for part in row.get("on_fail") or []]
        sub = replace(ctx, target=creature, targets=[creature], typed={**ctx.typed, "_area_centre": (anchor.x, anchor.y)})
        run_effects(sub, effects)
    for seal in seals:
        _consume(ctx, "seal", seal)


# ---------------------------------------------------------------------------------------------------- Court free seal
@hook("after_save")
def court_seal(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine, me = ctx.engine, ctx.actor
    if not failed or subject.team_id == me.team_id or not subject.active or "TAL_WAX_" not in str(ctx.source) and ".wax." not in str(ctx.source):
        return
    from .. import zones

    court = [zone for zone in zones.typed_zones(engine) if zone.owner_id == me.entity_id and COURT in str(zone.source_definition_id)]
    if not court or not any(zones._inside(engine, subject, zone) for zone in court):
        return
    if me.turn_flags.get("wax_court_round_used") == engine.state.round_number:
        return  # "the first time each round"
    from .needle import ask, checkpoint_id
    me.turn_flags["wax_court_round_used"] = int(engine.state.round_number)
    chosen = ask(engine, ctx.intent or getattr(engine, "_active_intent", None), checkpoint_id(engine, "wax_court", ctx.source), me,
                 "choice:needle.wax_court", ["seal"], allow_decline=True, labels={"seal": f"Place Wax Seal on {subject.display_name}"},
                 name="Court of Ten Thousand Candles", feature_id=COURT, target_id=subject.entity_id,
                 prompt=f"Court of Ten Thousand Candles: {subject.display_name} failed a save against {ctx.action.display_name}; place a free Wax Seal?")
    if not chosen:
        return
    sub = replace(ctx, target=subject, targets=[subject])
    run_effects(sub, [{"type": "mark", "mark": COURT_ONCE, "applies_to": "self", "duration": {"kind": "until_start_of_your_next_turn"}},
                      {"type": "mark", "mark": SEAL, "applies_to": "target", "duration": {"kind": "one_minute"},
                       "evidence": "Court of Ten Thousand Candles: a free Wax Seal on an enemy that failed a save against a Wax talent"}])


# ------------------------------------------------------------------------------------------------------ knocked Prone
@hook("event")
def prone_moment(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A creature knocked Prone inside a zone: the zone's ``prone`` moment (Adhesive Pool: "or is knocked Prone there")."""
    if event_type != "CONDITION_APPLIED" or (kwargs.get("payload") or {}).get("condition_id") != PRONE:
        return
    from .. import zones

    for target_id in kwargs.get("target_ids") or ():
        creature = engine.state.actors.get(target_id)
        if creature is None or not creature.active:
            continue
        for zone in zones.typed_zones(engine):
            if MOLD_WAX in zone.source_definition_id and zone.trigger_profile.get("triggers") and zones._inside(engine, creature, zone):
                zones._fire(engine, zone, creature, "prone")
