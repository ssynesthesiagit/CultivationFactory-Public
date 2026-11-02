"""Defensive Rider and Meat Shield (Beastmastery, Rider) on the lock round's ``retarget_attack`` hook (automation lane H2,
2026-09-29; through the shared owner combat/ext/redirection.py).

Owner text (rules_text.json):
  Defensive Rider -- "When an attack targets your mount, redirect the attack to yourself. No Action is required. You must be
    riding the mount and remain a legal target."
  Meat Shield (Bonus Action, until ended) -- "While mounted on a creature of your size or larger, choose one edge of your space.
    Your mount grants Total Cover against attacks targeting you that cross that edge. The mount remains targetable normally. You
    cannot use Defensive Rider while using the mount as cover. Reactive Cover: Expend Martial Focus to activate Meat Shield as a
    Reaction when targeted by an attack roll. The attack targets the mount instead. End Meat Shield without spending an Action on
    your turn."
No Spheres 5e or D&D 5.5e counterpart (5.5e Mounted Combat: "you can force an attack against your mount to target you instead" is
the closest and agrees with Defensive Rider).

How it runs
  * Defensive Rider is automatic ("redirect the attack"; no Action, no choice): a hostile attack aimed at the mount is re-aimed at
    the rider when the rider is on it (mounts.rider_of), is a legal target of that very attack (sight and range, the engine's own
    test) and is not using Meat Shield. The retarget hook records ATTACK_RETARGETED; the attack is then rolled against the rider.
  * Meat Shield is the compiled Bonus Action: it asks which edge of the rider's square (north/east/south/west; y grows south) and
    holds ``condition:typed.meat_shield`` until the free "End Meat Shield" action, the rider's dismount or the mount's fall. Total
    Cover means the rider cannot be targeted across that edge: the attack candidates that would do it are not offered to anyone
    (candidate_allowed), and an attack that reaches the rider anyway (a reaction attack) is re-aimed at the mount, which "remains
    targetable normally". Covered = every clear line from the attacker to the rider's square enters it through that edge.
  * Reactive Cover: when an attack roll is about to be made against the rider (the retarget checkpoint), a rider with Martial
    Focus and a Reaction may spend both to activate Meat Shield (choosing the edge) and turn that attack onto the mount. The
    table asks the player (the choice transport, with a decline); the built-in AI accepts while its mount has at least as many Hit
    Points as it does.
Judgment calls: Defensive Rider only answers hostile attackers; Reactive Cover leaves Meat Shield active on the chosen edge (it
"activates Meat Shield"). The mounted creature must have at least the rider's footprint, matching the printed size requirement.

Shared Meat Shield API. The single Meat Shield implementation lives here; combat/ext/meat_shield.py is the compatibility
surface other plug-ins use and reaches only for this module's public names: held is the rider's own Meat Shield state,
activate_cover puts the mount's chosen edge up as cover, offered is the candidate_allowed hook, defensive_allowed is the
row_allowed hook, and available/edge_of/covered answer the mount and edge questions. A further consumer must use these
public names, never an underscore-prefixed one.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .redirection import legal_target, owns, provider
from ..knowledge_policy import enabled, roster

SHIELD = "condition:typed.meat_shield"
FOCUS = "resource:core.martial_focus"
KEY = "TAL_BEASTMASTERY_MEAT_SHIELD"
EDGES = {"N": "north", "E": "east", "S": "south", "W": "west"}
DEFENSIVE = "ability:defensive_rider"
COVER = "ability:meat_shield"


@hook('decision_text')
def meat_shield_decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    source = context.get('reaction_source_id')
    if source not in (CHOICE + 'meat_shield_edge', CHOICE + 'meat_shield'):
        return None
    rider = engine.state.actors.get(context.get('reactor_id'))
    if rider is None or not owns(engine, rider, 'meat_shield'):
        return None
    reactive = source == CHOICE + 'meat_shield'
    return {'feature_id': KEY,
            'cost': 'Reaction and 1 Martial Focus if used' if reactive else 'Bonus Action already spent; no resource cost',
            'summary': 'Choose one edge for your mount to cover. It gives you Total Cover: attacks crossing that edge cannot target you. '
                       + ('This triggering attack targets your mount instead. ' if reactive else '')
                       + 'Your mount remains targetable normally.',
            'limits': 'The cover lasts until you end Meat Shield on your turn without an action, dismount, or the mount falls. '
                      'You cannot use Defensive Rider to redirect attacks from your mount to yourself while this cover is active.',
            'option_descriptions': {key: f'Your mount blocks attacks crossing the {name} edge of your space until Meat Shield ends.'
                                    for key, name in EDGES.items()}}


@hook("status_description")
def cover_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if row.get("condition_id") != SHIELD:
        return None
    from ..status_text import printed_excerpt

    edge = EDGES.get(str(data.get("edge") or ""), "chosen")
    return {"text": printed_excerpt(KEY) + f" The covered edge is {edge}.", "source_ability": "Meat Shield",
            "handling": "The table checks Total Cover across that edge. It ends when you end Meat Shield, dismount, or the mount falls."}


# ------------------------------------------------------------------------------------------------ state
def _mounts():
    from . import mounts

    return mounts


def held(actor: Any) -> Any | None:
    return next((row for row in actor.conditions.values() if row.condition_id == SHIELD), None)


def available(engine: Any, rider: Any) -> Any | None:
    mount = _mounts().mount_of(engine, rider)
    if mount is None or len(engine._actor_cells(mount)) < len(engine._actor_cells(rider)):
        return None
    return mount


def edge_of(engine: Any, rider: Any) -> str | None:
    """The edge the rider's mount is covering, while the pair is still together."""
    shield = held(rider)
    mount = available(engine, rider)
    if shield is None or mount is None or (shield.data or {}).get("mount") != mount.entity_id:
        return None
    return (shield.data or {}).get("edge")


def activate_cover(engine: Any, rider: Any, mount: Any, edge: str, how: str = "Bonus Action") -> None:
    engine._remove_condition(rider, SHIELD, COVER)
    engine._apply_condition(rider, SHIELD, COVER, mount.entity_id, expires_on="UNTIL_REMOVED",
                            data={"edge": edge, "mount": mount.entity_id, "label": f"Meat Shield: {EDGES[edge]} edge"})
    note(engine, COVER, rider, f"{rider.display_name} uses {mount.display_name} as cover on the {EDGES[edge]} edge ({how}).", [mount])


def _facing(rider: Any, other: Any) -> str:
    """The edge of the rider's square that faces ``other`` (y grows south)."""
    dx, dy = other.position.x - rider.position.x, other.position.y - rider.position.y
    if abs(dx) >= abs(dy):
        return "E" if dx > 0 else "W"
    return "S" if dy > 0 else "N"


def covered(engine: Any, attacker: Any, rider: Any, edge: str) -> bool:
    """Total Cover from ``edge``: every clear line from the attacker to the rider's square enters it through that edge."""
    from ..directional_cover import crossed_edges
    from ..gate2_runtime_models import Position

    obscured, lines = engine._obscured_cells(), []
    for start in sorted(engine._actor_cells(attacker)):
        for end in sorted(engine._actor_cells(rider)):
            if engine.grid.line_of_sight(Position(x=start[0], y=start[1]), Position(x=end[0], y=end[1]), obscured_cells=obscured):
                lines.append((end, crossed_edges(start, end)))
    return bool(lines) and all(any(row["cell"] == list(end) and row["edge"] == edge and row["direction"] == "enter" for row in crossing)
                               for end, crossing in lines)


def _can_react(engine: Any, actor: Any) -> bool:
    from .. import typed_reactions

    return typed_reactions._can_react(engine, actor)


# ------------------------------------------------------------------------------------------------ Defensive Rider
@provider(10)
def defensive_rider(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    rider = _mounts().rider_of(engine, defender)
    if (rider is None or rider.team_id == attacker.team_id or not owns(engine, rider, "defensive_rider")
            or edge_of(engine, rider) is not None or not legal_target(engine, attacker, rider, context.get("range_ft"))):
        return None
    return {"source_id": DEFENSIVE, "target_id": rider.entity_id, "cover_bonus": 0}


# ------------------------------------------------------------------------------------------------ Meat Shield
@provider(20)
def meat_shield(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    mount = available(engine, defender)
    if mount is None or defender.team_id == attacker.team_id or not owns(engine, defender, "meat_shield"):
        return None
    range_ft = context.get("range_ft")
    edge = edge_of(engine, defender)
    if edge is not None and covered(engine, attacker, defender, edge):
        # Total Cover: the rider cannot be targeted across that edge, the mount remains targetable normally.
        return {"source_id": COVER, "target_id": mount.entity_id, "cover_bonus": 0} if legal_target(engine, attacker, mount, range_ft) else None
    if (defender.resources.get(FOCUS, 0) < 1 or not _can_react(engine, defender) or not legal_target(engine, attacker, mount, range_ft)):
        return None
    known_attacker = next((other for other in roster(engine, defender) if other.entity_id == attacker.entity_id), None)
    facing = _facing(defender, known_attacker) if known_attacker is not None else (edge_of(engine, defender) or "N")
    attack = engine.action_catalog.get(context.get('source_id'))
    attack_name = context.get('action_name') or (attack.display_name if attack else 'attack')
    picked = ask(engine, intent, checkpoint_id(engine, "MEAT_SHIELD", defender.entity_id, attacker.entity_id), defender,
                 CHOICE + "meat_shield", list(EDGES), labels={key: f"Reactive Cover: the {name} edge (1 Martial Focus and your Reaction)" for key, name in EDGES.items()},
                 preferred=[facing], prompt=f"Meat Shield: put {mount.display_name} between {defender.display_name} and {attacker.display_name}'s {attack_name}?",
                 name='Meat Shield', feature_id=KEY, allow_decline=True, minimum=1, maximum=1,
                 automatic=mount.current_hp >= defender.current_hp, target_id=defender.entity_id, default="decline")
    if not picked:
        return None
    with activation(engine, defender, COVER):
        engine._spend_resource(defender, FOCUS, 1, COVER)
        defender.reaction_available = False
        activate_cover(engine, defender, mount, picked[0], "Reactive Cover")
        engine._append_event("REACTION_RESOLVED", COVER, actor_id=defender.entity_id, target_ids=(attacker.entity_id,),
                             payload={"reaction": "reactive_cover", "edge": picked[0]})
        return {"source_id": COVER, "target_id": mount.entity_id, "cover_bonus": 0}


@effect("meat_shield")
def _bonus_action(ctx: Any, spec: dict[str, Any]) -> None:
    engine, rider = ctx.engine, ctx.actor
    mount = available(engine, rider)
    if mount is None:
        ctx.rider("Meat Shield needs a mount to stand behind.")
        return
    foes = [other for other in roster(engine, rider) if other.active and other.team_id != rider.team_id]
    nearest = min(foes, key=lambda other: (engine._distance_actor_to_actor(rider, other), other.entity_id), default=None)
    facing = _facing(rider, nearest) if nearest is not None else (edge_of(engine, rider) if enabled(engine) else None) or "N"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "MEAT_SHIELD_EDGE", rider.entity_id), rider, CHOICE + "meat_shield_edge", list(EDGES),
                 labels={key: f"Meat Shield: the {name} edge" for key, name in EDGES.items()}, preferred=[facing],
                 prompt=f"Meat Shield: which edge should {mount.display_name} cover for {rider.display_name}?",
                 name="Meat Shield: choose cover direction", feature_id=KEY, target_id=rider.entity_id)
    activate_cover(engine, rider, mount, picked[0] if picked else facing, "Bonus Action")


@hook("button_description")
def end_description(row: dict[str, Any]) -> str | None:
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "end_meat_shield" for eff in effects):
        return "On your turn, end Meat Shield without spending an action or cultivation points. Your mount stops giving you Total Cover along the chosen edge; you may use Defensive Rider again."
    return None


@effect("end_meat_shield")
def _end(ctx: Any, spec: dict[str, Any]) -> None:
    if held(ctx.actor) is not None:
        ctx.engine._remove_condition(ctx.actor, SHIELD, COVER)


@hook("compile_actions")
def _actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if KEY not in info["owned_ids"]:
        return None
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.meat_shield.end", display_name="End Meat Shield", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "end_meat_shield"}], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [],
                              "source": "meat_shield.end"},
                    "expected_damage": 0, "player_only": True, "requires_condition": SHIELD})]


def _is_attack(action: Any) -> bool:
    if action is None:
        return False
    if getattr(action, "attack_bonus", None) is not None or getattr(action, "resolution_kind", None) in ("ATTACK", "MULTI_ATTACK", "ATTACK_THEN_SAVE"):
        return True
    return any(row.get("type") == "attack" for row in ((action.parameters or {}).get("typed") or {}).get("effects") or [])


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = ((action.parameters or {}).get("typed") or {}).get("source") if action is not None else None
    if source == KEY and action.owner_id == actor.entity_id:
        return False if available(engine, actor) is None else None  # nothing to stand behind
    if not candidate.target_ids or not _is_attack(action):
        return None
    for target_id in candidate.target_ids:
        rider = engine.state.actors.get(target_id)
        if rider is None or rider.team_id == actor.team_id or held(rider) is None:
            continue
        edge = edge_of(engine, rider)
        if edge is not None and covered(engine, actor, rider, edge):
            return False  # Total Cover: it cannot be targeted from there
    return None


@hook("row_allowed")
def defensive_allowed(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") == "TAL_BEASTMASTERY_DEFENSIVE_RIDER" and edge_of(engine, actor) is not None:
        return False
    return None


@hook("ai_candidate_allowed")
def _ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = ((action.parameters or {}).get("typed") or {}).get("source") if action is not None else None
    if source == KEY and action.owner_id == actor.entity_id:
        return edge_of(engine, actor) is None  # the built-in AI raises it once, and never lowers it by choice
    return None


@hook("turn_start")
def _tidy(engine: Any, actor: Any) -> None:
    """Meat Shield ends when the rider is no longer on that mount."""
    if held(actor) is not None and edge_of(engine, actor) is None:
        engine._remove_condition(actor, SHIELD, COVER)
