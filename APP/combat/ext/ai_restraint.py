"""What the built-in AI leaves alone because it would change nothing (fight audit 2026-09-29: the controller never ends a
turn while any Action or Bonus Action is left, so it spent every spare one casting again what was still up -- Dust Cloud
20 times in 21 rounds, Sand Shell 8 times, Darkness and Smoke Veil 6 times each -- and grabbed an improvised weapon
while holding its own). A player's menu keeps every choice (combat/gate4_context.py for_ai only).

Kept from the AI: the same technique while it still concentrates on it; an area of the same technique it already has on
the map, unless that one catches no enemy and this one would; Temporary Hit Points for itself while it still has some; a
buff on itself while the one it put up is still there; an improvised weapon while it has a weapon or natural attack of its
own and is not disarmed; a commanded (or free-acting) summon's Dodge or Disengage while it can still walk toward an enemy it cannot reach yet.

A free ``setting_only`` declaration (Set the Workpiece, a Quench carrier pick) costs nothing, so the engine offers it
again after it resolves. The AI scores a repeated declaration below acting or ending its turn, without removing any
choice. Independent declarations keep their value; an intervening non-setting action or move allows reconsideration.
A person's ranking and Ask-me questions are unchanged (combat/gate4_context.py ``ai_veto=False``). Declarations made
by a person also count when that creature is handed to the AI. History is per creature and clears next turn.

Closing in (fight audit 2026-09-29, hunt 1: Corpse Servants and Painted Formations Dashed and ended their turn where they
stood, so a fight with the enemy across the map ran to the round limit): the fallback policy scores every square 50 feet or
more from every enemy alike, and below an ended turn, so a summon on that policy never walks a long way in. While a
commanded (or free-acting) summon with an action against an enemy, none in reach and Movement left is offered a step that
ends nearer the nearest enemy, the AI is not offered to end its turn or Hold, nor a step that leaves it no nearer. Dash, and
a move after it, stay on the menu. With no nearer step on offer (walled in, Frightened of the only way, no Movement)
nothing is left out, so its menu is never empty.

Zones that hurt (fight audit 2026-09-29, hunt 2: 14 of 48 summon defeats were a zone's trigger, 7 of them before the summon
had made an attack -- all four of one caster's Corpse Servants walked into "Hell Opens Beneath the Sect Gate", which
damages at the start of the turn, by the nearer steps this menu had left them): a step that ends in a zone that would hurt
the summon (combat/zones.py hazard_test), one it does not stand in already, is no step toward the enemy and is not offered,
unless the summon can strike from there (an enemy in reach, and its Action still to use). When every step toward the enemy
is like that, nothing pushes it in: it may end its turn or Hold. Dash then stays only if the Movement it adds would open a
step toward the enemy that the menu has none of (round the end of a wall, the last square of difficult ground); sealed in
a corridor a Corpse Servant Dashed every turn and only stepped back and forth (hunt 2). Its menu is still never empty.

Striking (fight audit 2026-09-29, hunt 3: 26 of 397 summon decisions took a step or a Dodge with an attack legal -- a Wolf
beside its foe stepped round it five times, out of reach, then Dodged at 10 feet): the fallback policy scores any step that
ends 5 to 30 feet from an enemy above a plain attack (90 to 86, wherever the summon stands: it cannot tell a step toward
anything from one away), and a summon at 40% of its Hit Points or less scores a Dodge above any attack. While a commanded
(or free-acting) summon has an attack it can make right now -- an attack of its own on an enemy in reach, its Action still
to use -- the AI is not offered Dodge, Disengage, Dash, a step, ending its turn or Hold: what is left is the attack (and
whatever else it can do that is not one of those), and the attack is one this menu keeps, so the menu is never empty. A step
before the attack is nothing lost: attacking does not spend Movement, and once the Action is used the summon may step as it
did. With no attack to make (no enemy in reach, the Action spent, a condition that forbids actions) nothing is left out."""

from __future__ import annotations

from typing import Any, Callable, NamedTuple

from ..gate2_runtime_models import CandidateKind
from . import hook
from ..knowledge_policy import enabled, roster

_MEMO = "_ai_close_in_memo"  # on the engine, not in the game: what the last decision worked out (see _close_in)
_STRIKE_MEMO = "_ai_strike_memo"  # likewise, for whether the summon has an attack to make (see _can_strike)
_FREE_SETTING = "ai_restraint_setting:"  # turn-scoped declaration history; values are persisted integers
_STAY = (CandidateKind.END_TURN, CandidateKind.HOLD_POSITION)
_DASH = "system:combat.dash"
_NOT_A_STRIKE = ("system:combat.dodge", "system:combat.disengage", _DASH)  # what the engine offers in place of an attack

_HARMFUL = {"attack", "damage", "extra_damage", "save", "forced_movement"}


@hook('reaction_subject_allowed')
def spare_friendly_reaction_subject(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """Automatic optional retaliation never harms an ally or neutral creature.

    Manual Ask-me remains the player's choice. Free mandatory passives and
    defensive benefits retain their rules. No row ID or ability name is used.
    """
    if other is None or (row.get('free') and not row.get('optional')) or row.get('reaction_target') == 'creature_in_reach':
        return None
    if row.get('ask') and reactor.entity_id in (getattr(engine, 'typed_ask_reactors', ()) or ()):
        return None
    from ..relations import relation, ENEMY
    if relation(engine, reactor, other) == ENEMY:
        return None
    from ..area_safety import harmful_recipients
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context
    typed = {'source': row['feature_id'], 'effects': row.get('effects') or [],
             'numbers': row.get('numbers') or {}, 'duration': {'kind': 'instant'},
             'triggering_source_id': other.entity_id}
    action = ActionDefinition(source_definition_id=row['feature_id'], display_name=row.get('name') or 'Reaction',
        owner_id=reactor.entity_id, economy=EconomyKind.REACTION, resolution_kind='TYPED',
        target_kind='HOSTILE_ENTITY', parameters={'typed': typed})
    ctx = Context(engine, reactor, action, None, typed, [other], other)
    if other.entity_id in harmful_recipients(ctx, typed['effects']):
        return False
    return None


def _effects(action: Any) -> list[dict[str, Any]]:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    return [e for e in typed.get("effects") or [] if isinstance(e, dict)]


def _self_only(action: Any) -> bool:
    """Cast on itself, touching no enemy now: a retaliation it carries (Sand Shell hurts an attacker) or a bonus to its own
    damage (Battle Cadence) is part of the buff, not an attack. An action that targets SELF has no other target, so an effect
    aimed at "the target" is aimed at the actor: a damage rider that fires on a later hit (Lightning-God Body's
    extra_damage) is part of the buff too, and re-casting it while it lasts only spent the pool (hunt 74)."""
    if not str(getattr(action, "target_kind", "")).endswith("SELF"):
        return False
    return not any(e.get("type") in ("attack", "save") or
                   (e.get("type") in _HARMFUL and e.get("applies_to") not in (None, "self", "target", "attacker"))
                   for e in _effects(action))


def _has_own_attack(engine: Any, actor: Any) -> bool:
    if any("disarmed" in c.condition_id for c in actor.conditions.values()):
        # A natural weapon or Iron Fist strike keeps it armed; the shared 1 + Strength Unarmed Strike does not (an improvised
        # weapon hits harder, and grabbing one is a free object interaction).
        return any(".natural." in a.source_definition_id and ((a.parameters or {}).get("typed") or {}).get("source") != "unarmed_strike"
                   for a in engine.action_catalog.values() if a.owner_id == actor.entity_id)
    return any(a.owner_id == actor.entity_id and ".improvised." not in a.source_definition_id
               and ((a.parameters or {}).get("typed") or {}).get("weapon") for a in engine.action_catalog.values())


def _reach_ft(engine: Any, actor: Any) -> int:
    """How far its own attacks against an enemy reach."""
    return max((int(a.range_ft or 5) for a in engine.action_catalog.values()
                if a.owner_id == actor.entity_id and str(a.target_kind).endswith("HOSTILE_ENTITY")), default=5)


def _enemy_in_reach(engine: Any, actor: Any) -> bool:
    reach = _reach_ft(engine, actor)
    return any(other.active and other.team_id != actor.team_id and engine._distance_actor_to_actor(actor, other) <= reach
               for other in roster(engine, actor))


def _has_attack(engine: Any, actor: Any) -> bool:
    """It has an action against an enemy at all; a Ghost Lantern has none, so nothing sends it toward one."""
    return any(a.owner_id == actor.entity_id and str(a.target_kind).endswith("HOSTILE_ENTITY") for a in engine.action_catalog.values())


def _nearest_ft(engine: Any, actor: Any, foe_ids: tuple[str, ...], at: Any = None, *, known_roster: Any = None) -> int:
    """How far the nearest of the enemies is from the actor's footprint, standing where it is or at ``at``."""
    known = {other.entity_id: other for other in (roster(engine, actor) if known_roster is None else known_roster)}
    return min((engine._distance_actor_to_actor(actor, known[foe_id], actor_position=at)
                for foe_id in foe_ids if foe_id in known), default=10**9)


class _Walk(NamedTuple):
    foe_ids: tuple[str, ...]  # the enemies still up (ids: a transaction that fails puts back copies of the actors)
    here: int  # feet to the nearest of them now
    reach: int  # feet its own attacks reach
    hazard: Callable[[Any], bool] | None  # whether a step ending at a position exposes it to a zone's damage (None: none would)
    offered: bool  # some step on the menu ends nearer than that, and not perilous (see _step)
    known_roster: tuple[Any, ...] | None = None  # immutable decision-local geometry, never saved


def _step(engine: Any, actor: Any, walk: _Walk, destination: Any) -> tuple[int, bool]:
    """How far the nearest enemy is from ``destination``, and whether ending a step there is perilous: in a zone that would
    hurt it (one it does not stand in already) with nothing to strike at -- no enemy in reach from there, or no Action left
    to strike with -- so the damage comes at the start of its next turn for nothing."""
    nearest = _nearest_ft(engine, actor, walk.foe_ids, destination, known_roster=walk.known_roster)
    return nearest, walk.hazard is not None and walk.hazard(destination) and not (actor.action_available and nearest <= walk.reach)


def _toward(engine: Any, actor: Any, walk: _Walk, destination: Any) -> bool:
    nearest, perilous = _step(engine, actor, walk, destination)
    return nearest < walk.here and not perilous


def _dash_opens_a_step(engine: Any, actor: Any, walk: _Walk) -> bool:
    """Whether the Movement a Dash adds would let it take a step toward the enemy that the menu has none of now (round the
    end of a wall, the last square of difficult ground); in a dead end it opens nothing and the Dash only spends its Action.
    Listed as the engine lists a move (combat/gate2_engine.py _movement_candidates), with the Movement it would then have."""
    speed = engine._effective_speed(actor)
    if speed <= 0:
        return False
    cells = engine.grid.reachable(actor.position, movement_ft=(actor.movement_remaining_ft + speed) // engine._drag_multiplier(actor),
                                  occupied_cells=engine._occupied_cells_except(actor.entity_id, observed=enabled(engine)),
                                  difficult_cells=engine._hostile_difficult_cells(actor), footprint=engine._footprint(actor))
    # The Dash takes its Action, so from a square in a zone that would hurt it there is nothing to strike with, in reach or not.
    return any(_nearest_ft(engine, actor, walk.foe_ids, cell, known_roster=walk.known_roster) < walk.here
               and not (walk.hazard is not None and walk.hazard(cell)) for cell in cells)


def _close_in(engine: Any, actor: Any, candidate: Any) -> _Walk | None:
    """What an acting summon with Movement left, an attack of its own and no enemy in reach has to walk toward; None when
    it has nothing to close in on. Asked about every candidate of a decision (a move list runs to hundreds), so it is
    worked out once per decision and kept on the engine (not in the game state, nothing saved or replayed)."""
    key = (candidate.decision_id, actor.entity_id, actor.movement_remaining_ft, actor.position.x, actor.position.y, enabled(engine))
    memo = getattr(engine, _MEMO, None)
    if memo is not None and memo[0] == key:
        return memo[1]
    walk = None
    if _has_attack(engine, actor) and not _enemy_in_reach(engine, actor):
        foes = tuple(other for other in roster(engine, actor) if other.active and other.team_id != actor.team_id)
        foe_ids = tuple(other.entity_id for other in foes)
        if foe_ids:
            from .. import zones

            # Snapshot the knowledge projection once, not for every movement cell.
            # Historical fights still resolve IDs against the restored real roster.
            known = tuple(other.model_copy(deep=True) for other in foes) if enabled(engine) else None
            walk = _Walk(foe_ids, _nearest_ft(engine, actor, foe_ids, known_roster=known), _reach_ft(engine, actor),
                         zones.hazard_test(engine, actor), False, known)
            # The menu's own steps (frightened, grappled, walled in: whatever the engine leaves out is not counted).
            walk = walk._replace(offered=any(move.kind == CandidateKind.MOVE and move.actor_id == actor.entity_id and move.destination is not None
                                             and _toward(engine, actor, walk, move.destination) for move in engine.legal_candidates()))
    setattr(engine, _MEMO, (key, walk))
    return walk


def _is_strike(engine: Any, actor: Any, candidate: Any) -> bool:
    """An attack of its own on an enemy that the AI's menu keeps (combat/gate4_context.py for_ai drops what is inert or
    player-only, an area aimed at no one and a teleport; _allowed drops what it would not cast again), so the menu is never
    left without it."""
    if candidate.kind != CandidateKind.ACTION or candidate.actor_id != actor.entity_id or not candidate.target_ids:
        return False
    action = engine.action_catalog.get(candidate.source_definition_id)
    if action is None or action.owner_id != actor.entity_id or not str(action.target_kind).endswith("HOSTILE_ENTITY"):
        return False
    parameters, metadata = action.parameters or {}, candidate.metadata or {}
    if parameters.get("inert") or parameters.get("player_only") or metadata.get("empty_area") or metadata.get("teleport"):
        return False
    return _allowed(engine, actor, candidate, action) is not False  # (an attack is no step or Dodge, so this does not come back here)


def _can_strike(engine: Any, actor: Any) -> bool:
    """Whether the summon has an attack it can make right now: its Action to use and one of its own attacks legal against an
    enemy (in reach, in sight, not the creature that charmed it). Asked about every candidate of a decision (a move list runs
    to hundreds), so it is worked out once and kept on the engine, as _close_in does, under the decision's own numbers."""
    key = (engine.state.state_version, engine.state.event_sequence, actor.entity_id, actor.action_available,
           actor.movement_remaining_ft, actor.position.x, actor.position.y, enabled(engine))
    memo = getattr(engine, _STRIKE_MEMO, None)
    if memo is not None and memo[0] == key:
        return memo[1]
    strike = actor.action_available and _enemy_in_reach(engine, actor) and any(_is_strike(engine, actor, c) for c in engine.legal_candidates())
    setattr(engine, _STRIKE_MEMO, (key, strike))
    return strike


@hook("activation_end")
def note_free_setting(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Remember this free declaration, not an actor-wide allowance.

    Different source/target declarations are independent. Repeating one without
    intervening gameplay is still legal, but must not outrank taking a turn.
    Manual declarations participate too, so handing control to AI cannot loop.
    activation_end also runs for a declaration that was canceled, vetoed or
    failed. Only a declaration whose selection was actually stored counts; the
    engine marks that on the completed activation before this hook runs.
    """
    if getattr(engine, "_activation_stored_intent", None) != getattr(intent, "intent_id", None):
        return
    if ((getattr(action, "parameters", None) or {}).get("setting_only")
            and getattr(action.economy, "value", action.economy) == "NONE"):
        actor.turn_flags[setting_history_key(candidate)] = 1


def setting_history_key(candidate: Any) -> str:
    """Stable identity of a declaration, independent of decision/state versions."""
    from ..canonical import canonical_sha256
    return _FREE_SETTING + canonical_sha256({
        "source": candidate.source_definition_id, "targets": list(candidate.target_ids)})


@hook("event")
def reset_setting_history(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Non-setting intents reopen setup after gameplay; setting bookkeeping skips this hook."""
    if event_type != "INTENT_ACCEPTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is not None:
        for key in list(actor.turn_flags):
            if key.startswith(_FREE_SETTING):
                del actor.turn_flags[key]


def free_setting_metadata(actor: Any, candidate: Any, action: Any) -> dict[str, int]:
    """AI-only projection of its own declaration history; never removes a choice."""
    if (action.parameters.get("setting_only")
            and getattr(action.economy, "value", action.economy) == "NONE"
            and actor.turn_flags.get(setting_history_key(candidate))):
        return {"ai_repeated_setting": 1}
    return {}


@hook("ai_score_components")
def repeated_setting_value(context: Any, candidate: Any, option_ids: tuple[str, ...]) -> Any:
    """An already-made free selection has no new preparation value."""
    if not candidate.metadata.get("ai_repeated_setting"):
        return None
    from ..gate4_models import ComponentScore
    return (ComponentScore(component="repeated_setting", value=-10000,
        explanation="This declaration was already made; act or end the turn before repeating setup."),)


@hook("ai_candidate_allowed")
def restraint(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    try:
        return _allowed(engine, actor, candidate, action)
    except Exception:  # never let a restraint rule stop the AI from choosing
        return None


def _allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = candidate.source_definition_id
    summon = actor.summon or {}
    acting = summon.get("commanded") or summon.get("command") == "free"  # commanded now, or a tamed beast that needs none
    if source in ("system:combat.dodge", "system:combat.disengage") and acting and actor.movement_remaining_ft > 0 \
            and not _enemy_in_reach(engine, actor) and (not enabled(engine) or any(
                other.active and other.team_id != actor.team_id for other in roster(engine, actor))):
        return False  # it closes in rather than Dodge or Disengage where no enemy can reach it (the command would be wasted)
    kind = getattr(candidate, "kind", None)
    if acting and (kind == CandidateKind.MOVE or kind in _STAY or source in _NOT_A_STRIKE) and _can_strike(engine, actor):
        return False  # it has an attack to make: no step, Dodge, Dash or ended turn in its place (the attack itself stays)
    if acting and actor.movement_remaining_ft > 0 and (kind == CandidateKind.MOVE or kind in _STAY or source == _DASH):
        walk = _close_in(engine, actor, candidate)
        if walk is not None:
            if kind == CandidateKind.MOVE and candidate.destination is not None:
                nearest, perilous = _step(engine, actor, walk, candidate.destination)
                if perilous or (walk.offered and nearest >= walk.here):
                    return False  # into a zone that would hurt it with nothing to strike at, or a step that leaves it no nearer
            elif walk.offered:
                if kind in _STAY:
                    return False  # it walks toward the enemy rather than end its turn (or Hold) with one out of reach
            elif source == _DASH and not _dash_opens_a_step(engine, actor, walk):
                return False  # no step toward the enemy even with the Movement a Dash adds: it would only spend its Action
    if action is None:
        return None
    parameters = action.parameters or {}
    if parameters.get("setting_only"):
        return None  # selectors are not ongoing self buffs; repetition is a scoring preference, never a veto
    if source.endswith(".improvised.grab"):
        return not _has_own_attack(engine, actor)
    from .. import concentration

    typed = (action.parameters or {}).get("typed") or {}
    # A persistent hazard under a teammate can hurt it every turn. Instant
    # areas retain the scorer's tradeoff; delayed hazards require a safe aim.
    if typed.get('zone_spec') and int((candidate.metadata or {}).get('unavoidable_allies_in_area') or 0):
        return False
    technique = concentration.technique_of(engine, source)
    same = lambda other: bool(other) and concentration.technique_of(engine, str(other)) == technique  # noqa: E731
    # Recipient-aware Melds already passed docket_senses' grant/upgrade check.
    # Holding the same technique does not make a new recipient or a paid HP
    # offer redundant. Keep that admission authoritative in the AI context too.
    if (action.parameters or {}).get("meld_runtime") != 2 and (typed.get("duration") or {}).get("concentration") and any(same(held) for held in concentration.sources(actor)):
        return False
    def same_activation(zone: Any) -> bool:
        if not same(zone.source_definition_id):
            return False
        origin = engine.action_catalog.get(zone.source_definition_id)
        # A technique may expose different operations on its persistent object.
        # Sharing its source does not make directing it another activation of
        # the action that created it. Preserve the old restraint when an older
        # saved zone has no catalogued creation action to compare.
        return origin is None or tuple(e.get("type") for e in _effects(origin)) == tuple(e.get("type") for e in _effects(action))

    zones = [z for z in getattr(engine.state, "zones", {}).values()
             if z.active and z.owner_id == actor.entity_id and same_activation(z)]
    if zones:
        from ..target_knowledge import actors_for
        hostiles = {(a.position.x, a.position.y) for a in actors_for(engine, actor) if a.active and a.team_id != actor.team_id}
        catching = any((cell.x, cell.y) in hostiles for zone in zones for cell in zone.affected_cells)
        if catching or not int((candidate.metadata or {}).get("hostiles_in_area") or 0):
            return False
    if _self_only(action):
        effects = _effects(action)
        if actor.temporary_hp >= max(1, actor.maximum_hp // 10) and \
                any(e.get("type") == "temp_hp" and e.get("applies_to") in (None, "self") for e in effects):
            return False  # recast once the shell is nearly gone
        if any(c.source_actor_id == actor.entity_id and same(c.source_definition_id) for c in actor.conditions.values()) or \
                any(same(m.source_definition_id) and not m.consumed for m in actor.modifiers.values()):
            return False
    return None
