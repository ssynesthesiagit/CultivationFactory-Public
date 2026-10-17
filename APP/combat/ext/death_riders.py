"""Death riders the engine can resolve (automation lane AUTO22, 2026-10-04; owner: "automate everything").

Printed text: the owner's Sphere Compendium, "Sphere of Death" (APP/authority/typed_mechanics/rules_text.json, with
owner_text_edits.json on top).  Each rule is quoted above the hook that plays it.

Who has it: a character that learned one of these talents carries one compiled passive row of block ``auto22_death``
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

Nothing here branches on an ability id while a fight runs: the rows say who owns the talent, the conditions and marks
say who is affected, and every hook reads only those.
"""

from __future__ import annotations

from typing import Any

from . import hook, note
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
