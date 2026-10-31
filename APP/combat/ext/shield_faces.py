"""The Shield sphere's Faces: Flexible Cover, Seal the Breach, the Court, and what changes them (auto/H3, 2026-09-30; the lock round's
``directional_cover`` hook).

Rules text (the owner's Sphere Compendium, "The Shield", authority/typed_mechanics/rules_text.json):

  Flexible Cover  "Action. Choose one edge of your space and establish a physical Shield Face. The Shield Face provides
                  Three-Quarters Cover against attacks and effects whose routes cross the chosen edge toward a protected
                  creature directly behind that face. You may expend Martial Focus to use Flexible Cover as a Bonus Action. As a
                  Reaction, change the selected edge of your space." Until the start of your next turn.
  Projected Shield Face  "When using Flexible Cover, the Shield Face becomes a 15-foot-wide, 10-foot-high plane centered on the
                  chosen edge of your space ... remains attached to you, moves with you, and protects creatures behind it when an
                  attack or effect physically crosses its surface."
  Moving Rampart  "When you establish Flexible Cover: you may use it as a Bonus Action without expending Martial Focus; your
                  movement does not end the Shield Face; change the selected edge once during your turn without spending an
                  Action; allies may move with you behind the projected face, provided they remain within 5 feet of its
                  defended side. The Shield Face still ends at the start of your next turn."
  The Mountain Fits Behind One Shield  "When you establish Flexible Cover or Seal the Breach, increase the projected face to up to
                  30 feet wide and 20 feet high."
  Seal the Breach  "Bonus Action, Martial Focus, Concentration up to 1 minute. Manifest one 15-foot-wide, 15-foot-high Shield-Qi Face
                  centered on one edge of your space. It is a temporary Barrier attached to you. The face: moves with you; blocks
                  attacks, projectiles, breath weapons, line effects, and similar effects that must physically cross its surface
                  ... may be rotated once during your turn without spending an Action. It does not automatically block ... effects
                  originating behind the face. Ends if you stop wielding your Shield or have the Incapacitated condition."
  Court of Ten Thousand Turning Faces  "For the duration ... When you establish Flexible Cover, choose up to three different edges or
                  connected 5-foot segments inside the Court. Each becomes a projected Shield Face until the start of your next turn
                  ... Allies of your choice inside the Court gain Half Cover against ranged attacks originating outside the Court."

How it runs. A face is a condition on the shield-bearer (``condition:typed.shield_face``: kind, edge, width, and where it stands).
Geometry is the lock round's: each clear sight line between the attacker's and the target's footprint carries the square edges it
crosses (combat/directional_cover.py). A face gives Three-Quarters Cover (+5) to a line that enters a square directly behind the
face through it -- only inbound lines count (an ally behind the face shooting out is not covered against, an attack from beside the
face is not either). "Directly behind the face" is the row of squares along the face's width on the defended side: the bearer's own
space for a plain Face, the three squares (15 feet) behind a Projected one, six with the Mountain. Vertical extent (10 feet high) is
not modelled: the map has no elevation.

* A physical Flexible Cover Face ends when the bearer leaves its space. Projected Shield Face or Moving Rampart lets it move.
* Under the Court, Flexible Cover raises up to three projected Faces instead, on the edges of squares of the bearer or its allies inside
  the Court (a choice; the AI takes the most exposed allies' edges toward the nearest hostile). Those stand where they were raised.
* Seal the Breach is a Barrier: Total Cover, so a hostile attack that would have to cross it is not offered at all (``candidate_allowed``)
  and, for the attacks that reach the roll anyway, it is +5 like a Face. It goes with the bearer, ends with its Concentration (or after
  ten rounds, "up to 1 minute") or when the bearer is Incapacitated.
* The Reaction that turns a Flexible Cover Face is offered before an attack roll (the ``before_attack`` checkpoint): when the Face does
  not stop the attack but another edge would, the bearer may spend its Reaction to turn it there (the AI does).

Not modelled: cover against "effects" (a Dexterity save) -- the engine's save path has no directional hook, so a Face gives its cover to
attack rolls only; a Barrier does not stop movement (the map has no edge walls) or line effects that are not attacks; nothing here knows
whether the Shield is still in hand. Sovereign Shield-Soul Incarnation has a ten-round marker for wider Faces and their optional
Barrier attack cover; its flight and additional Shield-only Reaction rules are not represented here.

Shared Face-geometry API. The other Shield-sphere plug-ins that need to ask "does this line of effect cross that edge of that
space" use this module's public functions, never an underscore-prefixed one: enters says whether a ray crosses a named edge
through a given square, behind is the row of squares on the far side of a face, rays is an attack's clear lines, face_covers
and face_cover answer the cover a face grants, and raise_face is how a face is put up. combat/ext/meat_shield.py uses enters
for its own edge test; any other module that needs the same geometry must use these public names and be recorded here.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id, incapacitated

FACE = "condition:typed.shield_face"
FOCUS = "resource:core.martial_focus"
BLOCK = "shield_face"
CHOICE = "choice:shield."
EDGES = ("N", "E", "S", "W")
EDGE_WORDS = {"N": "north", "E": "east", "S": "south", "W": "west"}
TURNED = "shield_face_round_turned_"  # + the face's kind: the round the free "change the edge once during your turn" was used
COVER = 5  # Three-Quarters Cover
COURT_ID = "TAL_SHIELD_COURT_OF_TEN_THOUSAND_TURNING_FACES"
SOVEREIGN = "condition:typed.sovereign_shield_soul"
SEAL_ID = "TAL_SHIELD_SEAL_THE_BREACH"
FLEX_ID = "TAL_SHIELD_FLEXIBLE_COVER"
COURT_RANGE_FT = 30
BARRIER_ROUNDS = 10  # "Concentration, up to 1 minute"


# ------------------------------------------------------------------------------------------------ ownership
def kinds(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    """The Shield Face talents this character owns, by kind (combat/rules/feature_blocks.d/auto_h3.json)."""
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    return {str(row.get("kind")): row for row in rows if row.get("block") == BLOCK and row.get("kind")}


@hook("compile_block")
def _block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}] if block == BLOCK else None


def width_ft(engine: Any, actor: Any, *, barrier: bool = False) -> int:
    """How wide a face is: the bearer's own edge (0), the Projected plane (15 feet), the Mountain's (up to 30); a Barrier is 15."""
    owned = kinds(engine, actor)
    width = 30 if "mountain" in owned else 15 if barrier or "projected" in owned else 0
    if any(c.condition_id == SOVEREIGN for c in actor.conditions.values()) and (barrier or "projected" in owned):
        width += 20
    return width


@effect("sovereign_shield_soul")
def incarnate(ctx: Any, eff: dict[str, Any]) -> None:
    from .effect_durations import round_token

    ctx.engine._apply_condition(ctx.actor, SOVEREIGN, ctx.source, ctx.actor.entity_id,
                                expires_on=round_token(ctx.engine, 10), data={"label": "Sovereign Shield-Soul Incarnation"})


def barrier_choice(engine: Any, actor: Any) -> bool:
    if not any(c.condition_id == SOVEREIGN for c in actor.conditions.values()):
        return False
    picked = ask(engine, engine._active_intent, "SHIELD_BARRIER", actor,
                 "choice:shield.barrier:" + checkpoint_id(engine, "BARRIER", actor.entity_id), ["barrier", "cover"],
                 labels={"barrier": "Face is a Barrier", "cover": "Face grants cover and permits crossing"},
                 prompt="Sovereign Shield-Soul: does this new face form a Barrier?", preferred=["barrier"], automatic=True,
                 name="Sovereign Shield-Soul Incarnation")
    return picked == ["barrier"]


# ------------------------------------------------------------------------------------------------ geometry
def _box(cells: Any) -> tuple[int, int, int, int]:
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    return min(xs), max(xs), min(ys), max(ys)


def _span(low: int, high: int, wide_cells: int) -> list[int]:
    """The squares a face of ``wide_cells`` squares covers along an edge that spans low..high: at least the edge itself, the rest
    split evenly round it (the odd square of an even width goes to the higher side)."""
    length = high - low + 1
    if wide_cells <= length:
        return list(range(low, high + 1))
    extra = wide_cells - length
    left = extra // 2
    return list(range(low - left, high + (extra - left) + 1))


def behind(engine: Any, cells: Any, edge: str, wide_ft: int) -> list[tuple[int, int]]:
    """The squares directly behind a face raised on ``edge`` of a space of ``cells``: the row (or column) of squares on the
    defended side along the face's width."""
    x0, x1, y0, y1 = _box(cells)
    wide = max(1, wide_ft // 5) if wide_ft else 1
    if edge in ("N", "S"):
        y = y0 if edge == "N" else y1
        return [(x, y) for x in _span(x0, x1, wide) if 0 <= x < engine.grid.width]
    x = x0 if edge == "W" else x1
    return [(x, y) for y in _span(y0, y1, wide) if 0 <= y < engine.grid.height]


def _faces(engine: Any) -> list[tuple[Any, Any]]:
    out = []
    for holder in engine.state.actors.values():
        if not holder.active:
            continue
        for condition in holder.conditions.values():
            if condition.condition_id == FACE:
                out.append((holder, condition))
    return out


def _origin(engine: Any, holder: Any, data: dict[str, Any]) -> list[tuple[int, int]]:
    """The space a face stands on: the bearer's own (a Court face: the squares it was raised on)."""
    return [tuple(cell) for cell in data["cells"]] if data.get("cells") else list(engine._actor_cells(holder))


def _still_up(engine: Any, holder: Any, condition: Any) -> bool:
    data = condition.data
    if data.get("kind") == "barrier":
        return not incapacitated(holder) and engine.state.round_number <= int(data.get("until_round") or 0)
    return not (data.get("fixed") and holder.position.model_dump() != data.get("anchor"))


def rays(engine: Any, attacker: Any, target: Any) -> list[dict[str, Any]]:
    """Every clear footprint sight line from the attacker to the target with the square edges it crosses (as the core builds
    them for the ``directional_cover`` hook, combat/directional_cover.py)."""
    from ..directional_cover import sight_rays
    return [ray for _, _, ray in sight_rays(engine, attacker, target)]


def enters(ray: dict[str, Any], edge: str, squares: list[tuple[int, int]]) -> bool:
    wanted = {tuple(square) for square in squares}
    return any(row["direction"] == "enter" and row["edge"] == edge and tuple(row["cell"]) in wanted for row in ray["crossed_edges"])


def face_covers(engine: Any, cells: Any, edge: str, wide_ft: int, target: Any, ray: dict[str, Any], *, anywhere_behind: bool = False) -> bool:
    """Whether a face on ``edge`` of the space ``cells`` stops this line: it enters the row behind the face through the face, and
    the target stands in that row (a barrier: anywhere on the far side)."""
    squares = behind(engine, cells, edge, wide_ft)
    if not enters(ray, edge, squares):
        return False
    return anywhere_behind or bool(set(engine._actor_cells(target)) & set(squares))


def _stops(engine: Any, holder: Any, condition: Any, target: Any, ray: dict[str, Any]) -> bool:
    data = condition.data
    return face_covers(engine, _origin(engine, holder, data), str(data["edge"]), int(data.get("width_ft") or 0), target, ray,
                       anywhere_behind=data.get("kind") == "barrier" or bool(data.get("barrier")))


# ------------------------------------------------------------------------------------------------ the cover
@hook("directional_cover")
def face_cover(engine: Any, attacker: Any, target: Any, ray: dict[str, Any]) -> int | None:
    best = None
    for holder, condition in _faces(engine):
        if _still_up(engine, holder, condition) and _stops(engine, holder, condition, target, ray):
            best = COVER
    return best


def _court(engine: Any, owner: Any) -> Any | None:
    """The bearer's Court while it stands (a zone the Court's own action made)."""
    return next((zone for zone in engine.state.zones.values() if zone.active and zone.owner_id == owner.entity_id
                 and str(zone.source_definition_id).endswith(COURT_ID)), None)


def _in_court(engine: Any, owner: Any, creature: Any) -> bool:
    return engine.grid.distance_ft(owner.position, creature.position) <= COURT_RANGE_FT


@hook("cover")
def court_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """"Allies of your choice inside the Court gain Half Cover against ranged attacks originating outside the Court" (the AI chooses
    every ally)."""
    best = None
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id != target.team_id or _court(engine, owner) is None:
            continue
        if _in_court(engine, owner, target) and not _in_court(engine, owner, attacker):
            best = 2
    return best


# ------------------------------------------------------------------------------------------------ raising a face
def toward(engine: Any, actor: Any, other: Any) -> str:
    """The edge of the actor's space that looks at ``other``."""
    dx, dy = other.position.x - actor.position.x, other.position.y - actor.position.y
    if abs(dy) >= abs(dx):
        return "N" if dy < 0 else "S"
    return "W" if dx < 0 else "E"


def _nearest_hostile(engine: Any, actor: Any) -> Any | None:
    from ..senses import perceives
    foes = [other for other in engine.state.actors.values()
            if other.active and other.team_id != actor.team_id and perceives(engine, actor, other)]
    return min(foes, key=lambda o: (engine.grid.distance_ft(actor.position, o.position), o.entity_id), default=None)


def _face_of(actor: Any, kind: str = "flexible") -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == FACE and c.data.get("kind") == kind), None)


def _drop(engine: Any, actor: Any, kind: str, source: str) -> None:
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == FACE and held.data.get("kind") == kind:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=held.source_actor_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": FACE, "instance_id": iid})


def raise_face(engine: Any, actor: Any, edge: str, source: str, *, moving: bool | None = None) -> None:
    """Put (or replace) the bearer's Flexible Cover Face on ``edge``: until the start of its next turn."""
    owned = kinds(engine, actor)
    if moving is None:
        moving = "moving_rampart" in owned or "projected" in owned
    _drop(engine, actor, "flexible", source)
    _drop(engine, actor, "court", source)
    data = {"kind": "flexible", "edge": edge, "width_ft": width_ft(engine, actor), "fixed": not moving,
            "barrier": barrier_choice(engine, actor),
            "anchor": actor.position.model_dump(mode="json"), "label": f"Shield Face ({EDGE_WORDS[edge]} edge)"}
    engine._apply_condition(actor, FACE, source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data=data)


def pick_edge(engine: Any, intent: Any, actor: Any, prompt: str, *, preferred: str | None = None, allow_decline: bool = False,
              automatic: bool = True, exclude: tuple[str, ...] = (), name: str = "Shield Face") -> str | None:
    foe = _nearest_hostile(engine, actor)
    first = preferred or (toward(engine, actor, foe) if foe is not None else "N")
    options = [edge for edge in EDGES if edge not in exclude]
    if not options:
        return None
    picked = ask(engine, intent, "SHIELD_FACE_EDGE", actor, CHOICE + "edge:" + checkpoint_id(engine, "EDGE", actor.entity_id), options,
                 labels={edge: f"{EDGE_WORDS[edge].capitalize()} edge" for edge in EDGES}, prompt=prompt,
                 preferred=[first] if first in options else [], allow_decline=allow_decline, automatic=automatic,
                 target_id=actor.entity_id, default="decline" if allow_decline else "first", name=name)
    return picked[0] if picked and picked[0] in options else None


@hook("choice_options")
def _options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Every Shield choice (id "choice:shield.*"): the options and their bounds ride in the trigger context (as needle.py's)."""
    if not str(choice_id).startswith(CHOICE) or not (context or {}).get("needle_options"):
        return None
    spec = {"option_ids": list(context["needle_options"]), "minimum_selections": int(context.get("minimum", 1)),
            "maximum_selections": int(context.get("maximum", 1)), "allow_decline": bool(context.get("allow_decline", False)),
            "automatic_use": bool(context.get("automatic", True))}
    if context.get("preferred"):
        spec["preferred_option_ids"] = list(context["preferred"])
    return spec


def _court_options(engine: Any, actor: Any) -> tuple[list[str], dict[str, str], list[str]]:
    """Every (creature, edge) inside the Court a Face may stand on, with labels, and the AI's choice: the most exposed allies'
    edges toward the nearest hostile, three of them."""
    options, labels, exposure = [], {}, []
    for creature in sorted(engine.state.actors.values(), key=lambda c: c.entity_id):
        if not creature.active or creature.team_id != actor.team_id or not _in_court(engine, actor, creature):
            continue
        for edge in EDGES:
            key = f"{creature.entity_id}|{edge}"
            options.append(key)
            labels[key] = f"{creature.display_name}: {EDGE_WORDS[edge]} edge"
        foe = _nearest_hostile(engine, creature)
        if foe is not None:
            exposure.append((engine.grid.distance_ft(creature.position, foe.position), creature.entity_id,
                             f"{creature.entity_id}|{toward(engine, creature, foe)}"))
    return options[:64], labels, [key for _distance, _id, key in sorted(exposure)[:3]]


def _raise_court_faces(ctx: Any) -> bool:
    """Under the Court: up to three projected Faces on edges of the bearer's and its allies' squares inside it."""
    engine, actor = ctx.engine, ctx.actor
    options, labels, preferred = _court_options(engine, actor)
    if not options:
        return False
    picked = ask(engine, ctx.intent, "SHIELD_COURT_FACES", actor, CHOICE + "court:" + checkpoint_id(engine, "COURT", actor.entity_id), options,
                 labels=labels, prompt="Court of Ten Thousand Turning Faces: which edges (up to three) become projected Shield Faces?",
                 preferred=preferred, minimum=1, maximum=3, automatic=True, target_id=actor.entity_id,
                 name="Court of Ten Thousand Turning Faces")
    chosen = [key for key in dict.fromkeys(picked) if key in options][:3]
    if not chosen:
        return False
    _drop(engine, actor, "flexible", ctx.source)
    _drop(engine, actor, "court", ctx.source)
    wide = max(15, width_ft(engine, actor))
    for key in chosen:
        creature_id, _, edge = key.partition("|")
        creature = engine.state.actors[creature_id]
        data = {"kind": "court", "edge": edge, "width_ft": wide, "cells": [list(cell) for cell in engine._actor_cells(creature)],
                "barrier": barrier_choice(engine, actor),
                "label": f"Projected Shield Face ({creature.display_name}, {EDGE_WORDS[edge]} edge)"}
        engine._apply_condition(actor, FACE, ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data=data)
    ctx.rider(f"{actor.display_name}'s Court raises {len(chosen)} projected Shield Face(s) until the start of its next turn.")
    return True


@effect("shield_face")
def flexible_cover(ctx: Any, eff: dict[str, Any]) -> None:
    """Flexible Cover, however it is paid: choose the edge (the AI's is the one that looks at the nearest hostile); under a Court,
    up to three projected Faces inside it."""
    if _court(ctx.engine, ctx.actor) is not None and _raise_court_faces(ctx):
        return
    edge = pick_edge(ctx.engine, ctx.intent, ctx.actor, "Flexible Cover: which edge of your space does the Shield Face stand on?",
                     name="Flexible Cover")
    if edge is None:
        return
    raise_face(ctx.engine, ctx.actor, edge, ctx.source)
    ctx.rider(f"{ctx.actor.display_name} raises a Shield Face on the {EDGE_WORDS[edge]} edge of its space until the start of its next turn.")


@effect("shield_barrier")
def seal_the_breach(ctx: Any, eff: dict[str, Any]) -> None:
    """Seal the Breach: a Barrier face on one edge of the bearer's space, for as long as it concentrates (up to a minute)."""
    engine, actor = ctx.engine, ctx.actor
    edge = pick_edge(engine, ctx.intent, actor, "Seal the Breach: which edge of your space does the Barrier stand on?",
                     name="Seal the Breach")
    if edge is None:
        return
    _drop(engine, actor, "barrier", ctx.source)
    data = {"kind": "barrier", "edge": edge, "width_ft": width_ft(engine, actor, barrier=True),
            "until_round": engine.state.round_number + BARRIER_ROUNDS, "label": f"Seal the Breach ({EDGE_WORDS[edge]} edge)"}
    engine._apply_condition(actor, FACE, ctx.source, actor.entity_id, expires_on="CONCENTRATION_END", data=data)
    ctx.rider(f"{actor.display_name} seals the {EDGE_WORDS[edge]} edge of its space with a Shield-Qi Barrier while it concentrates.")


@effect("shield_face_turn")
def turn_face(ctx: Any, eff: dict[str, Any]) -> None:
    """Change the selected edge (the Reaction, or the once-a-turn free change of Moving Rampart / Seal the Breach)."""
    kind = str(eff.get("face") or "flexible")
    face = _face_of(ctx.actor, kind)
    if face is None:
        return
    edge = pick_edge(ctx.engine, ctx.intent, ctx.actor,
                     "Flexible Cover: turn your Shield Face to which edge? (uses your Reaction)" if not eff.get("free")
                     else "Turn your Shield Face to which edge? (free, once on your turn)",
                     exclude=(face.data["edge"],), automatic=True,
                     name="Flexible Cover" if kind == "flexible" else "Seal the Breach")
    if edge is None:
        return
    if not eff.get("free"):
        from ..typed_reactions import publish_reaction_used, spend_reaction
        notice = {"feature_id": FLEX_ID, "name": "Flexible Cover", "target_ids": (ctx.actor.entity_id,)}
        spend_reaction(ctx.engine, ctx.actor, notice)
        publish_reaction_used(ctx.engine, ctx.actor, notice)
    _rotate(ctx.engine, ctx.actor, face, edge, ctx.source)
    if eff.get("free"):
        ctx.actor.turn_flags[TURNED + kind] = ctx.engine.state.round_number


def _rotate(engine: Any, actor: Any, face: Any, edge: str, source: str) -> None:
    """The same face on another edge (a condition is never edited in place): it keeps its expiry, its source and where it stands."""
    barrier = face.data.get("kind") == "barrier"
    data = {**face.data, "edge": edge, "label": f"Seal the Breach ({EDGE_WORDS[edge]} edge)" if barrier else f"Shield Face ({EDGE_WORDS[edge]} edge)"}
    expires, source_id = face.expires_on, face.source_definition_id
    for iid, held in list(actor.conditions.items()):
        if held is face:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": FACE, "instance_id": iid})
    engine._apply_condition(actor, FACE, source_id, actor.entity_id, expires_on=expires, data=data)
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id,
                         payload={"trigger": f"{actor.display_name} turns the Shield Face to the {EDGE_WORDS[edge]} edge."})


# ------------------------------------------------------------------------------------------------ the Reaction: turn the face
def _covers_all(engine: Any, holder: Any, edge: str, wide: int, attacker: Any, target: Any) -> bool:
    lines = rays(engine, attacker, target)
    cells = list(engine._actor_cells(holder))
    return bool(lines) and all(face_covers(engine, cells, edge, wide, target, line) for line in lines)


@hook("before_attack")
def turn_before_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """"As a Reaction, change the selected edge of your space": before an attack roll against the bearer, when the face does not
    already stop it and another edge would. Nothing changes the roll's mode -- only the cover the roll meets."""
    if defender is None or attacker is None or defender.team_id == attacker.team_id or not defender.active:
        return None
    face = _face_of(defender)
    if face is None or not defender.reaction_available or incapacitated(defender) or not _still_up(engine, defender, face):
        return None
    wide = int(face.data.get("width_ft") or 0)
    if _covers_all(engine, defender, face.data["edge"], wide, attacker, defender):
        return None
    better = [edge for edge in EDGES if edge != face.data["edge"] and _covers_all(engine, defender, edge, wide, attacker, defender)]
    if not better:
        return None
    picked = ask(engine, intent, "SHIELD_FACE_TURN", defender,
                 CHOICE + "turn:" + checkpoint_id(engine, "TURN", attacker.entity_id, defender.entity_id, context.get("attack_index", 1)),
                 better, labels={edge: f"Turn the Face to the {EDGE_WORDS[edge]} edge" for edge in EDGES},
                 prompt=f"Turn your Shield Face against {attacker.display_name}'s attack? (uses your Reaction)", preferred=better[:1],
                 allow_decline=True, automatic=True, target_id=attacker.entity_id, default="first", name="Flexible Cover")
    if not picked or picked[0] not in better:
        return None
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, defender, f"reaction:shield_face:{defender.entity_id}", independent=True):
        defender.reaction_available = False
        _rotate(engine, defender, face, picked[0], f"reaction:shield_face:{defender.entity_id}")
        return {}


# ------------------------------------------------------------------------------------------------ the bearer moves, a barrier ends
@hook("event")
def face_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A physical Face ends when the bearer leaves its space (Projected Shield Face or Moving Rampart lets it move); a
    Barrier ends when its bearer is Incapacitated or its minute is up."""
    if event_type not in ("MOVEMENT_COMMITTED", "CONDITION_APPLIED", "TURN_STARTED"):
        return
    for holder, condition in _faces(engine):
        if _still_up(engine, holder, condition):
            continue
        for iid, held in list(holder.conditions.items()):
            if held is condition:
                del holder.conditions[iid]
                engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                                     payload={"condition_id": FACE, "instance_id": iid})
        engine._append_event("PASSIVE_TRIGGERED", condition.source_definition_id, actor_id=holder.entity_id,
                             payload={"trigger": f"{holder.display_name}'s {condition.data.get('label', 'Shield Face')} ends."})


# ------------------------------------------------------------------------------------------------ the buttons
@hook("compile_actions")
def face_buttons(info: dict[str, Any]) -> list[Any] | None:
    """The other ways to use Flexible Cover: a Bonus Action for Martial Focus (or for nothing with Moving Rampart), turning the
    face (a Reaction; free once during your turn with Moving Rampart); and turning Seal the Breach's Barrier once during your turn."""
    owned = set(info["owned_ids"])
    if FLEX_ID not in owned and SEAL_ID not in owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    base = {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []}
    rows = []
    if FLEX_ID in owned:
        rampart = "TAL_SHIELD_MOVING_RAMPART" in owned
        name = str(info["mechanics"][FLEX_ID].get("name") or "Flexible Cover")
        rows.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.flexible_cover.bonus", display_name=f"{name} (Bonus Action)" if rampart
            else f"{name} (Martial Focus, Bonus Action)", owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION,
            resolution_kind="TYPED", target_kind="SELF", costs=() if rampart else ((FOCUS, 1),),
            parameters={"typed": {**base, "effects": [{"type": "shield_face"}], "source": "shield.flexible_cover.bonus"}, "expected_damage": 0,
                        "player_only": True}))
        rows.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.flexible_cover.turn", display_name=f"Turn {name} face (free, once a turn)" if rampart
            else f"Turn {name} face (Reaction)", owner_id=info["actor_id"], economy=EconomyKind.NONE,
            resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {**base, "effects": [{"type": "shield_face_turn", "free": rampart, "face": "flexible"}],
                                  "source": "shield.flexible_cover.turn"}, "expected_damage": 0}))
    if SEAL_ID in owned:
        name = str(info["mechanics"][SEAL_ID].get("name") or "Seal the Breach")
        rows.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.seal_the_breach.turn", display_name=f"Turn {name} face (free, once a turn)",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {**base, "effects": [{"type": "shield_face_turn", "free": True, "face": "barrier"}],
                                  "source": "shield.seal_the_breach.turn"}, "expected_damage": 0}))
    return rows


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _makes_attack(action: Any) -> bool:
    if action is None:
        return False
    if action.attack_bonus is not None:
        return True
    return any(isinstance(row, dict) and row.get("type") == "attack" for row in _typed(action).get("effects") or [])


@hook("candidate_allowed")
def face_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Turning a face needs a face to turn (free once a turn for a Barrier or with Moving Rampart); a hostile attack that has to cross a
    Barrier to reach its target is not offered (Total Cover: it "blocks attacks, projectiles ... that must physically cross its surface")."""
    source = _typed(action).get("source") if action is not None else None
    if source in ("shield.flexible_cover.turn", "shield.seal_the_breach.turn"):
        barrier = source == "shield.seal_the_breach.turn"
        kind = "barrier" if barrier else "flexible"
        if _face_of(actor, kind) is None:
            return False
        if barrier or "moving_rampart" in kinds(engine, actor):
            return actor.turn_flags.get(TURNED + kind) != engine.state.round_number
        from ..typed_executor import condition_rules
        from ..typed_reactions import reaction_waived
        return actor.active and not any(rule.get("no_reactions") for rule in condition_rules(actor)) and (
            actor.reaction_available or reaction_waived(engine, actor, {"feature_id": FLEX_ID}))
    targets = getattr(candidate, "target_ids", None) or ()
    if not targets or not _makes_attack(action):
        return None
    barriers = [(holder, c) for holder, c in _faces(engine)
                if (c.data.get("kind") == "barrier" or c.data.get("barrier")) and _still_up(engine, holder, c)]
    if not barriers:
        return None
    for target_id in targets:
        target = engine.state.actors.get(target_id)
        if target is None or target.team_id == actor.team_id:
            continue
        lines = rays(engine, actor, target)
        if lines and all(any(_stops(engine, holder, c, target, line) for holder, c in barriers) for line in lines):
            return False
    return None


@hook("ai_candidate_allowed")
def face_ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """AI may voluntarily turn an existing face, with the same payment/turn limits.

    Raising a second face and the alternate bonus-form remain unnecessary for
    the built-in policy; edge selection uses only its perceived hostiles.
    """
    if action is None:
        return None
    typed = _typed(action)
    if typed.get("source") == "shield.flexible_cover.bonus":
        return False
    if typed.get("source") == FLEX_ID:
        return _face_of(actor) is None and _face_of(actor, "court") is None
    return None
