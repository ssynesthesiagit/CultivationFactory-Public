"""Default-off personal knowledge and analytic destination value, slices 1–2.

No live transport, playbook priors or rules modifications. Journal observations
are conservative: only own senses grant current knowledge, damage proves its
own square, and only a completely perceived visible area proves its boundary.
"""
import os
from . import hook
from ..ai_observation import (OwnKnowledgeFrame, KnownCreature, KnownSquare,
                              ObservedHarm, point)
from ..canonical import canonical_sha256
from ..gate4_models import ComponentScore

KEY = 'personal_observations'


def enabled():
    return os.environ.get('CF_COMBAT_AI_SLICES_1_2') == '1'


@hook('ai_policy_enrichment')
def policy_goal(policy, sheet):
    if not enabled():
        return None
    from ..ai_observation import goal_from_sheet
    return {'goal_description': goal_from_sheet(sheet)}


def latest_receipt(engine):
    for event in reversed(engine.events):
        if KEY in event.payload:
            return event.payload[KEY]
    return {}


@hook('target_personal_knowledge')
def personal_target(engine, viewer, target):
    if not enabled():
        return None
    from ..target_knowledge import Knowledge, located
    from ..gate2_runtime_models import Position
    if located(engine, viewer, target):
        return Knowledge('DIRECT', target.position)
    prior = latest_receipt(engine).get(viewer.entity_id, {}).get('creatures', {}).get(target.entity_id)
    if prior:
        x, y, z = prior['position']
        return Knowledge('LAST_OBSERVED', Position(x=x, y=y, z=z))
    return False


def personal_creatures(engine, viewer, previous):
    from ..target_knowledge import located
    from ..relations import relation
    memory = {cid: {**row, 'mode': 'LAST_OBSERVED'}
              for cid, row in previous.items()}
    for target in engine.state.actors.values():
        if target.entity_id == viewer.entity_id or not engine._on_battlefield(target):
            continue
        if located(engine, viewer, target):
            memory[target.entity_id] = {'entity_id': target.entity_id,
                'name': target.display_name, 'position': list(point(target.position)),
                'observed_sequence': engine.events[-1].sequence, 'mode': 'DIRECT',
                'relation': relation(engine, viewer, target)}
    return memory


def attributed_harms(engine, viewer, previous, since):
    """Match own area triggers to damage; never interpret unrelated hits.

    Receipt replay reads only new events. Keeping a prior harm after losing
    sight is conservative memory, never a claim that the area remains active.
    """
    from ..senses import perceives_cell
    # Retain at most one further personal turn without renewed damage. This
    # advisory memory must not discourage a cleared square indefinitely.
    memory = {key: value for key, value in previous.items()
              if value.get('own_turn', 0) + 1 >= viewer.turns_started}
    pending = None
    for event in engine.events:
        if event.sequence <= since:
            continue
        if event.event_type == 'PASSIVE_TRIGGERED':
            pending = event.payload.get('zone_id') if (
                viewer.entity_id in event.target_ids and
                event.payload.get('moment') == 'start') else None
        elif event.event_type == 'DAMAGE_COMMITTED':
            damage = max(0, int(event.payload.get('reduced_to') or 0))
            if pending and damage and viewer.entity_id in event.target_ids:
                zone = engine.state.zones.get(pending)
                cells = []
                complete = False
                # Missing visibility authority and invisible areas cannot grant
                # geometry. Observed damage alone grants just the occupied cell.
                visual = (zone.trigger_profile.get('visual') or {}) if zone else {}
                # Native painted terrain has a perceived physical footprint.
                # A material/colour alone on an arbitrary area does not prove
                # that its boundary is visible (e.g. an invisible poison veil).
                if (zone and zone.trigger_profile.get('terrain') and
                        visual.get('material') and not visual.get('invisible')):
                    cells = [list(point(cell)) for cell in zone.affected_cells
                             if perceives_cell(engine, viewer, cell)]
                    complete = bool(cells) and len(cells) == len(zone.affected_cells)
                memory[pending] = {'position': list(point(viewer.position)),
                    'damage': damage, 'sequence': event.sequence,
                    'own_turn': viewer.turns_started,
                    'cells': cells, 'complete_boundary': int(complete)}
            pending = None
    return memory


@hook('personal_observation_receipt')
def record_personal(engine):
    if not enabled():
        return None
    old = latest_receipt(engine)
    result = {}
    for viewer in engine.state.actors.values():
        if not viewer.active:
            continue
        prior = old.get(viewer.entity_id, {})
        result[viewer.entity_id] = {
            'sequence': engine.events[-1].sequence,
            'creatures': personal_creatures(engine, viewer, prior.get('creatures', {})),
            'harms': attributed_harms(engine, viewer, prior.get('harms', {}), prior.get('sequence', 0)),
        }
    return result


@hook('ai_observation_frame')
def observation_frame(engine, viewer, candidates, policy):
    if not enabled():
        return None
    from ..senses import perceives_cell
    from ..gate2_runtime_models import Position
    from . import run_strict
    prior = latest_receipt(engine).get(viewer.entity_id, {})
    memory = personal_creatures(engine, viewer, prior.get('creatures', {}))
    harms = attributed_harms(engine, viewer, prior.get('harms', {}), prior.get('sequence', 0))
    # Recheck current visibility after reload; old DIRECT receipts are memories.
    creatures = tuple(KnownCreature(**row) for _, row in sorted(memory.items()))
    positions = {point(viewer.position)} | {point(p) for c in candidates
                                         if c.kind == 'MOVE' for p in c.canonical_path}
    positions.update(point(c.destination) for c in candidates if c.kind == 'MOVE' and c.destination is not None)
    # Perception includes every occupied cell along a multi-cell creature's
    # route, not just its anchor. Hazard geometry must retain native footprints.
    positions.update(cell for c in candidates if c.kind == 'MOVE'
                     for p in c.canonical_path for cell in engine._actor_volume(viewer, p))
    objectives = {point(p) for answer in run_strict('ai_observed_objectives', engine, viewer)
                  for p in answer if perceives_cell(engine, viewer, p)}
    positions.update(objectives)
    squares = []
    for xyz in sorted(positions):
        position = Position(x=xyz[0], y=xyz[1], z=xyz[2])
        known = perceives_cell(engine, viewer, position)
        squares.append(KnownSquare(position=xyz, known=known,
            cover=known and engine.grid.terrain_at(position, 'SIMPLE_COVER'),
            objective=known and xyz in objectives,
            hazard=known and xyz[2] == 0 and xyz[:2] in engine.grid.qi_hazard,
            difficult=known and engine.grid.base_movement_cost.get(xyz[:2], 1) > 1))
    template = engine.actor_templates[viewer.entity_id]
    data = dict(actor_id=viewer.entity_id, position=point(viewer.position), hp=viewer.current_hp,
        maximum_hp=viewer.maximum_hp, movement_ft=viewer.movement_remaining_ft, own_turn=viewer.turns_started,
        resources=tuple(sorted(viewer.resources.items())), abilities=tuple(sorted(set(template.action_ids) | set(viewer.action_ids))),
        goal=policy.goal_description, creatures=creatures, squares=tuple(squares),
        harms=tuple(ObservedHarm(**h) for _, h in sorted(harms.items())),
        footprint_offsets=tuple(tuple(cell[i] - point(viewer.position)[i] for i in range(3))
                                for cell in engine._actor_volume(viewer)))
    # Observation timestamps of DIRECT actors use the latest journal sequence;
    # global hidden activity must not invalidate the own-knowledge revision.
    for row in creatures:
        if row.mode == 'DIRECT':
            data['creatures'] = tuple(c.model_copy(update={'observed_sequence': 0})
                if c.mode == 'DIRECT' else c for c in creatures)
            break
    frame = OwnKnowledgeFrame(revision='', **data)
    return frame.model_copy(update={'revision': canonical_sha256(frame.model_dump(exclude={'revision'}))})


def perceived_hazard_zones(engine, viewer):
    """Project physically perceived terrain; never invent unseen boundaries.

    Native terrain carries its source-backed entry/cross/distance effects.
    Arbitrary invisible areas or a colour alone grant no terrain knowledge.
    A partially seen line grants no guessed endpoints for a crossing query.
    """
    from ..senses import perceives_cell
    from ..zones import typed_zones
    result = []
    for zone in typed_zones(engine):
        profile = zone.trigger_profile
        visual = profile.get('visual') or {}
        if not (profile.get('terrain') and visual.get('material')) or visual.get('invisible'):
            continue
        cells = tuple(p for p in zone.affected_cells if perceives_cell(engine, viewer, p))
        if not cells:
            continue
        projected = dict(profile)
        if profile.get('shape') == 'line' and len(cells) != len(zone.affected_cells):
            projected['triggers'] = [dict(t, on=[m for m in t.get('on', ()) if m != 'cross'])
                                     for t in profile.get('triggers', ())]
        result.append(zone.model_copy(update={'affected_cells': cells, 'trigger_profile': projected}))
    return tuple(result)


@hook('ai_movement_hazards')
def movement_hazards(engine, viewer, candidates, frame):
    if not enabled():
        return None
    from ..gate2_runtime_models import Position
    from ..zones import hazard_test
    hazards = tuple(Position(x=s.position[0], y=s.position[1], z=s.position[2])
                    for s in frame.squares if s.hazard)
    remembered = tuple(Position(x=p[0], y=p[1], z=p[2]) for h in frame.harms
                       if h.position != frame.position for p in h.cells)
    # Native query omits occupied entry/start zones but keeps line crossing and
    # cumulative distance risks. It evaluates the creature's entire footprint.
    zone_risk = hazard_test(engine, viewer, zone_states=perceived_hazard_zones(engine, viewer))
    risk_by_cell = {}
    def dangerous(p):
        xyz = point(p)
        if xyz not in risk_by_cell:
            risk_by_cell[xyz] = bool(zone_risk and zone_risk(p))
        return risk_by_cell[xyz]
    result = {}
    for candidate in candidates:
        if candidate.kind != 'MOVE':
            continue
        path = candidate.canonical_path[1:]
        zone_exposure = any(dangerous(p) or engine._footprint_intersects(viewer, remembered, position=p)
                            for p in path)
        exposure = zone_exposure or any(engine._footprint_intersects(viewer, hazards, position=p) for p in path)
        result[candidate.candidate_id] = {'hazard_exposure': exposure, 'zone_hazard_exposure': zone_exposure}
    return result


def occupied_harm(frame):
    # Memory is advisory, not a damage forecast. Once an actor has moved away
    # from the hurt square we do not repeatedly reward moving farther away.
    return max((h.damage for h in frame.harms if h.position == frame.position), default=0)


def movement_features(frame, candidate):
    """Labelled integer differences; no engine, unseen bounds or future rolls."""
    if candidate.destination is None:
        return {}
    destination = point(candidate.destination)
    squares = {s.position: s for s in frame.squares}
    square = squares.get(destination)
    current = squares.get(frame.position)
    damage = occupied_harm(frame)
    distance = max(abs(destination[i] - frame.position[i]) for i in (0, 1))
    # Require actual horizontal displacement, not unsafe guessed vertical escape.
    escape, stay = 0, 0
    if damage and distance:
        covering = [h for h in frame.harms if h.position == frame.position]
        occupied = set(frame.occupied_at(destination))
        inside = any(occupied.intersection(h.cells) for h in covering)
        complete = all(h.complete_boundary for h in covering)
        if not inside:
            escape = min(100, damage * (8 if complete else 4)) - min(15, candidate.movement_cost_ft // 5)
        else:
            stay = -min(100, damage * 6)
    creatures = [c for c in frame.creatures if c.mode == 'DIRECT' and c.relation == 'ENEMY']
    approach = 0
    if creatures:
        # Approach only personally located enemies; last sightings are beliefs.
        before = min(max(abs(frame.position[i] - c.position[i]) for i in range(3)) for c in creatures)
        after = min(max(abs(destination[i] - c.position[i]) for i in range(3)) for c in creatures)
        approach = max(-5, min(5, before - after))
    from ..gate4_controller import native_flight_position_value
    return {'escape': max(0, escape), 'stay': stay, 'approach': approach,
        'cover': 8 * (int(bool(square and square.cover)) - int(bool(current and current.cover))),
        'flight': native_flight_position_value(candidate),
        'objective': 12 * int(bool(square and square.objective))}


def destination_details(context):
    """Public EMBEDMENU adapter: all ids with perceived square text and value.

    Pass destination_provider(context) as menu_rank.rank_menu's documented
    destination_provider(moves). This layer never ranks UI or calls embeddings.
    """
    frame = context.own_knowledge
    if frame is None:
        return {}
    squares = {s.position: s for s in frame.squares}
    return {c.candidate_id: {
        'description': f'Move using {c.movement_cost_ft} feet of movement. ' + squares[point(c.destination)].description(),
        'score': sum(movement_features(frame, c).values()),
        'features': movement_features(frame, c)} for c in context.legal_candidates
        if c.kind == 'MOVE' and c.destination is not None}


def destination_provider(context):
    details = destination_details(context)
    def scores(moves):
        return {row['candidate_id']: details.get(row['candidate_id'], {}).get('score', 0)
                for row in moves}
    scores.descriptions = {cid: row['description'] for cid, row in details.items()}
    return scores


@hook('ai_movement_order')
def movement_order(context, rows):
    if not enabled() or context.own_knowledge is None or context.bystander:
        return None
    frame = context.own_knowledge
    features = {c.candidate_id: movement_features(frame, c) for c in rows}
    ranked = sorted(rows, key=lambda c: (-sum(features[c.candidate_id].values()), c.candidate_id))
    # Protect escape, baseline (cheap route), cover and native flight purposes
    # in the first five, then retain ALL other destinations in ranked order.
    prefix = []
    def reserve(candidate):
        if candidate and candidate not in prefix:
            prefix.append(candidate)
    reserve(next((c for c in ranked if features[c.candidate_id].get('escape', 0) > 0), None))
    reserve(min(rows, key=lambda c: (c.movement_cost_ft, c.candidate_id), default=None))
    reserve(next((c for c in ranked if features[c.candidate_id].get('cover', 0) > 0), None))
    reserve(next((c for c in ranked if c.metadata.get('movement_mode') == 'fly'
                  and c.destination.z != frame.position[2]), None))
    for candidate in ranked:
        if len(prefix) >= 5:
            break
        reserve(candidate)
    return tuple(c.candidate_id for c in prefix + [c for c in ranked if c not in prefix])


@hook('ai_score_components')
def movement_value(context, candidate, option_ids):
    if not enabled() or context.own_knowledge is None or context.bystander:
        return None
    frame = context.own_knowledge
    if candidate.kind == 'MOVE':
        features = movement_features(frame, candidate)
        explanation = ('Leave the square where an area hurt you. Unseen area boundaries and destination safety remain unknown.'
                       if features.get('escape') else 'Move toward a personally observed creature or observed cover.')
        # Native flight reach/support value is already included by the core.
        value = sum(v for name, v in features.items() if name != 'flight')
        return (ComponentScore(component='personal_movement', value=value, explanation=explanation),)
    damage = occupied_harm(frame)
    # Staying value belongs only to ending/holding, not every attack (which may
    # be followed by an escape in this same turn).
    if damage and candidate.kind in ('END_TURN', 'HOLD_POSITION'):
        return (ComponentScore(component='observed_area_stay', value=-min(100, damage * 6),
            explanation='Ending here risks another area hit based on damage you personally suffered.'),)
    return None
