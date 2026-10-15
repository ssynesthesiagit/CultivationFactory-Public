"""Shared owner-bound rider choices for Disease, Force, Radiance, Music, Monkey and Chains.

Uses the public Needle transport; accepted END_TURN intents carry answers into
turn-start hooks. Standing menus are AI preferences, never manual answers.
"""
from typing import Any
from .needle import CHOICE, ask, checkpoint_id

# The table's own acts, which have no catalog action to name them.
_TABLE_ACTS = {"END_TURN": "End turn", "HOLD_POSITION": "Hold position", "MOVE": "Move"}


def intent_for(engine: Any) -> Any | None:
    return getattr(engine, "_active_intent", None)


def trigger(engine: Any) -> tuple[str, str]:
    """What the acting creature just accepted, as ``(kind, name)``.

    ``kind`` is ``"action"`` when a catalog action was accepted, the recorded ``INTENT_ACCEPTED``
    payload kind for one of the :data:`_TABLE_ACTS` (``MOVE``, ``HOLD_POSITION``, ``END_TURN``),
    ``"turn"`` at a turn start and ``""`` when neither is recorded. ``name`` is the wording
    :func:`trigger_name` prints. A caller whose text must not call a creature's walk an attack
    reads the kind first -- Chains' ``chains_counter_success`` does, because its printed trigger
    covers both an attack and entering reach.
    """
    for event in reversed(engine.events):
        if event.event_type == "INTENT_ACCEPTED":
            action = engine.action_catalog.get(event.source_definition_id)
            if action is not None:
                return "action", str(action.display_name or "")
            kind = str((event.payload or {}).get("kind") or "")
            return kind, _TABLE_ACTS.get(kind, "table action")
        if event.event_type == "TURN_STARTED":
            return "turn", "turn start"
    return "", "triggering action"


def trigger_name(engine: Any) -> str:
    return trigger(engine)[1]


def pick(engine: Any, owner: Any, key: str, name: str, options: list[str], *,
         subject: Any, trigger: str = "", labels: dict[str, str] | None = None,
         preferred: list[str] | None = None, optional: bool = True,
         maximum: int = 1, minimum: int = 1, intent: Any = None, automatic: bool = True,
         prompt_context: dict[str, str] | None = None, choose: str = "Choose an option.",
         prompt: str | None = None, automatic_options: list[str] | None = None) -> list[str]:
    """Choose a rider recipient/outcome; optional current-cost and action metadata
    uses Needle's display-only transport. Active effects can distinguish a free
    follow-up choice from their paid activation. Omission keeps legacy text.
    ``choose`` is the sentence that says how many of the offered options the question wants; a
    printed "Choose two:" overrides the generic one so a player is never left guessing the number.
    ``automatic_options`` passes Needle's strict computer-recipient subset; manual
    choosers retain the full menu (Music Shared Measure). Preferences only rank.
    ``prompt`` replaces the whole default question for an ability that needs its own plain wording;
    it changes only what the player reads, preserving the options, ownership and selection bounds.
    """
    return ask(engine, intent or intent_for(engine), checkpoint_id(engine, key, owner.entity_id, subject.entity_id),
               owner, CHOICE + key, options, labels=labels or {o: o for o in options},
               name=name, prompt=prompt if prompt is not None else
               f"{name}: {trigger or trigger_name(engine)} affecting {subject.display_name}. {choose}",
               preferred=preferred, allow_decline=optional, maximum=maximum, minimum=minimum, target_id=subject.entity_id,
               automatic=automatic, default=("all" if maximum > 1 else "first") if automatic else "decline",
               prompt_context=prompt_context, automatic_options=automatic_options)


def step(engine: Any, mover: Any, key: str, name: str, subject: Any, feet: int, source: str, intent: Any = None, *,
         trigger: str = "", ignored_oa: list[str] | None = None,
         prompt_context: dict[str, str] | None = None) -> bool:
    """Immediate optional movement; uses the mover's spaces, never the current actor's movement pool.

    Drunken Style supplies prompt_context to name the attack causing this step.
    Omission retains existing display text for other consumers.
    """
    from ..gate2_runtime_models import Position
    from .needle import free_cells, cell_options, cell_id, parse_cell, position_of, step_to
    from .granted_movement import choices, move
    paths = choices(engine, mover, feet) if ignored_oa is not None else []
    cells = {c.destination: c.movement_cost_ft for c in paths} if ignored_oa is not None else free_cells(engine, mover, feet)
    cells[mover.position] = 0
    options, labels = cell_options(engine, mover, cells)
    # the preferred square is one the menu actually offers: cell_options caps a long step at the cheapest squares, and a
    # preferred square outside the menu is a question the transport refuses (the step would silently do nothing)
    offered = [Position(x=cell[0], y=cell[1], z=cell[2]) for cell in (parse_cell(option) for option in options)]
    away = max(offered, key=lambda cell: (engine.grid.distance_ft(subject.position, cell), -cell.y, -cell.x)) \
        if offered else mover.position
    chosen = pick(engine, mover, key, name, options, labels=labels, preferred=[cell_id(away)],
                  subject=mover if ignored_oa is not None else subject,
                  trigger=trigger or f"attack hits {subject.display_name}", intent=intent, prompt_context=prompt_context)
    if chosen and chosen[0] != cell_id(mover.position):
        if ignored_oa is None:
            step_to(engine, mover, position_of(chosen[0]), source)
        else:
            path = next(c for c in paths if c.destination == position_of(chosen[0]))
            move(engine, mover, path, intent or intent_for(engine), feet, ignored_oa, name=name)
        return True
    return False
