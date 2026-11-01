"""Death riders the engine can resolve (automation lane AUTO22, 2026-10-04; owner: "automate everything").

Printed text: the owner's Sphere Compendium, "Sphere of Death" (APP/authority/typed_mechanics/rules_text.json, with
owner_text_edits.json on top).  Each rule is quoted above the hook that plays it.

Legacy passive riders: a character that learned one of these talents carries one compiled passive row of block ``auto22_death``
per talent (combat/rules/feature_blocks.d/riders_auto22.json, compiled by ``compile_rows`` below and read with
combat/ext/passive_rows.row_of).  Every hook returns at once without that row, so a creature without the talent, and a
fight saved before this change, behave exactly as before.

Mark for the Grave   "The first time each turn the marked creature takes Necrotic damage from you or one of your Death
                     servants, add your Proficiency Bonus to one damage roll."  The Grave Mark itself and the
                     Disadvantage on the marked creature's first death saving throw are ordinary typed rows; this is the
                     damage rider.  One gate, owned by the mark's CASTER and counted on the marked creature, is what
                     "the first time each turn" means, so any number of qualifying rolls that turn -- the caster's own
                     second technique, a different Death servant's attack -- pays it once.  It joins that one creature's
                     damage roll before the target's defenses (``attack_damage_bonus`` for a typed attack's own packet,
                     ``damage_roll_bonus`` for a save or a single-target effect, ``deal_bonus`` for a roll an area shares
                     between several creatures), and spends the executor's own turn gate
                     (``on_hit_turn_key``/``spend_on_hit_rider``), so a roll that carries it cannot also fire it as a
                     separate packet, and a miss costs nothing.  Eligibility reads the roll's RESOLVED damage type (an
                     ordinary Corpse Servant keeps its Necrotic type in its weapon, not in a printed damage row, and a
                     row printed "Radiant or Necrotic, your choice" counts when Necrotic is the type chosen) and
                     requires the damage to come from that caster or from one of ITS Death servants, never from another
                     summon it happens to command and never from another caster's mark.
Soul Hook            "Its Speed is reduced to 0, and it cannot willingly move more than 10 feet from the space it
                     occupied when it failed the save."  The Speed reduction and the repeated Charisma save are typed;
                     the chain's reach is not, so a voluntary step that would carry the hooked creature past the boundary
                     stops at it (``movement_attempt``, the seam boundary rules use).  Forced movement and teleportation
                     do not pass that seam.  The square it was hooked at is two integers on the creature's own Soul Hook
                     condition, so a saved fight reloads the same chain.
Court of the Ninth Grave
                     "Your Death servants inside the Domain may move through nonmagical Difficult Terrain without extra
                     movement."  Published SQUARE BY SQUARE while a servant of this Court stands in the caster's own
                     Domain, through the ordinary ``difficult_exempt`` query (combat/motion.py exempt_cells, read by
                     combat/zones.py difficult_cells and combat/flight.py step_cost).  It is a pure per-step query, so
                     the benefit follows where the servant actually stands -- walking out of the Domain costs again on
                     the next square, walking back in stops costing -- and nothing has to be cleaned up when the
                     Domain ends, the caster falls, or the fight reloads.

Second-pass activated mechanics use newly sealed effects, opt-in flags and an evented Incarnation condition.
Ability-specific decisions stay in this Death plug-in; generic core hooks do not branch on Death ability ids.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .creature_kinds import matches
from .passive_rows import row_of
from .rider_support import area_recipients, remove_instance

BLOCK = "auto22_death"
C = "condition:typed."
GRAVE_MARK = C + "mark.grave_mark"
SOUL_HOOK = C + "death_soul_hook"
COURT_ID = "TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"
#: The whole-creature condition older builds put on a servant of the Domain instead of publishing squares. A fight
#: saved while it stood there still carries the instance; retire_legacy_court_terrain() removes it.
LEGACY_TERRAIN = C + "ignore_difficult"
LEASH_FT = 10
# combat/rules/summons.json gives every Death servant (Corpse Servant, Lesser Corpse Servant, Grave Formation,
# Bone General, Deathless Guard) the command group "death" with the printed name "Death servants".  A Living Painting
# or any other companion carries a different one, so "your Death servants" is that group and nothing wider.
DEATH_GROUP = "death"

# Second-pass mechanics are opt-in through newly sealed typed effects. Retained
# fight catalogs have neither flag, and keep their original behavior.
SOVEREIGN_ID = "TAL_DEATH_DEATH_SOVEREIGN_INCARNATION"
SOVEREIGN = C + "death_sovereign_incarnation"
FREE_HAND = "death_sovereign_free_hand"


def _typed(action: Any) -> dict[str, Any]:
    return ((getattr(action, "parameters", None) or {}).get("typed") or {})


def _sovereign(actor: Any) -> bool:
    return actor is not None and any(c.condition_id == SOVEREIGN for c in actor.conditions.values())


@effect("death_sovereign")
def sovereign_form(ctx: Any, row: dict[str, Any]) -> None:
    """One minute of the printed flight, damage replacement and free Hand use."""
    from .effect_durations import round_token
    ctx.engine._apply_condition(ctx.actor, SOVEREIGN, ctx.source, ctx.actor.entity_id,
                               expires_on=round_token(ctx.engine, 10),
                               data={"label": "Death-Sovereign Incarnation for 1 minute: fly 40 feet and hover; Withering Hand deals 6d10 Necrotic damage; one free use on each of your turns"})


@hook("flight")
def sovereign_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    return {"fly_speed_ft": 40, "flight_hover": True} if _sovereign(actor) else None


@hook("damage_defenses")
def sovereign_physical_defenses(engine: Any, actor: Any, kind: str, typed: Any, source_actor_id: str) -> list[dict[str, Any]]:
    if not _sovereign(actor):
        return []
    return [{"feature_id": SOVEREIGN_ID, "kind": "resistance", "damage_types": ["BLUDGEONING", "PIERCING", "SLASHING"],
             "mundane_only": True}]


@hook("defense_description")
def sovereign_physical_description(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    if not _sovereign(actor):
        return None
    return [{"feature_id": SOVEREIGN_ID, "damage_types": ["BLUDGEONING", "PIERCING", "SLASHING"],
             "note": "only against nonmagical attacks"}]


@hook("attack_damage")
def sovereign_hand_damage(ctx: Any, dice: Any) -> Any:
    if not _sovereign(ctx.actor) or ctx.typed.get("source") not in {"TAL_DEATH_WITHERING_HAND", "TAL_DEATH_ROTTING_GRASP"}:
        return None
    from ..gate2_runtime_models import DiceSpec
    return DiceSpec(count=6, sides=10, modifier=0)


@hook("attack_damage_types")
def sovereign_hand_type(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    if _sovereign(ctx.actor) and ctx.typed.get("source") in {"TAL_DEATH_WITHERING_HAND", "TAL_DEATH_ROTTING_GRASP"}:
        return ["NECROTIC"]
    return None


@hook("compile_actions")
def sovereign_free_hand(info: dict[str, Any]) -> list[Any] | None:
    """Seal the printed ranged Hand mode and free variants of both modes.

    The generic parser's mixed melee/ranged header supplies only the melee row.
    Death's printed alternative is an Action attack within 60 feet. Both modes
    share the original on-hit effects and active Incarnation replacement.
    """
    if "TAL_DEATH_WITHERING_HAND" not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from ..action_variants import choice, cost_delta, extend_variant
    import copy
    out = []
    for action in info["actions"]:
        typed = _typed(action)
        if typed.get("source") != "TAL_DEATH_WITHERING_HAND" or typed.get("applied_modifiers"):
            continue
        modes = [action]
        attacks = [row for row in typed.get("effects") or [] if row.get("type") == "attack"]
        if attacks and all(row.get("attack_kind") == "cultivation_melee" for row in attacks):
            # The base mode is recognized from the printed replacement text.
            # This ranged alternative costs an Action, so explicitly exclude
            # it even though it shares the same source record.
            ranged = copy.deepcopy(action.parameters)
            ranged["replaces_attack"] = 0
            ranged["typed"]["range_ft"] = 60
            for row in ranged["typed"]["effects"]:
                if row.get("type") == "attack":
                    row["attack_kind"] = "cultivation_ranged"
            ranged["description"] = "Use your Action to make a ranged Cultivation Attack against one creature within 60 feet."
            # Mode axis: the same Withering Hand, ranged. Identity is data (base_key = the base's id); the ids and
            # printed names stay as they were.
            mode = extend_variant(action, choice("range", "ranged", "Ranged, 60 feet"))
            mode = mode.model_copy(update={"source_definition_id": action.source_definition_id + ".ranged",
                                           "display_name": action.display_name + " (ranged)",
                                           "range_ft": 60, "parameters": ranged})
            out.append(mode)
            modes.append(mode)
        if SOVEREIGN_ID not in info["owned_ids"]:
            continue
        for mode in modes:
            parameters = copy.deepcopy(mode.parameters)
            parameters["typed"][FREE_HAND] = True
            parameters["description"] = "While Death-Sovereign Incarnation lasts, use Withering Hand once on your turn without spending an Action."
            # Free-hand axis: no Action spent, so its cost delta is the negated base cost (signed, per pool).
            free = extend_variant(mode, choice("free_hand", "sovereign", "Death-Sovereign, no Action", cost_delta((), mode.costs)))
            out.append(free.model_copy(update={"source_definition_id": mode.source_definition_id + ".sovereign_free",
                                              "display_name": mode.display_name + " (Death-Sovereign, no Action)",
                                              "economy": EconomyKind.NONE, "parameters": parameters, "costs": ()}))
    return out or None


@hook("candidate_allowed")
def sovereign_hand_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not _typed(action).get(FREE_HAND):
        return None
    return bool(_sovereign(actor) and engine.state.current_actor_id == actor.entity_id
                and actor.turn_flags.get(FREE_HAND) != int(actor.turns_started))


@hook("technique_start")
def sovereign_hand_spent(engine: Any, actor: Any, action: Any) -> None:
    """Spend the shared free use at activation, even if a reaction counters it.

    The native transaction restores this ledger while a player decision is
    pending; a committed counter consumes the use just like a resolved Hand.
    """
    if (_typed(action).get(FREE_HAND) and _sovereign(actor)
            and engine.state.current_actor_id == actor.entity_id):
        actor.turn_flags[FREE_HAND] = int(actor.turns_started)


def grave_anchors(engine: Any, actor: Any) -> list[Any]:
    """Visible represented grave anchors. Never infer death from nonlethal defeat.

    Deathly Passage uses creatures with Undead typing, recorded corpses and dying
    creatures. Map objects must explicitly identify a corpse/remains, or carry
    death_anchor_owner for the caster's marked funerary object/Ghost Lantern.
    Unknown scenery and another caster's marked object are not grave anchors.

    Share this read-only snapshot across destination checks in one candidate
    pass. The existing query seam separates engine/state revisions, actor
    projections and shot frames; execution and the next menu compute afresh.
    Return a fresh list so a caller cannot edit the cached container.
    """
    from ..hook_queries import actor_action
    from ..read_queries import invariant_memo
    key = ("death_grave_anchors", actor_action(engine, actor, None, None))
    return list(invariant_memo(engine, key, lambda: tuple(_grave_anchors(engine, actor))))


def _grave_anchors(engine: Any, actor: Any) -> list[Any]:
    """Build the ordered anchor snapshot; reject ineligible scenery before sight."""
    from .. import senses
    from .life_state import is_deceased
    out = []
    for subject in engine.state.actors.values():
        if subject is actor:
            continue
        corpse = is_deceased(subject) and not subject.summon and not any(
            c.condition_id == C + "corpse_consumed" for c in subject.conditions.values())
        if (corpse or (subject.active and (matches(subject, "undead") or (subject.current_hp == 0 and subject.life_state == "DYING")))
                or (subject.active and _death_servant(engine, subject) and (subject.summon or {}).get("owner") == actor.entity_id)):
            if senses.perceives(engine, actor, subject) and engine._distance_actor_to_actor(actor, subject) <= 60:
                out.append(subject.position)
    for obj in engine.state.objects.values():
        component = obj.component or {}
        if obj.destroyed:
            continue
        if (str(obj.object_kind).lower() in {"corpse", "remains"}
                or component.get("death_anchor_owner") == actor.entity_id):
            if senses.perceives_cell(engine, actor, obj.position) and engine.grid.distance_ft(actor.position, obj.position) <= 60:
                out.append(obj.position)
    return out


@hook("candidate_allowed")
def grave_passage_destination(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not any(row.get("death_anchors") for row in _typed(action).get("effects") or []):
        return None
    cell = candidate.destination
    return bool(cell is not None and any(engine.grid.distance_ft(cell, anchor) <= 5
                                        for anchor in grave_anchors(engine, actor)))


@hook("damage_reduction_bonus")
def bone_ward_remains(engine: Any, owner: Any, protected: Any, attacker: Any, row: dict[str, Any]) -> int | None:
    """Printed Bone Ward +PB within 10 feet of a corpse or funerary object.

    The saved effect flag opts in; historical reactions remain unchanged. A
    servant is a creature, not a corpse. A nonlethally defeated actor is not dead.
    No sight requirement is added: the printed bonus only requires proximity.
    """
    if not any(e.get("bone_ward_remains") for e in row.get("effects") or []):
        return None
    from .life_state import is_deceased
    close = any(is_deceased(other) and not other.summon
                and not any(c.condition_id == C + "corpse_consumed" for c in other.conditions.values())
                and engine._distance_actor_to_actor(protected, other) <= 10
                for other in engine.state.actors.values())
    close = close or any(not obj.destroyed
                         and str(obj.object_kind).lower() in {"corpse", "remains", "bone_pile", "grave_marker", "funerary_object"}
                         and engine.grid.distance_ft(protected.position, obj.position) <= 10
                         for obj in engine.state.objects.values())
    return int((row.get("numbers") or {}).get("pb") or owner.proficiency_bonus) if close else 0


def explosion_sources(engine: Any, actor: Any) -> dict[str, Any]:
    """Perceived corpses and active undead servants within range.

    Actor corpses gain an evented consumed condition; object corpses are
    destroyed through the ordinary object event. Nonlethal defeat is not death.
    """
    from .. import senses
    from .life_state import is_deceased
    out = {}
    for other in engine.state.actors.values():
        corpse = is_deceased(other) and not other.summon and not any(
            c.condition_id == C + "corpse_consumed" for c in other.conditions.values())
        servant = other.active and other.summon and (_death_servant(engine, other) or matches(other, "undead"))
        if (corpse or servant) and senses.perceives(engine, actor, other) and engine._distance_actor_to_actor(actor, other) <= 60:
            out[other.entity_id] = other
    for obj in engine.state.objects.values():
        if (not obj.destroyed and str(obj.object_kind).lower() in {"corpse", "remains"}
                and senses.perceives_cell(engine, actor, obj.position)
                and engine.grid.distance_ft(actor.position, obj.position) <= 60):
            out[obj.object_id] = obj
    return out


def _explosion(typed: dict[str, Any]) -> bool:
    return any(row.get("type") == "corpse_explosion_source" for row in typed.get("effects") or [])


@hook("damage_type_choice")
def explosion_damage_choice(ctx: Any, kinds: list[str], targets: list[Any]) -> str | None:
    """One player-owned type for the whole blast; AI knows perceived targets only."""
    if not _explosion(ctx.typed):
        return None
    if "death_explosion_type" in ctx.damage_cache:
        return ctx.damage_cache["death_explosion_type"]
    from .needle import ask
    from .. import senses, typed_reactions
    known = [target for target in targets if senses.perceives(ctx.engine, ctx.actor, target)]
    preferred = max(kinds, key=lambda kind: sum(typed_reactions.damage_factor(
        ctx.engine, target, kind, ctx.source, ctx.actor.entity_id) for target in known))
    chosen = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor, "choice:needle.corpse_explosion_damage",
                 kinds, labels={kind: kind.title() + " damage" for kind in kinds}, preferred=[preferred],
                 name="Corpse Explosion damage",
                 prompt="Corpse Explosion: choose Necrotic or Piercing damage for the creatures in this explosion. Your Action and 3 Cultivation Points (CP) are already spent.",
                 feature_id="TAL_DEATH_CORPSE_EXPLOSION")
    kind = chosen[0] if chosen else preferred
    ctx.damage_cache["death_explosion_type"] = kind
    return kind


@hook("candidate_allowed")
def explosion_center(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not _explosion(_typed(action)):
        return None
    return any(candidate.destination == subject.position for subject in explosion_sources(engine, actor).values())


@effect("corpse_explosion_source", harmful=False)
def choose_explosion_source(ctx: Any, row: dict[str, Any]) -> None:
    """Choose the source before the blast can destroy a servant through damage."""
    from .needle import ask
    center = ctx.destination or ctx.intent.destination
    sources = {key: subject for key, subject in explosion_sources(ctx.engine, ctx.actor).items()
               if subject.position == center}
    labels = {}
    for key, subject in sources.items():
        name = getattr(subject, "display_name", None) or (getattr(subject, "component", None) or {}).get("name") or "Corpse"
        summon = getattr(subject, "summon", None)
        if summon:
            owner = ctx.engine.state.actors.get(summon.get("owner"))
            ownership = "yours" if summon.get("owner") == ctx.actor.entity_id else (
                f"{owner.display_name}'s" if owner else "another creature's")
            name += f" ({ownership})"
        labels[key] = name
    chosen = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor, "choice:needle.corpse_explosion_source",
                 sorted(sources), labels=labels, name="Corpse Explosion",
                 prompt="Corpse Explosion: choose a corpse or undead servant at the blast's center, or cancel. A corpse or your own Death servant is destroyed; other servants take the blast's damage. Your Action and 3 Cultivation Points (CP) are already spent.",
                 allow_decline=True,
                 preferred=[min(sources)],
                 feature_id="TAL_DEATH_CORPSE_EXPLOSION") if sources else []
    if chosen:
        ctx.damage_cache["death_explosion_source"] = chosen[0]
        from ..typed_executor import run_effects
        run_effects(ctx, row.get("effects") or [])
    else:
        note(ctx.engine, ctx.source, ctx.actor, "Corpse Explosion is canceled; no corpse or servant is destroyed, and no explosion damage is dealt.")


@hook("technique_final")
def destroy_explosion_source(ctx: Any) -> None:
    if not _explosion(ctx.typed):
        return
    key = ctx.damage_cache.get("death_explosion_source")
    obj = ctx.engine.state.objects.get(key)
    if obj is not None:
        ctx.engine._update_object(obj.model_copy(update={"destroyed": True, "current_hp": 0}), ctx.source, ctx.actor.entity_id)
        name = (obj.component or {}).get("name") or "The corpse"
    else:
        subject = ctx.engine.state.actors.get(key)
        if subject is None:
            return
        name = subject.display_name
        if subject.summon:
            if not (_death_servant(ctx.engine, subject) and subject.summon.get("owner") == ctx.actor.entity_id):
                note(ctx.engine, ctx.source, ctx.actor,
                     f"Corpse Explosion erupts around {name}; only your own Death servants are automatically destroyed.")
                return
            if subject.active:  # the blast itself may already have destroyed it
                ctx.engine._defeat(subject, ctx.source, final=True)
        else:
            ctx.engine._apply_condition(subject, C + "corpse_consumed", ctx.source, ctx.actor.entity_id,
                                        expires_on="UNTIL_REMOVED", data={"label": "Corpse destroyed by Corpse Explosion"})
    note(ctx.engine, ctx.source, ctx.actor, f"Corpse Explosion destroys {name}.")
NECROTIC = "NECROTIC"
_PENDING = "_auto22_grave_mark_pending"
_SHARED_ROLL = "_auto22_grave_mark_shared_roll"
# Transient (cleared at the next turn start, combat/gate2_engine.py): this servant was already told what the Domain
# does for it, so the notice is not repeated on every step.
_COURT_TOLD = "auto22_death.court_told"
# A stable gate name, not the action's own id: "the first time each turn" is one clock on the caster's mark, so a
# second technique and a servant's attack in the same turn must find it already spent.
MARK_GATE = "auto22_death.grave_mark"
MARK_DAMAGE_RULE = ("The first time each turn the marked creature takes Necrotic damage from you or one of your Death "
                    "servants, add your Proficiency Bonus to one damage roll.")
LEASH_LABEL = f"Soul Hook: the grave chains hold it within {LEASH_FT} feet of the square it was hooked at."


# ------------------------------------------------------------------------------------------------- ownership rows
@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """This module's ownership rows: one per talent, carrying its own block and kind."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2),
             "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return row_of(engine, getattr(actor, "entity_id", None) or "", BLOCK, kind)


def _summon_owner(creature: Any) -> str | None:
    """The caster that controls this summoned asset, or None for a character that is not one."""
    summon = getattr(creature, "summon", None) or {}
    return str(summon.get("owner") or "") or None


def _death_servant(engine: Any, creature: Any) -> bool:
    """Whether this creature is one of its owner's DEATH servants (printed "your Death servants")."""
    return (getattr(creature, "summon", None) or {}).get("command_group") == DEATH_GROUP


# ------------------------------------------------------------------------------------- Mark for the Grave
def _mark_caster(engine: Any, damager: Any) -> Any | None:
    """The caster whose Grave Mark this damage could use: the damager itself, or the owner of one of its Death servants.

    "from you or one of your Death servants" is two sources and no others: another summon this caster commands (a
    Living Painting), and a Death servant of a different caster, are both left alone.
    """
    if damager is None:
        return None
    if _row(engine, damager, "grave_mark") is not None:
        return damager
    if not _death_servant(engine, damager):
        return None
    owner = engine.state.actors.get(_summon_owner(damager) or "")
    return owner if owner is not None and _row(engine, owner, "grave_mark") is not None else None


def _bears_mark(subject: Any, caster: Any) -> bool:
    """Whether ``subject`` carries the Grave Mark this caster put on it (one mark per caster)."""
    prefix = GRAVE_MARK + "."
    return any(condition.condition_id.startswith(prefix) and condition.source_actor_id == caster.entity_id
               for condition in subject.conditions.values())


def _mark_gate(engine: Any, damager: Any, subject: Any) -> tuple[Any, str, str, int] | None:
    """(caster, gate key, this turn, Proficiency Bonus) when this damage may use that caster's Grave Mark."""
    if subject is None or not subject.active or damager is None or not damager.active:
        return None
    caster = _mark_caster(engine, damager)
    if caster is None or not _bears_mark(subject, caster):
        return None  # no mark of this caster's on that creature
    from .. import typed_executor as te

    key, turn = te.on_hit_turn_key(engine, caster, MARK_GATE, MARK_DAMAGE_RULE)
    return caster, key, turn, int(_row(engine, caster, "grave_mark")["pb"])


@hook("attack_damage_bonus")
def grave_mark_attack(ctx: Any, target: Any, effect: Any) -> int | None:
    """"The first time each turn the marked creature takes Necrotic damage from you or one of your Death servants, add your
    Proficiency Bonus to one damage roll." -- on a typed attack's own damage packet, before its defenses."""
    from .. import typed_executor as te

    engine, damager = ctx.engine, ctx.actor
    gate = _mark_gate(engine, damager, target)
    if gate is None or not _packet_is_necrotic(engine):
        return None
    caster, key, turn, pb = gate
    if not te.on_hit_rider_available(engine, caster, key, turn, target.entity_id):
        return None
    # The attack has not resolved yet: reserve now, claim the printed turn gate only if it lands.
    ctx.damage_cache.setdefault(_PENDING, []).append((target.entity_id, caster.entity_id, key, turn))
    return pb


@hook("after_hit")
def grave_mark_attack_landed(ctx: Any, target: Any, kind: Any) -> None:
    """Spend a reserved gate only for a packet that actually damaged the marked creature."""
    from .. import typed_executor as te

    pending = _take_pending(ctx, target)
    if not pending:
        return
    engine = ctx.engine
    subject_id = getattr(target, "entity_id", None)
    landed = any(e.event_type == "DAMAGE_COMMITTED"
                 and e.source_definition_id == ctx.source and subject_id in (e.target_ids or ())
                 and int((e.payload or {}).get("hp_damage") or 0) + int((e.payload or {}).get("temporary_hp_absorbed") or 0) > 0
                 for e in engine.events)
    if not landed:
        return
    for _, caster_id, key, turn in pending:
        caster = engine.state.actors.get(caster_id)
        if caster is not None:
            te.spend_on_hit_rider(engine, caster, key, turn, subject_id)


@hook("after_miss")
def grave_mark_attack_missed(ctx: Any, target: Any) -> None:
    """A miss costs nothing: the printed gate is still there for a later hit this turn."""
    _take_pending(ctx, target)


@hook("damage_roll_bonus")
def grave_mark_roll(ctx: Any, effect: Any = None, kinds: Any = None) -> int | None:
    """The same printed rider on damage that is not an attack roll and reaches one creature: a save, or a single-target effect."""
    from .. import typed_executor as te

    if effect is None:
        return None  # an attack sequence's shared dice, shaped before any strike: see grave_mark_attack
    # One roll several creatures share (an area's subjects, or a row printed for a whole area) is not a roll this
    # bonus may join -- it names one creature.  The decision is recorded for the delivery hook below, which sees each
    # recipient of that same cached roll in turn; a private roll clears it again.
    if area_recipients(ctx) or str(effect.get("applies_to") or "").endswith("_in_area"):
        ctx.damage_cache[_SHARED_ROLL] = True
        return None
    ctx.damage_cache.pop(_SHARED_ROLL, None)
    if not _roll_is_necrotic(ctx.engine, kinds):
        return None
    gate = _mark_gate(ctx.engine, ctx.actor, ctx.target)
    if gate is None:
        return None
    caster, key, turn, pb = gate
    return pb if te.spend_on_hit_rider(ctx.engine, caster, key, turn, ctx.target.entity_id) else None


@hook("deal_bonus")
def grave_mark_recipient(ctx: Any, subject: Any, amount: int) -> int | None:
    """The same printed rider when ONE roll is shared by several creatures.

    An area rolls once for every creature in it, so the printed bonus -- which names one creature -- is not part of that
    shared roll: the roll stays exactly as the area printed it, and the marked creature's own share carries the
    Proficiency Bonus here, after the roll and before its save and resistance.  Every other recipient is untouched,
    whichever order the area resolved them in, and a creature immune to Necrotic still takes nothing.
    """
    from .. import typed_executor as te

    if not ctx.damage_cache.get(_SHARED_ROLL) or subject is None:
        return None
    if str(getattr(ctx.engine, "_typed_pending_damage_type", "") or "").upper() != NECROTIC:
        return None
    gate = _mark_gate(ctx.engine, ctx.actor, subject)
    if gate is None:
        return None
    caster, key, turn, pb = gate
    return pb if te.spend_on_hit_rider(ctx.engine, caster, key, turn, subject.entity_id) else None


def _take_pending(ctx: Any, target: Any) -> list[tuple[Any, ...]]:
    """Drop and return this target's reserved gates, so a later attempt reserves its own."""
    entries = list(ctx.damage_cache.get(_PENDING) or [])
    if not entries or not hasattr(ctx, "damage_cache"):
        return []
    subject_id = getattr(target, "entity_id", None)
    mine = [entry for entry in entries if entry[0] == subject_id]
    if not mine:
        return []
    kept = [entry for entry in entries if entry[0] != subject_id]
    if kept:
        ctx.damage_cache[_PENDING] = kept
    else:
        ctx.damage_cache.pop(_PENDING, None)
    return mine


def _packet_is_necrotic(engine: Any) -> bool:
    """Whether the packet about to be committed to this target is Necrotic.

    The executor records the packet's RESOLVED damage type around ``attack_damage_bonus``
    (combat/typed_executor.py), so this is the type the dice will actually carry.  Reading the printed
    damage rows instead would be wrong in both directions: an ordinary Corpse Servant keeps its Necrotic
    type in its weapon and prints a bare weapon-damage row, and a Bone General's separate Necrotic
    extra-damage row is not the weapon packet at all.
    """
    return str(getattr(engine, "_typed_pending_damage_type", "") or "").upper() == NECROTIC


def _row_is_necrotic(kinds: Any) -> bool:
    """Whether a typed damage row can only deal Necrotic damage (its own printed damage types)."""
    printed = [str(kind).lower() for kind in (kinds or ())]
    return bool(printed) and all(kind == "necrotic" for kind in printed)


def _roll_is_necrotic(engine: Any, kinds: Any) -> bool:
    """Whether THIS roll will carry Necrotic damage.

    The executor resolves the row's choice of damage type before the roll's modifiers are folded in and records it in
    ``engine._typed_pending_damage_type`` (combat/typed_executor.py ``_damage_roll``), so a row printed "6d8 Radiant or
    Necrotic damage, your choice" counts when Necrotic is the type actually chosen, and a row printed "Necrotic or
    Poison" does not.  Only when the resolved type is missing -- an ordinary row with a single printed type -- does the
    printed row answer.
    """
    resolved = str(getattr(engine, "_typed_pending_damage_type", "") or "").upper()
    if resolved:
        return resolved == NECROTIC
    return _row_is_necrotic(kinds)


# ------------------------------------------------------------------------------------------------- Soul Hook
def _hook_anchor(mover: Any, owner_id: str) -> tuple[int, int] | None:
    """The square this caster hooked ``mover`` at, from the creature's own Soul Hook condition."""
    for condition in mover.conditions.values():
        data = condition.data or {}
        if condition.condition_id == SOUL_HOOK and condition.source_actor_id == owner_id:
            if data.get("hook_x") is not None and data.get("hook_y") is not None:
                return int(data["hook_x"]), int(data["hook_y"])
    return None


@hook("technique_final")
def remember_the_hooked_square(ctx: Any) -> None:
    """The chain reaches from the square the target occupied when it failed the save, so record that square.

    Runs after the typed save's own effects, when the Soul Hook condition exists; nothing between the failed save and
    the end of this technique moves the target."""
    engine, actor = ctx.engine, ctx.actor
    if _row(engine, actor, "soul_hook") is None:
        return
    for subject in ctx.targets or ():
        if subject is None or not subject.active or subject.team_id == actor.team_id:
            continue
        for condition in list(subject.conditions.values()):
            if condition.condition_id != SOUL_HOOK or condition.source_actor_id != actor.entity_id:
                continue
            if (condition.data or {}).get("hook_x") is not None:
                continue  # this chain already knows its square
            keep = {**(condition.data or {}), "hook_x": int(subject.position.x), "hook_y": int(subject.position.y)}
            instance, expiry = condition.instance_id, condition.expires_on

            remove_instance(engine, subject, instance, ctx.source)  # one condition, not a second copy of it
            from .effect_durations import apply_condition_preserving_clock
            apply_condition_preserving_clock(engine, subject, condition, SOUL_HOOK, ctx.source, actor.entity_id,
                                             expires_on=expiry, data=keep)
            note(engine, ctx.source, subject, f"{subject.display_name} is held within {LEASH_FT} feet of that square.")


@hook("movement_attempt")
def soul_hook_leash(engine: Any, mover: Any, previous: Any, following: Any, intent: Any) -> dict[str, Any] | None:
    """"... it cannot willingly move more than 10 feet from the space it occupied when it failed the save." A voluntary
    step that would take it past the boundary stops the move there."""
    if mover is None or not mover.active or following is None:
        return None
    owner_id = next((c.source_actor_id for c in mover.conditions.values()
                     if c.condition_id == SOUL_HOOK and (c.data or {}).get("hook_x") is not None), None)
    if owner_id is None or _row(engine, engine.state.actors.get(owner_id), "soul_hook") is None:
        return None
    anchor = _hook_anchor(mover, owner_id)
    if anchor is None:
        return None
    from ..gate2_runtime_models import Position

    start = engine.grid.distance_ft(previous, Position(x=anchor[0], y=anchor[1]))
    beyond = engine.grid.distance_ft(following, Position(x=anchor[0], y=anchor[1]))
    if start > LEASH_FT or beyond <= LEASH_FT:
        return None
    return {"stop": True, "source_id": SOUL_HOOK, "label": LEASH_LABEL}


# --------------------------------------------------------------- Court of the Ninth Grave: difficult terrain
def _court_domain(engine: Any, owner: Any) -> Any | None:
    """The caster's own Court of the Ninth Grave zone (its typed source names the talent)."""
    from .. import zones

    if owner is None or not owner.active:
        return None
    for zone in zones.typed_zones(engine):
        if not zone.active or zone.owner_id != owner.entity_id:
            continue
        action = engine.action_catalog.get(str(zone.source_definition_id or ""))
        typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
        if str(typed.get("source") or "") == COURT_ID:
            return zone
    return None


def _court_master(engine: Any, creature: Any) -> Any | None:
    """The Court of the Ninth Grave caster this creature's terrain benefit could come from, or None.

    The printed "your Death servants" is its caster's own Death servants only (combat/rules/summons.json command group
    "death"), so a Living Painting or any other companion gets nothing, and a caster that has fallen or lost its
    Domain gives nothing either.
    """
    if creature is None or not creature.active or not _death_servant(engine, creature):
        return None
    owner = engine.state.actors.get(_summon_owner(creature) or "")
    return owner if owner is not None and _row(engine, owner, "court") is not None else None


@hook("difficult_exempt")
def court_terrain(engine: Any, actor: Any) -> Any | None:
    """"Your Death servants inside the Domain may move through nonmagical Difficult Terrain without extra movement."
    The Domain's own squares, published only while this Death servant stands in its caster's Domain.

    Squares, not a condition, because the printed benefit is about where the servant STANDS: the engine asks this
    query for every step it prices and for every square it lists, so the boundary is honoured inside a single move and
    there is no remembered membership to go stale when the Domain ends or the fight is reloaded.

    Published with the ``nonmagical_only`` scope, because the printed line says "nonmagical": the map's own rough ground
    inside the Domain is free, but ground an ABILITY made there -- a hostile technique's Difficult Terrain -- is not.
    An unrestricted subscriber (Juggernaut, the Ninefold Array) still ignores both.  See combat/motion.py
    ``TerrainExemption``.
    """
    from .. import motion, zones

    master = _court_master(engine, actor)
    domain = _court_domain(engine, master)
    if domain is None or not zones._inside(engine, actor, domain):
        return None
    cells = frozenset((cell.x, cell.y) for cell in domain.affected_cells)
    return motion.TerrainExemption(cells, nonmagical_only=True) if cells else None


def _legacy_court_instance(condition: Any) -> bool:
    """Whether this saved condition instance is the stale whole-map Court terrain benefit an older build wrote.

    The condition id AND this talent's ``COURT_ID`` as the source, so Lotus Step's, Battle Rhythm's or any other caster's
    own ``ignore_difficult`` never matches.  Shared by both halves of the retirement: the ``condition_excluded`` reader
    below and ``retire_legacy_court_terrain``'s removal.
    """
    return (getattr(condition, "condition_id", None) == LEGACY_TERRAIN
            and getattr(condition, "source_definition_id", None) == COURT_ID)


@hook("condition_excluded")
def legacy_court_terrain_is_retired(engine: Any, actor: Any, condition: Any) -> bool:
    """Keep the old whole-map Court condition from doing anything the moment a fight carrying it is continued.

    ``retire_legacy_court_terrain`` removes the instance at the servant's next turn start, which is the recorded, ordinary
    way a condition leaves a fight.  That boundary is too late for the one case the engine cannot reach: a fight SAVED
    during the servant's own turn is continued with that turn already begun, and combat/gate3_storage.py load_match restores
    the state and rebuilds the walls without starting another turn.  Until the next turn start the stale instance would
    still be read by combat/motion.py ignores_difficult, so resumed movement -- including off-turn movement, such as a
    forced shove -- would cross rough ground anywhere on the map for free, which the printed "inside the Domain" never
    allowed.  Answering True here makes the instance inert from its first read instead, without editing the saved state or
    its record.

    Read-only, and inert for everything else: a creature with no stale Court instance, and any other ability's
    ``ignore_difficult``, both fall through the normal path unchanged.
    """
    return _legacy_court_instance(condition)


@hook("turn_start")
def retire_legacy_court_terrain(engine: Any, actor: Any) -> None:
    """Remove the whole-creature ``ignore_difficult`` condition older builds wrote on a servant of the Domain.

    Before this lane's square-by-square publication, a servant that stood in its caster's Domain carried a
    ``condition:typed.ignore_difficult`` instance with ``UNTIL_REMOVED`` that the caster's next turn or the servant's
    leaving the Domain cleared -- but only from a build that still wrote and cleaned it up.  A fight SAVED while the
    servant was inside the Domain keeps that instance forever once continued on this build: it would ignore rough ground
    anywhere on the map, which the printed "inside the Domain" never allowed.  The condition has no expiry of its own and
    is not concentration, so nothing else in the engine would ever remove it.

    Only the instances this ability wrote are retired (``_legacy_court_instance``), so Lotus Step's, Battle Rhythm's or
    any other caster's own ``ignore_difficult`` is untouched.  Removal goes through ``rider_support.remove_instance``,
    which records ``CONDITION_REMOVED`` like every other removal, so the retirement is an ordinary event in the saved
    fight's record rather than a silent edit to its state.  ``legacy_court_terrain_is_retired`` makes the same instance
    inert immediately on a resumed mid-turn continuation, before this removal gets a chance to run.
    """
    for iid, condition in list(getattr(actor, "conditions", {}).items()):
        if _legacy_court_instance(condition):
            remove_instance(engine, actor, iid, COURT_ID)


def _court_servants(engine: Any, owner: Any) -> list[Any]:
    """This caster's own Death servants -- the printed "your Death servants", not every creature it commands."""
    from .. import summons

    return summons.owned_by(engine, owner.entity_id, DEATH_GROUP)


def _court_notice(engine: Any, creature: Any) -> None:
    """Say once, in plain words, that this servant is standing where the Domain makes rough ground cost nothing."""
    if creature.turn_flags.get(_COURT_TOLD) or court_terrain(engine, creature) is None:
        return
    creature.turn_flags[_COURT_TOLD] = 1
    note(engine, COURT_ID, creature, f"{creature.display_name} stands in the Domain: nonmagical Difficult Terrain costs it "
                                    "no extra movement until it steps outside.")


@hook("technique_final")
def court_when_the_domain_opens(ctx: Any) -> None:
    """The Domain is laid down during a technique, so its servants are told on that activation, not a turn later."""
    engine = ctx.engine
    owner = ctx.actor
    if _row(engine, owner, "court") is None:
        return
    for servant in _court_servants(engine, owner):
        _court_notice(engine, servant)


@hook("after_move")
def court_after_a_move(engine: Any, mover: Any, moved_ft: int) -> None:
    """A servant that walked into the Domain learns it on that step, not at the Domain's next placement."""
    _court_notice(engine, mover)
