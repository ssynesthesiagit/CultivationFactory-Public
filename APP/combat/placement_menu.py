"""Lazy CELL menus shared by the engine, table and automatic controllers.

The default query remains exhaustive. Service menus opt into one placeholder
per action/origin. A placeholder is bound through an ordinary persisted square
choice before paying or resolving the action. Exact-cell intents remain native.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_QUERY = ContextVar('placement_menu_query', default=False)
CHOICE = 'choice:placement_menu.square'


def axes(grid, intent, levels):
    """Exact-cell queries visit one bounded coordinate; menus retain all axes."""
    if intent is None:
        return range(grid.width), range(grid.height), levels
    pos = intent.destination
    if pos is None or not (0 <= pos.x < grid.width and 0 <= pos.y < grid.height and pos.z in levels):
        return (), (), ()
    return (pos.x,), (pos.y,), (pos.z,)


@contextmanager
def query():
    token = _QUERY.set(True)
    try:
        yield
    finally:
        _QUERY.reset(token)


def representative(engine, actor, action, candidate, *, intent=None):
    """Return a legal placeholder, or None; absent query preserves enumeration."""
    if not _QUERY.get() or intent is not None:
        return None
    from . import ext
    if ext.any_false('candidate_allowed', engine, actor, candidate, action):
        return None
    root = engine._candidate(candidate.kind, actor, action.source_definition_id,
        action.display_name + ' — choose a square', option_ids=candidate.option_ids,
        metadata={'placement_picker': True,
                  'placement_witness': candidate.destination.model_dump(mode='json')})
    return root


def exact(engine, root, position):
    """Fresh authoritative candidates at any chosen cell, without menu caches."""
    from .gate2_runtime_models import ActionIntent
    from .canonical import canonical_sha256
    identity = engine._candidate_identity(root.kind,
        engine.state.actors[root.actor_id], root.source_definition_id, (), position)
    # Preserve the origin sealed into the placeholder identity.
    origin = root.metadata.get('effect_origin')
    if origin:
        identity['effect_origin'] = origin
    cid = 'candidate:' + canonical_sha256(identity)[:24]
    hint = ActionIntent(intent_id='intent:placement-query', candidate_id=cid,
        decision_id=root.decision_id, state_version=root.state_version,
        actor_id=root.actor_id, target_ids=(), destination=position, option_ids=())
    from . import ext
    actor = engine.state.actors[root.actor_id]
    action = engine.action_catalog[root.source_definition_id]
    # The unchanged-state placeholder has already passed the global turn,
    # loadout and action gates. Recheck this action's native costs, geometry and
    # plug-in cell gates without walking every unrelated action in its catalog.
    return next((c for c in engine._action_candidates(actor, action, intent=hint)
                 if c.candidate_id == cid and c.destination == position
                 and not ext.any_false('candidate_allowed', engine, actor, c, action)), None)


def cells(engine, root):
    """Exhaustive legal second-stage choices, including represented altitudes."""
    from .gate2_runtime_models import Position
    from .target_knowledge import actors_for
    actor = engine.state.actors[root.actor_id]
    levels = sorted({0, actor.position.z} | {a.position.z for a in actors_for(engine, actor)})
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            for z in levels:
                row = exact(engine, root, Position(x=x, y=y, z=z))
                if row is not None:
                    yield row


def search(engine, root, context):
    """Score a rotating, well-spread sample, then refine the best's neighbors.

    The sample is a ranking heuristic, not the legal choice set. If it finds
    nothing usable, enumerate the complete legal set before declaring failure.
    Scores use the ordinary controller unchanged; exhaustive choices remain
    available through cells() and explicit aims through exact().
    """
    from .gate2_runtime_models import Position
    from .gate4_controller import LocalDeterministicController, _option_sets
    from .candidate_knowledge import query as observed
    actor = engine.state.actors[root.actor_id]
    levels = sorted({0, actor.position.z} | {a.position.z for a in context.actors})
    width, height = engine.grid.width, engine.grid.height
    count = width * height * len(levels)
    phase = engine.state.state_version % count
    indices = {(phase + i * count // min(32, count)) % count for i in range(min(32, count))}
    points = [Position(x=(i // len(levels)) % width,
                       y=i // (len(levels) * width), z=levels[i % len(levels)])
              for i in sorted(indices)]
    points += [a.position for a in sorted(context.actors, key=lambda a: a.entity_id)[:8]]
    points.append(Position.model_validate(root.metadata['placement_witness']))
    controller = LocalDeterministicController()
    seen, scored = set(), []
    shared = next((c.metadata for c in context.legal_candidates if c.candidate_id == root.candidate_id), root.metadata)
    shared = {k: v for k, v in shared.items() if k not in {
        'placement_picker', 'placement_witness', 'placement_evaluation', 'expected_damage',
        'hostiles_in_area', 'empty_area', 'unavoidable_allies_in_area'}}
    def best_row():
        safe = [item for item in scored if item[2].metadata.get('hostiles_in_area')
                and not item[2].metadata.get('unavoidable_allies_in_area')]
        return min(safe or scored, key=lambda item: (-item[0], item[1]))[2] if scored else None
    def probe(point, row=None):
        key = (point.x, point.y, point.z)
        if key in seen or not (0 <= point.x < width and 0 <= point.y < height):
            return
        seen.add(key)
        if row is None:
            row = exact(engine, root, point)
        if row is None:
            return
        from . import ext
        action = engine.action_catalog[root.source_definition_id]
        if (ext.any_false('ai_candidate_allowed', engine, actor, row, action)
                or (row.metadata.get('empty_area') and not action.parameters.get('ai_allow_empty_area'))):
            return
        row = row.model_copy(update={'metadata': {**shared, **row.metadata}})
        scores = [controller._score_candidate(context, row, options)
                  for options in _option_sets(row)]
        scored.append((max(s.total for s in scores), row.candidate_id, row))
    with observed(engine):
        for point in points:
            probe(point)
        if scored:
            best = best_row().destination
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if 0 <= best.x + dx < width and 0 <= best.y + dy < height:
                        probe(Position(x=best.x + dx, y=best.y + dy, z=best.z))
        else:
            for row in cells(engine, root):
                probe(row.destination, row)
                if scored:
                    break  # First usable fallback; ranking need not find a global optimum.
    return best_row()


def annotate(engine, context):
    """Attach a scored preview to AI placeholders; never issue a new intent."""
    candidates = []
    for root in context.legal_candidates:
        if root.metadata.get('placement_picker'):
            best = search(engine, root, context)
            if best is None:
                candidates.append(root)
                continue
            root = root.model_copy(update={'metadata': {**root.metadata,
                **best.metadata, 'placement_evaluation': best.model_dump(mode='json')}})
        candidates.append(root)
    return context.model_copy(update={'legal_candidates': tuple(candidates)})


def context_for_payload(engine, context, payload):
    """Immutably admit a freshly validated legacy exact-cell selection."""
    if payload.get('destination') is None or any(c.candidate_id == payload.get('candidate_id')
                                                for c in context.legal_candidates):
        return context
    from .gate2_runtime_models import ActionIntent
    hint = ActionIntent(intent_id='intent:exact-placement', **{key: payload[key] for key in (
        'candidate_id', 'decision_id', 'state_version', 'actor_id', 'target_ids', 'destination', 'option_ids')})
    candidate = next((c for c in engine.candidates_for_intent(hint)
                      if c.candidate_id == hint.candidate_id and
                      engine.action_catalog.get(c.source_definition_id) is not None and
                      engine.action_catalog[c.source_definition_id].target_kind == 'CELL'), None)
    return (context.model_copy(update={'legal_candidates': (*context.legal_candidates, candidate)})
            if candidate is not None else context)


def resolve(engine, actor, action, root, intent):
    """Bind a placeholder through the existing saved player/model choice path."""
    if not root.metadata.get('placement_picker'):
        if intent.placement_destination is not None:
            raise ValueError('A placement aim requires a square-placement menu choice')
        return root, intent
    from .ext import needle, ai_controlled
    from .gate4_context import build_decision_context
    from .gate4_policy import PolicyLibrary
    def policy_for_actor():
        from .gate4_models import LocalControllerPolicy
        document = (getattr(engine, 'placement_policies', {}) or {}).get(actor.entity_id)
        return (LocalControllerPolicy.model_validate(document) if document is not None
                else PolicyLibrary(engine.source_root).for_actor(actor.entity_id)[0])
    if intent.placement_destination is not None:
        from .candidate_knowledge import query as observed
        from contextlib import nullcontext
        with observed(engine) if ai_controlled(engine, actor) else nullcontext():
            chosen = exact(engine, root, intent.placement_destination)
        if chosen is None:
            raise ValueError('The chosen placement square is not legal')
        return chosen, intent.model_copy(update={'destination': chosen.destination})
    # Enumerate only the selected ability, on demand, for every seat. Automatic
    # scoring orders this complete set; it never becomes the choice authority.
    from .candidate_knowledge import query as observed
    from contextlib import nullcontext
    with observed(engine) if ai_controlled(engine, actor) else nullcontext():
        rows = list(cells(engine, root))
    by_id = {needle.cell_id(c.destination, include_altitude=True): c for c in rows}
    if not by_id:
        raise ValueError('No legal placement remains for this action')
    preferred = []
    if rows:
        with query():
            prepared = engine.legal_candidates()
        policy = policy_for_actor()
        context = build_decision_context(engine, policy, prepared_candidates=prepared)
        best = search(engine, root, context)
        if best is not None:
            preferred = [needle.cell_id(best.destination, include_altitude=True)]
    selected = needle.ask(engine, intent, 'placement:' + intent.intent_id, actor,
        CHOICE, list(by_id), name=action.display_name,
        preferred=preferred,
        labels={key: f'Square {row.destination.x}, {row.destination.y}' +
                (f', {row.destination.z * 5} feet above ground' if row.destination.z else ', at ground level')
                for key, row in by_id.items()},
        prompt=f'Choose a square for {actor.display_name} to use {action.display_name}.',
        prompt_context={'source_definition_id': action.source_definition_id,
                        'action_name': action.display_name, 'affected_id': actor.entity_id})
    if not selected:
        raise ValueError('Choose a legal square to use this action')
    chosen = by_id[selected[0]]
    return chosen, intent.model_copy(update={'destination': chosen.destination})
