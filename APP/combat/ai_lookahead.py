"""Bounded native rollouts of a knowledge-only world, used by ai_mastermind.

Never clone the live world and then try to redact it: create a speculative
engine from an own-sheet snapshot and the already projected roster, then clone
THAT engine for each branch. Unknown enemies/objects/zones are absent. Enemy
moves/attacks are explicit estimates, not reads of their private catalogues.
Remembered positions remain estimates; no result grants targeting authority.
Native execution still enforces flight, costs, reactions and LoS/LoE.

A single cooperative worker has a wall-clock caller deadline; slow native
steps cannot hold the real turn open. At most one rollout worker exists, and
it checks the deadline between steps. No speculative state is persisted.
"""
import copy
import json
import threading
import time
from pathlib import Path

from .gate2_runtime_models import ActionIntent, ActorTemplate, ActorState, ActionDefinition, DiceSpec, Position
from .relations import relation, ENEMY, ALLY
from .read_queries import pure

_WORKER = threading.Lock()
MAX_PLANS = 4
# Leave headroom for native menu/context preparation and complete scoring.
ROLLOUT_SECONDS = 1.0


@pure
def own_snapshot(engine, actor, candidates=(), *, deadline=None):
    """Only owned mechanics and personally visible map cells; no foe/world clone."""
    from .senses import perceives_cell
    # Preserve the authored finite heights/occluders, but only for cells the
    # creature can currently perceive. Invisible zone geometry is NOT copied.
    source = engine.battlefield_document
    if source is None:
        source = json.loads((engine.source_root / "combat_gate1/generated/Battlefield.json").read_text())
    # One pure read frame shares invariant perception facts across the map,
    # without making the belief/knowledge projection depend on clock speed.
    visible = set()
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            if deadline is not None and time.monotonic() >= deadline:
                # Incomplete geometry is not a different belief world. Skip
                # optional verification and retain the complete native scores.
                return None
            if perceives_cell(engine, actor, Position(x=x, y=y)):
                visible.add((x, y))
    regions = []
    for row in source["terrain_regions"]:
        cells = [cell for cell in row["cells"] if (cell["x"], cell["y"]) in visible]
        if cells:
            regions.append({**row, "cells": cells})
    unknown = [{"x": x, "y": y} for y in range(engine.grid.height) for x in range(engine.grid.width)
               if (x, y) not in visible]
    if unknown:
        regions.append({"terrain_type": "BLOCKED", "movement_cost": 1, "cells": unknown})
    battlefield = {"width_squares": engine.grid.width, "height_squares": engine.grid.height,
                   "square_size_ft": 5, "starting_positions": {}, "terrain_regions": regions}
    # Native templates may include built-in IDs. The simulation installs its
    # private catalog after construction to avoid compiler collision semantics.
    ids = set(actor.action_ids) | set(actor.reaction_ids)
    ids.update(c.source_definition_id for c in candidates if c.actor_id == actor.entity_id)
    return {"actor": actor.model_dump(mode="json"),
            "template": engine.actor_templates[actor.entity_id].model_dump(mode="json"),
            "actions": [engine.action_catalog[aid].model_dump(mode="json")
                        for aid in sorted(ids) if aid in engine.action_catalog],
            "passives": copy.deepcopy(engine.typed_passive_rows.get(actor.entity_id, [])),
            "reactions": copy.deepcopy(engine.typed_reaction_rows.get(actor.entity_id, [])),
            "battlefield": battlefield}


def projected_engine(context):
    """Make the reusable native belief engine, with no handle to the live engine."""
    from .gate4_engine import Gate4ControllerEngine
    from .ai_tactics import TurnPlan
    snapshot = context.tactics["simulation"]
    own = ActorState.model_validate(snapshot["actor"])
    template = ActorTemplate.model_validate(snapshot["template"])
    own.ai_tier = "MASTERMIND"  # continue our actual goals, without recursive verification
    # Only own legal mechanics; never import an opponent's actual attacks.
    catalog = {r["source_definition_id"]: ActionDefinition.model_validate(r) for r in snapshot["actions"]}
    plan = TurnPlan(context)
    best = max((i for i in plan.actions.values() if i.get("damage")), key=lambda i: i["damage"], default={})
    templates, states = {own.entity_id: template}, {own.entity_id: own}
    for visible in context.actors:
        if visible.entity_id == own.entity_id or not visible.active:
            continue
        aid = visible.entity_id
        attack_id = "prediction:strike:" + aid
        # Neutral estimates for unknown defenses/speed. These are assumptions,
        # not claims that an unseen character has the boss's own build.
        armor = visible.armor_class or 14
        speed = visible.speed_ft or 30
        strike = ActionDefinition(source_definition_id=attack_id, display_name="Estimated enemy strike",
            owner_id=aid, economy="ACTION", resolution_kind="ATTACK", target_kind="HOSTILE_ENTITY",
            range_ft=max(5, int(best.get("range", 5))), attack_bonus=int(best.get("attack_bonus") or 5),
            damage=DiceSpec(count=1, sides=2, modifier=max(0, int(best.get("damage", 6)) - 1)),
            damage_type="force")
        catalog[attack_id] = strike
        t = ActorTemplate(entity_id=aid, display_name=visible.display_name, team_id=visible.team_id,
            primary_combatant=visible.primary_combatant, owner_id=visible.owner_id,
            armor_class=armor, maximum_hp=max(1, visible.maximum_hp), speed_ft=speed,
            fly_speed_ft=(speed if visible.position.z else 0), hover=bool(visible.position.z),
            initiative_bonus=0, dexterity_score=10, proficiency_bonus=2, saving_throws={},
            resources=(), action_ids=(attack_id,), reaction_ids=())
        templates[aid] = t
        states[aid] = ActorState(**t.model_dump(exclude={"resources", "ai_tier"}),
            current_hp=max(1, visible.current_hp), temporary_hp=visible.temporary_hp,
            active=True, position=visible.position, movement_remaining_ft=speed,
            resources={}, resource_maximums={})
    if len(states) < 2:
        return None
    # Engine construction is pure local scratch, no service or persistence.
    # Factory bundles register templates without copying any private foe bundle.
    bundles = tuple({"actor_id": t.entity_id, "actor_template": t.model_dump(mode="json"), "action_catalog": []}
                    for t in templates.values())
    engine = Gate4ControllerEngine(Path(__file__).resolve().parents[1],
        match_seed="mastermind-belief-v1", typed_bundles=bundles,
        battlefield=snapshot["battlefield"],
        roster_setup={"primary_actor_ids": list(states),
                      "starting_positions": {aid: a.position.model_dump() for aid, a in states.items()}})
    # A speculative decision reuses Mastermind goals but may not prepare a
    # second simulation or call transports. Enemy replies remain Tricky.
    engine.ai_projection = True
    # No unrelated stock character mechanics remain in the belief catalogue.
    from .gate2_runtime_content import ACTIONS
    engine.action_catalog = {aid: action for aid, action in ACTIONS.items()
                             if action.owner_id == "*"}
    engine.action_catalog.update(catalog)
    engine.actor_templates = templates
    engine.state.actors = states
    engine.state.current_actor_id = own.entity_id
    engine.state.initiative_order = list(states)
    engine.state.current_slot_index = 0
    engine.state.round_number = context.round_number
    engine.state.maximum_rounds = context.round_number + 3
    engine.state.terminal_result = None
    engine.state.setup_tasks = ()
    engine.state.pending_resolution = None
    engine.state.relations = context.relations
    engine.state.observations = {own.team_id: {a.entity_id: a.position for a in states.values()
                                             if a.entity_id != own.entity_id}}
    engine.typed_passive_rows[own.entity_id] = snapshot["passives"]
    engine.typed_reaction_rows[own.entity_id] = snapshot["reactions"]
    # Avoid closing over engine: deepcopy must not leave reactions bound to a
    # different branch. Each branch installs its own provider below.
    return engine


def _intent(engine, candidate, options=()):
    return ActionIntent(intent_id="prediction:" + candidate.candidate_id,
        candidate_id=candidate.candidate_id, decision_id=candidate.decision_id,
        actor_id=candidate.actor_id, state_version=candidate.state_version,
        target_ids=candidate.target_ids, destination=candidate.destination, option_ids=options,
        placement_destination=(Position.model_validate(
            candidate.metadata["placement_evaluation"]["destination"])
            if candidate.metadata.get("placement_evaluation") else None))


def _matches(original, candidate):
    return (original.kind == candidate.kind and original.source_definition_id == candidate.source_definition_id
            and original.target_ids == candidate.target_ids and original.destination == candidate.destination)


def _utility(engine, context):
    own = engine.state.actors[context.active_actor_id]
    allies, foes = [], []
    for actor in engine.state.actors.values():
        side = relation(engine, own, actor)
        if side == ENEMY:
            foes.append(actor)
        elif side == ALLY:
            allies.append(actor)
    hp = sum(max(0, a.current_hp) + a.temporary_hp for a in allies)
    hp -= sum(max(0, a.current_hp) + a.temporary_hp for a in foes)
    # A knockout prevents a whole reply; resources retain small future value.
    hp += 25 * sum(not a.active or a.current_hp <= 0 for a in foes)
    hp -= 35 * sum(not a.active or a.current_hp <= 0 for a in allies)
    hp += sum(own.resources.values()) // 4
    from .ai_tactics import _distance
    desired = max((i.get("range", 5) for i in context.tactics.get("actions", {}).values()
                   if i.get("damage") and i.get("ready", True)), default=5)
    pressure = min((max(0, _distance(own.position, a.position) - desired) // 5
                    for a in foes if a.active and a.current_hp > 0), default=0)
    return hp - pressure


def simulate(context, shortlist, candidates, deadline, publish=None):
    from .ai_plays import candidate_view
    from .gate4_controller import LocalDeterministicController
    from .gate4_context import build_decision_context, build_reaction_context
    from .gate4_policy import PolicyLibrary
    # An opponent\'s private Dao is not part of the observer\'s sheet. Use the
    # ordinary Tricky generic policy for that unknown reply, not the boss Dao.
    reply_policy = PolicyLibrary(Path(__file__).resolve().parents[1]).fallback()
    base = projected_engine(context)
    if base is None:
        return {}
    baseline = _utility(base, context)
    policy = context.policy.model_copy(update={"generic_fallback": False})
    # All branches start from this exact state. Reuse its complete native root
    # query, not a different placement recommendation for each cloned world.
    offered = build_decision_context(base, policy, for_ai=True, placement_previews=False).legal_candidates
    results = {}
    for score in shortlist:
        if time.monotonic() >= deadline:
            break
        engine = copy.deepcopy(base)
        controller = LocalDeterministicController()
        def reaction(request):
            reactor_policy = policy if request["reactor_id"] == context.active_actor_id else reply_policy
            choice = controller.choose_reaction(build_reaction_context(engine, reactor_policy, request))
            return choice.decision, None
        engine.set_reaction_provider(reaction)
        original = candidate_view(candidates[score.candidate_id])
        try:
            # Native query, not an injected speculative candidate or legality bypass.
            root = candidates[score.candidate_id]
            if root.metadata.get("placement_picker") and original.destination is not None:
                from .placement_menu import exact
                from .candidate_knowledge import query
                native_root = next((c for c in offered if c.metadata.get("placement_picker")
                    and c.source_definition_id == original.source_definition_id
                    and c.metadata.get("effect_origin") == root.metadata.get("effect_origin")), None)
                # Verify the proposed aim, not whichever different square a
                # fresh ranking of the speculative world happens to recommend.
                with query(engine):
                    candidate = exact(engine, native_root, original.destination) if native_root else None
            else:
                candidate = next((c for c in offered if _matches(original, c)), None)
            if candidate is None:
                continue  # unknown geometry/effect: keep precondition scoring
            engine.execute_intent(_intent(engine, candidate, score.option_ids))
            # Finish a bounded joint turn, then one likely enemy turn. Each
            # own continuation uses the same play policy, without recursive
            # search; the enemy uses Tricky and no hidden catalogue.
            enemy_id = None
            enemy_replied = False
            for step in range(8):
                if time.monotonic() >= deadline or engine.state.terminal_result is not None:
                    break
                current = engine.state.current_actor_id
                own = engine.state.actors[context.active_actor_id]
                if current != own.entity_id:
                    if relation(engine, own, engine.state.actors[current]) != ENEMY:
                        engine.end_turn()
                        continue
                    if enemy_id is None:
                        enemy_id = current
                    elif current != enemy_id:
                        break
                elif enemy_id is not None:
                    break
                turn_policy = policy if current == context.active_actor_id else reply_policy
                projected = build_decision_context(engine, turn_policy, for_ai=True)
                choice = controller.choose_primary_action(projected)
                engine.execute_intent(choice.intent)
                if current == enemy_id and (engine.state.current_actor_id != enemy_id
                                             or engine.state.terminal_result is not None):
                    enemy_replied = True
            if enemy_replied or engine.state.terminal_result is not None:
                key = (score.candidate_id, score.option_ids)
                results[key] = _utility(engine, context) - baseline
                if publish is not None:
                    publish(key, results[key])
        except (ValueError, KeyError, StopIteration):
            # Unsupported predictions are not failed live actions. The real
            # menu and complete scores survive and remain selectable.
            continue
    return results


def verify(context, shortlist, candidates, *, budget=ROLLOUT_SECONDS):
    """Bound caller wait even if a native branch is unexpectedly expensive."""
    if budget <= 0 or "simulation" not in context.tactics or not _WORKER.acquire(blocking=False):
        return {}
    completed, result = threading.Event(), {}
    result_lock = threading.Lock()
    deadline = time.monotonic() + max(0, budget)
    def publish(key, value):
        with result_lock:
            result[key] = value
    def work():
        try:
            final = simulate(context, shortlist[:MAX_PLANS], candidates, deadline, publish)
            with result_lock:
                result.update(final)
        except Exception:
            pass  # retain already completed branches, never partial native steps
        finally:
            _WORKER.release()
            completed.set()
    try:
        threading.Thread(target=work, name="mastermind-lookahead", daemon=True).start()
    except Exception:
        _WORKER.release()
        return {}
    completed.wait(max(0, deadline - time.monotonic()))
    # A slow later branch must not erase completed replies at the deadline.
    # Only immutable integer outcomes cross this lock, never live engine state.
    with result_lock:
        return dict(result)
