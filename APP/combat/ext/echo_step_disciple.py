"""Echo-Step Disciple (Spirit Awakening Tradition; subpaths worker 2026-09-28, rider lane C8 2026-09-30: "i want everything we can
automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "29. Echo-Step Disciple": Echo Positions, CL3 Afterimage Edge, CL6 Echo Counter,
CL10 Three-Step Soul Execution, CL14 Pursuit Without Distance, CL18 Hundred Echoes Kill One Moment). No Spheres 5e or D&D 5.5e
counterpart. Ownership: Afterimage Edge's ``echo_step_disciple`` row (feature_blocks.d/subpaths.json) and the ``spirit_tradition``
rows of feature_blocks.d/riders_c8.json (Echo Counter, Pursuit Without Distance); every hook returns early without them.

Echo Positions (tradition text): 5-foot spaces you occupied and recorded -- up to your Proficiency Bonus (the oldest removed), each
lasting until the end of your next turn; Hundred-Echo positions last with the State and do not count. A recorded square that becomes
a wall no longer counts. They are conditions on you ("Echo Position at x,y"), so they are saved with the fight.

What runs:
  * Record the Killing Step: once on each of your turns, when your own movement this turn reaches 10 feet, one square you occupied
    during it becomes an Echo Position (asked; the AI records where it started).
  * Strike From the Echo (once on each of your turns): "Strike From the Echo: <attack>" buttons for Mind Spike and each weapon
    attack (not an improvised weapon), aimed at a creature that is legal -- reach or range, and line of sight -- from one of your
    Echo Positions within 20 feet (asked which, when several). If it is Resonance Marked by you, your Wisdom modifier is added to one
    damage roll. The Echo is consumed; then Step Through the Opening (asked): 1 Resonance to move to it without provoking.
    (Before: the Wisdom bonus rode every hit on a marked creature and the Echo was the GM's.)
  * Echo Counter (Reaction, 2 Resonance, when a creature you can see attacks you; asked, the AI uses it when it can get out of
    reach): your space becomes an Echo Position and you move 10 feet without provoking; out of its reach the attack misses,
    otherwise you have +2 AC against it. If it misses, choose one: 2d8 + Wisdom Psychic to the attacker, Mind Spike against it with
    one damage die fewer, move to another Echo Position within 20 feet, or (Resonance Marked) no Reactions until the start of its
    next turn. Cross the Blade-Hum: a hostile creature that moves through or ends its move in one of your Echo Positions (once per
    turn) -- you may consume it (asked): Wisdom save, failed: Speed 0 for the rest of the turn and Resonance Marked until the end of
    your next turn; success: Speed -10 for the rest of the turn.
  * Three-Step Soul Execution (Action, 5 Resonance): up to three origins among your space and your Echo Positions, each within 30 feet
    of the one before; from each, a Cultivation Attack on a creature within 5 feet of it (3d8; 2d8 on a creature already hit), then an
    optional move there without provoking; the Echoes used are consumed; three hits on one Resonance Marked creature: its Charisma
    save (the reviewed rows).
  * Pursuit Without Distance: when you damage a creature Resonance Marked by you, 2 Resonance (asked) turns that mark into a Pursuit
    Mark for the fight -- one at a time, and it counts as your Resonance Mark. The bearer may use its Action ("Shake off the Pursuit
    Mark") for a Charisma save against your DC to end it. Follow the Vanishing Point (Reaction, 4 Resonance; the generic "bearing
    your Pursuit Mark moves at least 15 feet" row): move up to your Speed without provoking to within 10 feet of where it stopped
    (as near as you can), or to an Echo Position within 60 feet and use Mind Spike on it; then record your space.
  * Hundred Echoes Kill One Moment (Bonus Action, 10 Resonance, Concentration, 1 minute): the Hundred-Echo State -- your space is
    recorded at the start and end of each of your turns (lasting with the State), you do not provoke Opportunity Attacks, the map's
    (nonmagical) difficult terrain costs you nothing. One Soul, Many Edges (once on each of your turns, after Mind Spike, a weapon
    attack or a single-target Spirit Awakening technique): up to three Echo Positions within 60 feet each pick a creature legal from
    it; each picked creature takes 2d8 Psychic or Force once (4d8 when your Pursuit Mark target was picked more than once). Moment
    of the Final Edge (Action, once per State): to an Echo Position (or your space) from which the final attack is legal on a
    creature within 120 feet, by spiritual step, then a Cultivation Attack for 10d10, a weapon attack, or Mind Spike with maximum
    damage dice (within 30 feet); on a hit or failed save its Charisma save -- failed: choose two, success: choose one, of no
    Reactions / Speed 0 / no healing / Prone. After the Last Echo: when the State ends every Echo Position and Pursuit Mark you made
    ends and you cannot take Reactions until the start of your next turn.

A2GTRA2: Three-Step Soul Execution asks once for the whole technique's damage type;
Hundred-Echo State grants free passage through hostile spaces via native pass_through.
Stopping in an occupied space remains illegal.

Plug-in surface: effects echo_strike, echo_three_step, echo_hundred_state, echo_final_edge, echo_follow, echo_shake_pursuit; hooks
compile_block, compile_actions, candidate_allowed, event, before_attack, hit_response, damage_dealt, mark_apply, technique_used,
turn_start, turn_end, difficult_exempt, match_start, additional_actions. Shared helpers used: spirit_traditions (row/context/numbers/feature_action/
routes/choose_route/pick_creature/can_react/plain_difficult/is_spirit_feature/action_named/run_action/mind_spike/save/remove), needle
(ask/checkpoint_id/cell_id/position_of/step_to), rider_movement.step, typed_executor (Context/run_effects/effect_expiry/bears_mark/
mark_condition_id).
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

import copy
from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.echo_step_disciple.feature."
AFTERIMAGE_EDGE = TRADITION + "afterimage_edge"
COUNTER = TRADITION + "echo_counter"
THREE_STEP = TRADITION + "three_step_soul_execution"
PURSUIT = TRADITION + "pursuit_without_distance"
HUNDRED = TRADITION + "hundred_echoes_kill_one_moment"
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
ECHO = "condition:typed.echo_position"
STATE = "condition:typed.hundred_echo_state"
TRACE = "condition:typed.hundred_echo_trace"
FINAL_USED = "condition:typed.final_edge_used"
PURSUIT_MARK = "Pursuit Mark"
RESONANCE = "resource:core.resonance"
SHAKE = "system:combat.shake_off_the_pursuit_mark"
ENGINE_OUT_OF_REACH = "moved out of the attack's reach"  # the engine's own GM_RIDER when a defender left an attack's reach
_COUNTER = "_c8_echo_counter"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "echo_step_disciple" and row.get("kind") == "strike_from_the_echo"]


@hook("compile_block")
def echo_step_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "echo_step_disciple":
        return None
    return [{**row, "block": "echo_step_disciple", "kind": spec.get("kind")}]


def _pos(cell: Any) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=int(cell[0]), y=int(cell[1]))


def _free(engine: Any, actor: Any, cell: Any) -> bool:
    return engine.grid.placement_legal(cell, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id))


def _label(option: str) -> str:
    from . import needle

    cell = needle.position_of(option)
    return f"{cell.x},{cell.y}"


# ------------------------------------------------------------------------------------------------------------ Echo Positions
def echoes(actor: Any) -> list[Any]:
    return sorted((c for c in actor.conditions.values() if c.condition_id == ECHO and c.source_actor_id == actor.entity_id),
                  key=lambda c: c.applied_sequence)


def echo_cells(engine: Any, actor: Any) -> list[tuple[int, int]]:
    """The actor's Echo Positions, oldest first; a square that has become a wall no longer counts ("destroyed terrain")."""
    blocked = getattr(engine.grid, "blocked", set()) or set()
    cells = []
    for held in echoes(actor):
        cell = tuple((held.data or {}).get("cell") or ())
        if len(cell) == 2 and cell not in blocked and cell not in cells:
            cells.append(cell)
    return cells


def record(engine: Any, actor: Any, cell: Any, source: str, *, state: Any = None) -> None:
    for held in [c for c in echoes(actor) if tuple((c.data or {}).get("cell") or ()) == (cell.x, cell.y)]:
        st.remove(engine, actor, held, "REPLACED")
    if state is None:
        normal = [c for c in echoes(actor) if not (c.data or {}).get("state")]
        limit = max(1, int(st.numbers(engine, actor).get("pb") or 2))
        while len(normal) >= limit:
            st.remove(engine, actor, normal.pop(0), "REPLACED")  # "Recording a new position beyond the limit removes the oldest"
        ctx = st.context(engine, actor, st.feature_action(engine, actor, AFTERIMAGE_EDGE), [actor])
        expires = _te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_your_next_turn"}}, actor, condition=True)
        source_id = source
    else:  # "These State-created positions last until the State ends" (and do not count against the limit)
        expires, source_id = "CONCENTRATION_END", state.source_definition_id
    engine._apply_condition(actor, ECHO, source_id, actor.entity_id, expires_on=expires,
                            data={"cell": [int(cell.x), int(cell.y)], **({"state": 1} if state is not None else {}),
                                  "label": f"Echo Position at {cell.x},{cell.y}"})


def consume(engine: Any, actor: Any, cell: tuple[int, int]) -> None:
    for held in echoes(actor):
        if tuple((held.data or {}).get("cell") or ()) == tuple(cell):
            st.remove(engine, actor, held, "CONSUMED")


@hook("event")
def echo_movement(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "MOVEMENT_COMMITTED":
        mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        payload = kwargs.get("payload") or {}
        path = payload.get("path") or []
        if mover is None or not mover.active or payload.get("forced") or payload.get("dragged_by") or len(path) < 2:
            return
        if _rows(engine, mover) and engine.state.current_actor_id == mover.entity_id:
            _killing_step(engine, mover, path)
        _blade_hum(engine, mover, path)
    elif event_type in ("CONCENTRATION_ENDED", "PASSIVE_TRIGGERED"):  # after the engine has taken off what lasted with it (never mid-removal)
        actor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        if actor is not None:
            _after_the_last_echo(engine, actor)


def _killing_step(engine: Any, actor: Any, path: list[dict[str, Any]]) -> None:
    cells = list(actor.turn_flags.get("echo_step_path") or [])
    for square in path:
        cell = [int(square["x"]), int(square["y"])]
        if cell not in cells:
            cells.append(cell)
    actor.turn_flags["echo_step_path"] = cells
    moved = int(actor.turn_flags.get("echo_step_moved") or 0) + (len(path) - 1) * engine.grid.square_size_ft
    actor.turn_flags["echo_step_moved"] = moved
    if moved < 10 or actor.turn_flags.get("echo_step_recorded"):
        return
    actor.turn_flags["echo_step_recorded"] = True  # "Once on each of your turns when you move at least 10 feet"
    from . import needle

    options = [needle.cell_id(_pos(c)) for c in cells]
    chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "ECHO_RECORD", actor.entity_id), actor, "choice:needle.echo_step.record",
                        options, labels={o: f"Record {_label(o)} as an Echo Position" for o in options}, preferred=options[:1],
                        allow_decline=True, name="Record the Killing Step", feature_id=AFTERIMAGE_EDGE,
                        prompt=f"Record the Killing Step: which square of {actor.display_name}'s movement becomes an Echo Position?")
    if chosen:
        record(engine, actor, needle.position_of(chosen[0]), AFTERIMAGE_EDGE)


def _blade_hum(engine: Any, mover: Any, path: list[dict[str, Any]]) -> None:
    """Cross the Blade-Hum: "moves through or ends movement in one of your Echo Positions". A normal move is committed whole, so
    one crossed on the way is answered when the move is committed (its Speed 0 then ends what is left of its movement)."""
    squares = [(int(p["x"]), int(p["y"])) for p in path[1:]]
    token = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    for disciple in list(engine.state.actors.values()):
        if (not disciple.active or disciple.team_id == mover.team_id or st.row(engine, disciple, "echo_counter") is None
                or mover.turn_flags.get(f"blade_hum:{disciple.entity_id}") == token):
            continue
        crossed = next((cell for cell in squares if cell in echo_cells(engine, disciple)), None)
        if crossed is None:
            continue
        from . import needle

        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "BLADE_HUM", mover.entity_id), disciple,
                            "choice:needle.echo_step.blade_hum", ["hum"],
                            labels={"hum": f"Cross the Blade-Hum: consume the Echo at {crossed[0]},{crossed[1]}; {mover.display_name} makes a Wisdom save"},
                            prompt=f"{mover.display_name} crosses one of your Echo Positions. On a failed Wisdom save its Speed becomes 0 for the "
                                   "rest of the turn and it is Resonance Marked until the end of your next turn; on a success, Speed -10.",
                            preferred=["hum"], allow_decline=True, name="Cross the Blade-Hum", feature_id=COUNTER, target_id=mover.entity_id)
        if not chosen:
            continue
        mover.turn_flags[f"blade_hum:{disciple.entity_id}"] = token  # "A creature can trigger this once per turn"
        consume(engine, disciple, crossed)
        ctx = st.context(engine, disciple, st.feature_action(engine, disciple, COUNTER), [mover], st.numbers(engine, disciple))
        st.save(ctx, mover, "wis",
                on_fail=[{"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "END_OF_CURRENT_TURN",
                          "evidence": "Its Speed becomes 0 for the rest of the turn"},
                         {"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                          "evidence": "it becomes Resonance Marked until the end of your next turn"}],
                on_success=[{"type": "speed", "applies_to": "target", "flat": -10, "expires_on": "END_OF_CURRENT_TURN",
                             "evidence": "Its Speed is reduced by 10 feet for the rest of the turn"}])
        return


# -------------------------------------------------------------------------------------------------------- Strike From the Echo
def _strikes(actions: list[Any]) -> list[Any]:
    out = []
    for action in actions:
        typed = (action.parameters or {}).get("typed") or {}
        if action.economy.value != "ACTION" or action.target_kind != "HOSTILE_ENTITY":
            continue
        if typed.get("source") == MIND_SPIKE:
            out.append(action)
            continue
        attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
        if (attack is not None and typed.get("weapon") and typed.get("source") != "improvised_weapon"
                and int((action.parameters or {}).get("expected_damage") or 0) > 0):
            out.append(action)
    return out


@hook("compile_actions")
def echo_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    out = []
    if AFTERIMAGE_EDGE in owned:
        for action in _strikes(info["actions"]):
            reach = int(action.range_ft or action.reach_ft or 5)
            typed = (action.parameters or {}).get("typed") or {}
            out.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}.echo_origin", "display_name": f"Strike From the Echo: {action.display_name}",
                "target_kind": "HOSTILE_ENTITY", "range_ft": reach + 20, "reach_ft": None,
                "parameters": {**(action.parameters or {}), "echo_strike": action.source_definition_id,
                               "variant_of": action.source_definition_id,
                               "typed": {**typed, "effects": [{"type": "echo_strike", "applies_to": "target", "harmful": True, "of": action.source_definition_id,
                                                               "evidence": "treat one Echo Position within 20 feet as the attack's origin"}], "riders": []},
                               "description": f"Afterimage Edge (once on each of your turns): {action.display_name} from one of your Echo Positions within "
                                              "20 feet -- reach, range and line of sight are measured from it; the Echo is consumed. A creature Resonance "
                                              "Marked by you takes your Wisdom modifier more damage. Then you may spend 1 Resonance to step to the Echo "
                                              "without provoking (Step Through the Opening)."}}))
    if HUNDRED in owned:
        from ..gate2_runtime_models import ActionDefinition, EconomyKind

        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.echo_final_edge", display_name="Moment of the Final Edge", owner_id=info["actor_id"],
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=120,
            parameters={"typed": {"effects": [{"type": "echo_final_edge", "applies_to": "target", "harmful": True,
                                               "evidence": "Move through the sequence by spiritual step, then choose one"}],
                                  "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": HUNDRED},
                        "expected_damage": 55, "echo_final_edge": True,
                        "description": "Hundred Echoes (once during the State, Action): step along your Echo Positions to one from which your final "
                                       "attack is legal on a creature within 120 feet, then a Cultivation Attack for 10d10, a weapon attack, or Mind "
                                       "Spike with maximum damage dice. On a hit or failed save it makes a Charisma save -- failed: two of no "
                                       "Reactions, Speed 0, no healing, Prone; success: one of them until the start of its next turn."}))
    return out or None


@hook("weapon_variant_parent")
def echo_weapon_parent(parameters: dict[str, Any]) -> str | None:
    """Legacy Echo wrappers use the original weapon, never another physical grip."""
    return parameters.get("echo_strike") or None


def legal_from(engine: Any, actor: Any, cell: tuple[int, int], target: Any, reach: int) -> bool:
    """``target`` is within ``reach`` of ``actor`` standing at ``cell``, with line of sight from there."""
    spot = _pos(cell)
    if engine._distance_actor_to_actor(actor, target, actor_position=spot) > reach:
        return False
    return engine.grid.line_of_sight_between_cell_sets(engine._actor_cells(actor, spot), engine._actor_cells(target),
                                                       obscured_cells=engine._obscured_cells())


def _strike_origins(engine: Any, actor: Any, target: Any, source: Any) -> list[tuple[int, int]]:
    reach = int(source.range_ft or source.reach_ft or 5)
    here = (actor.position.x, actor.position.y)
    return [cell for cell in echo_cells(engine, actor) if cell != here and engine._distance_actor_to_cell(actor, _pos(cell)) <= 20
            and legal_from(engine, actor, cell, target, reach)]


@hook("candidate_allowed")
def echo_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (action.parameters or {}) if action is not None else {}
    if params.get("echo_strike"):
        source = engine.action_catalog.get(params["echo_strike"])
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        if actor.turn_flags.get("strike_from_the_echo") or source is None or target is None:
            return False
        return None if _strike_origins(engine, actor, target, source) else False
    if params.get("echo_final_edge"):
        if _state(actor) is None or any(c.condition_id == FINAL_USED and c.source_actor_id == actor.entity_id for c in actor.conditions.values()):
            return False
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        return None if target is not None and _final_options(engine, actor, target) else False
    if action is not None and st.feature_of(action) == THREE_STEP:  # an origin (your space or an Echo) with a creature within 5 feet
        cells = [(actor.position.x, actor.position.y), *echo_cells(engine, actor)]
        return None if any(f.active and f.team_id != actor.team_id and legal_from(engine, actor, c, f, 5)
                           for c in cells for f in engine.state.actors.values()) else False
    return None


def _with_reach(action: Any, engine: Any, actor: Any, target: Any) -> Any:
    """The action as used from an Echo: the engine checks reach from the user's real space, so the copy's reach covers it."""
    reach = int(action.range_ft or action.reach_ft or 5)
    return action.model_copy(update={"range_ft": max(reach, engine._distance_actor_to_actor(actor, target))})


@effect("echo_strike")
def echo_strike(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    source = engine.action_catalog.get(str(row.get("of") or ""))
    if source is None or target is None or not target.active:
        return
    origins = _strike_origins(engine, actor, target, source)
    if not origins:
        return
    ids = [needle.cell_id(_pos(c)) for c in origins]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "ECHO_STRIKE", target.entity_id), actor, "choice:needle.echo_step.strike_origin",
                        ids, labels={i: f"Strike from the Echo at {_label(i)}" for i in ids}, preferred=ids[:1],
                        prompt=f"Strike From the Echo: {source.display_name} on {target.display_name} from which Echo Position?",
                        name="Strike From the Echo", feature_id=AFTERIMAGE_EDGE, target_id=target.entity_id)
    origin = needle.position_of(chosen[0]) if chosen else _pos(origins[0])
    actor.turn_flags["strike_from_the_echo"] = True  # "Once on each of your turns"
    typed = copy.deepcopy((source.parameters or {}).get("typed") or {})
    effects = typed.get("effects") or []
    if _te().bears_mark(target, actor.entity_id, "Resonance"):
        bonus = {"type": "extra_damage", "applies_to": "target", "flat": 0, "formula": "key_ability_modifier",
                 "evidence": "Strike From the Echo: your Wisdom modifier added to one damage roll"}
        for effect_row in effects:
            branch = {"attack": "on_hit", "save": "on_fail"}.get(effect_row.get("type") if isinstance(effect_row, dict) else "")
            if branch:
                effect_row[branch] = [*(effect_row.get(branch) or []), bonus]
                break
    # Use the shared bound-origin contract throughout declaration, native reach,
    # cover and revalidation. Merely extending reach no longer supplies a legal
    # projectile origin and incorrectly measures this attack from the caster.
    from ..action_geometry import activate
    action = ctx.action.model_copy(update={'range_ft': source.range_ft, 'reach_ft': source.reach_ft})
    sub = _te().Context(engine, actor, action, ctx.intent, typed, [target], target, {})
    bound = {'id': needle.cell_id(origin), 'label': f'Echo at {origin.x},{origin.y}',
             'position': origin.model_dump(mode='json')}
    with activate(engine, actor, action.source_definition_id, bound):
        _te().run_effects(sub, effects)
    consume(engine, actor, (origin.x, origin.y))  # "consumes it after the attack resolves"
    note(engine, AFTERIMAGE_EDGE, actor, f"{actor.display_name} strikes {target.display_name} from the Echo at {origin.x},{origin.y}.", (target,))
    _step_through(engine, actor, origin, ctx.intent)


@hook('effect_origins')
def resolving_echo_origins(engine, actor, action):
    """Validate an owned Echo selected inside Strike From the Echo's action.

    The spent once-turn flag makes this provider inert during menu generation;
    it validates the existing bounded choice without adding another origin menu.
    """
    if (not _rows(engine, actor) or not action.parameters.get('echo_strike') or not actor.turn_flags.get('strike_from_the_echo')
            or action.owner_id != actor.entity_id):
        return None
    from .needle import cell_id
    here = (actor.position.x, actor.position.y)
    return [{'id': cell_id(_pos(cell)), 'label': f'Echo at {cell[0]},{cell[1]}',
             'position': _pos(cell).model_dump(mode='json')}
            for cell in echo_cells(engine, actor) if cell != here
            and engine._distance_actor_to_cell(actor, _pos(cell)) <= 20]


def _step_through(engine: Any, actor: Any, origin: Any, intent: Any) -> None:
    if not actor.active or actor.resources.get(RESONANCE, 0) < 1 or not _free(engine, actor, origin):
        return  # an occupied or illegal space: you stay and spend nothing
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "STEP_THROUGH", actor.entity_id), actor, "choice:needle.echo_step.step_through",
                        ["step"], labels={"step": f"Step Through the Opening: move to {origin.x},{origin.y} (1 Resonance, no Opportunity Attacks)"},
                        prompt="Step Through the Opening?", allow_decline=True, default="decline", name="Step Through the Opening",
                        feature_id=AFTERIMAGE_EDGE)
    if chosen:
        engine._spend_resource(actor, RESONANCE, 1, AFTERIMAGE_EDGE)
        needle.step_to(engine, actor, origin, AFTERIMAGE_EDGE)


# ---------------------------------------------------------------------------------------------------------------- Echo Counter
@hook("before_attack")
def echo_counter(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    if (attacker is None or defender is None or attacker.team_id == defender.team_id or st.row(engine, defender, "echo_counter") is None
            or not st.can_react(defender) or defender.resources.get(RESONANCE, 0) < 2 or engine._effective_speed(defender) <= 0):
        return None
    reach = int(context.get("range_ft") or 5)
    options = {cell: v for cell, v in st.routes(engine, defender, 10).items() if cell != defender.position}
    if not options:
        return None
    escapes = [cell for cell in options if engine._distance_actor_to_actor(attacker, defender, target_position=cell) > reach]
    from . import needle
    from .choice_prompt import action_context

    ordered = sorted(options, key=lambda cell: (options[cell][1], cell.y, cell.x))[:48]
    preferred = [min(escapes, key=lambda c: (options[c][1], c.y, c.x))] if escapes else []
    ordered = [*preferred, *[c for c in ordered if c not in preferred]]
    ids = [needle.cell_id(cell) for cell in ordered]
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "ECHO_COUNTER", attacker.entity_id, context.get("attack_index", 1)), defender,
                        "choice:needle.echo_step.counter", ids, labels={needle.cell_id(c): f"Move to {c.x},{c.y} ({options[c][1]} ft)" for c in ordered},
                        preferred=[needle.cell_id(c) for c in preferred], allow_decline=True, automatic=bool(escapes), default="decline",
                        prompt=f"Echo Counter (Reaction, 2 Resonance): {attacker.display_name} attacks you. Leave an Echo Position here and move "
                               "10 feet without provoking: out of its reach it misses, otherwise you have +2 AC against it.", name="Echo Counter",
                        feature_id=COUNTER, target_id=attacker.entity_id,
                        prompt_context=action_context(engine, attacker, str(context.get("source_id") or ""), defender))
    if not chosen or chosen[0] not in ids:
        return None
    with activation(engine, defender, COUNTER):
        engine._spend_resource(defender, RESONANCE, 2, COUNTER)
        defender.reaction_available = False
        engine._append_event("REACTION_RESOLVED", COUNTER, actor_id=defender.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Echo Counter"})
        record(engine, defender, defender.position, COUNTER)  # "Record your current space as an Echo Position"
        preserve_pending(engine, _COUNTER)
        engine.__dict__[_COUNTER] = {"attacker": attacker.entity_id, "defender": defender.entity_id, "events": len(engine.events),
                                     "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"}
        retain(engine, _COUNTER, capture(engine))
        cell = needle.position_of(chosen[0])
        path = next((p for spot, (p, _c) in options.items() if spot == cell), None)
        if path is not None and len(path) > 1:
            from .rider_movement import step

            step(engine, defender, list(path), COUNTER)
        note(engine, COUNTER, defender, f"{defender.display_name} uses Echo Counter, leaving an Echo Position and moving to {cell.x},{cell.y}.", (attacker,))
        return {}


def _pending(engine: Any, attacker_id: str | None) -> dict[str, Any] | None:
    held = engine.__dict__.get(_COUNTER)
    return held if held and held.get("attacker") == attacker_id else None


def _rolls_since(engine: Any, held: dict[str, Any]) -> list[Any]:
    return [e for e in engine.events[int(held.get("events") or 0):] if e.event_type == "ATTACK_ROLLED" and e.actor_id == held["attacker"]]


@hook("hit_response")
def counter_guard(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    held = _pending(engine, getattr(attacker, "entity_id", None))
    if held is None or held.get("defender") != target.entity_id:
        return None
    rolled = _rolls_since(engine, held)
    with causal_scope(engine, take(engine, _COUNTER)):
        preserve_pending(engine, _COUNTER)
        engine.__dict__.pop(_COUNTER, None)
        if len(rolled) != 1 or str((rolled[0].payload or {}).get("reason") or "") != held.get("roll"):
            return None  # a later attack: Echo Counter answered only the triggering one
        if natural == 20 or total >= effective_ac + 2:
            return None
        note(engine, COUNTER, target, f"Echo Counter: +2 AC turns {attacker.display_name}'s attack into a miss.", (attacker,))
        _counter_miss(engine, target, attacker)
        return effective_ac + 2, False


@hook("event")
def counter_missed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The answered attack missed: the engine's own out-of-reach miss (a GM_RIDER before any roll) or a rolled miss."""
    if event_type not in ("ATTACK_ROLLED", "GM_RIDER"):
        return
    held = _pending(engine, kwargs.get("actor_id"))
    if held is None:
        return
    payload = kwargs.get("payload") or {}
    rolled = _rolls_since(engine, held)
    if event_type == "GM_RIDER":
        if ENGINE_OUT_OF_REACH not in str(payload.get("rider") or "") or held["defender"] not in (kwargs.get("target_ids") or ()) or rolled:
            return
    else:
        if len(rolled) != 1 or str(payload.get("reason") or "") != held.get("roll"):
            preserve_pending(engine, _COUNTER)
            engine.__dict__.pop(_COUNTER, None)  # not the answered attack: forget it
            take(engine, _COUNTER)
            return
        if payload.get("provisional_hit"):
            return  # a provisional hit is settled by counter_guard
    preserve_pending(engine, _COUNTER)
    engine.__dict__.pop(_COUNTER, None)
    with causal_scope(engine, take(engine, _COUNTER)):
        defender, attacker = engine.state.actors.get(held["defender"]), engine.state.actors.get(held["attacker"])
        if defender is not None and attacker is not None and defender.active:
            _counter_miss(engine, defender, attacker)


def _counter_miss(engine: Any, defender: Any, attacker: Any) -> None:
    from . import needle

    intent = engine._active_intent
    here = (defender.position.x, defender.position.y)
    others = [c for c in echo_cells(engine, defender) if c != here and engine._distance_actor_to_cell(defender, _pos(c)) <= 20
              and _free(engine, defender, _pos(c))]
    spike = st.action_named(engine, defender, "Mind Spike")
    options = ["psychic", *(["spike"] if spike is not None and engine._distance_actor_to_actor(defender, attacker) <= int(spike.range_ft or 60) else []),
               *(["echo"] if others else []), *(["stilled"] if _te().bears_mark(attacker, defender.entity_id, "Resonance") else [])]
    labels = {"psychic": f"{attacker.display_name} takes 2d8 + your Wisdom modifier Psychic damage",
              "spike": f"Use Mind Spike against {attacker.display_name}, one damage die fewer",
              "echo": "Move to another of your Echo Positions within 20 feet",
              "stilled": f"{attacker.display_name} cannot take Reactions until the start of its next turn"}
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "ECHO_COUNTER_MISS", attacker.entity_id), defender,
                        "choice:needle.echo_step.counter_miss", options, labels={k: labels[k] for k in options}, preferred=["psychic"],
                        prompt="Echo Counter: the attack misses. Choose one.", name="Echo Counter", feature_id=COUNTER, target_id=attacker.entity_id)
    pick = chosen[0] if chosen else "psychic"
    ctx = st.context(engine, defender, st.feature_action(engine, defender, COUNTER), [attacker], st.numbers(engine, defender), intent)
    if pick == "psychic":
        _te().run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "formula": "key_ability_modifier",
                                 "damage_types": ["psychic"], "evidence": "the attacker takes 2d8 + Wisdom modifier Psychic damage"}])
    elif pick == "stilled":
        _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                                 "evidence": "remove its Reactions until the start of its next turn"}])
    elif pick == "echo":
        spots = [needle.cell_id(_pos(c)) for c in others]
        where = needle.ask(engine, intent, needle.checkpoint_id(engine, "ECHO_COUNTER_TO", attacker.entity_id), defender,
                           "choice:needle.echo_step.counter_echo", spots, labels={s: f"Move to the Echo at {_label(s)}" for s in spots},
                           preferred=spots[:1], prompt="Echo Counter: move to which Echo Position?", name="Echo Counter", feature_id=COUNTER)
        needle.step_to(engine, defender, needle.position_of(where[0] if where else spots[0]), COUNTER)
    elif pick == "spike":
        st.mind_spike(engine, defender, attacker, intent, dice_delta=-1)


# ------------------------------------------------------------------------------------------------- Three-Step Soul Execution
@effect("echo_three_step")
def three_step(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    kinds = ["psychic", "force", "slashing", "necrotic"]
    chosen_type = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "THREE_STEP_DAMAGE", actor.entity_id), actor,
                            "choice:needle.echo_step.three_step_damage", kinds,
                            labels={k: k.title() for k in kinds}, preferred=["psychic"],
                            prompt="Three-Step Soul Execution: choose one damage type for every strike.",
                            name="Three-Step Soul Execution", feature_id=THREE_STEP)
    damage_type = chosen_type[0] if chosen_type else "psychic"
    start = (actor.position.x, actor.position.y)
    hits: list[str] = []
    struck: list[str] = []
    last: tuple[int, int] | None = None
    used: list[tuple[int, int]] = []
    for index in range(3):
        cells = [c for c in [start, *echo_cells(engine, actor)] if c not in used and c != last
                 and (last is None or engine.grid.distance_ft(_pos(last), _pos(c)) <= 30)]
        foes = {c: [f for f in engine.state.actors.values() if f.active and f.team_id != actor.team_id and legal_from(engine, actor, c, f, 5)]
                for c in dict.fromkeys(cells)}
        cells = [c for c in foes if foes[c]]
        if not cells:
            break
        ids = [needle.cell_id(_pos(c)) for c in cells]
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "THREE_STEP", actor.entity_id, index), actor,
                            "choice:needle.echo_step.three_step_origin", ids,
                            labels={i: ("Strike from where you started" if needle.position_of(i) == _pos(start) else f"Strike from the Echo at {_label(i)}")
                                    for i in ids},
                            preferred=ids[:1], allow_decline=index > 0, prompt=f"Three-Step Soul Execution: origin {index + 1} of up to 3"
                            + (" (within 30 feet of the last)." if index else "."), name="Three-Step Soul Execution", feature_id=THREE_STEP)
        if not chosen:
            break
        spot = needle.position_of(chosen[0])
        cell = (spot.x, spot.y)
        if cell not in foes:
            break
        target = st.pick_creature(engine, ctx.intent, actor, foes[cell], checkpoint="THREE_STEP_TARGET", choice_id="choice:needle.echo_step.three_step_target",
                                  prompt=f"Three-Step Soul Execution: which creature within 5 feet of {cell[0]},{cell[1]}?", name="Three-Step Soul Execution",
                                  feature_id=THREE_STEP, preferred=next((f for f in foes[cell] if f.entity_id in struck), None)
                                  or min(foes[cell], key=lambda f: (f.current_hp, f.entity_id)))
        if target is None:
            break
        dice = 2 if target.entity_id in hits else 3  # "full damage from the first hit and 2d8 from each later hit"
        before = len(engine.events)
        sub = st.context(engine, actor, _with_reach(ctx.action, engine, actor, target), [target], ctx.numbers, ctx.intent)
        _te().run_effects(sub, [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1,
                                 "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8},
                                             "damage_types": [damage_type],
                                             "evidence": f"{dice}d8 Psychic, Force, Slashing, or Necrotic damage"}], "on_miss": []}])
        struck.append(target.entity_id)
        if any(e.event_type == "DAMAGE_COMMITTED" and target.entity_id in e.target_ids for e in engine.events[before:]):
            hits.append(target.entity_id)
        if cell != start:
            used.append(cell)
        last = cell
        if cell != (actor.position.x, actor.position.y) and actor.active and _free(engine, actor, spot):
            go = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "THREE_STEP_MOVE", actor.entity_id, index), actor,
                            "choice:needle.echo_step.three_step_move", ["move"], labels={"move": f"Move to {cell[0]},{cell[1]} (no Opportunity Attacks)"},
                            preferred=["move"], allow_decline=True, prompt="Three-Step Soul Execution: move to that origin by spiritual step?",
                            name="Three-Step Soul Execution", feature_id=THREE_STEP)
            if go:
                needle.step_to(engine, actor, spot, THREE_STEP)
    for cell in used:
        consume(engine, actor, cell)  # "Consume every Echo Position used as an origin"
    final = row.get("final_save")
    if len(hits) == 3 and len(set(hits)) == 1 and isinstance(final, dict):
        victim = engine.state.actors.get(hits[0])
        if victim is not None and victim.active and _te().bears_mark(victim, actor.entity_id, "Resonance"):
            _te().run_effects(st.context(engine, actor, ctx.action, [victim], ctx.numbers, ctx.intent), [final])


# ---------------------------------------------------------------------------------------------------- Pursuit Without Distance
def pursuit_id(owner_id: str) -> str:
    return _te().mark_condition_id(PURSUIT_MARK, owner_id)


@hook("damage_dealt")
def pursuit_mark(ctx: Any, target: Any, amount: int) -> None:
    engine, actor = ctx.engine, ctx.actor
    if (amount <= 0 or target is None or not target.active or target.team_id == actor.team_id or st.row(engine, actor, "pursuit_without_distance") is None
            or actor.resources.get(RESONANCE, 0) < 2 or any(c.condition_id == pursuit_id(actor.entity_id) for c in target.conditions.values())):
        return
    resonance = _te().mark_condition_id("Resonance", actor.entity_id)
    marks = [c for c in target.conditions.values() if c.condition_id == resonance]
    if not marks:
        return
    from . import needle

    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PURSUIT_MARK", target.entity_id), actor, "choice:needle.echo_step.pursuit_mark",
                        ["pursue"], labels={"pursue": f"Pursuit Mark (2 Resonance): your Resonance Mark on {target.display_name} becomes a Pursuit Mark for the fight"},
                        prompt=f"You damaged {target.display_name}, Resonance Marked by you. Convert the mark? (one Pursuit Mark at a time)",
                        preferred=["pursue"], allow_decline=True, name="Pursuit Without Distance", feature_id=PURSUIT, target_id=target.entity_id)
    if not chosen:
        return
    engine._spend_resource(actor, RESONANCE, 2, PURSUIT)
    for creature in engine.state.actors.values():  # "You can maintain one Pursuit Mark at a time"
        for held in [c for c in creature.conditions.values() if c.condition_id == pursuit_id(actor.entity_id)]:
            st.remove(engine, creature, held, "REPLACED")
    for held in marks:
        st.remove(engine, target, held, "CONVERTED")
    engine._apply_condition(target, pursuit_id(actor.entity_id), PURSUIT, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": f"Pursuit Mark ({actor.display_name}): a Resonance Mark for the fight"})
    note(engine, PURSUIT, actor, f"{actor.display_name}'s Resonance Mark on {target.display_name} becomes a Pursuit Mark.", (target,))


@hook("mark_apply")
def pursuit_is_resonance(ctx: Any, effect_row: dict[str, Any], subject: Any, expires: Any, data: Any) -> bool | None:
    """"A Pursuit Mark is a special Resonance Mark": your Resonance Mark on a creature bearing your Pursuit Mark is already there
    (Mind Spike's own mark after the damage that converted it does not add a second one)."""
    te = _te()
    if subject is None or te.mark_condition_id(str(effect_row.get("mark") or ""), ctx.actor.entity_id) != te.mark_condition_id("Resonance", ctx.actor.entity_id):
        return None
    return True if any(c.condition_id == pursuit_id(ctx.actor.entity_id) for c in subject.conditions.values()) else None


@hook("match_start")
def shake_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[SHAKE] = ActionDefinition(
        source_definition_id=SHAKE, display_name="Shake off the Pursuit Mark", owner_id="*", economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="SELF", parameters={"typed": {"effects": [{"type": "echo_shake_pursuit"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
                                        "expected_damage": 0, "echo_shake_pursuit": True,
                                        "description": "You bear a Pursuit Mark: use your Action to make a Charisma saving throw against the marker's "
                                                       "Cultivation Save DC; on a success the mark ends."})


def _pursuers(engine: Any, actor: Any) -> list[Any]:
    prefix = _te().mark_condition_id(PURSUIT_MARK, "")
    owners = [c.source_actor_id for c in actor.conditions.values() if c.condition_id.startswith(prefix)]
    return [engine.state.actors[o] for o in dict.fromkeys(owners) if o in engine.state.actors]


@hook("additional_actions")
def shake_offered(engine: Any, actor: Any) -> list[str]:
    return [SHAKE] if _pursuers(engine, actor) else []


@effect("echo_shake_pursuit")
def shake(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    for owner in _pursuers(engine, actor):
        sub = st.context(engine, owner, st.feature_action(engine, owner, PURSUIT), [actor], st.numbers(engine, owner), ctx.intent)
        if not st.save(sub, actor, "cha"):
            for held in [c for c in actor.conditions.values() if c.condition_id == pursuit_id(owner.entity_id)]:
                st.remove(engine, actor, held, "SHAKEN_OFF")
            note(engine, PURSUIT, actor, f"{actor.display_name} shakes off {owner.display_name}'s Pursuit Mark.")


@effect("echo_follow")
def follow(ctx: Any, row: dict[str, Any]) -> None:
    """Follow the Vanishing Point: the generic "bearing your Pursuit Mark moves at least 15 feet" reaction row has checked the
    trigger and taken the Reaction and 4 Resonance; ctx.target is the marked creature where it stopped."""
    from . import needle

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    intent = ctx.intent or engine._active_intent  # the generic moved row runs without its own intent
    if target is None or not target.active:
        return
    speed = engine._effective_speed(actor)
    reachable = {cell: v for cell, v in st.routes(engine, actor, speed).items() if cell != actor.position} if speed > 0 else {}
    near = {cell: v for cell, v in reachable.items() if engine._distance_actor_to_cell(target, cell) <= 10}
    if not near and reachable:  # "toward a legal space within 10 feet": as near as the move gets
        best = min(engine._distance_actor_to_cell(target, cell) for cell in reachable)
        near = {cell: v for cell, v in reachable.items() if engine._distance_actor_to_cell(target, cell) == best
                and best < engine._distance_actor_to_actor(actor, target)}
    spike = st.action_named(engine, actor, "Mind Spike")
    echo_spots = [c for c in echo_cells(engine, actor) if engine._distance_actor_to_cell(actor, _pos(c)) <= 60 and _free(engine, actor, _pos(c))]
    options = [*(["follow"] if near else []), *(["echo"] if echo_spots else [])]
    if not options:
        return
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "FOLLOW_VANISHING", target.entity_id), actor, "choice:needle.echo_step.follow",
                        options, labels={"follow": f"Move up to your Speed (no Opportunity Attacks) to within 10 feet of {target.display_name}",
                                         "echo": f"Move to one of your Echo Positions within 60 feet and use Mind Spike on {target.display_name}"},
                        preferred=options[:1], prompt="Follow the Vanishing Point: choose one.", name="Follow the Vanishing Point", feature_id=PURSUIT,
                        target_id=target.entity_id)
    pick = chosen[0] if chosen and chosen[0] in options else options[0]
    if pick == "follow":
        best = min(near, key=lambda c: (engine._distance_actor_to_cell(target, c), near[c][1], c.y, c.x))
        path = st.choose_route(engine, actor, near, intent, checkpoint="FOLLOW_ROUTE", prompt=f"Follow {target.display_name} to which square?",
                               name="Follow the Vanishing Point", feature=PURSUIT, preferred=best, stay=False)
        if path is not None:
            from .rider_movement import step

            step(engine, actor, list(path), PURSUIT)
    else:
        spots = [needle.cell_id(_pos(c)) for c in sorted(echo_spots, key=lambda c: (engine._distance_actor_to_cell(target, _pos(c)), c[1], c[0]))]
        where = needle.ask(engine, intent, needle.checkpoint_id(engine, "FOLLOW_ECHO", target.entity_id), actor, "choice:needle.echo_step.follow_echo",
                           spots, labels={s: f"Move to the Echo at {_label(s)}" for s in spots}, preferred=spots[:1],
                           prompt="Follow the Vanishing Point: which Echo Position?", name="Follow the Vanishing Point", feature_id=PURSUIT)
        needle.step_to(engine, actor, needle.position_of(where[0] if where else spots[0]), PURSUIT)
        if spike is not None and engine._distance_actor_to_actor(actor, target) <= int(spike.range_ft or 60) and target.active:
            st.mind_spike(engine, actor, target, intent)  # "if it is legal from that position"
    if actor.active:
        record(engine, actor, actor.position, PURSUIT)  # "After arriving, record your space as an Echo Position"


# ---------------------------------------------------------------------------------------------------- Hundred Echoes
def _state(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == STATE and c.source_actor_id == actor.entity_id), None)


@effect("echo_hundred_state")
def hundred_state(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    for held in [c for c in actor.conditions.values() if c.condition_id in (STATE, TRACE, FINAL_USED) and c.source_actor_id == actor.entity_id]:
        st.remove(engine, actor, held, "REPLACED")
    engine._apply_condition(actor, STATE, ctx.source, actor.entity_id, expires_on=ctx.expires_on() or "CONCENTRATION_END",
                            data={"label": "Hundred-Echo State: Echo Positions each turn, no Opportunity Attacks against your movement, "
                                           "nonmagical difficult terrain costs nothing"})
    engine._apply_condition(actor, TRACE, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Hundred-Echo State (when it ends: After the Last Echo)"})
    actor.turn_flags["disengaged"] = True  # "do not provoke opportunity attacks"
    record(engine, actor, actor.position, ctx.source, state=_state(actor))


@hook("turn_start")
def state_turn_start(engine: Any, actor: Any) -> None:
    _after_the_last_echo(engine, actor)
    held = _state(actor)
    if held is not None and actor.active:
        actor.turn_flags["disengaged"] = True
        record(engine, actor, actor.position, HUNDRED, state=held)


@hook("turn_end")
def state_turn_end(engine: Any, actor: Any) -> None:
    held = _state(actor)
    if held is not None and actor.active:
        record(engine, actor, actor.position, HUNDRED, state=held)


@hook("difficult_exempt")
def state_footing(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    return st.plain_difficult(engine) if _state(actor) is not None else None


def _after_the_last_echo(engine: Any, actor: Any) -> None:
    """When the State ends (Concentration broken or ended), remove every Echo Position and Pursuit Mark you created; you cannot
    take Reactions until the start of your next turn."""
    trace = next((c for c in actor.conditions.values() if c.condition_id == TRACE and c.source_actor_id == actor.entity_id), None)
    if trace is None or _state(actor) is not None:
        return
    st.remove(engine, actor, trace, "STATE_ENDED")
    for held in [c for c in actor.conditions.values() if c.condition_id in (ECHO, FINAL_USED) and c.source_actor_id == actor.entity_id]:
        st.remove(engine, actor, held, "STATE_ENDED")
    for creature in engine.state.actors.values():
        for held in [c for c in creature.conditions.values() if c.condition_id == pursuit_id(actor.entity_id)]:
            st.remove(engine, creature, held, "STATE_ENDED")
    if actor.active:
        ctx = st.context(engine, actor, st.feature_action(engine, actor, HUNDRED), [actor], st.numbers(engine, actor))
        _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "self", "duration": {"kind": "until_start_of_your_next_turn"},
                                 "evidence": "You cannot take Reactions until the start of your next turn"}])
        note(engine, HUNDRED, actor, f"After the Last Echo: {actor.display_name}'s echoes and Pursuit Mark end; no Reactions until the start of its next turn.")


@hook("technique_used")
def many_edges(ctx: Any) -> None:
    """One Soul, Many Edges (once on each of your turns during the State)."""
    from . import needle

    engine, actor = ctx.engine, ctx.actor
    if (_state(actor) is None or actor.turn_flags.get("one_soul_many_edges") or engine.state.current_actor_id != actor.entity_id
            or (ctx.action.parameters or {}).get("echo_final_edge")):
        return
    typed = ctx.typed or {}
    weapon = bool(typed.get("weapon")) and typed.get("source") != "improvised_weapon" and any(
        isinstance(r, dict) and r.get("type") in ("attack", "echo_strike") for r in typed.get("effects") or [])
    single = st.is_spirit_feature(ctx.action) and ctx.action.target_kind == "HOSTILE_ENTITY" and len(ctx.targets) == 1
    if not (typed.get("source") == MIND_SPIKE or weapon or single):
        return
    reach = int(ctx.action.range_ft or ctx.action.reach_ft or 5)
    if (ctx.action.parameters or {}).get("echo_strike"):
        reach = max(5, reach - 20)
    spots = [c for c in echo_cells(engine, actor) if engine._distance_actor_to_cell(actor, _pos(c)) <= 60]
    legal = {c: [f for f in engine.state.actors.values() if f.active and f.team_id != actor.team_id and legal_from(engine, actor, c, f, reach)]
             for c in spots}
    spots = [c for c in spots if legal[c]]
    if not spots:
        return
    actor.turn_flags["one_soul_many_edges"] = True
    ids = [needle.cell_id(_pos(c)) for c in spots]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "MANY_EDGES", actor.entity_id), actor, "choice:needle.echo_step.many_edges",
                        ids, labels={i: f"Echo at {_label(i)}" for i in ids}, preferred=ids[:3], minimum=1, maximum=3, default="all",
                        allow_decline=True, prompt="One Soul, Many Edges: choose up to three Echo Positions within 60 feet.",
                        name="One Soul, Many Edges", feature_id=HUNDRED)
    pursued = [f.entity_id for f in engine.state.actors.values() if any(c.condition_id == pursuit_id(actor.entity_id) for c in f.conditions.values())]
    picks: list[str] = []
    for option in chosen[:3]:
        spot = needle.position_of(option)
        foes = legal.get((spot.x, spot.y)) or []
        preferred = next((f for f in foes if f.entity_id in pursued), None) or min(foes, key=lambda f: (f.current_hp, f.entity_id), default=None)
        foe = st.pick_creature(engine, ctx.intent, actor, foes, checkpoint="MANY_EDGES_TARGET", choice_id="choice:needle.echo_step.many_edges_target",
                               prompt=f"One Soul, Many Edges: which creature does the Echo at {spot.x},{spot.y} cut?", name="One Soul, Many Edges",
                               feature_id=HUNDRED, preferred=preferred)
        if foe is not None:
            picks.append(foe.entity_id)
    state = _state(actor)
    base = engine.action_catalog.get(state.source_definition_id) or st.feature_action(engine, actor, HUNDRED)
    numbers = st.numbers(engine, actor)
    for foe_id in dict.fromkeys(picks):  # "A creature chosen multiple times takes damage only once"
        foe = engine.state.actors.get(foe_id)
        if foe is None or not foe.active:
            continue
        dice = 4 if foe_id in pursued and picks.count(foe_id) > 1 else 2
        _te().run_effects(st.context(engine, actor, base, [foe], numbers, ctx.intent),
                          [{"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8}, "damage_types": ["psychic", "force"],
                            "evidence": f"secondary echo damage: {dice}d8 Psychic or Force"}])


# ------------------------------------------------------------------------------------------------ Moment of the Final Edge
def _weapons(engine: Any, actor: Any) -> list[Any]:
    return [a for a in _strikes([engine.action_catalog[i] for i in actor.action_ids if i in engine.action_catalog])
            if ((a.parameters or {}).get("typed") or {}).get("source") != MIND_SPIKE and not (a.parameters or {}).get("echo_strike")]


def _final_options(engine: Any, actor: Any, target: Any) -> dict[str, list[tuple[int, int]]]:
    """Final attack -> the squares (your space and Echo Positions you can stand in) it is legal from."""
    here = (actor.position.x, actor.position.y)
    spots = [here, *[c for c in echo_cells(engine, actor) if c != here and _free(engine, actor, _pos(c))]]
    out = {"cultivation": [c for c in spots if legal_from(engine, actor, c, target, 5)]}
    weapons = _weapons(engine, actor)
    if weapons:
        reach = max(int(w.range_ft or w.reach_ft or 5) for w in weapons)
        out["weapon"] = [c for c in spots if legal_from(engine, actor, c, target, reach)]
    if st.action_named(engine, actor, "Mind Spike") is not None:
        out["spike"] = [c for c in spots if legal_from(engine, actor, c, target, 30)]  # "within 30 feet of the target"
    return {k: v for k, v in out.items() if v}


@effect("echo_final_edge")
def final_edge(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    options = _final_options(engine, actor, target)
    if not options:
        return
    engine._apply_condition(actor, FINAL_USED, ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Moment of the Final Edge used (once during the State)"})
    labels = {"cultivation": "Cultivation Attack: 10d10 Psychic, Force, Slashing, or Necrotic", "weapon": "One weapon attack",
              "spike": "Mind Spike with maximum damage on its dice on a failed save"}
    kinds = [k for k in ("cultivation", "weapon", "spike") if k in options]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "FINAL_EDGE_KIND", target.entity_id), actor, "choice:needle.echo_step.final_attack",
                        kinds, labels={k: labels[k] for k in kinds}, preferred=kinds[:1], prompt="Moment of the Final Edge: your final attack?",
                        name="Moment of the Final Edge", feature_id=HUNDRED, target_id=target.entity_id)
    kind = chosen[0] if chosen and chosen[0] in options else kinds[0]
    spots = [needle.cell_id(_pos(c)) for c in options[kind]]
    where = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "FINAL_EDGE_SPOT", target.entity_id), actor, "choice:needle.echo_step.final_spot",
                       spots, labels={s: (f"Strike from where you stand ({_label(s)})" if needle.position_of(s) == actor.position
                                          else f"Step to the Echo at {_label(s)}") for s in spots},
                       preferred=spots[:1], prompt="Moment of the Final Edge: the last Echo Position of your sequence?", name="Moment of the Final Edge",
                       feature_id=HUNDRED)
    choice = where[0] if where and where[0] in spots else spots[0]
    needle.step_to(engine, actor, needle.position_of(choice), ctx.source)  # "Move through the sequence by spiritual step"
    before = len(engine.events)
    if kind == "cultivation":
        _te().run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1,
                                 "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 10, "sides": 10},
                                             "damage_types": ["psychic", "force", "slashing", "necrotic"], "evidence": "10d10 damage on a hit"}],
                                 "on_miss": []}])
    elif kind == "weapon":
        weapon = max(_weapons(engine, actor), key=lambda w: (int(w.range_ft or w.reach_ft or 5) >= engine._distance_actor_to_actor(actor, target),
                                                           int((w.parameters or {}).get("expected_damage") or 0)))
        st.run_action(engine, actor, weapon, target, ctx.intent)
    else:
        st.mind_spike(engine, actor, target, ctx.intent, maximize=True)
    landed = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in e.target_ids]
    if not landed or not target.active:
        return  # "On a hit or failed save"
    failed = st.save(ctx, target, "cha")
    count = 2 if failed else 1
    until_start = {"kind": "until_start_of_next_turn"}
    menu = {"reactions": {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"} if failed else until_start,
                          "evidence": "no Reactions"},
            "speed": {"type": "speed", "applies_to": "target", "becomes": 0, "duration": until_start, "evidence": "Speed 0 until the start of its next turn"},
            "healing": {"type": "healing_reduction", "applies_to": "target", "evidence": "cannot regain Hit Points until the start of its next turn"},
            "prone": {"type": "condition", "applies_to": "target", "condition": "prone", "evidence": "it is knocked Prone"}}
    labels = {"reactions": "No Reactions " + ("until the end of your next turn" if failed else "until the start of its next turn"),
              "speed": "Speed 0 until the start of its next turn", "healing": "Cannot regain Hit Points until the start of its next turn",
              "prone": "Knocked Prone"}
    picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "FINAL_EDGE", target.entity_id), actor, "choice:needle.echo_step.final_edge",
                        list(menu), labels=labels, preferred=["reactions", "speed"][:count], minimum=count, maximum=count, default_count=count,
                        prompt=f"Moment of the Final Edge: {target.display_name} {'failed' if failed else 'made'} its Charisma save -- choose {count}.",
                        name="Moment of the Final Edge", feature_id=HUNDRED, target_id=target.entity_id)
    picks = [k for k in (picked or ["reactions", "speed"][:count]) if k in menu][:count]
    _te().run_effects(st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent), [menu[k] for k in picks])


@hook("pass_through")
def hundred_echo_passage(engine, mover, occupant):
    if mover.team_id != occupant.team_id and any(c.condition_id == STATE for c in mover.conditions.values()):
        return "free"
    return None
