from __future__ import annotations

from .relations import relation, ALLY, ENEMY

from typing import Any

from .canonical import canonical_sha256
from . import concentration as _conc
from .gate2_engine import Gate2Engine
from .gate2_runtime_content import ACTIONS
from .gate2_runtime_models import LegalCandidate
from .gate4_models import (
    DecisionContext, LocalControllerPolicy, ReactionContext, TeamBehavior,
    VisibleActor, VisibleZone,
)


def _visible_actor(actor, engine=None) -> VisibleActor:
    return VisibleActor(
        entity_id=actor.entity_id,
        display_name=actor.display_name,
        team_id=actor.team_id,
        primary_combatant=actor.primary_combatant,
        owner_id=actor.owner_id,
        active=actor.active,
        current_hp=actor.current_hp,
        maximum_hp=actor.maximum_hp,
        temporary_hp=actor.temporary_hp,
        armor_class=actor.armor_class,
        position=actor.position,
        speed_ft=actor.speed_ft,
        movement_remaining_ft=actor.movement_remaining_ft,
        action_available=actor.action_available,
        bonus_action_available=actor.bonus_action_available,
        reaction_available=actor.reaction_available,
        resources=dict(sorted(actor.resources.items())),
        conditions=tuple(sorted(c.condition_id for c in actor.conditions.values())),
        # None while it may still start another Concentration technique (owner 2026-09-29: several at once by CL,
        # combat/concentration.py): the AI weighs a new one as free, not as ending the current one.
        concentration_source_id=(None if actor.concentration is None or (engine is not None and _conc.free_slot(engine, actor))
                                else actor.concentration.source_definition_id),
    )


def derive_team_behavior(engine: Gate2Engine, actor_id: str, *, known_actors=None) -> TeamBehavior:
    """Reuse the caller's read-only knowledge projection when supplied."""
    actor = engine.state.actors[actor_id]
    from .target_knowledge import actors_for
    hostiles = [a for a in (actors_for(engine, actor) if known_actors is None else known_actors)
                if a.active and relation(engine, a, actor) == ENEMY]
    primaries = [a for a in hostiles if a.primary_combatant] or hostiles
    focus = min(primaries, key=lambda a: (a.current_hp, a.entity_id), default=None)
    friendly = [a for a in engine.state.actors.values() if a.active and relation(engine, a, actor) == ALLY]
    enemy_positions = {(a.position.x, a.position.y) for a in hostiles}
    friendly_positions = {(a.position.x, a.position.y) for a in friendly}
    direction = "HOLD"
    if hostiles and friendly:
        avg_enemy_x = sum(x for x, _ in enemy_positions) / len(enemy_positions)
        avg_friend_x = sum(x for x, _ in friendly_positions) / len(friendly_positions)
        if abs(avg_enemy_x - avg_friend_x) > 5:
            direction = "CLOSE"
        elif len(friendly_positions) != len(friendly):
            direction = "SPREAD"
    pressure = bool(focus and focus.current_hp <= max(8, focus.maximum_hp // 4))
    return TeamBehavior(
        focus_target_id=focus.entity_id if focus else None,
        immediate_defeat_pressure=pressure,
        formation_direction=direction,
    )


def build_decision_context(
    engine: Gate2Engine,
    policy: LocalControllerPolicy,
    *,
    recent_event_limit: int = 12,
    no_progress_signals: tuple[str, ...] = (),
    for_ai: bool = False,
    include_item_actions: bool = False,
    prepared_candidates: tuple[LegalCandidate, ...] | None = None,
    known_actors=None,
    placement_previews: bool = True,
) -> DecisionContext:
    """``for_ai`` (owner 2026-09-26, step 11): the controller's menu, without the abilities combat runs
    nothing for (``inert``, combat/factory_compiler.py); a player's own decision context keeps them.

    Non-built-in paid actions expose their compiled costs as integer pairs in
    candidate.metadata.compiled_costs. This is the acting creature's known price,
    not a catalogue export. Candidate identity, the engine's canonical candidate,
    state and payment are unchanged. Missing metadata keeps old contexts readable;
    built-in costs retain their static lookup and exact serialized representation.
    Optional action.parameters.ai_area_family groups alternative shapes of one
    ability for safe AI placement. It is copied only into the decision context;
    absent metadata groups placements by source ID and changes no saved candidate.

    ``placement_previews=False`` lets a second-stage recommendation score one
    selected ability without recursively ranking all CELL placeholders. It
    retains the complete observed candidate set and tactical context; ordinary
    AI decisions keep previews enabled by default. Native AI queries use lazy
    placement roots just like the table; cells()/exact() still expose every aim.
    This flag grants no intent
    authority and does not change legality or the creature's knowledge.

    If AI filtering empties an ordinary summon's menu, retain its canonical
    END_TURN candidate. This default-inert safety fallback uses the normal
    controller choice, journal and turn-end path; it invents no action and never
    applies to reaction/choice windows or a nonempty menu.
    """
    # Internal read-only seam: callers may supply the complete native query for
    # this exact state/view (observed generation for AI, canonical for players).
    # No authority is issued here; execution still validates the native intent.
    # None generates a fresh full query (lazy area roots for AI). Never pass a truncated/ranked menu.
    # Generate, not merely filter, AI placements from observed actors so a
    # last-observed area aim survives hidden movement. The scope is query-only;
    # candidate identities and the real execution roster remain unchanged.
    from time import monotonic_ns
    preparation_started = monotonic_ns()
    if prepared_candidates is not None:
        raw_candidates = tuple(prepared_candidates)
    elif for_ai:
        from .candidate_knowledge import query
        from .placement_menu import query as placement_query
        # Match the table's lazy area query: one root per ability/origin,
        # bounded ranking previews below, exhaustive cells()/exact() on demand.
        # This caps plans evaluated, never the legal human/model/AI aim set.
        with query(engine), placement_query():
            raw_candidates = tuple(engine.legal_candidates())
    else:
        raw_candidates = tuple(engine.legal_candidates())
    from .relations import ordinary_turn
    ordinary = ordinary_turn(raw_candidates)
    filtered: list[LegalCandidate] = []
    recovery_cache = {}  # local to this immutable decision query
    from . import ext

    ai_vetoes = for_ai and ext.has("ai_candidate_allowed")  # the built-in AI's own restraint (combat/ext/ai_restraint.py)
    for candidate in raw_candidates:
        actor = engine.state.actors[candidate.actor_id]
        action = engine.action_catalog.get(candidate.source_definition_id)
        if for_ai and action is not None and action.parameters.get("inert"):
            continue
        if for_ai and ordinary and any(relation(engine, actor, engine.state.actors[aid]) == 'NEUTRAL'
                          for aid in candidate.target_ids if aid in engine.state.actors):
            continue
        if (ai_vetoes and not candidate.metadata.get('placement_picker')
                and ext.any_false("ai_candidate_allowed", engine, actor, candidate, action)):
            continue  # e.g. casting again what is still up (fight audit 2026-09-29); a player keeps the choice
        # Utility actions may need an empty destination (for example moving a
        # persistent zone). Opt-in is generic and does not expose unseen cells:
        # Gate 2 has already applied the acting creature's candidate-knowledge
        # view before this context filter runs.
        if (for_ai and (candidate.metadata or {}).get("empty_area")
                and not (action is not None and action.parameters.get("ai_allow_empty_area"))):
            continue  # an area ability aimed where it catches no one (a player may still lay terrain there)
        if action is not None and action.parameters.get("player_only") and not include_item_actions:
            continue  # Hide, Search, choosing an area's talents: a player's (or an AI pilot's) menu, not the built-in AI's
        item = action.parameters.get("item_action") if action is not None else None
        if item:
            # Drop / Pick up an item (owner 2026-09-27, combat/carry.py): only a player's own menu offers them, and only
            # what it holds or has dropped within reach; no AI drops its gear.
            from . import carry

            if not include_item_actions:
                continue
            key = action.parameters.get("item_key")
            if (item == "drop" and not carry.holds(engine, actor, key)) or (item == "pickup" and not carry.can_pick_up(engine, actor, key)):
                continue
        if candidate.source_definition_id == "action:ling_qi.reflection_cut" and actor.resources.get("resource:ling_qi.mirror_trace", 0) < 1:
            continue
        if candidate.source_definition_id == "action:bai_meizhen.command_cui" and not engine.state.actors.get("bai_cui").active:
            continue
        if candidate.source_definition_id == "action:bai_meizhen.moon_disc_descent" and actor.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) < 1:
            continue
        if candidate.source_definition_id == "action:bai_meizhen.bloodline_strike" and actor.resources.get("resource:bai_meizhen.ancestral_resonance", 0) < 1:
            continue
        if action is not None and action.costs and candidate.source_definition_id not in ACTIONS:
            candidate = candidate.model_copy(update={'metadata': {
                **candidate.metadata, 'compiled_costs': [[rid, cost] for rid, cost in action.costs]}})
        if action is not None:
            # Explicit, free setup actions may be sequenced before paid actions.
            # The provider's ordinary legal/AI gates must bound repeated use.
            # This is a controller projection, never a player/saved candidate change.
            if (for_ai and action.parameters.get('ai_free_preparation') is True
                    and action.economy.value == 'NONE'):
                candidate = candidate.model_copy(update={'metadata': {
                    **candidate.metadata, 'ai_free_preparation': True}})
            if action.parameters.get('ai_area_family'):
                candidate = candidate.model_copy(update={'metadata': {
                    **candidate.metadata, 'ai_area_family': action.parameters['ai_area_family']}})
            from .support_estimates import recovery
            support = recovery(engine, actor, candidate, action, cache=recovery_cache)
            if support is not None:
                candidate = candidate.model_copy(update={'metadata': {
                    **candidate.metadata, 'useful_recovery': support}})
        filtered.append(candidate)
    candidates = tuple(filtered)
    if not candidates and for_ai and ordinary:
        candidates = tuple(c for c in raw_candidates if c.kind == "END_TURN"
                           and engine.state.actors[c.actor_id].summon)
    if not candidates:
        raise ValueError("CONTROLLER_NO_LEGAL_CHOICE")
    actor_id = candidates[0].actor_id
    decision_ids = {c.decision_id for c in candidates}
    if len(decision_ids) != 1:
        raise ValueError("CONTROLLER_DECISION_CONTEXT_INVALID")
    from .target_knowledge import actors_for, recent_events
    viewer = engine.state.actors[actor_id]
    recent = recent_events(engine, viewer, engine.events[-recent_event_limit:])
    from .relations import bystander
    from .movement_history import endpoints
    from .ai_search import search_move
    known_actors = actors_for(engine, viewer) if known_actors is None else known_actors
    annotation_deadline = None
    profile_deadline = None
    if for_ai:
        from .ai_tiers import effective_tier
        if effective_tier(viewer, getattr(engine, "ai_tier_overrides", {})) == "MASTERMIND" and not viewer.summon:
            from .ai_mastermind import FLIGHT_SECONDS, PREPARATION_SECONDS
            annotation_deadline = preparation_started / 1e9 + FLIGHT_SECONDS
            profile_deadline = preparation_started / 1e9 + PREPARATION_SECONDS
        from .ai_tactics import annotate_flight
        candidates = (annotate_flight(engine, candidates, actor_id, known_actors)
                      if annotation_deadline is None else
                      annotate_flight(engine, candidates, actor_id, known_actors, deadline=annotation_deadline))
    own_frame = (next(iter(ext.run_strict('ai_observation_frame', engine, viewer, candidates, policy)), None)
                 if for_ai else None)
    visible_actors = tuple(_visible_actor(a, engine) for a in sorted(known_actors, key=lambda a: a.entity_id))
    behavior = derive_team_behavior(engine, actor_id, known_actors=known_actors)
    if own_frame is not None:
        # The analytic contract supplies personal positions, not enemy HP or
        # private defenses. Legacy scorers get neutral estimates for unknown
        # statistics, never an enemy's actual sheet or teammates' remote view.
        from .gate2_runtime_models import Position
        personal = {a.entity_id: a for a in own_frame.creatures}
        hazard_metadata = {}
        for answer in ext.run_strict('ai_movement_hazards', engine, viewer, candidates, own_frame):
            hazard_metadata.update(answer)
        candidates = tuple(c.model_copy(update={'metadata': {**c.metadata,
            **hazard_metadata.get(c.candidate_id, {}),
            'reaction_exposure': [aid for aid in c.metadata.get('reaction_exposure', ()) if aid in personal]}})
            if c.kind == 'MOVE' else c for c in candidates)
        # Personally visible allies retain the native authorized support and
        # companion facts. Remembered allies use the same neutral projection
        # as opponents: losing sight never grants their current sheet/location.
        visible_actors = tuple(a if (a.entity_id == actor_id or (
            a.entity_id in personal and personal[a.entity_id].mode == 'DIRECT'
            and relation(engine, a, viewer) == ALLY)) else a.model_copy(update={
            'display_name': personal[a.entity_id].name,
            'position': Position(x=personal[a.entity_id].position[0], y=personal[a.entity_id].position[1], z=personal[a.entity_id].position[2]),
            'current_hp': 100, 'maximum_hp': 100, 'temporary_hp': 0,
            'armor_class': 0, 'resources': {}, 'conditions': (),
            'speed_ft': 0, 'movement_remaining_ft': 0, 'active': True,
            'action_available': False, 'bonus_action_available': False,
            'reaction_available': False, 'concentration_source_id': None})
            for a in visible_actors if a.entity_id == actor_id or a.entity_id in personal)
        hostiles = [a for a in visible_actors if relation(engine, a, viewer) == ENEMY]
        behavior = TeamBehavior(focus_target_id=min((a.entity_id for a in hostiles), default=None),
                                immediate_defeat_pressure=False, formation_direction='HOLD')
    from .information_results import for_observer
    from .ai_tactics import owned_profile, preparation_deadline
    context = DecisionContext(
        # Local choices and crash-recovery must see the same own-sheet facts,
        # including callers that build a full player context before choosing AI.
        tactics=(owned_profile(engine, viewer, known_actors, candidates)
                 if profile_deadline is None else
                 owned_profile(engine, viewer, known_actors, candidates, deadline=profile_deadline)),
        information=tuple(for_observer(engine, viewer)),
        relations=engine.state.relations,
        bystander=ordinary and bystander(engine, viewer),
        match_id=engine.state.match_id,
        state_version=engine.state.state_version,
        decision_id=next(iter(decision_ids)),
        active_actor_id=actor_id,
        round_number=engine.state.round_number,
        current_slot_index=engine.state.current_slot_index,
        actors=visible_actors,
        zones=() if own_frame is not None else tuple(
            VisibleZone(
                zone_id=z.zone_id,
                source_definition_id=z.source_definition_id,
                owner_id=z.owner_id,
                center=z.center,
                radius_cells=z.radius_cells,
                active=z.active,
            )
            for z in sorted(engine.state.zones.values(), key=lambda z: z.zone_id)
        ),
        legal_candidates=candidates,
        policy=policy,
        own_knowledge=own_frame,
        team_behavior=behavior,
        recent_events=recent,
        no_progress_signals=no_progress_signals,
        movement_endpoints=endpoints(engine, actor_id),
        search_move_candidate_id=(search_move(engine, viewer, candidates, policy,
                                  visible_actors if own_frame is not None else known_actors,
                                  () if own_frame is not None else recent,
                                  sightings={a.entity_id: (a.position[:2], a.observed_sequence)
                                             for a in own_frame.creatures}
                                  if own_frame is not None else None)
                                  if for_ai and ordinary and not bystander(engine, viewer) else None),
    )
    if for_ai and placement_previews:
        from .placement_menu import annotate
        deadline = preparation_deadline(context, preparation_started)
        context = (annotate(engine, context) if deadline is None
                   else annotate(engine, context, deadline=deadline))
    return context.model_copy(update={"preparation_ns": monotonic_ns() - preparation_started})


def build_reaction_context(
    engine: Gate2Engine,
    policy: LocalControllerPolicy,
    request: dict[str, Any],
) -> ReactionContext:
    reactor_id = str(request["reactor_id"])
    reactor = engine.state.actors[reactor_id]
    from .target_knowledge import recent_events
    decision_payload = {
        "match_id": engine.state.match_id,
        "state_version": engine.state.state_version,
        "checkpoint": request["checkpoint"],
        "reactor_id": reactor_id,
        "reaction_source_id": request["reaction_source_id"],
        "event_sequence": engine.state.event_sequence,
    }
    return ReactionContext(
        match_id=engine.state.match_id,
        state_version=engine.state.state_version,
        decision_id=f"reaction-decision:{canonical_sha256(decision_payload)[:24]}",
        checkpoint=str(request["checkpoint"]),
        reactor_id=reactor_id,
        protected_target_id=request.get("protected_target_id"),
        damaged_target_id=request.get("damaged_target_id"),
        attacking_actor_id=request.get("attacking_actor_id"),
        reaction_source_id=str(request["reaction_source_id"]),
        provisional_hit=request.get("provisional_hit"),
        pending_damage=request.get("pending_damage"),
        legal_reaction_ids=tuple(request.get("legal_reaction_ids") or (request["reaction_source_id"],)),
        spend_options=tuple(int(v) for v in request.get("spend_options", ())),
        legal_option_ids=tuple(str(v) for v in request.get("legal_option_ids", ())),
        extension_choice=request.get("extension_choice"),
        choice_trigger=request.get("choice_trigger"),
        resources=dict(sorted(reactor.resources.items())),
        conditions=tuple(sorted(c.condition_id for c in reactor.conditions.values())),
        policy=policy,
        recent_events=recent_events(engine, reactor, engine.events[-8:]),
    )


def reject_future_roll_access() -> None:
    from .diagnostics import error
    raise error(
        "CONTROLLER_FUTURE_ROLL_ACCESS_REJECTED",
        "Controller contexts do not expose future rolls or deterministic seed internals.",
        phase="CONTROLLER_CONTEXT", subsystem="GATE4_CONTROLLER",
        recommended_action="Choose only from visible state and legal engine candidates.",
    )
