"""Shared read-only turn scheduling for Gate2Engine and CombatService.

All creatures retain their initiative slots for expiry. Stamped new fights omit
defeated/dead turns; historical fights retain their old boundaries. Dying and
Stable creatures keep actual turns for death saves and recovery. After those turn-start effects they have no decision
unless they recovered or a rule plug-in retains their control decision. A save
or a defeat during the current turn can also leave one forced End Turn to commit;
the service completes it locally without changing
the participant's chosen control mode. Setup and pending resolutions always keep
their own decision authority. Conscious creatures at zero HP can still act.
"""


FINALIZED_TURNS = "skip_finalized_v1"


def omits_turn(engine, actor_id):
    """New-fight scheduler query, before turn callbacks; HP alone never omits a turn.

    Keep records/initiative slots and all legacy saves. Waiting/destroyed summon
    bodies are inactive; present summons still use their own command lifecycle.
    Dying/Stable creatures keep saves/recovery, including owned recovery rules.
    """
    if engine.state.rules.get("finalized_turns") != FINALIZED_TURNS:
        return False
    actor = engine.state.actors[actor_id]
    from .ext.life_state import is_deceased
    return is_deceased(actor) or (not actor.active and actor.life_state not in ("DYING", "STABLE"))


def passes_without_decision(engine, actor_id):
    """Whether this current turn has only its automatic End Turn remaining.

    Pure query: no state changes, events, controller calls or ability-specific
    rules. Call after turn-start gameplay so a successful recovery keeps its turn.
    """
    state = engine.state
    if (state.terminal_result is not None or state.setup_tasks
            or state.pending_resolution is not None or actor_id != state.current_actor_id):
        return False
    actor = state.actors[actor_id]
    if not actor.active:
        return True
    if actor.life_state not in ("DYING", "STABLE"):
        return False
    from . import ext
    # A rule plug-in may retain a decision for an otherwise automatic turn.
    # Absent a subscriber opting in, historical turn scheduling stays unchanged.
    if not any(ext.run("turn_decision_required", engine, actor)):
        return True
    # A retained decision is only a choice when the fighter has something other
    # than the automatic End Turn to pick. A downed fighter with only End Turn
    # left (dying, stable, restrained, no action) must end on its own under
    # every controller, not wait for a click.
    return all(c.kind == "END_TURN" for c in engine._generate_legal_candidates())
